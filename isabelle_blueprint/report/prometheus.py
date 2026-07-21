"""Render blueprint status as a Prometheus text-exposition payload.

This lets a scrape job (or a CI step that writes a ``.prom`` file into a
node-exporter textfile directory) track formalization progress over time in the
same monitoring stack used for everything else.

Only **project-level** gauges are emitted - never per-node series - so the
metric cardinality stays bounded no matter how large the blueprint grows. Every
metric carries a ``# HELP``/``# TYPE`` preamble as the exposition format
requires.

Undefined coverage (a project with no formal targets yet) is represented by the
companion ``isabelle_blueprint_coverage_defined`` gauge being ``0`` rather than
emitting a misleading ``NaN`` or ``0`` ratio.
"""

from __future__ import annotations

from isabelle_blueprint.report.metrics import StatusMetrics

_PREFIX = "isabelle_blueprint"


def render_prometheus(
    metrics: StatusMetrics,
    *,
    eta_days: float | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    """Render ``metrics`` as a Prometheus text-exposition string (trailing newline).

    ``eta_days`` (from a burndown forecast) is emitted only when available.

    ``labels`` is an optional mapping of extra static labels injected onto every
    emitted metric line (merged with any existing labels). When empty or
    ``None`` the output is byte-identical to a label-free render.
    """
    label_text = _render_labels(labels)

    lines: list[str] = []

    def gauge(name: str, value: float | int, help_text: str) -> None:
        metric = f"{_PREFIX}_{name}"
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric}{label_text} {_format_value(value)}")

    gauge("nodes_total", metrics.node_count, "Total number of blueprint nodes.")
    gauge(
        "formal_targets_total",
        metrics.formal_target_count,
        "Nodes assigned an Isabelle fact (formal status not 'missing').",
    )
    gauge("proved_total", metrics.proved_count, "Nodes whose formal status is 'proved'.")
    gauge("found_total", metrics.found_count, "Nodes whose formal status is 'found'.")
    gauge(
        "problems_total",
        metrics.problem_count,
        "Nodes in a problem formal status (not_found/broken/failed_check/tainted).",
    )
    gauge("stale_total", metrics.stale_count, "Nodes whose formal status is 'stale'.")
    gauge(
        "has_cycles",
        1 if metrics.has_cycles else 0,
        "1 when the dependency graph contains a cycle, else 0.",
    )

    coverage_defined = metrics.coverage_percent is not None
    gauge(
        "coverage_defined",
        1 if coverage_defined else 0,
        "1 when proved coverage is defined (there is at least one formal target), else 0.",
    )
    if coverage_defined:
        gauge(
            "coverage_ratio",
            metrics.coverage_percent / 100.0,  # type: ignore[operator]
            "Proved coverage as a ratio in [0, 1]; only meaningful when coverage_defined is 1.",
        )

    if eta_days is not None:
        gauge(
            "burndown_eta_days",
            eta_days,
            "Forecast days until full proved coverage (from the burndown trend).",
        )

    return "\n".join(lines) + "\n"


def _render_labels(labels: dict[str, str] | None) -> str:
    """Render ``labels`` as a ``{key="value",...}`` suffix (empty string if none).

    Label values are escaped per the Prometheus text exposition format
    (backslash, double-quote and newline). Keys are emitted in insertion order.
    """
    if not labels:
        return ""
    parts = [f'{key}="{_escape_label_value(value)}"' for key, value in labels.items()]
    return "{" + ",".join(parts) + "}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(value: float | int) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    # Trim trailing zeros for a tidy float, but keep at least one decimal.
    text = f"{value:.6f}".rstrip("0")
    return text + "0" if text.endswith(".") else text
