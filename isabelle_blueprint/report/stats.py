"""Aggregate analytics over agent-memory attempts.

``stats`` turns the raw per-node attempt log (see :mod:`isabelle_blueprint.agents.memory`)
into a quick health read: how many attempts have been logged, how they break
down by outcome, the success rate overall and per node-kind, and a per-node
roll-up. It answers "where is the proof effort getting stuck?" without opening
the memory file by hand.

The JSON form is intentionally lightweight and not part of the frozen v1.0
contract surface; it is meant for humans and ad-hoc scripts, so fields may grow
over time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from isabelle_blueprint.agents.memory import AgentMemory
from isabelle_blueprint.model.project import BlueprintProject

# Canonical outcome ordering for stable output. Mirrors ``VALID_OUTCOMES`` but
# ordered from "most resolved" to "least", which reads naturally in a table.
OUTCOME_ORDER = ("succeeded", "failed", "blocked", "needs_human", "note")

# Outcomes that count toward the success-rate denominator (a definitive result).
_RESOLVED_OUTCOMES = frozenset({"succeeded", "failed"})


@dataclass(frozen=True)
class NodeStat:
    """Per-node attempt roll-up."""

    node_id: str
    kind: str | None
    attempt_count: int
    outcomes: dict[str, int]
    last_outcome: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "attempt_count": self.attempt_count,
            "outcomes": dict(self.outcomes),
            "last_outcome": self.last_outcome,
        }


@dataclass(frozen=True)
class KindStat:
    """Per node-kind aggregate."""

    kind: str
    node_count: int
    attempt_count: int
    outcomes: dict[str, int]
    success_rate: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "node_count": self.node_count,
            "attempt_count": self.attempt_count,
            "outcomes": dict(self.outcomes),
            "success_rate": self.success_rate,
        }


@dataclass(frozen=True)
class StatsReport:
    """Aggregate analytics for one project's agent memory."""

    project: str
    total_attempts: int
    nodes_with_memory: int
    outcomes: dict[str, int]
    success_rate: float | None
    per_kind: list[KindStat] = field(default_factory=list)
    nodes: list[NodeStat] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "total_attempts": self.total_attempts,
            "nodes_with_memory": self.nodes_with_memory,
            "outcomes": dict(self.outcomes),
            "success_rate": self.success_rate,
            "per_kind": [k.to_dict() for k in self.per_kind],
            "nodes": [n.to_dict() for n in self.nodes],
        }


def _empty_counts() -> dict[str, int]:
    return {outcome: 0 for outcome in OUTCOME_ORDER}


def _success_rate(counts: dict[str, int]) -> float | None:
    resolved = sum(counts.get(o, 0) for o in _RESOLVED_OUTCOMES)
    if resolved == 0:
        return None
    return round(counts.get("succeeded", 0) / resolved, 4)


def build_stats_report(memory: AgentMemory, project: BlueprintProject) -> StatsReport:
    """Aggregate ``memory`` attempts, using ``project`` to resolve node kinds."""

    kind_by_id = {node.id: node.kind.value for node in project.nodes}

    overall = _empty_counts()
    per_kind_counts: dict[str, dict[str, int]] = {}
    per_kind_nodes: dict[str, set[str]] = {}
    node_stats: list[NodeStat] = []

    for node_id, node_memory in memory.nodes.items():
        attempts = node_memory.attempts
        if not attempts:
            continue
        kind = kind_by_id.get(node_id)
        node_counts = _empty_counts()
        for attempt in attempts:
            outcome = attempt.outcome if attempt.outcome in overall else "note"
            node_counts[outcome] += 1
            overall[outcome] += 1
            if kind is not None:
                per_kind_counts.setdefault(kind, _empty_counts())[outcome] += 1
        if kind is not None:
            per_kind_nodes.setdefault(kind, set()).add(node_id)
        node_stats.append(
            NodeStat(
                node_id=node_id,
                kind=kind,
                attempt_count=len(attempts),
                outcomes=node_counts,
                last_outcome=attempts[-1].outcome,
            )
        )

    node_stats.sort(key=lambda n: n.node_id)

    per_kind = [
        KindStat(
            kind=kind,
            node_count=len(per_kind_nodes.get(kind, set())),
            attempt_count=sum(counts.values()),
            outcomes=counts,
            success_rate=_success_rate(counts),
        )
        for kind, counts in sorted(per_kind_counts.items())
    ]

    return StatsReport(
        project=project.name,
        total_attempts=sum(overall.values()),
        nodes_with_memory=len(node_stats),
        outcomes=overall,
        success_rate=_success_rate(overall),
        per_kind=per_kind,
        nodes=node_stats,
    )


def _format_rate(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def render_stats_report(report: StatsReport) -> str:
    """Render ``report`` as human-facing text."""

    lines: list[str] = []
    lines.append(f"Agent memory stats for {report.project}")
    if report.total_attempts == 0:
        lines.append("  no attempts recorded yet")
        return "\n".join(lines) + "\n"

    lines.append(
        f"  {report.total_attempts} attempt(s) across "
        f"{report.nodes_with_memory} node(s); "
        f"success rate {_format_rate(report.success_rate)}"
    )
    lines.append("  outcomes:")
    for outcome in OUTCOME_ORDER:
        count = report.outcomes.get(outcome, 0)
        if count:
            lines.append(f"    {outcome:<12} {count}")

    if report.per_kind:
        lines.append("  by kind:")
        for kind in report.per_kind:
            lines.append(
                f"    {kind.kind:<14} "
                f"{kind.attempt_count} attempt(s), "
                f"{kind.node_count} node(s), "
                f"success {_format_rate(kind.success_rate)}"
            )

    return "\n".join(lines) + "\n"


def render_stats_markdown(report: StatsReport) -> str:
    """Render ``report`` as a Markdown document."""

    lines: list[str] = []
    lines.append(f"# Agent memory stats for {report.project}")
    lines.append("")

    if report.total_attempts == 0:
        lines.append("No attempts recorded yet.")
        return "\n".join(lines) + "\n"

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Total attempts | {report.total_attempts} |")
    lines.append(f"| Nodes with memory | {report.nodes_with_memory} |")
    lines.append(f"| Success rate | {_format_rate(report.success_rate)} |")
    lines.append("")

    lines.append("## Outcomes")
    lines.append("")
    lines.append("| Outcome | Count |")
    lines.append("| --- | --- |")
    for outcome in OUTCOME_ORDER:
        count = report.outcomes.get(outcome, 0)
        if count:
            lines.append(f"| {outcome} | {count} |")
    lines.append("")

    lines.append("## Per node")
    lines.append("")
    lines.append("| Node | Kind | Attempts | Last outcome |")
    lines.append("| --- | --- | --- | --- |")
    for node in report.nodes:
        lines.append(
            f"| {node.node_id} | {node.kind or 'n/a'} | "
            f"{node.attempt_count} | {node.last_outcome or 'n/a'} |"
        )

    return "\n".join(lines) + "\n"
