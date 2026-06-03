"""Build agent handoff context bundles."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from isabelle_blueprint import __version__
from isabelle_blueprint.agents.memory import NodeMemorySummary
from isabelle_blueprint.agents.tasks import AgentTask
from isabelle_blueprint.config import BlueprintConfig
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.report.roadmap import RoadmapOverview
from isabelle_blueprint.report.status_overview import StatusOverview

AGENT_CONTEXT_SCHEMA_VERSION = 1
DEFAULT_AGENT_CONTEXT_TASK_LIMIT = 5


@dataclass(frozen=True)
class AgentContextWarning:
    code: str
    message: str
    severity: str = "warning"
    related_nodes: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "related_nodes": list(self.related_nodes or []),
        }


@dataclass(frozen=True)
class AgentContextCommand:
    intent: str
    description: str
    argv: list[str]
    writes: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AgentContextTask:
    id: str
    node_id: str
    title: str
    kind: str
    target_fact: str | None
    target_theory: str | None
    prompt_path: str
    priority: str | None
    difficulty: str | None
    blocking_count: int | None
    suggested_order: int | None
    memory: NodeMemorySummary | None = None

    @classmethod
    def from_task(cls, task: AgentTask, *, prompt_path: str) -> AgentContextTask:
        metadata = task.metadata
        return cls(
            id=task.id,
            node_id=task.node_id,
            title=task.title,
            kind=task.kind,
            target_fact=task.target_fact,
            target_theory=task.target_theory,
            prompt_path=prompt_path,
            priority=metadata.priority if metadata is not None else None,
            difficulty=metadata.difficulty if metadata is not None else None,
            blocking_count=metadata.blocking_count if metadata is not None else None,
            suggested_order=metadata.suggested_order if metadata is not None else None,
            memory=task.memory,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "title": self.title,
            "kind": self.kind,
            "target_fact": self.target_fact,
            "target_theory": self.target_theory,
            "prompt_path": self.prompt_path,
            "priority": self.priority,
            "difficulty": self.difficulty,
            "blocking_count": self.blocking_count,
            "suggested_order": self.suggested_order,
            "memory": self.memory.to_dict() if self.memory is not None else None,
        }


@dataclass(frozen=True)
class AgentContext:
    schema_version: int
    tool_version: str
    generated_at: str
    project: dict[str, object]
    health: str
    metrics: dict[str, object]
    ready_task_count: int
    ready_tasks_truncated: bool
    suggested_next_task: str | None
    suggested_path: list[str]
    warnings: list[AgentContextWarning]
    artifacts: dict[str, str]
    commands: list[AgentContextCommand]
    ready_tasks: list[AgentContextTask]
    filters: dict[str, list[str]] | None = None
    filtered_ready_task_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "generated_at": self.generated_at,
            "project": dict(self.project),
            "health": self.health,
            "metrics": dict(self.metrics),
            "ready_task_count": self.ready_task_count,
            "ready_tasks_truncated": self.ready_tasks_truncated,
            "suggested_next_task": self.suggested_next_task,
            "suggested_path": list(self.suggested_path),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "artifacts": dict(self.artifacts),
            "commands": [command.to_dict() for command in self.commands],
            "ready_tasks": [task.to_dict() for task in self.ready_tasks],
        }
        if self.filters is not None:
            payload["filters"] = {key: list(values) for key, values in self.filters.items()}
        if self.filtered_ready_task_count is not None:
            payload["filtered_ready_task_count"] = self.filtered_ready_task_count
        return payload


def build_agent_context(
    config: BlueprintConfig,
    status: StatusOverview,
    roadmap: RoadmapOverview,
    ready_tasks: list[AgentTask],
    *,
    max_tasks: int = DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
    generated_at: str | None = None,
    filtered_ready_tasks: list[AgentTask] | None = None,
    filters: dict[str, list[str]] | None = None,
    filter_argv: list[str] | None = None,
) -> AgentContext:
    """Project status, roadmap, task, and memory data in one agent-friendly payload.

    ``ready_tasks`` is the canonical (unfiltered) ready set; ``ready_task_count``
    and warnings (including ``stale_memory`` / ``no_ready_tasks``) are computed
    from it so the bundle stays a faithful project snapshot.  When ``filters``
    narrow the embedded list, callers pass the filtered ordering as
    ``filtered_ready_tasks`` and the active filter flags as ``filter_argv``;
    the latter is appended to filter-sensitive recommended commands so an
    agent re-running them stays in the filtered subset.
    """

    if max_tasks < 1:
        raise BlueprintError("agent context max_tasks must be at least 1")
    artifacts = _artifact_paths(config)
    embedded_source = filtered_ready_tasks if filtered_ready_tasks is not None else ready_tasks
    shown_tasks = embedded_source[:max_tasks]
    filters_payload = (
        {key: list(values) for key, values in filters.items()} if filters is not None else None
    )
    filtered_count = len(embedded_source) if filters_payload is not None else None
    return AgentContext(
        schema_version=AGENT_CONTEXT_SCHEMA_VERSION,
        tool_version=__version__,
        generated_at=generated_at or agent_context_timestamp(),
        project={
            "name": status.project,
            "root": ".",
            "blueprints": [
                _relative_path(path, config.project_root) for path in config.blueprint_paths
            ],
        },
        health=status.health,
        metrics=status.metrics.to_dict(),
        ready_task_count=len(ready_tasks),
        ready_tasks_truncated=len(embedded_source) > len(shown_tasks),
        suggested_next_task=roadmap.suggested_next_task,
        suggested_path=list(roadmap.suggested_path),
        warnings=_context_warnings(status, roadmap, ready_tasks),
        artifacts=artifacts,
        commands=_recommended_commands(
            roadmap.suggested_next_task,
            filter_argv=filter_argv,
        ),
        ready_tasks=[
            AgentContextTask.from_task(
                task,
                prompt_path=_relative_path(
                    config.build_dir / "prompts" / f"{task.id}.md",
                    config.project_root,
                ),
            )
            for task in shown_tasks
        ],
        filters=filters_payload,
        filtered_ready_task_count=filtered_count,
    )


def write_agent_context(
    context: AgentContext,
    build_dir: Path,
    *,
    json_name: str = "agent-context.json",
    md_name: str = "agent-context.md",
) -> dict[str, Path]:
    """Write agent-context JSON and Markdown handoff artifacts."""

    build_dir.mkdir(parents=True, exist_ok=True)
    json_path = build_dir / json_name
    md_path = build_dir / md_name
    json_path.write_text(json.dumps(context.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_agent_context(context), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def render_agent_context(context: AgentContext) -> str:
    """Render a concise Markdown handoff for humans or chat-oriented agents."""

    project_name = str(context.project["name"])
    filters_active = context.filters is not None
    lines = [
        f"# {project_name} agent context",
        "",
        f"Health: `{context.health}`",
        f"Ready tasks: `{context.ready_task_count}`",
    ]
    if filters_active:
        formatted = _format_filters_dict(context.filters or {})
        if formatted:
            lines.append(f"Filters: `{formatted}`")
        filtered = context.filtered_ready_task_count or 0
        lines.append(f"Filtered ready tasks: `{filtered}`")
    lines.extend(
        [
            (
                f"Suggested next task: `{context.suggested_next_task}`"
                if context.suggested_next_task
                else "Suggested next task: none"
            ),
            "Suggested path: "
            + (" -> ".join(f"`{node_id}`" for node_id in context.suggested_path) or "none"),
            "",
            "## Artifacts",
            "",
        ]
    )
    for name, path in context.artifacts.items():
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")

    if context.warnings:
        lines.extend(["## Warnings", ""])
        for warning in context.warnings:
            related = (
                " (" + ", ".join(f"`{node}`" for node in warning.related_nodes or []) + ")"
                if warning.related_nodes
                else ""
            )
            lines.append(
                f"- `{warning.severity}` `{warning.code}`: {warning.message}{related}"
            )
        lines.append("")

    ready_heading = "## Ready tasks matching filters" if filters_active else "## Ready tasks"
    lines.extend([ready_heading, ""])
    if not context.ready_tasks:
        if filters_active and context.ready_task_count:
            lines.append(
                "No ready tasks match the active filters; "
                f"{context.ready_task_count} canonical ready task(s) excluded."
            )
        else:
            lines.append("No ready tasks are currently available.")
    else:
        for task in context.ready_tasks:
            details = []
            if task.priority:
                details.append(f"priority `{task.priority}`")
            if task.difficulty:
                details.append(f"difficulty `{task.difficulty}`")
            if task.blocking_count is not None:
                details.append(f"blocks `{task.blocking_count}`")
            detail = "; ".join(details)
            suffix = f" ({detail})" if detail else ""
            target = f" -> `{task.target_fact}`" if task.target_fact else ""
            lines.append(
                f"- `{task.id}` - {task.title}{target}; prompt `{task.prompt_path}`{suffix}"
            )
        if context.ready_tasks_truncated:
            tasks_json = context.artifacts["tasks_json"]
            if filters_active:
                lines.append(
                    "- _Filtered ready task list truncated; see "
                    f"`{tasks_json}` for the canonical (unfiltered) catalog._"
                )
            else:
                lines.append(
                    f"- _Ready task list truncated; see `{tasks_json}` for all tasks._"
                )
    lines.append("")

    lines.extend(["## Recommended commands", ""])
    for command in context.commands:
        lines.append(f"- `{command.intent}`: `{' '.join(command.argv)}`")
    lines.append("")
    return "\n".join(lines)


_FILTER_LABELS: tuple[tuple[str, str], ...] = (
    ("kind", "kind"),
    ("priority", "priority"),
    ("difficulty", "difficulty"),
    ("memory_state", "memory-state"),
    ("last_outcome", "last-outcome"),
    ("exclude_node", "exclude-node"),
)


def _format_filters_dict(filters: dict[str, list[str]]) -> str:
    """Render a filter dict (kind/priority/...) into a compact human-readable string."""

    parts: list[str] = []
    for key, label in _FILTER_LABELS:
        values = filters.get(key) or []
        if values:
            parts.append(f"{label}={','.join(values)}")
    return "; ".join(parts)


def agent_context_timestamp() -> str:
    """Return a UTC generation timestamp, honoring SOURCE_DATE_EPOCH if set."""

    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        try:
            value = int(source_date_epoch)
        except ValueError as exc:
            raise BlueprintError("SOURCE_DATE_EPOCH must be an integer Unix timestamp") from exc
        current = datetime.fromtimestamp(value, UTC)
    else:
        current = datetime.now(UTC)
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _artifact_paths(config: BlueprintConfig) -> dict[str, str]:
    return {
        "agent_context_json": _relative_path(config.build_dir / "agent-context.json", config.project_root),
        "agent_context_md": _relative_path(config.build_dir / "agent-context.md", config.project_root),
        "project_json": _relative_path(config.project_json_path, config.project_root),
        "tasks_json": _relative_path(config.tasks_json_path, config.project_root),
        "tasks_md": _relative_path(config.tasks_md_path, config.project_root),
        "prompts_dir": _relative_path(config.build_dir / "prompts", config.project_root),
        "roadmap_json": _relative_path(config.build_dir / "roadmap.json", config.project_root),
        "roadmap_md": _relative_path(config.build_dir / "roadmap.md", config.project_root),
        "agent_memory": _relative_path(config.agent_memory_path, config.project_root),
        "check_report": _relative_path(config.check_report_path, config.project_root),
    }


def _relative_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _context_warnings(
    status: StatusOverview,
    roadmap: RoadmapOverview,
    ready_tasks: list[AgentTask],
) -> list[AgentContextWarning]:
    warnings: list[AgentContextWarning] = []
    if roadmap.cycles:
        related = sorted({node_id for cycle in roadmap.cycles for node_id in cycle})
        warnings.append(
            AgentContextWarning(
                code="cycles_detected",
                severity="error",
                message=f"{len(roadmap.cycles)} dependency cycle(s) need human repair.",
                related_nodes=related,
            )
        )
    problem_nodes = sorted(
        item.node_id
        for stage in roadmap.stages
        for item in stage.items
        if item.status == "problem"
    )
    if problem_nodes:
        warnings.append(
            AgentContextWarning(
                code="problem_nodes",
                severity="error",
                message=f"{len(problem_nodes)} node(s) have failed or unresolved formal status.",
                related_nodes=problem_nodes,
            )
        )
    stale_nodes = sorted(
        item.node_id
        for stage in roadmap.stages
        for item in stage.items
        if item.status == "stale"
    )
    if stale_nodes:
        warnings.append(
            AgentContextWarning(
                code="stale_nodes",
                message=f"{len(stale_nodes)} node(s) should be rechecked before proof work.",
                related_nodes=stale_nodes,
            )
        )
    missing_dependencies = sorted(
        item.node_id
        for stage in roadmap.stages
        for item in stage.items
        for blocker in item.blocked_by
        if blocker.reason == "missing_dependency"
    )
    if missing_dependencies:
        warnings.append(
            AgentContextWarning(
                code="missing_dependencies",
                severity="error",
                message="Some nodes depend on undefined blueprint ids.",
                related_nodes=missing_dependencies,
            )
        )
    stale_memory = sorted(
        task.node_id
        for task in ready_tasks
        if task.memory is not None and task.memory.stale
    )
    if stale_memory:
        warnings.append(
            AgentContextWarning(
                code="stale_memory",
                message="Some ready-task memory was recorded against older task inputs.",
                related_nodes=stale_memory,
            )
        )
    if not ready_tasks and status.health not in {"complete", "problem"}:
        warnings.append(
            AgentContextWarning(
                code="no_ready_tasks",
                severity="info",
                message="No unblocked task is available; inspect blockers in the roadmap.",
            )
        )
    return warnings


def _recommended_commands(
    suggested_next_task: str | None,
    *,
    filter_argv: list[str] | None = None,
) -> list[AgentContextCommand]:
    extras = list(filter_argv or [])
    commands = [
        AgentContextCommand(
            intent="refresh_context",
            description="Refresh the machine-readable handoff without writing artifacts.",
            argv=["isabelle-blueprint", "agent-context", ".", "--json", *extras],
        ),
        AgentContextCommand(
            intent="write_context",
            description="Regenerate the full handoff bundle, task prompts, and roadmap artifacts.",
            argv=["isabelle-blueprint", "agent-context", ".", "--write", *extras],
            writes=True,
        ),
        AgentContextCommand(
            intent="next_task_prompt",
            description=(
                "Print the highest-priority ready proof-task prompt matching the active filters."
                if extras
                else "Print the highest-priority ready proof-task prompt."
            ),
            argv=["isabelle-blueprint", "next", ".", *extras],
        ),
        AgentContextCommand(
            intent="inspect_roadmap",
            description="Inspect the staged proof-work plan.",
            argv=["isabelle-blueprint", "roadmap", ".", "--json"],
        ),
    ]
    node_arg = suggested_next_task.removeprefix("task-") if suggested_next_task else "<node-id>"
    commands.append(
        AgentContextCommand(
            intent="prepare_attempt",
            description="Write the selected task prompt and run a best-effort check pass.",
            argv=[
                "isabelle-blueprint",
                "attempt",
                ".",
                "--node",
                node_arg,
                "--check",
            ],
            writes=True,
        )
    )
    commands.append(
        AgentContextCommand(
            intent="record_attempt",
            description="Record proof-attempt memory after working on a node.",
            argv=[
                "isabelle-blueprint",
                "memory",
                ".",
                "--record",
                "--node",
                node_arg,
                "--outcome",
                "failed",
                "--summary",
                "<summary>",
            ],
            writes=True,
        )
    )
    return commands
