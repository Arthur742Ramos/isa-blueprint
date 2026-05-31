"""Shared status metrics used by the badge, GitHub Actions output, and reports.

Defining the metrics in one place keeps the badge color, the
``$GITHUB_OUTPUT`` values, and the Markdown report's coverage line in lock-step.
If the calculation drifts, the badge ends up disagreeing with the README and
with the CI step summary - exactly the sort of confusion the roadmap's
"shareable status badge" item was meant to avoid.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

# Statuses that signal something is actively wrong with a formal target.
# ``stale`` is intentionally NOT included: it means dependencies changed, not
# that the proof itself failed, so it should not flip the badge to red.
PROBLEM_FORMAL_STATUSES: frozenset[str] = frozenset(
    {
        FormalStatus.NOT_FOUND.value,
        FormalStatus.BROKEN.value,
        FormalStatus.FAILED_CHECK.value,
        FormalStatus.TAINTED.value,
    }
)


@dataclass(frozen=True)
class StatusMetrics:
    """Aggregate counts derived from a :class:`BlueprintProject`.

    ``coverage_percent`` is ``None`` when the denominator is undefined - either
    the project has no nodes at all, or no node has been assigned an Isabelle
    reference yet. Callers should treat ``None`` as "unknown" rather than 0%.
    """

    node_count: int
    formal_target_count: int  # nodes whose formal status is anything other than MISSING
    proved_count: int
    found_count: int
    problem_count: int
    stale_count: int
    has_cycles: bool
    coverage_percent: int | None

    @property
    def has_problems(self) -> bool:
        return self.problem_count > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "node_count": self.node_count,
            "formal_target_count": self.formal_target_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "stale_count": self.stale_count,
            "has_cycles": self.has_cycles,
            "coverage_percent": self.coverage_percent,
        }


def build_status_metrics(project: BlueprintProject) -> StatusMetrics:
    """Compute the status metrics for ``project``.

    "Formal targets" are nodes that have been assigned an Isabelle reference
    (i.e. their formal status is anything other than ``missing``). Counting
    only those keeps the coverage percentage meaningful in early-stage
    projects where most nodes are still just blueprint text.
    """
    counts = Counter(n.status.formal.value for n in project.nodes)
    missing = counts.get(FormalStatus.MISSING.value, 0)
    proved = counts.get(FormalStatus.PROVED.value, 0)
    found = counts.get(FormalStatus.FOUND.value, 0)
    stale = counts.get(FormalStatus.STALE.value, 0)
    problems = sum(counts.get(value, 0) for value in PROBLEM_FORMAL_STATUSES)

    node_count = len(project.nodes)
    formal_target_count = node_count - missing

    coverage_percent: int | None
    if node_count == 0 or formal_target_count == 0:
        coverage_percent = None
    else:
        coverage_percent = round(proved / formal_target_count * 100)

    has_cycles = bool(project.validate().cycles)

    return StatusMetrics(
        node_count=node_count,
        formal_target_count=formal_target_count,
        proved_count=proved,
        found_count=found,
        problem_count=problems,
        stale_count=stale,
        has_cycles=has_cycles,
        coverage_percent=coverage_percent,
    )


def output_values(metrics: StatusMetrics) -> dict[str, str]:
    """Render ``metrics`` as the stable, scalar GitHub Actions output set.

    The keys here are a public contract - downstream Actions reference them by
    name (``${{ steps.blueprint.outputs.coverage_percent }}`` etc.), so they
    should only ever be extended, never renamed or removed.
    """
    coverage = "" if metrics.coverage_percent is None else str(metrics.coverage_percent)
    return {
        "coverage_percent": coverage,
        "node_count": str(metrics.node_count),
        "formal_target_count": str(metrics.formal_target_count),
        "proved_count": str(metrics.proved_count),
        "found_count": str(metrics.found_count),
        "problem_count": str(metrics.problem_count),
        "has_cycles": "true" if metrics.has_cycles else "false",
    }


def stable_output_keys() -> Iterable[str]:
    """The frozen list of output keys, in their canonical order."""
    return (
        "coverage_percent",
        "node_count",
        "formal_target_count",
        "proved_count",
        "found_count",
        "problem_count",
        "has_cycles",
    )
