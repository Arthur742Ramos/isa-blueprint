"""Downstream *blast-radius* analysis: "what rests on this node?".

``impact`` is the downstream complement to ``critical-path``:

* ``critical-path`` walks *upstream* over dependencies to find the longest
  remaining incomplete chain and ranks bottleneck nodes by how many *incomplete*
  nodes depend on them (leverage). It only ever counts remaining work.
* ``impact`` walks *downstream* over dependents to measure the **blast radius**
  of a node - every node that would be affected (directly or transitively) if
  this node changed or broke. It counts *all* dependents regardless of status.

The distinction matters. A foundational lemma that is already ``proved`` has a
``critical-path`` leverage of ``0`` (nothing *incomplete* depends on it) yet an
enormous blast radius (much of the project rests on it). ``impact`` surfaces that
risk so you can see which trusted facts a change would invalidate.

Definitions used throughout this module:

* The **blast radius** of a node is the set of nodes that transitively depend on
  it (its downstream cone). Each affected node carries the **distance** - the
  shortest number of dependency hops from the target out to that node.
* An **affected goal** is a node in the blast radius that itself has no
  dependents: a terminal project target that ultimately rests on the node.
* A **complete affected** node is one in the blast radius whose formal status is
  ``found`` or ``proved`` - a currently-trusted fact that would go stale if the
  target node broke or changed.

Nodes participating in a dependency cycle are still traversed (so the blast
radius stays honest), but the cycle membership of the *target* is reported via
``in_cycle`` because its own ordering relative to the cycle is ambiguous.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from isabelle_blueprint.errors import UnknownNodeError
from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import COMPLETE_FORMAL_STATUSES
from isabelle_blueprint.report.mermaid import mermaid_label, mermaid_node_id

IMPACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AffectedNode:
    """A single node inside a target's blast radius."""

    node_id: str
    title: str
    formal_status: str
    distance: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "distance": self.distance,
        }


@dataclass(frozen=True)
class ImpactReport:
    """The downstream blast radius for a single target node."""

    node_id: str
    title: str
    formal_status: str
    in_cycle: bool
    direct_dependents: list[str]
    blast_radius: list[AffectedNode]
    affected_goals: list[str]
    complete_affected: list[str]

    @property
    def blast_radius_count(self) -> int:
        return len(self.blast_radius)

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "in_cycle": self.in_cycle,
            "direct_dependent_count": len(self.direct_dependents),
            "blast_radius_count": self.blast_radius_count,
            "direct_dependents": list(self.direct_dependents),
            "blast_radius": [item.to_dict() for item in self.blast_radius],
            "affected_goals": list(self.affected_goals),
            "complete_affected": list(self.complete_affected),
        }


@dataclass(frozen=True)
class ImpactRank:
    """A node ranked by the size of its downstream blast radius."""

    node_id: str
    title: str
    formal_status: str
    blast_radius_count: int
    direct_dependent_count: int
    affected_goal_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "blast_radius_count": self.blast_radius_count,
            "direct_dependent_count": self.direct_dependent_count,
            "affected_goal_count": self.affected_goal_count,
        }


@dataclass(frozen=True)
class ImpactOverview:
    """Project-wide ranking of nodes by blast radius."""

    project: str
    node_count: int
    rankings: list[ImpactRank]
    cycles: list[list[str]] = field(default_factory=list)
    schema_version: int = IMPACT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "node_count": self.node_count,
            "rankings": [rank.to_dict() for rank in self.rankings],
            "cycles": [list(cycle) for cycle in self.cycles],
        }


def _build_context(project: BlueprintProject):
    by_id = project.by_id()
    graph = build_graph(project)
    cycle_nodes = {node_id for cycle in project.validate().cycles for node_id in cycle}
    return by_id, graph, cycle_nodes


def _blast_radius(graph, start: str) -> dict[str, int]:
    """BFS shortest-hop distances over reverse edges (dependents).

    Returns a mapping of ``dependent_id -> distance`` excluding ``start``. The
    visited guard keeps the traversal finite even when ``start`` sits in a
    dependency cycle.
    """

    distances: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((dep, 1) for dep in graph.reverse_edges.get(start, []))
    while queue:
        node_id, dist = queue.popleft()
        if node_id == start:
            continue
        existing = distances.get(node_id)
        if existing is not None and existing <= dist:
            continue
        distances[node_id] = dist
        for child in graph.reverse_edges.get(node_id, []):
            queue.append((child, dist + 1))
    return distances


def build_impact_report(project: BlueprintProject, node_id: str) -> ImpactReport:
    """Compute the downstream blast radius for a single ``node_id``.

    Raises :class:`UnknownNodeError` when ``node_id`` is not a known node.
    """

    by_id, graph, cycle_nodes = _build_context(project)
    target = by_id.get(node_id)
    if target is None:
        raise UnknownNodeError(node_id)

    distances = _blast_radius(graph, node_id)

    affected = [
        AffectedNode(
            node_id=dep_id,
            title=by_id[dep_id].title if dep_id in by_id else "",
            formal_status=(by_id[dep_id].status.formal.value if dep_id in by_id else "missing"),
            distance=distance,
        )
        for dep_id, distance in distances.items()
    ]
    affected.sort(key=lambda item: (item.distance, item.node_id))

    direct_dependents = sorted(
        dep for dep in graph.reverse_edges.get(node_id, []) if dep != node_id
    )

    affected_goals = sorted(
        dep_id
        for dep_id in distances
        if not [child for child in graph.reverse_edges.get(dep_id, []) if child != dep_id]
    )

    complete_affected = sorted(
        dep_id
        for dep_id in distances
        if dep_id in by_id and by_id[dep_id].status.formal in COMPLETE_FORMAL_STATUSES
    )

    return ImpactReport(
        node_id=node_id,
        title=target.title,
        formal_status=target.status.formal.value,
        in_cycle=node_id in cycle_nodes,
        direct_dependents=direct_dependents,
        blast_radius=affected,
        affected_goals=affected_goals,
        complete_affected=complete_affected,
    )


def build_impact_overview(project: BlueprintProject) -> ImpactOverview:
    """Rank every node by the size of its downstream blast radius."""

    graph = build_graph(project)
    cycles = project.validate().cycles
    rankings = []
    for node in project.nodes:
        distances = _blast_radius(graph, node.id)
        affected_goal_count = sum(
            1
            for dep_id in distances
            if not [child for child in graph.reverse_edges.get(dep_id, []) if child != dep_id]
        )
        rankings.append(
            ImpactRank(
                node_id=node.id,
                title=node.title,
                formal_status=node.status.formal.value,
                blast_radius_count=len(distances),
                direct_dependent_count=len(
                    [dep for dep in graph.reverse_edges.get(node.id, []) if dep != node.id]
                ),
                affected_goal_count=affected_goal_count,
            )
        )
    rankings.sort(key=lambda rank: (-rank.blast_radius_count, rank.node_id))

    return ImpactOverview(
        project=project.name,
        node_count=len(project.nodes),
        rankings=rankings,
        cycles=[list(cycle) for cycle in cycles],
    )


def impact_report_payload(report: ImpactReport) -> dict[str, object]:
    """Return the JSON payload for a single-node impact report."""

    return report.to_dict()


def impact_overview_payload(
    overview: ImpactOverview, *, top: int | None = None
) -> dict[str, object]:
    """Return the JSON payload, optionally limiting the ranking list."""

    payload = overview.to_dict()
    if top is not None:
        payload["rankings"] = payload["rankings"][:top]  # type: ignore[index]
    return payload


def render_impact_report(report: ImpactReport, *, top: int = 10) -> str:
    """Render a single-node blast-radius report as compact Markdown."""

    from isabelle_blueprint import console

    lines = [f"# {report.title or report.node_id} impact", ""]
    lines.append(f"Target `{report.node_id}` - {report.title} (formal `{report.formal_status}`)")
    if report.in_cycle:
        lines.append(console.warning("Note: this node participates in a dependency cycle."))
    lines.append(
        f"Blast radius: {report.blast_radius_count} node(s) depend on it "
        f"({len(report.direct_dependents)} directly)."
    )
    lines.append("")

    if report.blast_radius_count == 0:
        lines.append(console.success("Nothing depends on this node - changes are self-contained."))
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.extend(["## Blast radius", ""])
    for item in report.blast_radius[:top]:
        lines.append(
            f"- `{item.node_id}` - {item.title} "
            f"(distance `{item.distance}`, formal `{item.formal_status}`)"
        )
    hidden = report.blast_radius_count - top
    if hidden > 0:
        lines.append(console.dim(f"  ... and {hidden} more"))
    lines.append("")

    if report.affected_goals:
        lines.extend(["## Affected goals", ""])
        for goal_id in report.affected_goals:
            lines.append(f"- `{goal_id}`")
        lines.append("")

    if report.complete_affected:
        lines.extend(["## Complete dependents at risk", ""])
        lines.append(
            console.warning(
                "These trusted (found/proved) facts transitively rest on the target "
                "and would go stale if it changed:"
            )
        )
        for dep_id in report.complete_affected:
            lines.append(f"- `{dep_id}`")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def _impact_dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_impact_dot(project: BlueprintProject, node_id: str) -> str:
    """Return a Graphviz DOT subgraph of ``node_id`` and its blast radius.

    The subgraph contains the focus node plus every downstream dependent, with
    edges following ``uses`` (drawn from dependent to dependency, matching the
    project's dependency-graph orientation). The focus node is highlighted.
    Raises :class:`UnknownNodeError` when ``node_id`` is not a known node.
    """

    by_id, graph, _cycle_nodes = _build_context(project)
    if node_id not in by_id:
        raise UnknownNodeError(node_id)

    distances = _blast_radius(graph, node_id)
    members = [node_id] + sorted(distances, key=lambda dep: (distances[dep], dep))
    member_set = set(members)

    lines = [
        f'digraph "impact_{_impact_dot_escape(node_id)}" {{',
        '  graph [rankdir=BT, splines=true, bgcolor="white", fontname="Helvetica"];',
        '  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11];',
        '  edge  [color="#94a3b8"];',
    ]
    for member in members:
        node = by_id[member]
        member_id = _impact_dot_escape(member)
        label = _impact_dot_escape(f"{node.id}\n{node.title}")
        if member == node_id:
            lines.append(
                f'  "{member_id}" [label="{label}", fillcolor="#fde047", '
                f'color="#1f2937", penwidth=2];'
            )
        else:
            lines.append(
                f'  "{member_id}" [label="{label}", fillcolor="#e5e7eb", color="#1f2937"];'
            )
    for src in members:
        for dep in graph.edges.get(src, []):
            if dep in member_set:
                lines.append(f'  "{_impact_dot_escape(src)}" -> "{_impact_dot_escape(dep)}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_impact_mermaid(project: BlueprintProject, node_id: str) -> str:
    """Return a Mermaid ``flowchart`` of ``node_id`` and its blast radius.

    Mirrors :func:`render_impact_dot` exactly but in Mermaid syntax: the focus
    node plus every downstream dependent, edges following ``uses`` (drawn from
    dependent to dependency), with the focus node highlighted. Raises
    :class:`UnknownNodeError` when ``node_id`` is not a known node.
    """

    by_id, graph, _cycle_nodes = _build_context(project)
    if node_id not in by_id:
        raise UnknownNodeError(node_id)

    distances = _blast_radius(graph, node_id)
    members = [node_id] + sorted(distances, key=lambda dep: (distances[dep], dep))
    member_set = set(members)

    lines = ["flowchart BT"]
    for member in members:
        node = by_id[member]
        safe = mermaid_node_id(member)
        label = mermaid_label(f"{node.id}\n{node.title}")
        lines.append(f'  {safe}["{label}"]')
    for src in members:
        for dep in graph.edges.get(src, []):
            if dep in member_set:
                lines.append(f"  {mermaid_node_id(src)} --> {mermaid_node_id(dep)}")
    lines.append(f"  style {mermaid_node_id(node_id)} fill:#fde047,stroke:#1f2937,color:#111827")
    return "\n".join(lines) + "\n"


def render_impact_report_csv(report: ImpactReport) -> str:
    """Return the single-node blast radius as CSV (one row per dependent).

    Columns: ``dependent_id``, ``distance``. Rows follow the same ordering as
    the Markdown/JSON report (shortest distance first, then node id).
    """

    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["dependent_id", "distance"])
    for item in report.blast_radius:
        writer.writerow([item.node_id, item.distance])
    return out.getvalue()


def render_impact_overview_csv(overview: ImpactOverview, *, top: int | None = None) -> str:
    """Return the project-wide blast-radius ranking as CSV (one row per node).

    Columns: ``node_id``, ``direct_dependent_count``, ``blast_radius_count``,
    ``affected_goal_count``. Rows follow the same ranking order as the
    JSON/Markdown overview (largest blast radius first, ties broken by node id).
    """

    import csv
    import io

    rankings = overview.rankings if top is None else overview.rankings[:top]

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "node_id",
            "direct_dependent_count",
            "blast_radius_count",
            "affected_goal_count",
        ]
    )
    for rank in rankings:
        writer.writerow(
            [
                rank.node_id,
                rank.direct_dependent_count,
                rank.blast_radius_count,
                rank.affected_goal_count,
            ]
        )
    return out.getvalue()


def render_impact_overview(overview: ImpactOverview, *, top: int = 10) -> str:
    """Render the project-wide blast-radius ranking as compact Markdown."""

    from isabelle_blueprint import console

    lines = [f"# {overview.project} impact ranking", ""]
    if overview.node_count == 0:
        lines.append(console.dim("No nodes in the blueprint."))
        return "\n".join(lines).rstrip("\n") + "\n"

    ranked = [rank for rank in overview.rankings if rank.blast_radius_count > 0]
    lines.append(f"{overview.node_count} node(s); {len(ranked)} have downstream dependents.")
    lines.append("")

    if not ranked:
        lines.append(console.dim("No node has dependents - every node is independent."))
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.extend(["## Highest blast radius", ""])
    for rank in ranked[:top]:
        lines.append(
            f"- `{rank.node_id}` - {rank.title} "
            f"(blast `{rank.blast_radius_count}`, direct `{rank.direct_dependent_count}`, "
            f"formal `{rank.formal_status}`)"
        )
    hidden = len(ranked) - top
    if hidden > 0:
        lines.append(console.dim(f"  ... and {hidden} more"))
    lines.append("")

    if overview.cycles:
        lines.extend(["## Cycles", ""])
        lines.append(
            console.error(
                "Dependency cycles were detected; blast radii of nodes in a cycle "
                "include the cyclic dependents:"
            )
        )
        for cycle in overview.cycles:
            lines.append("- " + " -> ".join(f"`{node_id}`" for node_id in cycle))
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
