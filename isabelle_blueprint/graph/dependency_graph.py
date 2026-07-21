"""Build an in-memory dependency graph from a :class:`BlueprintProject`."""
from __future__ import annotations

from dataclasses import dataclass, field

from isabelle_blueprint.errors import UnknownNodeError
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


@dataclass
class DependencyGraph:
    """Adjacency-list dependency graph.

    ``edges[node_id]`` is the list of node ids that ``node_id`` *depends on*
    (i.e. the targets of a ``uses:`` entry). The reverse mapping
    ``reverse_edges[node_id]`` lists the nodes that depend on ``node_id``.
    """

    nodes: list[str] = field(default_factory=list)
    edges: dict[str, list[str]] = field(default_factory=dict)
    reverse_edges: dict[str, list[str]] = field(default_factory=dict)

    def neighbours(self, node_id: str) -> list[str]:
        return list(self.edges.get(node_id, []))


def build_graph(project: BlueprintProject) -> DependencyGraph:
    """Build a :class:`DependencyGraph` for ``project``.

    Edges to missing dependencies are dropped; use
    :meth:`BlueprintProject.validate` to surface them as errors first.
    """
    known = {n.id for n in project.nodes}
    g = DependencyGraph()
    for node in project.nodes:
        g.nodes.append(node.id)
        g.edges.setdefault(node.id, [])
        g.reverse_edges.setdefault(node.id, [])
    for node in project.nodes:
        for dep in node.uses:
            if dep not in known:
                continue
            g.edges[node.id].append(dep)
            g.reverse_edges.setdefault(dep, []).append(node.id)
    return g


def roots_subproject(project: BlueprintProject) -> BlueprintProject:
    """Return a pruned copy of ``project`` limited to its ROOT nodes.

    A root is a node that nothing else ``uses`` (no incoming dependency edge);
    these are the end-goals of the blueprint. Because roots have no incoming
    edges they cannot depend on one another, so the pruned graph has no edges
    between them: when :func:`build_graph` rebuilds the graph on the pruned
    project it drops every edge to a pruned (non-root) node. The original
    :class:`BlueprintNode` objects are reused unchanged and the relevant source
    files are kept, mirroring :func:`focus_subproject`.
    """
    graph = build_graph(project)
    keep = {node_id for node_id in graph.nodes if not graph.reverse_edges.get(node_id)}
    kept_nodes = [node for node in project.nodes if node.id in keep]
    sources = [
        src
        for src in project.source_files
        if any(node.source_file == src for node in kept_nodes)
    ]
    if not sources and not any(node.source_file for node in kept_nodes):
        sources = list(project.source_files)
    return BlueprintProject.from_nodes(project.name, kept_nodes, sources)


def leaves_subproject(project: BlueprintProject) -> BlueprintProject:
    """Return a pruned copy of ``project`` limited to its LEAF nodes.

    A leaf is a node that does not ``use`` anything (no outgoing dependency
    edge); these are the foundational axioms/definitions the blueprint builds
    on. Because leaves have no outgoing edges they cannot depend on one another,
    so the pruned graph has no edges between them: when :func:`build_graph`
    rebuilds the graph on the pruned project it drops every edge to a pruned
    (non-leaf) node. The original :class:`BlueprintNode` objects are reused
    unchanged and the relevant source files are kept, mirroring
    :func:`roots_subproject`.
    """
    graph = build_graph(project)
    keep = {node_id for node_id in graph.nodes if not graph.edges.get(node_id)}
    kept_nodes = [node for node in project.nodes if node.id in keep]
    sources = [
        src
        for src in project.source_files
        if any(node.source_file == src for node in kept_nodes)
    ]
    if not sources and not any(node.source_file for node in kept_nodes):
        sources = list(project.source_files)
    return BlueprintProject.from_nodes(project.name, kept_nodes, sources)


def incomplete_subproject(project: BlueprintProject) -> BlueprintProject:
    """Return a pruned copy of ``project`` limited to its INCOMPLETE nodes.

    An incomplete node is one whose :class:`FormalStatus` is neither
    :attr:`FormalStatus.FOUND` nor :attr:`FormalStatus.PROVED` - i.e. the
    remaining formal work. Edges to pruned (already complete) nodes are dropped
    automatically when :func:`build_graph` rebuilds on the pruned project, so the
    result is a "what is left to do" view: incomplete nodes plus the edges among
    them. The original :class:`BlueprintNode` objects are reused unchanged and
    the relevant source files are kept, mirroring :func:`roots_subproject`.
    """
    complete = {FormalStatus.FOUND, FormalStatus.PROVED}
    kept_nodes = [node for node in project.nodes if node.status.formal not in complete]
    sources = [
        src
        for src in project.source_files
        if any(node.source_file == src for node in kept_nodes)
    ]
    if not sources and not any(node.source_file for node in kept_nodes):
        sources = list(project.source_files)
    return BlueprintProject.from_nodes(project.name, kept_nodes, sources)


def dependency_levels(project: BlueprintProject) -> list[list[str]]:
    """Topological layering: level 0 = leaves (no dependencies), level k =
    nodes whose dependencies all lie in prior levels; the final level holds
    roots/goals.

    Nodes participating in cycles are placed in the final layer.
    """
    graph = build_graph(project)
    remaining = {n: set(graph.edges.get(n, [])) for n in graph.nodes}
    levels: list[list[str]] = []
    placed: set[str] = set()
    while remaining:
        ready = sorted(n for n, deps in remaining.items() if deps.issubset(placed))
        if not ready:
            levels.append(sorted(remaining.keys()))
            break
        levels.append(ready)
        for n in ready:
            placed.add(n)
            del remaining[n]
    return levels


def neighbourhood(
    project: BlueprintProject, focus: str, depth: int | None = None
) -> list[str]:
    """Return the ids within ``depth`` dependency hops of ``focus`` (inclusive).

    Proximity is measured treating the dependency graph as undirected, so the
    neighbourhood includes both ancestors (nodes that depend on ``focus``) and
    descendants (nodes ``focus`` depends on), as well as nodes reached by a mix
    of the two within ``depth`` hops. ``depth=None`` (the default) collects the
    entire connected component. ``depth=0`` yields just ``focus``.

    Ids are returned in the project's declaration order. Raises
    :class:`UnknownNodeError` when ``focus`` is not a known node.
    """
    known = {n.id for n in project.nodes}
    if focus not in known:
        raise UnknownNodeError(focus)
    if depth is not None and depth < 0:
        raise ValueError("depth must be non-negative")

    graph = build_graph(project)
    visited = {focus}
    frontier = [focus]
    hops = 0
    while frontier and (depth is None or hops < depth):
        nxt: list[str] = []
        for node_id in frontier:
            adjacent = graph.edges.get(node_id, []) + graph.reverse_edges.get(node_id, [])
            for other in adjacent:
                if other not in visited:
                    visited.add(other)
                    nxt.append(other)
        frontier = nxt
        hops += 1

    return [n.id for n in project.nodes if n.id in visited]


def focus_subproject(
    project: BlueprintProject, focus: str, depth: int | None = None
) -> BlueprintProject:
    """Return a pruned copy of ``project`` limited to ``focus``'s neighbourhood.

    The original :class:`BlueprintNode` objects are reused unchanged, so a
    node's ``uses`` list may still reference pruned nodes; :func:`build_graph`
    and the renderers drop those dangling edges automatically. The project name
    and the subset of relevant source files are preserved. Raises
    :class:`UnknownNodeError` when ``focus`` is unknown.
    """
    keep = set(neighbourhood(project, focus, depth))
    kept_nodes = [node for node in project.nodes if node.id in keep]
    sources = [
        src
        for src in project.source_files
        if any(node.source_file == src for node in kept_nodes)
    ]
    # When none of the kept nodes carry per-node source provenance, the filter
    # above erases every source file the caller supplied. Fall back to the
    # original list so focusing never silently drops source metadata.
    if not sources and not any(node.source_file for node in kept_nodes):
        sources = list(project.source_files)
    return BlueprintProject.from_nodes(project.name, kept_nodes, sources)
