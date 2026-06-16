"""Concise project health overview for terminal and JSON status output."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from isabelle_blueprint import console
from isabelle_blueprint.agents.tasks import AgentTask
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics


@dataclass(frozen=True)
class NextTaskOverview:
    id: str
    node_id: str
    title: str
    kind: str
    target_fact: str | None
    priority: str | None
    difficulty: str | None
    blocking_count: int | None
    suggested_order: int | None

    @classmethod
    def from_task(cls, task: AgentTask) -> NextTaskOverview:
        metadata = task.metadata
        return cls(
            id=task.id,
            node_id=task.node_id,
            title=task.title,
            kind=task.kind,
            target_fact=task.target_fact,
            priority=metadata.priority if metadata is not None else None,
            difficulty=metadata.difficulty if metadata is not None else None,
            blocking_count=metadata.blocking_count if metadata is not None else None,
            suggested_order=metadata.suggested_order if metadata is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StatusOverview:
    project: str
    health: str
    metrics: StatusMetrics
    ready_task_count: int
    next_task: NextTaskOverview | None
    top_ready_tasks: tuple[NextTaskOverview, ...] | None = None
    filters: dict[str, list[str]] | None = None
    filtered_ready_task_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "project": self.project,
            "health": self.health,
            "metrics": self.metrics.to_dict(),
            "ready_task_count": self.ready_task_count,
            "next_task": self.next_task.to_dict() if self.next_task is not None else None,
        }
        if self.top_ready_tasks is not None:
            payload["top_ready_tasks"] = [task.to_dict() for task in self.top_ready_tasks]
        if self.filters is not None:
            payload["filters"] = {key: list(values) for key, values in self.filters.items()}
        if self.filtered_ready_task_count is not None:
            payload["filtered_ready_task_count"] = self.filtered_ready_task_count
        return payload


def build_status_overview(
    project: BlueprintProject,
    ready_tasks: Sequence[AgentTask],
    *,
    top_task_count: int | None = None,
    selected_ready_tasks: Sequence[AgentTask] | None = None,
    filters: dict[str, list[str]] | None = None,
) -> StatusOverview:
    """Build the read-only summary used by ``isabelle-blueprint status``.

    ``ready_tasks`` is the canonical (unfiltered) ready set used for health
    classification and ``ready_task_count``. When filter flags narrow the
    view, callers pass the filtered ordering as ``selected_ready_tasks`` so
    ``next_task`` and ``top_ready_tasks`` reflect that subset while project
    health remains tied to the full set.
    """

    metrics = build_status_metrics(project)
    selected = list(selected_ready_tasks) if selected_ready_tasks is not None else list(ready_tasks)
    next_task = NextTaskOverview.from_task(selected[0]) if selected else None
    top_ready_tasks = (
        tuple(NextTaskOverview.from_task(task) for task in selected[:top_task_count])
        if top_task_count is not None
        else None
    )
    filters_payload = (
        {key: list(values) for key, values in filters.items()} if filters is not None else None
    )
    filtered_count = len(selected) if filters_payload is not None else None
    return StatusOverview(
        project=project.name,
        health=_health(metrics, ready_tasks),
        metrics=metrics,
        ready_task_count=len(ready_tasks),
        next_task=next_task,
        top_ready_tasks=top_ready_tasks,
        filters=filters_payload,
        filtered_ready_task_count=filtered_count,
    )


def render_status_overview(overview: StatusOverview) -> str:
    """Render a compact terminal summary."""

    metrics = overview.metrics
    filters_active = overview.filters is not None
    ready_line = f"Ready tasks: {overview.ready_task_count}"
    if filters_active:
        filtered = overview.filtered_ready_task_count or 0
        ready_line = f"Ready tasks: {overview.ready_task_count} total, {filtered} match filters"
    lines = [
        f"{overview.project}: {_paint_health(overview.health, metrics)}",
        f"Coverage: {_coverage_text(metrics)}",
        (
            "Nodes: "
            f"{metrics.node_count} total, "
            f"{metrics.formal_target_count} formal target(s), "
            f"{metrics.problem_count} problem(s), "
            f"{metrics.stale_count} stale, "
            f"cycles {_yes_no(metrics.has_cycles)}"
        ),
    ]
    if filters_active:
        formatted = _format_filters_dict(overview.filters or {})
        if formatted:
            lines.append(f"Filters: {formatted}")
    lines.append(ready_line)
    next_label = "Next task matching filters" if filters_active else "Next task"
    if overview.next_task is None:
        if filters_active and overview.ready_task_count:
            lines.append(
                f"{next_label}: none "
                f"({overview.ready_task_count} ready task(s) excluded by filters)"
            )
        else:
            lines.append(f"{next_label}: none")
    else:
        lines.append(f"{next_label}: " + _next_task_text(overview.next_task))
    if overview.top_ready_tasks is not None:
        top_label = "Top ready tasks matching filters" if filters_active else "Top ready tasks"
        if overview.top_ready_tasks:
            lines.append(f"{top_label}:")
            lines.extend(
                f"  {index}. {_next_task_text(task)}"
                for index, task in enumerate(overview.top_ready_tasks, start=1)
            )
        else:
            lines.append(f"{top_label}: none")
    return "\n".join(lines) + "\n"


def _md_cell(text: str) -> str:
    """Escape a value for safe inclusion in a Markdown table cell.

    A literal ``|`` would otherwise start a new column and a newline would
    terminate the row, so both are neutralised.
    """
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


def render_status_markdown(overview: StatusOverview) -> str:
    """Render the health overview as a Markdown document.

    A heading carries the project name and health label, a metrics table lists
    coverage/proved/problems/stale/ready-tasks/cycle-status, and a short
    next-task line closes the document. Used by ``status --markdown``.
    """

    metrics = overview.metrics
    filters_active = overview.filters is not None
    if filters_active:
        ready_cell = (
            f"{overview.ready_task_count} total, "
            f"{overview.filtered_ready_task_count or 0} match filters"
        )
    else:
        ready_cell = str(overview.ready_task_count)
    rows = (
        ("Coverage", _coverage_text(metrics)),
        ("Proved", f"{metrics.proved_count}/{metrics.formal_target_count}"),
        ("Problems", str(metrics.problem_count)),
        ("Stale", str(metrics.stale_count)),
        ("Ready tasks", ready_cell),
        ("Cycles", _yes_no(metrics.has_cycles)),
    )
    lines = [
        f"# {_md_cell(overview.project)} status: {_md_cell(overview.health)}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    lines.extend(f"| {label} | {_md_cell(value)} |" for label, value in rows)
    if filters_active:
        formatted = _format_filters_dict(overview.filters or {})
        if formatted:
            lines.extend(["", f"Filters: {_md_cell(formatted)}"])
    lines.append("")
    next_label = "Next task matching filters" if filters_active else "Next task"
    if overview.next_task is None:
        if filters_active and overview.ready_task_count:
            lines.append(
                f"{next_label}: none "
                f"({overview.ready_task_count} ready task(s) excluded by filters)"
            )
        else:
            lines.append(f"{next_label}: none")
    else:
        lines.append(f"{next_label}: {_md_cell(_next_task_text(overview.next_task))}")
    return "\n".join(lines) + "\n"


def _paint_health(health: str, metrics: StatusMetrics) -> str:
    """Colour the health label red/yellow/green by project condition."""

    if metrics.problem_count or metrics.has_cycles:
        return console.error(health)
    if metrics.stale_count:
        return console.warning(health)
    return console.success(health)


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


def _health(metrics: StatusMetrics, ready_tasks: Sequence[AgentTask]) -> str:
    if metrics.has_cycles or metrics.has_problems:
        return "problem"
    if metrics.stale_count:
        return "stale"
    if metrics.coverage_percent == 100 and not ready_tasks:
        return "complete"
    if metrics.formal_target_count == 0:
        return "unstarted"
    if ready_tasks:
        return "ready"
    return "blocked"


def _coverage_text(metrics: StatusMetrics) -> str:
    if metrics.coverage_percent is None:
        return "no formal targets"
    return (
        f"{metrics.coverage_percent}% formal "
        f"({metrics.proved_count}/{metrics.formal_target_count} proved)"
    )


def _next_task_text(task: NextTaskOverview) -> str:
    target = f" -> {task.target_fact}" if task.target_fact else ""
    details = []
    if task.priority:
        details.append(f"priority {task.priority}")
    if task.difficulty:
        details.append(f"difficulty {task.difficulty}")
    if task.blocking_count is not None:
        details.append(f"blocks {task.blocking_count}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{task.id} - {task.title}{target}{suffix}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
