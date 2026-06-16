"""Topological layering of the dependency DAG into levels.

``levels`` arranges the blueprint dependency graph into topological *levels*:
level 0 holds the leaves (nodes with no dependencies), and each subsequent level
holds nodes whose dependencies all live in strictly earlier levels. The level
count is therefore the depth of the longest dependency chain, and the widest
level shows how much work can proceed in parallel at a given depth.

Cycles are handled gracefully: any node that can never be placed because it
participates in (or only reaches the project through) a dependency cycle is
reported separately as ``cyclic_nodes`` rather than crashing or being silently
folded into the last level. No Isabelle invocation is required.
"""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.graph.dependency_graph import build_graph, dependency_levels
from isabelle_blueprint.model.project import BlueprintProject

LEVELS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Level:
    """A single topological level: its index and the node ids it contains."""

    index: int
    node_ids: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.node_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "node_ids": list(self.node_ids),
            "count": self.count,
        }


@dataclass(frozen=True)
class LevelsReport:
    """The dependency DAG arranged into topological levels."""

    project: str
    levels: tuple[Level, ...]
    cyclic_nodes: tuple[str, ...]
    schema_version: int = LEVELS_SCHEMA_VERSION

    @property
    def level_count(self) -> int:
        return len(self.levels)

    @property
    def max_width(self) -> int:
        return max((level.count for level in self.levels), default=0)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "level_count": self.level_count,
            "max_width": self.max_width,
            "levels": [level.to_dict() for level in self.levels],
            "cyclic_nodes": list(self.cyclic_nodes),
        }


def _cyclic_nodes(project: BlueprintProject) -> list[str]:
    """Return the node ids that cannot be topologically placed.

    Mirrors the Kahn-style sweep in
    :func:`isabelle_blueprint.graph.dependency_graph.dependency_levels`: when no
    further node is ready (every remaining node still depends on an unplaced
    node), those remaining nodes are exactly the cycle participants and the
    nodes reachable only through them.
    """

    graph = build_graph(project)
    remaining = {n: set(graph.edges.get(n, [])) for n in graph.nodes}
    placed: set[str] = set()
    while remaining:
        ready = [n for n, deps in remaining.items() if deps.issubset(placed)]
        if not ready:
            return sorted(remaining.keys())
        for n in ready:
            placed.add(n)
            del remaining[n]
    return []


def build_levels_report(project: BlueprintProject) -> LevelsReport:
    """Compute the topological-level layering for ``project``.

    Nodes participating in a dependency cycle are split out into
    ``cyclic_nodes``; the remaining (acyclic) layers form ``levels``.
    """

    raw = dependency_levels(project)
    cyclic = _cyclic_nodes(project)
    # When the sweep hits a cycle the helper appends the unresolved set as a
    # final bucket; drop that bucket from the proper levels and report it apart.
    layers = raw[:-1] if cyclic else raw
    levels = tuple(
        Level(index=index, node_ids=tuple(layer))
        for index, layer in enumerate(layers)
    )
    return LevelsReport(
        project=project.name,
        levels=levels,
        cyclic_nodes=tuple(cyclic),
    )


def render_levels_report(report: LevelsReport) -> str:
    """Render the level layering as compact Markdown for the terminal."""

    lines = [f"# {report.project} dependency levels", ""]
    if not report.levels and not report.cyclic_nodes:
        lines.append("_(no nodes)_")
        return "\n".join(lines) + "\n"

    for level in report.levels:
        ids = ", ".join(f"`{node_id}`" for node_id in level.node_ids)
        lines.append(f"## Level {level.index} ({level.count} node(s))")
        lines.append(ids if ids else "_(empty)_")
        lines.append("")

    lines.append(
        f"{report.level_count} level(s); widest level holds "
        f"{report.max_width} node(s)."
    )
    if report.cyclic_nodes:
        cyclic = ", ".join(f"`{node_id}`" for node_id in report.cyclic_nodes)
        lines.append(
            f"{len(report.cyclic_nodes)} node(s) in dependency cycle(s): {cyclic}."
        )
    return "\n".join(lines) + "\n"
