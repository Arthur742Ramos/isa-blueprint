"""Render the static HTML site for a blueprint project."""
from __future__ import annotations

import json
import shutil
from collections import Counter, deque
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from jinja2 import Environment, FileSystemLoader, select_autoescape

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.graph.graphviz_render import (
    render_dot,
    render_json,
    render_svg,
)
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import (
    STATUS_COLORS,
    AgentStatus,
    BlueprintStatus,
    FormalStatus,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "templates" / "static"
StatusBreakdown: TypeAlias = dict[str, object]
DependencyLevel: TypeAlias = dict[str, object]


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_site(
    project: BlueprintProject,
    output_dir: Path,
    *,
    graphviz_executable: str = "dot",
) -> Path:
    """Render the project to a static HTML site under ``output_dir``.

    Returns the path to ``index.html``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    env = _make_env()

    dot_source = render_dot(project)
    graph_json = render_json(project)
    svg = render_svg(dot_source, executable=graphviz_executable)
    (output_dir / "graph.dot").write_text(dot_source, encoding="utf-8")
    (output_dir / "graph.json").write_text(graph_json, encoding="utf-8")
    if svg is not None:
        (output_dir / "graph.svg").write_text(svg, encoding="utf-8")

    tasks = generate_tasks(project)
    formal_counts = Counter(n.status.formal.value for n in project.nodes)
    blueprint_counts = Counter(n.status.blueprint.value for n in project.nodes)
    agent_counts = Counter(n.status.agent.value for n in project.nodes)
    dependency_levels = _dependency_levels(project)

    common = {
        "project": project,
        "status_colors": STATUS_COLORS,
        "formal_counts": dict(formal_counts),
        "blueprint_counts": dict(blueprint_counts),
        "agent_counts": dict(agent_counts),
        "formal_breakdown": _count_breakdown(formal_counts, FormalStatus, colors=STATUS_COLORS),
        "blueprint_breakdown": _count_breakdown(blueprint_counts, BlueprintStatus),
        "agent_breakdown": _count_breakdown(agent_counts, AgentStatus),
        "dependency_levels": dependency_levels,
        "dependency_stats": _dependency_stats(project, dependency_levels),
        "has_svg": svg is not None,
        "tasks": tasks,
        "page_count": len(project.nodes),
        "dot_source": dot_source,
    }

    _render_page(env, "index.html.j2", output_dir / "index.html", page="index", **common)
    _render_page(env, "graph.html.j2", output_dir / "graph.html", page="graph", **common)
    _render_page(env, "status.html.j2", output_dir / "status.html", page="status", **common)
    _render_page(env, "tasks.html.j2", output_dir / "tasks.html", page="tasks", **common)

    node_dir = output_dir / "nodes"
    node_dir.mkdir(parents=True, exist_ok=True)
    by_id = project.by_id()
    for node in project.nodes:
        downstream = [m for m in project.nodes if node.id in m.uses]
        _render_page(
            env,
            "node.html.j2",
            node_dir / f"{node.id}.html",
            page="node",
            node=node,
            dependencies=[by_id[d] for d in node.uses if d in by_id],
            downstream=downstream,
            **common,
        )

    _write_static(output_dir)
    (output_dir / "project.json").write_text(project.to_json(), encoding="utf-8")
    (output_dir / "tasks.json").write_text(
        json.dumps({"tasks": [t.to_dict() for t in tasks]}, indent=2),
        encoding="utf-8",
    )

    return output_dir / "index.html"


def _render_page(env: Environment, template_name: str, out_path: Path, **context) -> None:
    template = env.get_template(template_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(template.render(**context), encoding="utf-8")


def _write_static(output_dir: Path) -> None:
    static_out = output_dir / "static"
    static_out.mkdir(parents=True, exist_ok=True)
    if _STATIC_DIR.exists():
        for entry in _STATIC_DIR.iterdir():
            target = static_out / entry.name
            if entry.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(entry, target)
            else:
                shutil.copyfile(entry, target)


def _count_breakdown(
    counts: Counter[str],
    enum_cls: type[Enum],
    *,
    colors: dict[str, str] | None = None,
) -> list[StatusBreakdown]:
    total = sum(counts.values())
    rows: list[StatusBreakdown] = []
    for status in enum_cls:
        value = str(status.value)
        count = counts.get(value, 0)
        rows.append(
            {
                "label": value,
                "count": count,
                "percent": round((count / total) * 100, 1) if total else 0,
                "color": (colors or {}).get(value, "#9ca3af"),
            }
        )
    return rows


def _dependency_levels(project: BlueprintProject) -> list[DependencyLevel]:
    by_id = project.by_id()
    dependency_counts = {
        node.id: sum(1 for dep_id in node.uses if dep_id in by_id)
        for node in project.nodes
    }
    dependents: dict[str, list[str]] = {node.id: [] for node in project.nodes}
    for node in project.nodes:
        for dep_id in node.uses:
            if dep_id in dependents:
                dependents[dep_id].append(node.id)

    queue = deque(node.id for node in project.nodes if dependency_counts[node.id] == 0)
    level_by_id = {node_id: 0 for node_id in queue}
    processed: set[str] = set()

    while queue:
        node_id = queue.popleft()
        processed.add(node_id)
        next_level = level_by_id[node_id] + 1
        for dependent_id in dependents[node_id]:
            dependency_counts[dependent_id] -= 1
            level_by_id[dependent_id] = max(level_by_id.get(dependent_id, 0), next_level)
            if dependency_counts[dependent_id] == 0:
                queue.append(dependent_id)

    levels: dict[int, list[BlueprintNode]] = {}
    unlevelled_nodes: list[BlueprintNode] = []
    for node in project.nodes:
        if node.id in processed:
            levels.setdefault(level_by_id[node.id], []).append(node)
        else:
            unlevelled_nodes.append(node)

    rows: list[DependencyLevel] = [
        {"label": f"Level {level}", "level": level, "nodes": nodes, "count": len(nodes), "is_cycle": False}
        for level, nodes in sorted(levels.items())
    ]
    if unlevelled_nodes:
        rows.append(
            {
                "label": "Cycle",
                "level": None,
                "nodes": unlevelled_nodes,
                "count": len(unlevelled_nodes),
                "is_cycle": True,
            }
        )
    return rows


def _dependency_stats(
    project: BlueprintProject,
    levels: list[DependencyLevel],
) -> dict[str, int]:
    by_id = project.by_id()
    max_level = max(
        (int(row["level"]) for row in levels if row["level"] is not None),
        default=-1,
    )
    cycle_count = sum(int(row["count"]) for row in levels if row["is_cycle"])
    missing_dependency_count = sum(
        1 for node in project.nodes for dep_id in node.uses if dep_id not in by_id
    )
    return {
        "max_level": max_level,
        "cycle_count": cycle_count,
        "missing_dependency_count": missing_dependency_count,
    }
