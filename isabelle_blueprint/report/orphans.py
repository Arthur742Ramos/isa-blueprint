"""Unreachable-node analysis: nodes disconnected from the project goals.

``orphans`` finds the nodes that no top-level goal is building towards. The
*goals* of a blueprint are its root results - nodes that nothing else ``uses``
(no incoming dependency edge) and that themselves ``use`` at least one
sub-result. Starting from those goals, the analysis walks the uses-dependency
graph; any node it never reaches is an **orphan**: dead planning weight or a
forgotten sub-result that no goal depends on.

This deliberately catches more than ``lint``'s ``isolated-node`` rule, which
only flags a single node of zero degree. ``orphans`` also surfaces whole
disconnected *subgraphs* - for example a self-contained dependency cycle that no
goal can reach, where every member has edges yet none is a root. A node with no
dependencies *and* no dependents is reported as ``isolated`` (a subset of the
orphans). No Isabelle invocation is required.
"""
from __future__ import annotations

import csv
import io
from collections import deque
from dataclasses import dataclass

from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report._markdown import md_cell as _escape_cell

ORPHANS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OrphanNode:
    """A single node not reachable from any project goal."""

    id: str
    kind: str
    formal_status: str
    isolated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "formal_status": self.formal_status,
            "isolated": self.isolated,
        }


@dataclass(frozen=True)
class OrphanReport:
    """The orphans (and the isolated subset) of a :class:`BlueprintProject`."""

    project: str
    orphan_count: int
    orphans: tuple[OrphanNode, ...]
    schema_version: int = ORPHANS_SCHEMA_VERSION

    @property
    def isolated_count(self) -> int:
        return sum(1 for orphan in self.orphans if orphan.isolated)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "orphan_count": self.orphan_count,
            "orphans": [orphan.to_dict() for orphan in self.orphans],
        }


def build_orphan_report(project: BlueprintProject) -> OrphanReport:
    """Compute the :class:`OrphanReport` for ``project``.

    A *goal* is a root (no incoming dependency edge) that itself depends on at
    least one node. Every node reachable from a goal along ``uses`` edges is
    justified; the rest are orphans, listed by id. A node with neither
    dependencies nor dependents is flagged ``isolated``.
    """

    graph = build_graph(project)
    goals = [
        node_id
        for node_id in graph.nodes
        if not graph.reverse_edges.get(node_id) and graph.edges.get(node_id)
    ]

    reachable: set[str] = set()
    queue: deque[str] = deque(goals)
    reachable.update(goals)
    while queue:
        current = queue.popleft()
        for dep in graph.edges.get(current, []):
            if dep not in reachable:
                reachable.add(dep)
                queue.append(dep)

    by_id = project.by_id()
    orphans: list[OrphanNode] = []
    for node_id in sorted(set(graph.nodes) - reachable):
        node = by_id[node_id]
        isolated = not graph.edges.get(node_id) and not graph.reverse_edges.get(node_id)
        orphans.append(
            OrphanNode(
                id=node_id,
                kind=node.kind.value,
                formal_status=node.status.formal.value,
                isolated=isolated,
            )
        )

    return OrphanReport(
        project=project.name,
        orphan_count=len(orphans),
        orphans=tuple(orphans),
    )


def _render_orphan_table(report: OrphanReport) -> str:
    """Render the heading, summary and Markdown table for a non-empty report.

    Shared by :func:`render_orphan_report` and :func:`render_orphans_markdown`
    so the two only differ in how they handle the clean/empty case.
    """

    lines = [f"# {report.project} orphans", ""]
    lines.append(
        f"{report.orphan_count} orphan node(s) unreachable from any goal "
        f"({report.isolated_count} fully isolated)."
    )
    lines.extend(
        [
            "",
            "| Node | Kind | Formal status | Isolated |",
            "| --- | --- | --- | --- |",
        ]
    )
    for orphan in report.orphans:
        isolated = "yes" if orphan.isolated else "no"
        lines.append(
            f"| {_escape_cell(orphan.id)} | {orphan.kind} | "
            f"{orphan.formal_status} | {isolated} |"
        )
    return "\n".join(lines) + "\n"


def render_orphan_report(report: OrphanReport) -> str:
    """Render the orphan report as compact Markdown for the terminal."""

    if not report.orphans:
        return (
            f"{report.project}: No orphan nodes "
            "(every node is reachable from a project goal).\n"
        )

    return _render_orphan_table(report)


def render_orphans_markdown(report: OrphanReport) -> str:
    """Render the orphan list as a standalone Markdown document.

    Columns: id, kind, formal status, isolated. Id cells are escaped so a
    ``|`` in a node id cannot break the table. The clean case renders a single
    note line under the heading with no table.
    """

    if report.orphans:
        return _render_orphan_table(report)
    return f"# {report.project} orphans\n\n_(no orphan nodes)_\n"


ORPHANS_CSV_COLUMNS = ("id", "kind", "formal_status", "isolated")


def render_orphans_csv(report: OrphanReport) -> str:
    """Render the orphan list as CSV: a header plus one row per orphan.

    Columns: id, kind, formal_status, isolated. The clean case emits just the
    header row.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ORPHANS_CSV_COLUMNS)
    for orphan in report.orphans:
        writer.writerow(
            [
                orphan.id,
                orphan.kind,
                orphan.formal_status,
                "true" if orphan.isolated else "false",
            ]
        )
    return buffer.getvalue()
