"""Build an in-memory dependency graph from a :class:`BlueprintProject`."""
from __future__ import annotations

from dataclasses import dataclass, field

from isabelle_blueprint.model.project import BlueprintProject


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


def dependency_levels(project: BlueprintProject) -> list[list[str]]:
    """Topological layering: level 0 = roots, level k = all-deps-in-prior-levels.

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
