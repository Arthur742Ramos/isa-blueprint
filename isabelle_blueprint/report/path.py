"""Dependency-path tracing between two chosen nodes.

``path SOURCE TARGET`` answers "how does SOURCE rest on TARGET?" by tracing the
``uses`` edges that connect them: a chain ``SOURCE -> n1 -> ... -> TARGET`` means
SOURCE depends on ``n1``, which depends on ..., which ultimately depends on
TARGET.

It is the point-to-point complement to the project-wide graph analyses:

* ``critical-path`` finds the longest *remaining* chain across the whole project.
* ``impact`` measures a single node's downstream blast radius.
* ``path`` explains the concrete dependency chain(s) linking *two* chosen nodes -
  the "why does my theorem need this lemma?" question that comes up constantly
  when navigating a large formalization.

The shortest connecting chain is always reported (via BFS). ``paths`` enumerates
the distinct *simple* chains up to a bound (``max_paths``) so that dense graphs
cannot produce unbounded output; traversal is cycle-safe. When SOURCE does not
reach TARGET, the analysis records whether the *reverse* dependency holds - a
common sign that the two arguments were given in the wrong order.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from isabelle_blueprint.graph.dependency_graph import DependencyGraph, build_graph
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.impact import UnknownNodeError

PATH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PathNodeInfo:
    """Display metadata for a node appearing in the analysis."""

    node_id: str
    title: str
    kind: str
    formal_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "kind": self.kind,
            "formal_status": self.formal_status,
        }


@dataclass(frozen=True)
class PathAnalysis:
    """The structured result of a ``path SOURCE TARGET`` query."""

    project: str
    source: str
    target: str
    connected: bool
    distance: int | None
    shortest_path: list[str]
    paths: list[list[str]]
    paths_truncated: bool
    reverse_connected: bool
    nodes: list[PathNodeInfo]
    schema_version: int = PATH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "source": self.source,
            "target": self.target,
            "connected": self.connected,
            "distance": self.distance,
            "shortest_path": list(self.shortest_path),
            "paths": [list(p) for p in self.paths],
            "paths_truncated": self.paths_truncated,
            "reverse_connected": self.reverse_connected,
            "nodes": [n.to_dict() for n in self.nodes],
        }


def _shortest_path(graph: DependencyGraph, source: str, target: str) -> list[str]:
    """BFS shortest path over forward (``uses``) edges; ``[]`` if unreachable."""
    if source == target:
        return [source]
    prev: dict[str, str] = {}
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        cur = queue.popleft()
        for nxt in graph.edges.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            prev[nxt] = cur
            if nxt == target:
                chain = [target]
                while chain[-1] != source:
                    chain.append(prev[chain[-1]])
                chain.reverse()
                return chain
            queue.append(nxt)
    return []


def _reachable(graph: DependencyGraph, source: str, target: str) -> bool:
    """Whether ``target`` is reachable from ``source`` over forward edges."""
    if source == target:
        return True
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        cur = queue.popleft()
        for nxt in graph.edges.get(cur, []):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def _all_simple_paths(
    graph: DependencyGraph, source: str, target: str, *, max_paths: int
) -> tuple[list[list[str]], bool]:
    """Enumerate distinct simple paths ``source -> target`` (forward edges).

    Returns ``(paths, truncated)``. An on-stack visited set keeps the search
    finite even through dependency cycles, and the DFS stops as soon as one more
    than ``max_paths`` chains have been found so a dense graph cannot blow up the
    output. The returned chains are sorted shortest-first.
    """
    if max_paths <= 0:
        return [], False
    if source == target:
        return [[source]], False

    found: list[list[str]] = []
    stack_path = [source]
    on_path = {source}

    def dfs(cur: str) -> None:
        for nxt in sorted(graph.edges.get(cur, [])):
            if nxt in on_path:
                continue
            if nxt == target:
                found.append([*stack_path, target])
            else:
                stack_path.append(nxt)
                on_path.add(nxt)
                dfs(nxt)
                on_path.discard(nxt)
                stack_path.pop()
            if len(found) > max_paths:
                return

    dfs(source)
    found.sort(key=lambda p: (len(p), p))
    truncated = len(found) > max_paths
    if truncated:
        found = found[:max_paths]
    return found, truncated


def build_path_analysis(
    project: BlueprintProject, source: str, target: str, *, max_paths: int = 20
) -> PathAnalysis:
    """Trace dependency chains from ``source`` to ``target``.

    Raises :class:`UnknownNodeError` if either id is not a known node.
    """
    by_id = project.by_id()
    if source not in by_id:
        raise UnknownNodeError(source)
    if target not in by_id:
        raise UnknownNodeError(target)

    graph = build_graph(project)
    shortest = _shortest_path(graph, source, target)
    connected = bool(shortest)
    paths, truncated = _all_simple_paths(graph, source, target, max_paths=max_paths)
    reverse_connected = (
        not connected and source != target and _reachable(graph, target, source)
    )

    referenced = {source, target}
    for chain in paths:
        referenced.update(chain)
    nodes = [
        PathNodeInfo(
            node_id=node_id,
            title=by_id[node_id].title,
            kind=by_id[node_id].kind.value,
            formal_status=by_id[node_id].status.formal.value,
        )
        for node_id in sorted(referenced)
    ]

    distance = (len(shortest) - 1) if connected else None
    return PathAnalysis(
        project=project.name,
        source=source,
        target=target,
        connected=connected,
        distance=distance,
        shortest_path=shortest,
        paths=paths,
        paths_truncated=truncated,
        reverse_connected=reverse_connected,
        nodes=nodes,
    )


def path_payload(analysis: PathAnalysis) -> dict[str, object]:
    """Return the JSON payload for a path analysis."""
    return analysis.to_dict()


def render_path(analysis: PathAnalysis) -> str:
    """Render a path analysis as compact Markdown (trailing newline)."""
    from isabelle_blueprint import console

    info_by_id = {n.node_id: n for n in analysis.nodes}
    lines = [f"# path `{analysis.source}` -> `{analysis.target}`", ""]

    if analysis.source == analysis.target:
        lines.append(console.dim("Source and target are the same node."))
        return "\n".join(lines).rstrip("\n") + "\n"

    if not analysis.connected:
        lines.append(
            console.warning(
                f"No dependency path: `{analysis.source}` does not "
                f"(transitively) use `{analysis.target}`."
            )
        )
        if analysis.reverse_connected:
            lines.append(
                console.dim(
                    f"However `{analysis.target}` depends on `{analysis.source}` "
                    "- did you mean to swap the arguments?"
                )
            )
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.append(f"Shortest chain ({analysis.distance} hop(s)):")
    lines.append("  " + " -> ".join(f"`{node_id}`" for node_id in analysis.shortest_path))
    lines.append("")

    if len(analysis.paths) > 1:
        suffix = "+" if analysis.paths_truncated else ""
        lines.extend([f"## All simple paths ({len(analysis.paths)}{suffix})", ""])
        for chain in analysis.paths:
            lines.append("- " + " -> ".join(f"`{node_id}`" for node_id in chain))
        if analysis.paths_truncated:
            lines.append(
                console.dim(f"  ... more paths exist (showing the first {len(analysis.paths)})")
            )
        lines.append("")

    lines.extend(["## Nodes on the shortest chain", ""])
    for node_id in analysis.shortest_path:
        info = info_by_id.get(node_id)
        if info is not None:
            lines.append(
                f"- `{node_id}` - {info.title} ({info.kind}, formal `{info.formal_status}`)"
            )
    return "\n".join(lines).rstrip("\n") + "\n"
