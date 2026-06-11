"""Shortest dependency path between two nodes.

``path`` answers "how does ``a`` depend on ``b`` (or vice versa)?" by finding
the shortest chain of ``uses`` edges connecting two node ids. A blueprint edge
``a -> b`` means *``a`` uses (depends on) ``b``*, so a forward path
``a -> ... -> b`` shows ``a`` transitively depending on ``b``.

The search is direction-aware: it first looks for a path *from* ``source`` *to*
``target`` (``source`` depends on ``target``); if there is none it looks the
other way (``target`` depends on ``source``) and reports which direction it
found. Ties between equal-length paths are broken deterministically by visiting
each node's dependencies in sorted order. Missing-dependency edges are ignored
(they are not real nodes); use ``lint``/``critical-path`` to surface those. No
Isabelle invocation is required.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject

PATH_SCHEMA_VERSION = 1

# ``direction`` values reported by :func:`build_path_report`.
DIRECTION_SELF = "self"
DIRECTION_DEPENDS_ON = "depends-on"  # source -> ... -> target (source uses target)
DIRECTION_DEPENDED_ON_BY = "depended-on-by"  # target -> ... -> source (target uses source)


class UnknownNodeError(KeyError):
    """Raised when a ``path`` endpoint id is not present in the project."""


@dataclass(frozen=True)
class PathReport:
    """The shortest dependency chain connecting two nodes (if any)."""

    project: str
    source: str
    target: str
    source_title: str
    target_title: str
    found: bool
    direction: str | None
    path: list[str]
    length: int
    schema_version: int = PATH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "source": self.source,
            "target": self.target,
            "source_title": self.source_title,
            "target_title": self.target_title,
            "found": self.found,
            "direction": self.direction,
            "path": list(self.path),
            "length": self.length,
        }


def build_path_report(project: BlueprintProject, source: str, target: str) -> PathReport:
    """Find the shortest dependency path between ``source`` and ``target``.

    Raises :class:`UnknownNodeError` (carrying the offending id) when either
    endpoint is not a known node.
    """

    by_id = project.by_id()
    if source not in by_id:
        raise UnknownNodeError(source)
    if target not in by_id:
        raise UnknownNodeError(target)

    graph = build_graph(project)

    def make(found: bool, direction: str | None, path: list[str]) -> PathReport:
        return PathReport(
            project=project.name,
            source=source,
            target=target,
            source_title=by_id[source].title,
            target_title=by_id[target].title,
            found=found,
            direction=direction,
            path=path,
            length=max(len(path) - 1, 0) if found else 0,
        )

    if source == target:
        return make(True, DIRECTION_SELF, [source])

    forward = _shortest_path(graph.edges, source, target)
    if forward is not None:
        return make(True, DIRECTION_DEPENDS_ON, forward)

    backward = _shortest_path(graph.edges, target, source)
    if backward is not None:
        return make(True, DIRECTION_DEPENDED_ON_BY, backward)

    return make(False, None, [])


def render_path_report(report: PathReport) -> str:
    """Render the path report as compact Markdown for the terminal."""

    lines = [f"# {report.project} dependency path", ""]
    if not report.found:
        lines.append(
            f"`{report.source}` and `{report.target}` are not connected by dependencies."
        )
        return "\n".join(lines) + "\n"

    if report.direction == DIRECTION_SELF:
        lines.append(f"`{report.source}` is the same node (0 step(s)).")
        return "\n".join(lines) + "\n"

    if report.direction == DIRECTION_DEPENDS_ON:
        summary = f"`{report.source}` depends on `{report.target}`"
    else:
        summary = f"`{report.target}` depends on `{report.source}`"
    lines.append(f"{summary} ({report.length} step(s)).")
    lines.append("Path: " + " -> ".join(f"`{node_id}`" for node_id in report.path))
    return "\n".join(lines) + "\n"


def _shortest_path(
    edges: dict[str, list[str]], start: str, goal: str
) -> list[str] | None:
    """Breadth-first shortest path from ``start`` to ``goal`` along ``edges``.

    Neighbours are visited in sorted order so that, among equal-length paths,
    the lexicographically smallest predecessor wins - making the result stable.
    """

    if start == goal:
        return [start]
    parents: dict[str, str] = {start: start}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in sorted(edges.get(current, [])):
            if neighbour in parents:
                continue
            parents[neighbour] = current
            if neighbour == goal:
                return _reconstruct(parents, start, goal)
            queue.append(neighbour)
    return None


def _reconstruct(parents: dict[str, str], start: str, goal: str) -> list[str]:
    chain = [goal]
    while chain[-1] != start:
        chain.append(parents[chain[-1]])
    chain.reverse()
    return chain
