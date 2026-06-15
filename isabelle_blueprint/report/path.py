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
from dataclasses import dataclass, field

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
    paths: list[list[str]] = field(default_factory=list)
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
            "paths": [list(p) for p in self.paths],
        }


def build_path_report(
    project: BlueprintProject,
    source: str,
    target: str,
    *,
    all_paths: bool = False,
) -> PathReport:
    """Find the shortest dependency path between ``source`` and ``target``.

    Raises :class:`UnknownNodeError` (carrying the offending id) when either
    endpoint is not a known node. When ``all_paths`` is true, every shortest
    path of equal minimal length is enumerated into ``PathReport.paths`` (the
    single ``path`` field keeps the first for back-compat).
    """

    by_id = project.by_id()
    if source not in by_id:
        raise UnknownNodeError(source)
    if target not in by_id:
        raise UnknownNodeError(target)

    graph = build_graph(project)

    def make(found: bool, direction: str | None, paths: list[list[str]]) -> PathReport:
        first = paths[0] if paths else []
        return PathReport(
            project=project.name,
            source=source,
            target=target,
            source_title=by_id[source].title,
            target_title=by_id[target].title,
            found=found,
            direction=direction,
            path=first,
            length=max(len(first) - 1, 0) if found else 0,
            paths=[list(p) for p in paths],
        )

    if source == target:
        return make(True, DIRECTION_SELF, [[source]])

    forward = _resolve_paths(graph.edges, source, target, all_paths=all_paths)
    if forward:
        return make(True, DIRECTION_DEPENDS_ON, forward)

    backward = _resolve_paths(graph.edges, target, source, all_paths=all_paths)
    if backward:
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
    paths = report.paths or [report.path]
    if len(paths) > 1:
        lines.append(f"{summary} ({report.length} step(s), {len(paths)} shortest path(s)).")
        for index, chain in enumerate(paths, start=1):
            lines.append(
                f"Path {index}: " + " -> ".join(f"`{node_id}`" for node_id in chain)
            )
    else:
        lines.append(f"{summary} ({report.length} step(s)).")
        lines.append("Path: " + " -> ".join(f"`{node_id}`" for node_id in report.path))
    return "\n".join(lines) + "\n"


def _resolve_paths(
    edges: dict[str, list[str]], start: str, goal: str, *, all_paths: bool
) -> list[list[str]]:
    """Shortest path(s) from ``start`` to ``goal``.

    With ``all_paths`` false this returns at most one path (the back-compatible
    deterministic shortest path). With ``all_paths`` true it returns every
    shortest path of equal minimal length, sorted lexicographically so the first
    matches the single-path result.
    """

    if not all_paths:
        single = _shortest_path(edges, start, goal)
        return [single] if single is not None else []
    return _all_shortest_paths(edges, start, goal)


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


def _all_shortest_paths(
    edges: dict[str, list[str]], start: str, goal: str
) -> list[list[str]]:
    """Enumerate every shortest path from ``start`` to ``goal``.

    A breadth-first sweep records the minimal distance to each node and every
    predecessor lying on a shortest route; the predecessor DAG is then expanded
    into concrete chains. Results are sorted lexicographically.
    """

    if start == goal:
        return [[start]]
    dist: dict[str, int] = {start: 0}
    preds: dict[str, list[str]] = {}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        # Once the goal's distance is known, nodes already at/beyond it cannot
        # lie on a shortest path to goal (their successors are strictly deeper),
        # so stop expanding them. BFS visits nodes in distance order, so every
        # predecessor of goal is still recorded before we reach this point.
        if goal in dist and dist[current] >= dist[goal]:
            continue
        for neighbour in edges.get(current, []):
            nd = dist[current] + 1
            if neighbour not in dist:
                dist[neighbour] = nd
                preds[neighbour] = [current]
                queue.append(neighbour)
            elif dist[neighbour] == nd:
                preds[neighbour].append(current)
    if goal not in dist:
        return []

    chains: list[list[str]] = []

    def walk(node: str, suffix: list[str]) -> None:
        chain = [node, *suffix]
        if node == start:
            chains.append(chain)
            return
        for parent in preds.get(node, []):
            walk(parent, chain)

    walk(goal, [])
    chains.sort()
    return chains


def _reconstruct(parents: dict[str, str], start: str, goal: str) -> list[str]:
    chain = [goal]
    while chain[-1] != start:
        chain.append(parents[chain[-1]])
    chain.reverse()
    return chain
