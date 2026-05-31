"""Report generators."""

from isabelle_blueprint.report.badge import (
    build_endpoint_payload,
    coverage_color,
    coverage_message,
    render_badge_svg,
    write_badge_endpoint,
    write_badge_svg,
)
from isabelle_blueprint.report.github_actions import (
    build_summary_markdown,
    emit_step_outputs,
    emit_step_summary,
)
from isabelle_blueprint.report.json_report import write_project_report
from isabelle_blueprint.report.markdown_report import write_markdown_report
from isabelle_blueprint.report.metrics import (
    StatusMetrics,
    build_status_metrics,
    output_values,
    stable_output_keys,
)

__all__ = [
    "StatusMetrics",
    "build_endpoint_payload",
    "build_status_metrics",
    "build_summary_markdown",
    "coverage_color",
    "coverage_message",
    "emit_step_outputs",
    "emit_step_summary",
    "output_values",
    "render_badge_svg",
    "stable_output_keys",
    "write_badge_endpoint",
    "write_badge_svg",
    "write_markdown_report",
    "write_project_report",
]
