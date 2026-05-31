"""Render the static HTML site for a blueprint project."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.graph.graphviz_render import (
    render_dot,
    render_json,
    render_svg,
)
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import STATUS_COLORS

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "templates" / "static"


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

    common = {
        "project": project,
        "status_colors": STATUS_COLORS,
        "formal_counts": dict(formal_counts),
        "blueprint_counts": dict(blueprint_counts),
        "agent_counts": dict(agent_counts),
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
