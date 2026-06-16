"""Summarise the ``trends.json`` history written by ``report``.

The ``report`` command appends one entry per run to ``build/trends.json`` with a
snapshot of the coverage / problem counts. ``history`` reads that store back and
presents the series plus the delta between the two most recent entries, so a
glance shows whether coverage is moving in the right direction.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

# Numeric metric keys we compute a delta for, in display order.
_DELTA_KEYS = (
    "coverage_percent",
    "proved_count",
    "found_count",
    "problem_count",
    "stale_count",
    "formal_target_count",
    "node_count",
)


@dataclass(frozen=True)
class TrendDelta:
    """The change in a single numeric metric between two trend entries."""

    metric: str
    before: int | float | None
    after: int | float | None
    delta: int | float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class TrendSummary:
    """A bounded view of the trend series plus the latest delta."""

    entry_count: int
    entries: list[dict] = field(default_factory=list)
    deltas: list[TrendDelta] = field(default_factory=list)

    @property
    def latest(self) -> dict | None:
        return self.entries[-1] if self.entries else None

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_count": self.entry_count,
            "entries": list(self.entries),
            "deltas": [d.to_dict() for d in self.deltas],
        }


def summarize_trends(entries: list[dict], *, limit: int | None = None) -> TrendSummary:
    """Build a :class:`TrendSummary` from raw ``load_trends`` output.

    ``limit`` keeps only the most recent ``limit`` entries in the returned view;
    the delta is always computed from the two most recent entries regardless of
    ``limit`` (so a small ``--limit 1`` still shows movement).
    """
    total = len(entries)
    shown = entries if limit is None else entries[-limit:] if limit > 0 else []

    deltas: list[TrendDelta] = []
    if total >= 2:
        before, after = entries[-2], entries[-1]
        for key in _DELTA_KEYS:
            b = _as_number(before.get(key))
            a = _as_number(after.get(key))
            delta = a - b if a is not None and b is not None else None
            deltas.append(TrendDelta(metric=key, before=b, after=a, delta=delta))

    return TrendSummary(entry_count=total, entries=list(shown), deltas=deltas)


def _as_number(value: object) -> int | float | None:
    """Return ``value`` as a number, preserving ``int`` vs ``float``.

    Booleans are excluded (``bool`` is a subclass of ``int``) and non-numeric
    values yield ``None``. Floats are kept as-is so decimal metrics such as
    ``coverage_percent`` are not silently truncated.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def render_trend_summary(summary: TrendSummary) -> str:
    """Render ``summary`` as a concise human-readable report (trailing newline)."""
    if summary.entry_count == 0:
        return "No trend history yet. Run `isabelle-blueprint report` to record a snapshot.\n"

    lines = [
        f"Trend history ({summary.entry_count} "
        f"entr{'y' if summary.entry_count == 1 else 'ies'}):"
    ]
    for entry in summary.entries:
        timestamp = entry.get("timestamp", "?")
        coverage = entry.get("coverage_percent")
        coverage_str = "n/a" if coverage is None else f"{coverage}%"
        proved = entry.get("proved_count", "?")
        problems = entry.get("problem_count", "?")
        commit = entry.get("commit_sha")
        commit_str = f" {commit[:8]}" if isinstance(commit, str) and commit else ""
        lines.append(
            f"  {timestamp}{commit_str}  coverage={coverage_str} proved={proved} "
            f"problems={problems}"
        )

    if summary.deltas:
        lines.append("Latest change:")
        for delta in summary.deltas:
            lines.append(f"  {delta.metric}: {_format_delta(delta)}")
    else:
        lines.append("Latest change: (need at least two entries to compute a delta)")
    return "\n".join(lines) + "\n"


def _format_delta(delta: TrendDelta) -> str:
    before = "n/a" if delta.before is None else str(delta.before)
    after = "n/a" if delta.after is None else str(delta.after)
    if delta.delta is None:
        change = ""
    elif delta.delta > 0:
        change = f" (+{delta.delta})"
    elif delta.delta < 0:
        change = f" ({delta.delta})"
    else:
        change = " (no change)"
    return f"{before} -> {after}{change}"


# CSV columns, in display order: the timestamp plus the same numeric metrics
# surfaced in the text/delta views.
_CSV_COLUMNS = ("timestamp",) + _DELTA_KEYS


def render_trend_csv(summary: TrendSummary) -> str:
    """Render ``summary.entries`` as CSV (header row + one row per snapshot).

    Columns are the timestamp followed by the numeric coverage / count metrics.
    Missing values are emitted as empty cells. Uses ``\\r\\n`` line terminators
    per the :mod:`csv` module default.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for entry in summary.entries:
        row = []
        for column in _CSV_COLUMNS:
            value = entry.get(column)
            row.append("" if value is None else value)
        writer.writerow(row)
    return buffer.getvalue()


def _md_cell(value: object) -> str:
    """Escape a value for safe inclusion in a Markdown table cell."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", r"\|")
    )


def render_trend_markdown(summary: TrendSummary) -> str:
    """Render ``summary.entries`` as a Markdown table (trailing newline).

    The columns mirror the CSV view: the timestamp followed by the numeric
    coverage / count metrics, one row per snapshot. Missing values are emitted
    as empty cells. User-controlled cell text is escaped for table safety.
    """
    header = "| " + " | ".join(_CSV_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in _CSV_COLUMNS) + " |"
    lines = [header, separator]
    for entry in summary.entries:
        cells = [_md_cell(entry.get(column)) for column in _CSV_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
