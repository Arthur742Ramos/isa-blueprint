"""Human-readable Markdown status report."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def render_markdown_report(project: BlueprintProject) -> str:
    counts = Counter(n.status.formal.value for n in project.nodes)
    total = len(project.nodes)
    proved = counts.get(FormalStatus.PROVED.value, 0) + counts.get(FormalStatus.FOUND.value, 0)
    coverage = (proved / total * 100.0) if total else 0.0

    lines: list[str] = []
    lines.append(f"# {project.name} - blueprint status")
    lines.append("")
    lines.append(f"- Nodes: **{total}**")
    lines.append(f"- Formalised (found or proved): **{proved}** ({coverage:.1f}%)")
    lines.append("")
    if counts:
        lines.append("| Formal status | Count |")
        lines.append("| --- | ---: |")
        for status, count in sorted(counts.items()):
            lines.append(f"| `{status}` | {count} |")
        lines.append("")
    lines.append("## Nodes")
    lines.append("")
    lines.append("| ID | Kind | Title | Isabelle fact | Blueprint | Formal | Agent |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for node in project.nodes:
        fact = node.isabelle.fact or ""
        lines.append(
            f"| `{node.id}` | {node.kind.value} | {node.title} | "
            f"`{fact}` | {node.status.blueprint.value} | {node.status.formal.value} | "
            f"{node.status.agent.value} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_markdown_report(project: BlueprintProject, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(project), encoding="utf-8")
    return path
