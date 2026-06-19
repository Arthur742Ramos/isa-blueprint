"""Shared status metrics used by the badge, GitHub Actions output, and reports.

Defining the metrics in one place keeps the badge color, the
``$GITHUB_OUTPUT`` values, and the Markdown report's coverage line in lock-step.
If the calculation drifts, the badge ends up disagreeing with the README and
with the CI step summary - exactly the sort of confusion the roadmap's
"shareable status badge" item was meant to avoid.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from isabelle_blueprint.model.node import BlueprintNode
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


def coverage_percent(proved: int, target: int) -> int | None:
    """Proved share of ``target`` formal work as a 0-100 integer percentage.

    This is the single source of truth for the project's coverage figure, shared
    by the status metrics, the effort-weighted report, and the portfolio
    roll-up so the badge, README, CI summary, and dashboards never drift apart.

    Returns ``None`` when ``target`` is 0 — coverage is undefined when nothing
    has been assigned a formal target (callers should treat ``None`` as
    "unknown", not 0%). Otherwise the ratio is *truncated* rather than rounded,
    so 100 means *genuinely* all-proved: ``round()`` would report a false 100%
    for 999/1000, and floor cannot reach 100 unless ``proved == target`` (since
    ``proved <= target``). Symmetrically, 0 is reserved for "none proved" — a
    non-zero-but-sub-1% ratio (e.g. 1/1000) is clamped up to 1 so real progress
    is never shown as a misleading 0%.
    """
    if target <= 0:
        return None
    percent = proved * 100 // target
    if percent == 0 and proved > 0:
        percent = 1
    return percent


@dataclass
class StatusCounts:
    """Per-group formal-status tally produced by :func:`group_status_counts`.

    ``targets`` counts nodes with any non-``missing`` formal status; ``proved``,
    ``found``, and ``problems`` are sub-tallies of that target set (a node can
    be both counted as a target and as a problem). Mirrors the accumulation in
    :func:`build_status_metrics` so per-group coverage stays consistent with the
    project-wide figure.
    """

    nodes: int = 0
    targets: int = 0
    proved: int = 0
    found: int = 0
    problems: int = 0


def group_status_counts(
    project: BlueprintProject,
    key_fn: Callable[[BlueprintNode], str],
) -> dict[str, StatusCounts]:
    """Group ``project`` nodes by ``key_fn`` and tally their formal statuses.

    Returns a mapping from group key to :class:`StatusCounts`, with keys in
    first-seen node order so callers can apply their own deterministic sort.
    The per-group classification matches :func:`build_status_metrics` exactly,
    keeping the kind/theory roll-ups in lock-step with the project totals.
    """

    buckets: dict[str, StatusCounts] = {}
    for node in project.nodes:
        bucket = buckets.setdefault(key_fn(node), StatusCounts())
        bucket.nodes += 1
        formal = node.status.formal.value
        if formal != FormalStatus.MISSING.value:
            bucket.targets += 1
            if formal == FormalStatus.PROVED.value:
                bucket.proved += 1
            elif formal == FormalStatus.FOUND.value:
                bucket.found += 1
            if formal in PROBLEM_FORMAL_STATUSES:
                bucket.problems += 1
    return buckets


def build_status_metrics(
    project: BlueprintProject,
    *,
    has_cycles: bool | None = None,
) -> StatusMetrics:
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

    coverage = coverage_percent(proved, formal_target_count)

    if has_cycles is None:
        has_cycles = bool(project.validate().cycles)

    return StatusMetrics(
        node_count=node_count,
        formal_target_count=formal_target_count,
        proved_count=proved,
        found_count=found,
        problem_count=problems,
        stale_count=stale,
        has_cycles=has_cycles,
        coverage_percent=coverage,
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
