"""Direct one-hop neighbourhood of a single node.

``depends`` answers a deliberately narrow question: "what does this node use,
and who uses it?" - listing only the *direct* (one-hop) dependencies and
dependents of a single node. It is the focused complement to the transitive
views: ``impact`` walks the whole downstream blast radius, ``path`` finds a
chain between two nodes, and ``depends`` stops at the immediate neighbours.

A blueprint edge ``a -> b`` means *``a`` uses (depends on) ``b``*. So for a
target node:

* its **depends_on** set is the ids in its ``uses`` (the nodes it rests on), and
* its **depended_on_by** set is the nodes whose ``uses`` name it (its dependents).

Only real nodes appear: a ``uses`` entry that does not resolve to a known node is
a missing-dependency edge (surfaced by ``lint``/``critical-path``) and is omitted
here. No Isabelle invocation is required.
"""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject

DEPENDS_SCHEMA_VERSION = 1


class UnknownNodeError(KeyError):
    """Raised when the ``depends`` target id is not present in the project."""


@dataclass(frozen=True)
class Neighbour:
    """A single direct neighbour (dependency or dependent) of the target."""

    id: str
    kind: str
    formal_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "formal_status": self.formal_status,
        }


@dataclass(frozen=True)
class DependsReport:
    """A node's direct dependencies and direct dependents."""

    project: str
    node: str
    depends_on: list[Neighbour]
    depended_on_by: list[Neighbour]
    schema_version: int = DEPENDS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "node": self.node,
            "depends_on": [item.to_dict() for item in self.depends_on],
            "depended_on_by": [item.to_dict() for item in self.depended_on_by],
        }


def build_depends_report(project: BlueprintProject, node_id: str) -> DependsReport:
    """Compute the direct neighbourhood of ``node_id``.

    Raises :class:`UnknownNodeError` (carrying the offending id) when ``node_id``
    is not a known node. Both lists are sorted by id and contain only real
    nodes; missing-dependency edges are omitted.
    """

    by_id = project.by_id()
    if node_id not in by_id:
        raise UnknownNodeError(node_id)

    graph = build_graph(project)

    def neighbour(other_id: str) -> Neighbour:
        node = by_id[other_id]
        return Neighbour(
            id=other_id,
            kind=node.kind.value,
            formal_status=node.status.formal.value,
        )

    depends_on = [
        neighbour(dep) for dep in sorted(graph.edges.get(node_id, [])) if dep != node_id
    ]
    depended_on_by = [
        neighbour(dep)
        for dep in sorted(graph.reverse_edges.get(node_id, []))
        if dep != node_id
    ]

    return DependsReport(
        project=project.name,
        node=node_id,
        depends_on=depends_on,
        depended_on_by=depended_on_by,
    )


def render_depends_report(report: DependsReport) -> str:
    """Render the direct neighbourhood as compact Markdown for the terminal."""

    lines = [f"# {report.project} direct dependencies: `{report.node}`", ""]

    lines.append("Depends on:")
    if report.depends_on:
        for item in report.depends_on:
            lines.append(
                f"- `{item.id}` ({item.kind}, formal `{item.formal_status}`)"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("Depended on by:")
    if report.depended_on_by:
        for item in report.depended_on_by:
            lines.append(
                f"- `{item.id}` ({item.kind}, formal `{item.formal_status}`)"
            )
    else:
        lines.append("- (none)")

    return "\n".join(lines) + "\n"
