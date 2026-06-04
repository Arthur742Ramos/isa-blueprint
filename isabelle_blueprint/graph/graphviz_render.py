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
            f'  "{node_id}" [label="{label}", tooltip="{tooltip}", '
            f'fillcolor="{color}", color="#1f2937"];'
        )
    for src, deps in g.edges.items():
        for dep in deps:
            lines.append(f'  "{src}" -> "{dep}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_mermaid(project: BlueprintProject) -> str:
    """Return a Mermaid ``flowchart`` representation of the dependency graph.

    Mermaid renders inline on GitHub/GitLab and most Markdown viewers, so this
    gives a zero-dependency picture of the blueprint without needing Graphviz.
    Nodes are coloured by formal status (agent-ready tasks share the purple used
    by the DOT/JSON renderers) via per-node ``style`` directives.
    """
    g = build_graph(project)
    by_id = project.by_id()
    lines = ["flowchart BT"]
    for node_id in g.nodes:
        node = by_id[node_id]
        safe = _mermaid_id(node_id)
        label = _mermaid_label(f"{node.id}\n{node.title}")
        lines.append(f'  {safe}["{label}"]')
    for src, deps in g.edges.items():
        for dep in deps:
            lines.append(f"  {_mermaid_id(src)} --> {_mermaid_id(dep)}")
    for node_id in g.nodes:
        node = by_id[node_id]
        color = _color_for_node(node.status.formal, node.status.agent)
        lines.append(
            f"  style {_mermaid_id(node_id)} fill:{color},stroke:#1f2937,color:#111827"
        )
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


def write_graph_artifacts(
    project: BlueprintProject,
    build_dir: Path,
    *,
    executable: str = "dot",
    formats: tuple[str, ...] | None = None,
) -> dict[str, Path]:
    """Write the requested graph renderings to ``build_dir``.

    ``formats`` selects which artefacts to emit; ``None`` (the default) writes
    the classic ``dot``/``json``/``svg`` set so existing callers are unchanged.
    Recognised values are ``"dot"``, ``"json"``, ``"svg"``, and ``"mermaid"``.
    SVG is only written when Graphviz's ``dot`` binary is available.

    Returns a mapping of artefact name -> written path.
    """
    selected = formats or ("dot", "json", "svg")
    build_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    dot_text = render_dot(project) if ("dot" in selected or "svg" in selected) else None

    if "dot" in selected and dot_text is not None:
        dot_path = build_dir / "graph.dot"
        dot_path.write_text(dot_text, encoding="utf-8")
        written["dot"] = dot_path
    if "json" in selected:
        json_path = build_dir / "graph.json"
        json_path.write_text(render_json(project), encoding="utf-8")
        written["json"] = json_path
    if "mermaid" in selected:
        mmd_path = build_dir / "graph.mmd"
        mmd_path.write_text(render_mermaid(project), encoding="utf-8")
        written["mermaid"] = mmd_path
    if "svg" in selected and dot_text is not None:
        svg = render_svg(dot_text, executable=executable)
        if svg is not None:
            svg_path = build_dir / "graph.svg"
            svg_path.write_text(svg, encoding="utf-8")
            written["svg"] = svg_path
    return written


def _mermaid_id(node_id: str) -> str:
    """Return a Mermaid-safe identifier for ``node_id``.

    Mermaid node ids may only contain alphanumerics and underscores, so any
    other character (``.``, ``-``, ``/``, ``:`` are all legal in blueprint ids)
    is replaced with an underscore. A leading ``n_`` keeps ids that start with a
    digit valid.
    """
    safe = "".join(ch if ch.isalnum() else "_" for ch in node_id)
    return f"n_{safe}"


def _mermaid_label(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', "&quot;")
        .replace("\n", "<br/>")
    )


def _dot_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
