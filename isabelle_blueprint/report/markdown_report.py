"""Human-readable Markdown status report."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import build_status_metrics


def render_markdown_report(project: BlueprintProject) -> str:
    counts = Counter(n.status.formal.value for n in project.nodes)
    metrics = build_status_metrics(project)
    total = metrics.node_count
    proved = metrics.proved_count
    found = metrics.found_count
    if metrics.coverage_percent is None:
        coverage_line = "- Coverage (proved / formal targets): _no formal targets assigned yet_"
    else:
        coverage_line = (
            f"- Coverage (proved / formal targets): **{metrics.coverage_percent}%** "
            f"({proved}/{metrics.formal_target_count})"
        )

    lines: list[str] = []
    lines.append(f"# {project.name} - blueprint status")
    lines.append("")
    lines.append(f"- Nodes: **{total}**")
    lines.append(f"- Formal targets (with Isabelle ref): **{metrics.formal_target_count}**")
    lines.append(f"- Proved: **{proved}**")
    lines.append(f"- Found (exists, not yet trusted): **{found}**")
    lines.append(f"- Problems (broken/not_found/tainted/failed_check): **{metrics.problem_count}**")
    lines.append(coverage_line)
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
