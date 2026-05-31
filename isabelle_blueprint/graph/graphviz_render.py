"""Emit DOT/JSON/SVG renderings of the dependency graph."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from isabelle_blueprint.graph.dependency_graph import build_graph
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import STATUS_COLORS, AgentStatus, FormalStatus


def _color_for_node(formal: FormalStatus, agent: AgentStatus) -> str:
    if agent == AgentStatus.READY and formal not in {FormalStatus.PROVED, FormalStatus.FOUND}:
        return "#a855f7"  # purple - agent-ready task
    return STATUS_COLORS.get(formal, "#9ca3af")


def render_dot(project: BlueprintProject) -> str:
    """Return a Graphviz DOT representation of the dependency graph."""
    g = build_graph(project)
    by_id = project.by_id()
    lines = [
        "digraph blueprint {",
        '  graph [rankdir=BT, splines=true, bgcolor="white", fontname="Helvetica"];',
        '  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11];',
        '  edge  [color="#94a3b8"];',
    ]
    for node_id in g.nodes:
        node = by_id[node_id]
        color = _color_for_node(node.status.formal, node.status.agent)
        label = _dot_escape(f"{node.id}\n{node.title}")
        tooltip = _dot_escape(
            f"{node.kind.value} | blueprint={node.status.blueprint.value} "
            f"formal={node.status.formal.value} agent={node.status.agent.value}"
        )
        lines.append(
            f'  "{node_id}" [label="{label}", tooltip="{tooltip}", fillcolor="{color}", color="#1f2937"];'
        )
    for src, deps in g.edges.items():
        for dep in deps:
            lines.append(f'  "{src}" -> "{dep}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_json(project: BlueprintProject) -> str:
    """Return a JSON representation of the dependency graph for the web UI."""
    g = build_graph(project)
    by_id = project.by_id()
    data = {
        "name": project.name,
        "nodes": [
            {
                "id": node_id,
                "title": by_id[node_id].title,
                "kind": by_id[node_id].kind.value,
                "blueprint_status": by_id[node_id].status.blueprint.value,
                "formal_status": by_id[node_id].status.formal.value,
                "agent_status": by_id[node_id].status.agent.value,
                "color": _color_for_node(by_id[node_id].status.formal, by_id[node_id].status.agent),
                "isabelle": by_id[node_id].isabelle.to_dict(),
            }
            for node_id in g.nodes
        ],
        "edges": [
            {"source": src, "target": dep}
            for src, deps in g.edges.items()
            for dep in deps
        ],
    }
    return json.dumps(data, indent=2)


def render_svg(dot_source: str, executable: str = "dot") -> str | None:
    """Render ``dot_source`` to SVG using the ``dot`` binary.

    Returns the SVG XML, or ``None`` if Graphviz is not installed.
    """
    if shutil.which(executable) is None:
        return None
    try:
        proc = subprocess.run(
            [executable, "-Tsvg"],
            input=dot_source,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - graphviz failure
        return f"<!-- graphviz failed: {exc.stderr.strip()} -->"
    return proc.stdout


def write_graph_artifacts(project: BlueprintProject, build_dir: Path, *, executable: str = "dot") -> dict[str, Path]:
    """Write DOT and JSON (and SVG if Graphviz is available) to ``build_dir``.

    Returns a mapping of artefact name -> written path.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    dot_text = render_dot(project)
    json_text = render_json(project)
    dot_path = build_dir / "graph.dot"
    json_path = build_dir / "graph.json"
    dot_path.write_text(dot_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    written = {"dot": dot_path, "json": json_path}
    svg = render_svg(dot_text, executable=executable)
    if svg is not None:
        svg_path = build_dir / "graph.svg"
        svg_path.write_text(svg, encoding="utf-8")
        written["svg"] = svg_path
    return written


def _dot_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
