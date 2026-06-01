"""Concise project health overview for terminal and JSON status output."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

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

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "health": self.health,
            "metrics": self.metrics.to_dict(),
            "ready_task_count": self.ready_task_count,
            "next_task": self.next_task.to_dict() if self.next_task is not None else None,
        }


def build_status_overview(
    project: BlueprintProject,
    ready_tasks: Sequence[AgentTask],
) -> StatusOverview:
    """Build the read-only summary used by ``isabelle-blueprint status``."""

    metrics = build_status_metrics(project)
    next_task = NextTaskOverview.from_task(ready_tasks[0]) if ready_tasks else None
    return StatusOverview(
        project=project.name,
        health=_health(metrics, ready_tasks),
        metrics=metrics,
        ready_task_count=len(ready_tasks),
        next_task=next_task,
    )


def render_status_overview(overview: StatusOverview) -> str:
    """Render a compact terminal summary."""

    metrics = overview.metrics
    lines = [
        f"{overview.project}: {overview.health}",
        f"Coverage: {_coverage_text(metrics)}",
        (
            "Nodes: "
            f"{metrics.node_count} total, "
            f"{metrics.formal_target_count} formal target(s), "
            f"{metrics.problem_count} problem(s), "
            f"{metrics.stale_count} stale, "
            f"cycles {_yes_no(metrics.has_cycles)}"
        ),
        f"Ready tasks: {overview.ready_task_count}",
    ]
    if overview.next_task is None:
        lines.append("Next task: none")
    else:
        lines.append("Next task: " + _next_task_text(overview.next_task))
    return "\n".join(lines) + "\n"


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
