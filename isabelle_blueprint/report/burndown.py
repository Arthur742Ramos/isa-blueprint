"""Velocity / burndown forecast over the recorded coverage history.

The ``report`` command appends one entry per run to ``build/trends.json`` with a
snapshot of the proved/target counts (see :mod:`isabelle_blueprint.report.trends`).
This module reads that series back and projects when the project will reach full
*proved* coverage, based on the observed rate at which the remaining work is
burning down.

Design notes (informed by review):

* The headline KPI is ``coverage_percent = proved_count / formal_target_count``.
  We therefore track ``completed = proved_count`` and ``total =
  formal_target_count``, with ``remaining = total - completed``.
* The ETA is forecast from the slope of **remaining vs time**, not from the
  completed velocity. ``formal_target_count`` is a moving goalpost (it grows as
  new nodes are added), so a positive completed velocity does not guarantee the
  project is converging. Regressing ``remaining`` itself captures scope growth:
  if the target grows as fast as work is proved, ``remaining`` stays flat and no
  ETA is produced.
* The series is "report snapshots over time" (keyed by the report ``timestamp``),
  not commit-graph order. The trend store is deduped by ``(commit_sha, branch)``,
  so forecasts describe how recorded runs moved, not the commit history.
* The analysis is pure and best-effort: malformed or partial historical entries
  are skipped, never fatal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from isabelle_blueprint.report._markdown import md_cell as _md_cell

BURNDOWN_SCHEMA_VERSION = 1

# Default number of most-recent usable points used for the "recent" velocity.
DEFAULT_RECENT_WINDOW = 5

# Slopes whose magnitude is below this (targets/day) are treated as flat. This
# keeps floating-point dust from producing absurd century-scale ETAs.
_SLOPE_EPSILON = 1e-6

# Forecasts further out than this are reported as ``beyond_horizon`` rather than
# an implausible calendar date (and it keeps ``timedelta`` well away from
# overflow).
_MAX_HORIZON_DAYS = 36500.0  # ~100 years

# Status taxonomy (also documented in the CLI contract / README).
STATUS_NO_HISTORY = "no_history"
STATUS_NO_TARGETS = "no_targets"
STATUS_COMPLETE = "complete"
STATUS_INSUFFICIENT = "insufficient_history"
STATUS_ON_TRACK = "on_track"
STATUS_STALLED = "stalled"
STATUS_SCOPE_GROWING = "scope_growing"
STATUS_REGRESSING = "regressing"
STATUS_BEYOND_HORIZON = "beyond_horizon"


@dataclass(frozen=True)
class BurndownPoint:
    """A single usable snapshot in the burndown series."""

    timestamp: str
    completed: int
    total: int
    remaining: int
    found: int | None = None
    problems: int | None = None
    _dt: datetime = field(default=datetime.min, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "completed": self.completed,
            "total": self.total,
            "remaining": self.remaining,
            "found": self.found,
            "problems": self.problems,
        }


@dataclass(frozen=True)
class VelocityBlock:
    """Least-squares velocities over a window of the series (per day)."""

    basis: str
    point_count: int
    span_days: float | None
    proved_per_day: float | None
    remaining_per_day: float | None
    target_per_day: float | None

    @property
    def net_burndown_per_day(self) -> float | None:
        if self.remaining_per_day is None:
            return None
        return -self.remaining_per_day

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "point_count": self.point_count,
            "span_days": self.span_days,
            "proved_per_day": self.proved_per_day,
            "remaining_per_day": self.remaining_per_day,
            "net_burndown_per_day": self.net_burndown_per_day,
            "target_per_day": self.target_per_day,
        }


@dataclass(frozen=True)
class BurndownReport:
    """The full forecast over a coverage history."""

    schema_version: int
    status: str
    total_entries: int
    entry_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    span_days: float | None
    completed: int | None
    total: int | None
    remaining: int | None
    found: int | None
    problems: int | None
    forecast: VelocityBlock | None
    overall: VelocityBlock | None
    eta_days: float | None
    eta_date: str | None
    points: list[BurndownPoint] = field(default_factory=list)


def _as_count(value: object) -> int | None:
    """Return ``value`` as a non-negative int, rejecting bools and junk."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    return None


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC ``datetime``."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _usable_points(entries: list[dict[str, Any]]) -> list[BurndownPoint]:
    """Extract well-formed, forecastable points from raw trend entries.

    A point is usable only when its timestamp parses and both ``proved_count``
    and ``formal_target_count`` are real, non-negative ints with ``proved <=
    target`` (an impossible snapshot is excluded rather than clamped, since bad
    points poison a regression worse than missing ones). Exact-duplicate
    timestamps are collapsed, keeping the latest occurrence, so a CI matrix that
    writes several entries at the same instant does not over-weight that moment.
    """
    points: list[BurndownPoint] = []
    for entry in entries:
        dt = _parse_timestamp(entry.get("timestamp"))
        if dt is None:
            continue
        completed = _as_count(entry.get("proved_count"))
        total = _as_count(entry.get("formal_target_count"))
        if completed is None or total is None or completed > total:
            continue
        points.append(
            BurndownPoint(
                timestamp=entry["timestamp"],
                completed=completed,
                total=total,
                remaining=total - completed,
                found=_as_count(entry.get("found_count")),
                problems=_as_count(entry.get("problem_count")),
                _dt=dt,
            )
        )

    points.sort(key=lambda p: p._dt)

    collapsed: dict[datetime, BurndownPoint] = {}
    for point in points:
        collapsed[point._dt] = point
    return [collapsed[key] for key in sorted(collapsed)]


def _ols_slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares slope of ``ys`` vs ``xs`` (``None`` if undetermined)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx < 1e-12:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    if not math.isfinite(slope):
        return None
    return slope


def _velocity_block(points: list[BurndownPoint], *, basis: str) -> VelocityBlock:
    first_dt = points[0]._dt
    xs = [(p._dt - first_dt).total_seconds() / 86400.0 for p in points]
    span = xs[-1] - xs[0] if len(xs) >= 2 else (0.0 if points else None)
    return VelocityBlock(
        basis=basis,
        point_count=len(points),
        span_days=None if span is None else round(span, 4),
        proved_per_day=_round_opt(_ols_slope(xs, [float(p.completed) for p in points])),
        remaining_per_day=_round_opt(_ols_slope(xs, [float(p.remaining) for p in points])),
        target_per_day=_round_opt(_ols_slope(xs, [float(p.total) for p in points])),
    )


def _round_opt(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)


def build_burndown_report(
    entries: list[dict[str, Any]],
    *,
    recent_window: int = DEFAULT_RECENT_WINDOW,
) -> BurndownReport:
    """Build a :class:`BurndownReport` from raw ``load_trends`` output."""
    window = recent_window if recent_window and recent_window > 0 else DEFAULT_RECENT_WINDOW
    points = _usable_points(entries)
    total_entries = len(entries)

    if not points:
        return BurndownReport(
            schema_version=BURNDOWN_SCHEMA_VERSION,
            status=STATUS_NO_HISTORY,
            total_entries=total_entries,
            entry_count=0,
            first_timestamp=None,
            last_timestamp=None,
            span_days=None,
            completed=None,
            total=None,
            remaining=None,
            found=None,
            problems=None,
            forecast=None,
            overall=None,
            eta_days=None,
            eta_date=None,
            points=[],
        )

    last = points[-1]
    first_dt = points[0]._dt
    span_days = round((last._dt - first_dt).total_seconds() / 86400.0, 4)

    overall = _velocity_block(points, basis="overall")
    forecast = overall
    if len(points) > window:
        recent = points[-window:]
        recent_block = _velocity_block(recent, basis="recent")
        if recent_block.remaining_per_day is not None:
            forecast = recent_block

    status, eta_days, eta_date = _classify(last, forecast)

    return BurndownReport(
        schema_version=BURNDOWN_SCHEMA_VERSION,
        status=status,
        total_entries=total_entries,
        entry_count=len(points),
        first_timestamp=points[0].timestamp,
        last_timestamp=last.timestamp,
        span_days=span_days,
        completed=last.completed,
        total=last.total,
        remaining=last.remaining,
        found=last.found,
        problems=last.problems,
        forecast=forecast,
        overall=overall,
        eta_days=eta_days,
        eta_date=eta_date,
        points=points,
    )


def _classify(
    last: BurndownPoint, forecast: VelocityBlock
) -> tuple[str, float | None, str | None]:
    """Resolve status + ETA from the latest point and forecast velocities."""
    if last.total == 0:
        return STATUS_NO_TARGETS, None, None
    if last.remaining == 0:
        return STATUS_COMPLETE, 0.0, last._dt.date().isoformat()

    slope = forecast.remaining_per_day
    if slope is None:
        return STATUS_INSUFFICIENT, None, None

    if slope < -_SLOPE_EPSILON:
        eta_days = last.remaining / (-slope)
        if eta_days > _MAX_HORIZON_DAYS:
            return STATUS_BEYOND_HORIZON, round(eta_days, 1), None
        eta_date = (last._dt + timedelta(days=eta_days)).date().isoformat()
        return STATUS_ON_TRACK, round(eta_days, 1), eta_date

    if abs(slope) <= _SLOPE_EPSILON:
        return STATUS_STALLED, None, None

    # remaining is growing.
    proved = forecast.proved_per_day
    if proved is not None and proved > _SLOPE_EPSILON:
        return STATUS_SCOPE_GROWING, None, None
    return STATUS_REGRESSING, None, None


def burndown_payload(report: BurndownReport, *, limit: int | None = None) -> dict[str, Any]:
    """Render ``report`` as a JSON-friendly dict.

    ``limit`` trims the displayed ``points`` to the most recent N; it never
    affects the velocity/ETA, which always use the full usable series.
    """
    shown = report.points if limit is None else report.points[-limit:] if limit > 0 else []
    return {
        "schema_version": report.schema_version,
        "status": report.status,
        "total_entries": report.total_entries,
        "entry_count": report.entry_count,
        "first_timestamp": report.first_timestamp,
        "last_timestamp": report.last_timestamp,
        "span_days": report.span_days,
        "completed": report.completed,
        "total": report.total,
        "remaining": report.remaining,
        "found": report.found,
        "problems": report.problems,
        "eta_days": report.eta_days,
        "eta_date": report.eta_date,
        "forecast": None if report.forecast is None else report.forecast.to_dict(),
        "overall": None if report.overall is None else report.overall.to_dict(),
        "points": [p.to_dict() for p in shown],
    }


_STATUS_HEADLINES = {
    STATUS_NO_HISTORY: "No coverage history yet.",
    STATUS_NO_TARGETS: "No formal targets yet (nothing to burn down).",
    STATUS_COMPLETE: "Complete - every formal target is proved.",
    STATUS_INSUFFICIENT: "Not enough history to estimate velocity.",
    STATUS_ON_TRACK: "On track.",
    STATUS_STALLED: "Stalled - remaining work is not moving.",
    STATUS_SCOPE_GROWING: "Scope growing - targets are being added faster than proofs land.",
    STATUS_REGRESSING: "Regressing - remaining work is increasing.",
    STATUS_BEYOND_HORIZON: "Burning down, but completion is more than a century out.",
}


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.3f}/day"


def render_burndown_report(report: BurndownReport, *, limit: int = 10) -> str:
    """Render ``report`` as concise human-readable text (trailing newline)."""
    headline = _STATUS_HEADLINES.get(report.status, report.status)

    if report.status == STATUS_NO_HISTORY:
        return (
            "Burndown forecast: No coverage history yet. "
            "Run `isabelle-blueprint report` to record snapshots.\n"
        )

    lines = [f"Burndown forecast: {headline}"]
    lines.append(
        f"  Snapshots: {report.entry_count} usable "
        f"(of {report.total_entries}) over {report.span_days} days"
    )
    if report.total is not None:
        lines.append(
            f"  Proved {report.completed}/{report.total} "
            f"(remaining {report.remaining})"
        )

    forecast = report.forecast
    if forecast is not None and forecast.remaining_per_day is not None:
        lines.append(
            f"  Velocity ({forecast.basis}, {forecast.point_count} pts / "
            f"{forecast.span_days} days):"
        )
        lines.append(f"    proved   {_fmt_rate(forecast.proved_per_day)}")
        lines.append(f"    net burn {_fmt_rate(forecast.net_burndown_per_day)}")
        lines.append(f"    target   {_fmt_rate(forecast.target_per_day)}")

    if report.eta_date is not None:
        lines.append(f"  ETA: {report.eta_date} (~{report.eta_days} days)")
    elif report.status == STATUS_BEYOND_HORIZON:
        lines.append(f"  ETA: beyond horizon (~{report.eta_days} days)")

    shown = report.points[-limit:] if limit > 0 else []
    if shown:
        lines.append("  Recent snapshots:")
        for point in shown:
            lines.append(
                f"    {point.timestamp}  proved={point.completed} "
                f"target={point.total} remaining={point.remaining}"
            )

    return "\n".join(lines) + "\n"


# Statuses that warrant a "completion is not in sight" caveat in the Markdown.
_STALLED_STATUSES = frozenset(
    {STATUS_STALLED, STATUS_REGRESSING, STATUS_SCOPE_GROWING}
)

_STALLED_NOTES = {
    STATUS_STALLED: (
        "Remaining work is not burning down, so no completion date can be "
        "forecast. Record more progress before relying on an ETA."
    ),
    STATUS_REGRESSING: (
        "Remaining work is increasing - the project is moving away from "
        "completion, so no ETA is produced."
    ),
    STATUS_SCOPE_GROWING: (
        "Targets are being added faster than proofs land, so remaining work "
        "grows despite progress and no ETA can be forecast."
    ),
}


def _md_opt(value: object) -> str:
    return "n/a" if value is None else str(value)


def render_burndown_markdown(report: BurndownReport) -> str:
    """Render ``report`` as a Markdown document (trailing newline).

    Emits a heading, a summary table (status / remaining / eta_days / eta_date /
    forecast) and, when the project is stalled / regressing / scope-growing, a
    short note explaining why no ETA is produced.
    """
    headline = _STATUS_HEADLINES.get(report.status, report.status)
    lines = ["# Burndown forecast", "", _md_cell(headline), ""]

    forecast = report.forecast
    if forecast is None or forecast.remaining_per_day is None:
        forecast_cell = "n/a"
    else:
        forecast_cell = (
            f"{forecast.basis} ({forecast.point_count} pts / "
            f"{_md_opt(forecast.span_days)} days), "
            f"net burn {_fmt_rate(forecast.net_burndown_per_day)}"
        )

    lines.append("| Status | Remaining | ETA (days) | ETA date | Forecast |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| `{report.status}` | {_md_opt(report.remaining)} "
        f"| {_md_opt(report.eta_days)} | {_md_opt(report.eta_date)} "
        f"| {_md_cell(forecast_cell)} |"
    )

    note = _STALLED_NOTES.get(report.status)
    if report.status in _STALLED_STATUSES and note is not None:
        lines.append("")
        lines.append(f"> **Note:** {note}")

    return "\n".join(lines) + "\n"
