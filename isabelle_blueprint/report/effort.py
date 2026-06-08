"""Effort-weighted progress metrics.

Each node may carry an optional ``effort`` weight (a story-point-style estimate
of how much work the formal proof is expected to take). This module aggregates
those weights into a weighted view of formalization progress, complementing the
unweighted coverage in :mod:`isabelle_blueprint.report.metrics`.

The weighting mirrors :func:`build_status_metrics`: "formal targets" are nodes
whose formal status is anything other than ``missing``, and weighted coverage is
the proved share of that target effort. Nodes without an explicit ``effort`` are
treated as weight :data:`DEFAULT_EFFORT` so the figure stays meaningful while a
project is still adopting effort estimates incrementally.
"""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

DEFAULT_EFFORT = 1


@dataclass(frozen=True)
class EffortReport:
    """Effort-weighted aggregate derived from a :class:`BlueprintProject`.

    ``coverage_percent`` is ``None`` when the denominator is undefined - either
    the project has no nodes, or no node has been assigned an Isabelle reference
    yet. Callers should treat ``None`` as "unknown" rather than 0%.
    """

    node_count: int
    explicit_effort_count: int
    total_effort: int
    formal_target_effort: int
    proved_effort: int
    found_effort: int
    remaining_effort: int
    coverage_percent: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_count": self.node_count,
            "explicit_effort_count": self.explicit_effort_count,
            "total_effort": self.total_effort,
            "formal_target_effort": self.formal_target_effort,
            "proved_effort": self.proved_effort,
            "found_effort": self.found_effort,
            "remaining_effort": self.remaining_effort,
            "coverage_percent": self.coverage_percent,
            "default_effort": DEFAULT_EFFORT,
        }


def _weight(node: BlueprintNode) -> int:
    return node.effort if node.effort is not None else DEFAULT_EFFORT


def build_effort_report(project: BlueprintProject) -> EffortReport:
    """Compute effort-weighted progress for ``project``."""
    node_count = len(project.nodes)
    explicit = 0
    total = 0
    formal_target = 0
    proved = 0
    found = 0
    for node in project.nodes:
        weight = _weight(node)
        total += weight
        if node.effort is not None:
            explicit += 1
        formal = node.status.formal
        if formal != FormalStatus.MISSING:
            formal_target += weight
            if formal == FormalStatus.PROVED:
                proved += weight
            elif formal == FormalStatus.FOUND:
                found += weight

    coverage_percent: int | None
    if node_count == 0 or formal_target == 0:
        coverage_percent = None
    else:
        # Truncate (not round) so 100 means genuinely all proved; clamp a
        # non-zero-but-sub-1% ratio up to 1 so real progress is never shown as
        # a misleading 0%. Mirrors report.metrics.build_status_metrics.
        coverage_percent = proved * 100 // formal_target
        if coverage_percent == 0 and proved > 0:
            coverage_percent = 1

    return EffortReport(
        node_count=node_count,
        explicit_effort_count=explicit,
        total_effort=total,
        formal_target_effort=formal_target,
        proved_effort=proved,
        found_effort=found,
        remaining_effort=formal_target - proved,
        coverage_percent=coverage_percent,
    )


def render_effort_report(report: EffortReport) -> str:
    """Render ``report`` as a short Markdown summary."""
    coverage = "n/a" if report.coverage_percent is None else f"{report.coverage_percent}%"
    lines = [
        "# Effort-weighted progress",
        "",
        f"- Weighted coverage: {coverage} (proved effort / formal-target effort)",
        f"- Proved effort: {report.proved_effort}",
        f"- Found effort: {report.found_effort}",
        f"- Remaining effort: {report.remaining_effort}",
        f"- Formal-target effort: {report.formal_target_effort}",
        f"- Total effort: {report.total_effort}",
        (
            f"- Nodes with explicit effort: {report.explicit_effort_count} of "
            f"{report.node_count} (others weighted as {DEFAULT_EFFORT})"
        ),
    ]
    return "\n".join(lines) + "\n"
