"""Render the static HTML site for a blueprint project."""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, deque
from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from isabelle_blueprint.agents.assignments import AssignmentStore
from isabelle_blueprint.agents.memory import AgentMemory, summaries_by_node
from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.graph.graphviz_render import (
    render_dot,
    render_json,
    render_svg,
)
from isabelle_blueprint.isabelle.suggestions import FactSuggestion, suggestions_by_node
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import (
    STATUS_COLORS,
    AgentStatus,
    BlueprintStatus,
    FormalStatus,
)
from isabelle_blueprint.report.badge import write_badge_endpoint, write_badge_svg
from isabelle_blueprint.report.critical_path import build_critical_path
from isabelle_blueprint.report.roadmap import build_roadmap, roadmap_payload

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
    trends: list[dict[str, Any]] | None = None,
    fact_suggestions: list[FactSuggestion] | None = None,
    memory: AgentMemory | None = None,
    assignments: AssignmentStore | None = None,
) -> Path:
    """Render the project to a static HTML site under ``output_dir``.

    Returns the path to ``index.html``.

    ``trends`` is an optional list of historical entries (as written by
    :mod:`isabelle_blueprint.report.trends`) used to render the trend
    chart on ``trends.html``. When omitted, the trends page renders an
    empty-state.

    ``assignments`` is an optional :class:`AssignmentStore` mapping node ids
    to owners. When supplied, owner badges and an owner filter are surfaced on
    the graph page and per-node pages; stale ids that no longer match a project
    node are ignored.
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

    fact_suggestions = fact_suggestions or []
    fact_suggestions_by_node = suggestions_by_node(fact_suggestions)
    tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    roadmap = build_roadmap(project, tasks)
    memory_summaries = summaries_by_node(memory, project.nodes) if memory is not None else {}
    formal_counts = Counter(n.status.formal.value for n in project.nodes)
    blueprint_counts = Counter(n.status.blueprint.value for n in project.nodes)
    agent_counts = Counter(n.status.agent.value for n in project.nodes)
    dependency_levels = _dependency_levels(project)

    critical = build_critical_path(project)
    critical_path_ids = list(critical.longest.path) if critical.longest else []
    critical_path_set = set(critical_path_ids)

    project_ids = {node.id for node in project.nodes}
    owners_by_node: dict[str, str] = {}
    if assignments is not None:
        owners_by_node = {
            node_id: assignment.owner
            for node_id, assignment in assignments.nodes.items()
            if assignment.owner and node_id in project_ids
        }
    has_owner_assignments = bool(owners_by_node)
    owner_counts = Counter(owners_by_node.values())
    owner_facets = [
        {"owner": owner, "count": count} for owner, count in sorted(owner_counts.items())
    ]
    unassigned_count = sum(1 for node in project.nodes if node.id not in owners_by_node)

    trends_data = list(trends or [])
    (output_dir / "trends.json").write_text(
        json.dumps({"entries": trends_data}, indent=2),
        encoding="utf-8",
    )

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
        "critical_path": critical,
        "critical_path_ids": critical_path_ids,
        "critical_path_set": critical_path_set,
        "owners_by_node": owners_by_node,
        "has_owner_assignments": has_owner_assignments,
        "owner_facets": owner_facets,
        "unassigned_count": unassigned_count,
        "has_svg": svg is not None,
        "svg_source": _inline_svg(svg),
        "tasks": tasks,
        "task_board": _task_board(project, tasks),
        "suggested_next_task": tasks[0] if tasks else None,
        "memory_summaries": memory_summaries,
        "page_count": len(project.nodes),
        "dot_source": dot_source,
        "formal_status_values": [s.value for s in FormalStatus],
        "trends": trends_data,
        "trend_delta": _trend_delta(trends_data),
        "fact_suggestions_by_node": fact_suggestions_by_node,
        "roadmap": roadmap,
    }

    _render_page(env, "index.html.j2", output_dir / "index.html", page="index", **common)
    _render_page(env, "graph.html.j2", output_dir / "graph.html", page="graph", **common)
    _render_page(env, "status.html.j2", output_dir / "status.html", page="status", **common)
    _render_page(env, "tasks.html.j2", output_dir / "tasks.html", page="tasks", **common)
    _render_page(env, "trends.html.j2", output_dir / "trends.html", page="trends", **common)
    _render_page(env, "roadmap.html.j2", output_dir / "roadmap.html", page="roadmap", **common)

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
        json.dumps(
            {
                "tasks": [t.to_dict() for t in tasks],
                "suggested_next_task": tasks[0].id if tasks else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "roadmap.json").write_text(
        json.dumps(roadmap_payload(roadmap), indent=2),
        encoding="utf-8",
    )
    (output_dir / "critical-path.json").write_text(
        json.dumps(critical.to_dict(), indent=2),
        encoding="utf-8",
    )
    if fact_suggestions:
        (output_dir / "fact-suggestions.json").write_text(
            json.dumps({"suggestions": [s.to_dict() for s in fact_suggestions]}, indent=2),
            encoding="utf-8",
        )
    write_badge_endpoint(project, output_dir / "badge.json")
    write_badge_svg(project, output_dir / "badge.svg")

    return output_dir / "index.html"


def _task_board(project: BlueprintProject, tasks) -> list[dict[str, object]]:
    ready_ids = {task.node_id for task in tasks}
    columns: dict[str, list[BlueprintNode]] = {
        AgentStatus.READY.value: [],
        AgentStatus.IN_PROGRESS.value: [],
        AgentStatus.ATTEMPTED.value: [],
        AgentStatus.NEEDS_HUMAN.value: [],
        AgentStatus.BLOCKED.value: [],
        AgentStatus.SOLVED.value: [],
    }
    for node in project.nodes:
        agent_status = node.status.agent.value
        if node.id in ready_ids:
            columns[AgentStatus.READY.value].append(node)
        elif agent_status in columns:
            columns[agent_status].append(node)
        else:
            columns[AgentStatus.BLOCKED.value].append(node)
    return [
        {"id": key, "title": title, "nodes": nodes, "count": len(nodes)}
        for key, title, nodes in [
            (AgentStatus.READY.value, "Ready", columns[AgentStatus.READY.value]),
            (AgentStatus.IN_PROGRESS.value, "In progress", columns[AgentStatus.IN_PROGRESS.value]),
            (AgentStatus.ATTEMPTED.value, "Attempted", columns[AgentStatus.ATTEMPTED.value]),
            (AgentStatus.NEEDS_HUMAN.value, "Needs human", columns[AgentStatus.NEEDS_HUMAN.value]),
            (AgentStatus.BLOCKED.value, "Blocked", columns[AgentStatus.BLOCKED.value]),
            (AgentStatus.SOLVED.value, "Solved", columns[AgentStatus.SOLVED.value]),
        ]
    ]


_SVG_PROLOG_RE = re.compile(r"<\?xml[^>]*\?>\s*", re.IGNORECASE)
_SVG_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>\s*", re.IGNORECASE)


def _inline_svg(svg: str | None) -> str | None:
    """Return ``svg`` stripped of its XML prolog / DOCTYPE for inline embedding.

    Graphviz emits a standalone SVG document with an XML prolog and a DTD
    reference; both are invalid inside an HTML body and trip strict parsers.
    Returning ``None`` (or ``None`` input) lets the template fall back to the
    raw-DOT callout.
    """
    if svg is None:
        return None
    text = _SVG_PROLOG_RE.sub("", svg, count=1)
    text = _SVG_DOCTYPE_RE.sub("", text, count=1)
    return text


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
        {
            "label": f"Level {level}",
            "level": level,
            "nodes": nodes,
            "count": len(nodes),
            "is_cycle": False,
        }
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
        (cast(int, row["level"]) for row in levels if row["level"] is not None),
        default=-1,
    )
    cycle_count = sum(cast(int, row["count"]) for row in levels if row["is_cycle"])
    missing_dependency_count = sum(
        1 for node in project.nodes for dep_id in node.uses if dep_id not in by_id
    )
    return {
        "max_level": max_level,
        "cycle_count": cycle_count,
        "missing_dependency_count": missing_dependency_count,
    }


def _trend_delta(entries: list[dict[str, Any]]) -> dict[str, object] | None:
    if len(entries) < 2:
        return None
    previous = entries[-2]
    current = entries[-1]

    def delta(key: str) -> int | None:
        prev = previous.get(key)
        cur = current.get(key)
        if isinstance(prev, int) and isinstance(cur, int):
            return cur - prev
        return None

    return {
        "previous_timestamp": previous.get("timestamp"),
        "current_timestamp": current.get("timestamp"),
        "coverage_percent": delta("coverage_percent"),
        "problem_count": delta("problem_count"),
        "proved_count": delta("proved_count"),
        "node_count": delta("node_count"),
    }
