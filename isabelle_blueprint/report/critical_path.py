"""Longest-pole analysis of the *remaining* (incomplete) proof work.

``critical-path`` answers the headline planning question "which theorem is
blocking this proof, and what is the longest sequence of proofs I still have to
finish?". It is the structural, project-wide complement to ``roadmap``:

* ``roadmap``'s ``suggested_path`` walks *downstream* from the current next
  ready task (what to attempt next, in order).
* ``critical-path`` walks *upstream* over dependencies to measure how deep the
  remaining work is for every terminal goal, and ranks the bottleneck nodes
  that unblock the most downstream work.

Definitions used throughout this module:

* A node is **complete** when its formal status is :data:`COMPLETE_FORMAL_STATUSES`
  (``found`` or ``proved``); every other status counts as **incomplete**.
* A **goal** is an incomplete node that no other incomplete node depends on -
  the terminal remaining targets of the project.
* The **critical depth** of an incomplete node is the number of incomplete
  nodes on the longest dependency chain ending at it (an incomplete node with
  no incomplete dependencies has depth ``1``).
* The **leverage** of a node is the number of incomplete nodes that depend on
  it (transitively) - completing a high-leverage node unblocks the most work.

Nodes that participate in a dependency cycle are excluded from depth, path, and
leverage ranking (their ordering would be arbitrary) and surfaced in a separate
cycles section instead. Note this is a *remaining-work* longest path, not a
scheduler-style weighted critical path: there is no duration/effort weighting.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.roadmap import COMPLETE_FORMAL_STATUSES

CRITICAL_PATH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GoalChain:
    """The longest incomplete dependency chain ending at a goal node."""

    goal_id: str
    title: str
    formal_status: str
    depth: int
    path: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "depth": self.depth,
            "path": list(self.path),
        }


@dataclass(frozen=True)
class Bottleneck:
    """An incomplete node ranked by how much downstream work it unblocks."""

    node_id: str
    title: str
    formal_status: str
    leverage: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "leverage": self.leverage,
        }


@dataclass(frozen=True)
class InconsistentNode:
    """A complete node that still depends on incomplete work (stale metadata)."""

    node_id: str
    incomplete_dependencies: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "incomplete_dependencies": list(self.incomplete_dependencies),
        }


@dataclass(frozen=True)
class MissingDependency:
    """A node whose ``uses`` references one or more unknown node ids."""

    node_id: str
    missing: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"node_id": self.node_id, "missing": list(self.missing)}


@dataclass(frozen=True)
class CriticalPathOverview:
    """Project-wide critical-path analysis."""

    project: str
    remaining_count: int
    goal_count: int
    longest: GoalChain | None
    goals: list[GoalChain]
    bottlenecks: list[Bottleneck]
    cycles: list[list[str]] = field(default_factory=list)
    missing_dependencies: list[MissingDependency] = field(default_factory=list)
    inconsistent: list[InconsistentNode] = field(default_factory=list)
    schema_version: int = CRITICAL_PATH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "remaining_count": self.remaining_count,
            "goal_count": self.goal_count,
            "longest": self.longest.to_dict() if self.longest else None,
            "goals": [goal.to_dict() for goal in self.goals],
            "bottlenecks": [b.to_dict() for b in self.bottlenecks],
            "cycles": [list(cycle) for cycle in self.cycles],
            "missing_dependencies": [m.to_dict() for m in self.missing_dependencies],
            "inconsistent": [i.to_dict() for i in self.inconsistent],
        }


def build_critical_path(project: BlueprintProject) -> CriticalPathOverview:
    """Compute the critical-path analysis for ``project``."""

    by_id = project.by_id()
    graph = build_graph(project)
    validation = project.validate()
    cycle_nodes = {node_id for cycle in validation.cycles for node_id in cycle}

    def is_incomplete(node_id: str) -> bool:
        node = by_id.get(node_id)
        return node is not None and node.status.formal not in COMPLETE_FORMAL_STATUSES

    # "Relevant" = incomplete work we can order: excludes complete nodes and any
    # node tangled in a cycle (whose position in a chain would be arbitrary).
    def is_relevant(node_id: str) -> bool:
        return is_incomplete(node_id) and node_id not in cycle_nodes

    relevant_ids = sorted(node.id for node in project.nodes if is_relevant(node.id))
    remaining_count = sum(1 for node in project.nodes if is_incomplete(node.id))

    def relevant_deps(node_id: str) -> list[str]:
        return sorted(dep for dep in graph.edges.get(node_id, []) if is_relevant(dep))

    def relevant_dependents(node_id: str) -> list[str]:
        return sorted(
            child for child in graph.reverse_edges.get(node_id, []) if is_relevant(child)
        )

    # Longest incomplete dependency chain ending at each relevant node, memoised
    # with a visiting guard so any residual self-reference stays finite.
    chain_memo: dict[str, list[str]] = {}
    visiting: set[str] = set()

    def longest_chain(node_id: str) -> list[str]:
        if node_id in chain_memo:
            return chain_memo[node_id]
        if node_id in visiting:
            return [node_id]
        visiting.add(node_id)
        best: list[str] = []
        for dep in relevant_deps(node_id):
            candidate = longest_chain(dep)
            if _chain_key(candidate) > _chain_key(best):
                best = candidate
        visiting.discard(node_id)
        chain = best + [node_id]
        chain_memo[node_id] = chain
        return chain

    # Transitive count of incomplete dependents (leverage / bottleneck score).
    leverage_memo: dict[str, set[str]] = {}
    lev_visiting: set[str] = set()

    def descendants(node_id: str) -> set[str]:
        if node_id in leverage_memo:
            return leverage_memo[node_id]
        if node_id in lev_visiting:
            return set()
        lev_visiting.add(node_id)
        found: set[str] = set()
        for child in relevant_dependents(node_id):
            found.add(child)
            found |= descendants(child)
        lev_visiting.discard(node_id)
        leverage_memo[node_id] = found
        return found

    goal_ids = [node_id for node_id in relevant_ids if not relevant_dependents(node_id)]
    goals = [
        GoalChain(
            goal_id=node_id,
            title=by_id[node_id].title,
            formal_status=by_id[node_id].status.formal.value,
            depth=len(longest_chain(node_id)),
            path=longest_chain(node_id),
        )
        for node_id in goal_ids
    ]
    goals.sort(key=lambda goal: (-goal.depth, goal.goal_id))
    longest = goals[0] if goals else None

    bottlenecks = [
        Bottleneck(
            node_id=node_id,
            title=by_id[node_id].title,
            formal_status=by_id[node_id].status.formal.value,
            leverage=len(descendants(node_id)),
        )
        for node_id in relevant_ids
    ]
    bottlenecks = [b for b in bottlenecks if b.leverage > 0]
    bottlenecks.sort(key=lambda b: (-b.leverage, b.node_id))

    known = set(by_id)
    missing_dependencies = [
        MissingDependency(
            node_id=node.id,
            missing=sorted({dep for dep in node.uses if dep not in known}),
        )
        for node in project.nodes
        if any(dep not in known for dep in node.uses)
    ]
    missing_dependencies.sort(key=lambda m: m.node_id)

    inconsistent = [
        InconsistentNode(
            node_id=node.id,
            incomplete_dependencies=sorted(
                dep for dep in graph.edges.get(node.id, []) if is_incomplete(dep)
            ),
        )
        for node in project.nodes
        if node.status.formal in COMPLETE_FORMAL_STATUSES
        and any(is_incomplete(dep) for dep in graph.edges.get(node.id, []))
    ]
    inconsistent.sort(key=lambda i: i.node_id)

    return CriticalPathOverview(
        project=project.name,
        remaining_count=remaining_count,
        goal_count=len(goals),
        longest=longest,
        goals=goals,
        bottlenecks=bottlenecks,
        cycles=[list(cycle) for cycle in validation.cycles],
        missing_dependencies=missing_dependencies,
        inconsistent=inconsistent,
    )


def goal_chain_for(overview: CriticalPathOverview, node_id: str) -> GoalChain | None:
    """Return the recorded goal chain for ``node_id`` if it is a goal."""

    for goal in overview.goals:
        if goal.goal_id == node_id:
            return goal
    return None


def critical_path_payload(
    overview: CriticalPathOverview, *, top: int | None = None
) -> dict[str, object]:
    """Return the JSON payload, optionally limiting the bottleneck list."""

    payload = overview.to_dict()
    if top is not None:
        payload["bottlenecks"] = payload["bottlenecks"][:top]  # type: ignore[index]
    return payload


def render_critical_path(
    overview: CriticalPathOverview,
    *,
    top: int = 5,
    goal: str | None = None,
) -> str:
    """Render the analysis as compact Markdown for the terminal or a file."""

    from isabelle_blueprint import console

    lines = [f"# {overview.project} critical path", ""]

    if goal is not None:
        return "\n".join(_render_single_goal(overview, goal, console)).rstrip("\n") + "\n"

    if overview.remaining_count == 0:
        lines.append(console.success("All formal targets are complete - no remaining work."))
        lines.append("")
        _append_cycles(lines, overview, console)
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.append(
        f"Remaining: {overview.remaining_count} incomplete node(s) across "
        f"{overview.goal_count} goal(s)."
    )
    if overview.longest is not None:
        lines.append(
            f"Critical path ({overview.longest.depth} step(s)): "
            + _format_path(overview.longest.path)
        )
    else:
        lines.append("Critical path: none (remaining work is tangled in cycles).")
    lines.append("")

    lines.extend(["## Goals", ""])
    if overview.goals:
        for goal_chain in overview.goals:
            lines.append(
                f"- `{goal_chain.goal_id}` - {goal_chain.title} "
                f"(depth `{goal_chain.depth}`): " + _format_path(goal_chain.path)
            )
    else:
        lines.append("_(no goals outside of cycles)_")
    lines.append("")

    lines.extend(["## Bottlenecks", ""])
    if overview.bottlenecks:
        for bottleneck in overview.bottlenecks[:top]:
            lines.append(
                f"- `{bottleneck.node_id}` - {bottleneck.title} "
                f"(unblocks `{bottleneck.leverage}` node(s), "
                f"formal `{bottleneck.formal_status}`)"
            )
        hidden = len(overview.bottlenecks) - top
        if hidden > 0:
            lines.append(console.dim(f"  ... and {hidden} more"))
    else:
        lines.append("_(no node unblocks others - the remaining work is independent)_")
    lines.append("")

    if overview.inconsistent:
        lines.extend(["## Inconsistent (complete but depends on incomplete)", ""])
        for item in overview.inconsistent:
            deps = ", ".join(f"`{dep}`" for dep in item.incomplete_dependencies)
            lines.append(console.warning(f"- `{item.node_id}` depends on {deps}"))
        lines.append("")

    if overview.missing_dependencies:
        lines.extend(["## Missing dependencies", ""])
        for missing_item in overview.missing_dependencies:
            deps = ", ".join(f"`{dep}`" for dep in missing_item.missing)
            lines.append(console.error(f"- `{missing_item.node_id}` references unknown {deps}"))
        lines.append("")

    _append_cycles(lines, overview, console)

    return "\n".join(lines).rstrip("\n") + "\n"


def _render_single_goal(overview: CriticalPathOverview, node_id: str, console) -> list[str]:
    lines = [f"# {overview.project} critical path", ""]
    goal_chain = goal_chain_for(overview, node_id)
    if goal_chain is None:
        lines.append(
            console.warning(
                f"`{node_id}` is not a remaining goal "
                "(it is complete, unknown, has incomplete dependents, or is in a cycle)."
            )
        )
        lines.append("")
        return lines
    lines.append(
        f"Goal `{goal_chain.goal_id}` - {goal_chain.title} "
        f"(depth `{goal_chain.depth}`, formal `{goal_chain.formal_status}`)"
    )
    lines.append("Path: " + _format_path(goal_chain.path))
    lines.append("")
    return lines


def _append_cycles(lines: list[str], overview: CriticalPathOverview, console) -> None:
    if not overview.cycles:
        return
    lines.extend(["## Cycles", ""])
    lines.append(
        console.error(
            "Dependency cycles were detected; their nodes are excluded from the "
            "critical-path ranking until resolved:"
        )
    )
    for cycle in overview.cycles:
        lines.append("- " + " -> ".join(f"`{node_id}`" for node_id in cycle))
    lines.append("")


def critical_path_strict_failures(overview: CriticalPathOverview) -> list[str]:
    """Return human-readable strings describing cycle failures, if any."""

    return [
        "cycle: " + " -> ".join(cycle)
        for cycle in overview.cycles
    ]


def _format_path(path: Iterable[str]) -> str:
    rendered = " -> ".join(f"`{node_id}`" for node_id in path)
    return rendered or "none"


def _chain_key(chain: list[str]) -> tuple[int, list[str]]:
    # Longest chain wins; ties broken lexicographically for determinism.
    return (len(chain), chain)
