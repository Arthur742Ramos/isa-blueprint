"""Generate agent-ready tasks.

A node becomes a task when:

* its own formal status is not yet ``FOUND``/``PROVED``, **and**
* every dependency listed in ``uses`` has formal status ``FOUND`` or ``PROVED``.

For each such node we emit a structured JSON entry plus a Markdown prompt that
includes the informal statement, the informal proof sketch, the names of any
dependencies (with their Isabelle facts), and explicit acceptance criteria. See
roadmap section 9.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


@dataclass
class AgentTaskDependency:
    id: str
    title: str
    fact: str | None
    theory: str | None


@dataclass
class AgentTask:
    id: str
    node_id: str
    title: str
    kind: str
    target_fact: str | None
    target_theory: str | None
    informal_statement: str
    informal_proof: str
    dependencies: list[AgentTaskDependency] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dependencies"] = [asdict(dep) for dep in self.dependencies]
        return d


def _is_ready(node: BlueprintNode, project: BlueprintProject) -> bool:
    if node.status.formal in {FormalStatus.FOUND, FormalStatus.PROVED}:
        return False
    by_id = project.by_id()
    for dep_id in node.uses:
        dep = by_id.get(dep_id)
        if dep is None:
            return False
        if dep.status.formal not in {FormalStatus.FOUND, FormalStatus.PROVED}:
            return False
    return True


def generate_tasks(project: BlueprintProject) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    by_id = project.by_id()
    for node in project.nodes:
        if not _is_ready(node, project):
            continue
        deps = [
            AgentTaskDependency(
                id=dep_id,
                title=by_id[dep_id].title,
                fact=by_id[dep_id].isabelle.fact,
                theory=by_id[dep_id].isabelle.theory,
            )
            for dep_id in node.uses
            if dep_id in by_id
        ]
        criteria = _acceptance_criteria(node)
        tasks.append(
            AgentTask(
                id=f"task-{node.id}",
                node_id=node.id,
                title=node.title,
                kind=node.kind.value,
                target_fact=node.isabelle.fact,
                target_theory=node.isabelle.theory,
                informal_statement=node.statement,
                informal_proof=node.informal_proof,
                dependencies=deps,
                acceptance_criteria=criteria,
            )
        )
    return tasks


def _acceptance_criteria(node: BlueprintNode) -> list[str]:
    criteria = [
        f"`{node.isabelle.fact}` exists in the Isabelle session after the change."
        if node.isabelle.fact
        else "An Isabelle fact matching the informal statement is added.",
        "The proof does not use `sorry`, `oops`, or any oracle.",
        "`isabelle build` succeeds with no new warnings about the modified theory.",
        "`isabelle-blueprint check` reports this node's formal status as `found`.",
    ]
    return criteria


def write_tasks(
    project: BlueprintProject,
    build_dir: Path,
    *,
    json_name: str = "tasks.json",
    md_name: str = "tasks.md",
    prompt_dir_name: str = "prompts",
) -> dict[str, Path]:
    """Write ``tasks.json``, ``tasks.md`` and ``prompts/<task-id>.md`` files."""
    build_dir.mkdir(parents=True, exist_ok=True)
    tasks = generate_tasks(project)

    json_path = build_dir / json_name
    md_path = build_dir / md_name
    prompts_dir = build_dir / prompt_dir_name
    prompts_dir.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps({"tasks": [t.to_dict() for t in tasks]}, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(_render_tasks_index(tasks), encoding="utf-8")

    for task in tasks:
        (prompts_dir / f"{task.id}.md").write_text(_render_prompt(task), encoding="utf-8")

    return {"json": json_path, "md": md_path, "prompts": prompts_dir}


def _render_tasks_index(tasks: list[AgentTask]) -> str:
    if not tasks:
        return "# Agent tasks\n\nNo ready tasks - every node is either complete or blocked.\n"
    lines = ["# Agent tasks", ""]
    for task in tasks:
        target = task.target_fact or "(no Isabelle ref)"
        lines.append(f"- **{task.title}** (`{task.node_id}`) -> `{target}`")
    lines.append("")
    lines.append(f"Total: {len(tasks)} ready task(s).")
    return "\n".join(lines) + "\n"


def _render_prompt(task: AgentTask) -> str:
    parts: list[str] = []
    parts.append(f"# Task: {task.title}")
    parts.append("")
    parts.append(f"- **Blueprint id**: `{task.node_id}`")
    parts.append(f"- **Kind**: `{task.kind}`")
    if task.target_fact:
        parts.append(f"- **Target Isabelle fact**: `{task.target_fact}`")
    if task.target_theory:
        parts.append(f"- **Theory**: `{task.target_theory}`")
    parts.append("")
    parts.append("## Informal statement")
    parts.append("")
    parts.append(task.informal_statement.strip() or "_(statement missing in blueprint)_")
    parts.append("")
    if task.informal_proof.strip():
        parts.append("## Informal proof sketch")
        parts.append("")
        parts.append(task.informal_proof.strip())
        parts.append("")
    if task.dependencies:
        parts.append("## Dependencies you may use")
        parts.append("")
        for dep in task.dependencies:
            fact = f"`{dep.fact}`" if dep.fact else "_(no Isabelle ref)_"
            parts.append(f"- `{dep.id}` - {dep.title} -> {fact}")
        parts.append("")
    parts.append("## Acceptance criteria")
    parts.append("")
    for crit in task.acceptance_criteria:
        parts.append(f"- {crit}")
    parts.append("")
    parts.append("Do not modify other theories unless required by the change.")
    parts.append("")
    return "\n".join(parts)
