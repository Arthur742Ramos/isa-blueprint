"""Ready-task filtering and selection shared by CLI and MCP surfaces."""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.agents.memory import VALID_OUTCOMES
from isabelle_blueprint.agents.tasks import AgentTask
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

READY_TASK_PRIORITIES = ("high", "medium", "low")
READY_TASK_DIFFICULTIES = ("low", "medium", "high")
READY_TASK_MEMORY_STATES = ("fresh", "attempted", "stale")
READY_TASK_LAST_OUTCOMES = tuple(sorted(VALID_OUTCOMES))


@dataclass(frozen=True)
class ReadyTaskFilters:
    kinds: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    difficulties: tuple[str, ...] = ()
    memory_states: tuple[str, ...] = ()
    last_outcomes: tuple[str, ...] = ()
    excluded_nodes: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(
            self.kinds
            or self.priorities
            or self.difficulties
            or self.memory_states
            or self.last_outcomes
            or self.excluded_nodes
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "kind": list(self.kinds),
            "priority": list(self.priorities),
            "difficulty": list(self.difficulties),
            "memory_state": list(self.memory_states),
            "last_outcome": list(self.last_outcomes),
            "exclude_node": list(self.excluded_nodes),
        }


def ready_task_filters_from_values(
    *,
    kinds: list[str] | tuple[str, ...] | None = None,
    priorities: list[str] | tuple[str, ...] | None = None,
    difficulties: list[str] | tuple[str, ...] | None = None,
    memory_states: list[str] | tuple[str, ...] | None = None,
    last_outcomes: list[str] | tuple[str, ...] | None = None,
    excluded_nodes: list[str] | tuple[str, ...] | None = None,
) -> ReadyTaskFilters:
    """Build validated ready-task filters from plain values."""

    filters = ReadyTaskFilters(
        kinds=_dedupe(kinds),
        priorities=_dedupe(priorities),
        difficulties=_dedupe(difficulties),
        memory_states=_dedupe(memory_states),
        last_outcomes=_dedupe(last_outcomes),
        excluded_nodes=_dedupe(excluded_nodes),
    )
    _validate_filter_values(filters)
    return filters


def ready_task_filters_from_args(args: object) -> ReadyTaskFilters:
    """Build ready-task filters from an argparse-like object."""

    return ready_task_filters_from_values(
        kinds=getattr(args, "kind", None),
        priorities=getattr(args, "priority", None),
        difficulties=getattr(args, "difficulty", None),
        memory_states=getattr(args, "memory_state", None),
        last_outcomes=getattr(args, "last_outcome", None),
        excluded_nodes=getattr(args, "exclude_node", None),
    )


def filter_ready_tasks(tasks: list[AgentTask], filters: ReadyTaskFilters) -> list[AgentTask]:
    if not filters.active:
        return tasks
    return [task for task in tasks if task_matches_filters(task, filters)]


def task_matches_filters(task: AgentTask, filters: ReadyTaskFilters) -> bool:
    if filters.kinds and task.kind not in filters.kinds:
        return False
    metadata = task.metadata
    if filters.priorities and (
        metadata is None or metadata.priority not in filters.priorities
    ):
        return False
    if filters.difficulties and (
        metadata is None or metadata.difficulty not in filters.difficulties
    ):
        return False
    if filters.memory_states and not _task_matches_memory_states(task, filters.memory_states):
        return False
    if filters.last_outcomes and not _task_matches_last_outcomes(task, filters.last_outcomes):
        return False
    if filters.excluded_nodes and _task_is_excluded(task, filters.excluded_nodes):
        return False
    return True


def selection_metadata(
    filters: ReadyTaskFilters,
    *,
    ready_task_count: int,
    filtered_ready_task_count: int,
) -> dict[str, object]:
    return {
        "filters": filters.to_dict(),
        "ready_task_count": ready_task_count,
        "filtered_ready_task_count": filtered_ready_task_count,
    }


def format_ready_task_filters(filters: ReadyTaskFilters) -> str:
    parts: list[str] = []
    if filters.kinds:
        parts.append(f"kind={','.join(filters.kinds)}")
    if filters.priorities:
        parts.append(f"priority={','.join(filters.priorities)}")
    if filters.difficulties:
        parts.append(f"difficulty={','.join(filters.difficulties)}")
    if filters.memory_states:
        parts.append(f"memory-state={','.join(filters.memory_states)}")
    if filters.last_outcomes:
        parts.append(f"last-outcome={','.join(filters.last_outcomes)}")
    if filters.excluded_nodes:
        parts.append(f"exclude-node={','.join(filters.excluded_nodes)}")
    return "; ".join(parts)


def ready_task_filters_to_argv(filters: ReadyTaskFilters) -> list[str]:
    """Render filter flags back to argv form for embedding in suggested commands."""

    argv: list[str] = []
    for flag, values in (
        ("--kind", filters.kinds),
        ("--priority", filters.priorities),
        ("--difficulty", filters.difficulties),
        ("--memory-state", filters.memory_states),
        ("--last-outcome", filters.last_outcomes),
        ("--exclude-node", filters.excluded_nodes),
    ):
        for value in values:
            argv.extend([flag, value])
    return argv


def no_ready_task_message(ready_task_count: int, filters: ReadyTaskFilters) -> str:
    if filters.active and ready_task_count:
        excluded = (
            "1 ready task was excluded"
            if ready_task_count == 1
            else f"{ready_task_count} ready tasks were excluded"
        )
        return (
            "No ready tasks match the requested filters "
            f"({format_ready_task_filters(filters)}); {excluded}."
        )
    return "No ready tasks are currently available."


def select_ready_task(
    ready_tasks: list[AgentTask],
    selector: str | None,
    project: BlueprintProject,
    *,
    filters: ReadyTaskFilters | None = None,
    unfiltered_ready_tasks: list[AgentTask] | None = None,
) -> AgentTask | None:
    if selector is None:
        return ready_tasks[0] if ready_tasks else None

    filters = filters or ReadyTaskFilters()
    unfiltered_ready_tasks = unfiltered_ready_tasks or ready_tasks
    for task in ready_tasks:
        if task.id == selector:
            return task
    for task in ready_tasks:
        if task.node_id == selector:
            return task

    for task in unfiltered_ready_tasks:
        if task.id == selector or task.node_id == selector:
            raise BlueprintError(_filter_mismatch_message(task, filters))

    by_id = project.by_id()
    candidate_node_id = selector.removeprefix("task-") if selector.startswith("task-") else selector
    if selector in by_id:
        raise BlueprintError(_not_ready_node_message(selector, project))
    if candidate_node_id in by_id:
        raise BlueprintError(_not_ready_node_message(candidate_node_id, project))
    raise BlueprintError(f"unknown ready task or node {selector!r}")


def _dedupe(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values or ()))


def _validate_filter_values(filters: ReadyTaskFilters) -> None:
    _validate_choices("kind", filters.kinds, tuple(kind.value for kind in NodeKind))
    _validate_choices("priority", filters.priorities, READY_TASK_PRIORITIES)
    _validate_choices("difficulty", filters.difficulties, READY_TASK_DIFFICULTIES)
    _validate_choices("memory_state", filters.memory_states, READY_TASK_MEMORY_STATES)
    _validate_choices("last_outcome", filters.last_outcomes, READY_TASK_LAST_OUTCOMES)


def _validate_choices(name: str, values: tuple[str, ...], choices: tuple[str, ...]) -> None:
    unknown = [value for value in values if value not in choices]
    if unknown:
        raise BlueprintError(
            f"unknown {name} value {unknown[0]!r}; choose one of: {', '.join(choices)}"
        )


def _task_matches_memory_states(task: AgentTask, memory_states: tuple[str, ...]) -> bool:
    return any(_task_has_memory_state(task, memory_state) for memory_state in memory_states)


def _task_has_memory_state(task: AgentTask, memory_state: str) -> bool:
    memory = task.memory
    if memory_state == "fresh":
        return memory is None
    if memory_state == "attempted":
        return memory is not None
    if memory_state == "stale":
        return memory is not None and memory.stale
    return False


def _task_matches_last_outcomes(task: AgentTask, last_outcomes: tuple[str, ...]) -> bool:
    return task.memory is not None and task.memory.last_outcome in last_outcomes


def _task_is_excluded(task: AgentTask, excluded_nodes: tuple[str, ...]) -> bool:
    return task.id in excluded_nodes or task.node_id in excluded_nodes


def _filter_mismatch_message(task: AgentTask, filters: ReadyTaskFilters) -> str:
    mismatches: list[str] = []
    if filters.kinds and task.kind not in filters.kinds:
        mismatches.append(f"kind={task.kind} does not match --kind={','.join(filters.kinds)}")
    metadata = task.metadata
    priority = metadata.priority if metadata is not None else None
    difficulty = metadata.difficulty if metadata is not None else None
    if filters.priorities and priority not in filters.priorities:
        actual = priority or "unknown"
        mismatches.append(
            f"priority={actual} does not match --priority={','.join(filters.priorities)}"
        )
    if filters.difficulties and difficulty not in filters.difficulties:
        actual = difficulty or "unknown"
        mismatches.append(
            f"difficulty={actual} does not match --difficulty={','.join(filters.difficulties)}"
        )
    if filters.memory_states and not _task_matches_memory_states(task, filters.memory_states):
        mismatches.append(
            f"memory={_format_task_memory_summary(task)} "
            f"does not match --memory-state={','.join(filters.memory_states)}"
        )
    if filters.last_outcomes and not _task_matches_last_outcomes(task, filters.last_outcomes):
        actual = (
            task.memory.last_outcome
            if task.memory is not None and task.memory.last_outcome is not None
            else "none"
        )
        mismatches.append(
            f"last-outcome={actual} does not match --last-outcome={','.join(filters.last_outcomes)}"
        )
    if filters.excluded_nodes and _task_is_excluded(task, filters.excluded_nodes):
        mismatches.append(f"excluded by --exclude-node={','.join(filters.excluded_nodes)}")
    detail = "; ".join(mismatches) if mismatches else format_ready_task_filters(filters)
    return f"ready task {task.id!r} was excluded by filters ({detail})"


def _format_task_memory_summary(task: AgentTask) -> str:
    memory = task.memory
    if memory is None:
        return "none"
    last_outcome = memory.last_outcome or "unknown"
    stale = "true" if memory.stale else "false"
    return f"attempts={memory.attempt_count},last_outcome={last_outcome},stale={stale}"


def _not_ready_node_message(node_id: str, project: BlueprintProject) -> str:
    node = project.by_id()[node_id]
    details = [f"formal status: {node.status.formal.value}"]
    blockers = _readiness_blockers(node_id, project)
    if blockers:
        details.append(f"blocked by {_format_readiness_blockers(blockers)}")
    return f"node {node_id!r} is not currently ready for a task ({'; '.join(details)})"


def _readiness_blockers(node_id: str, project: BlueprintProject) -> list[str]:
    by_id = project.by_id()
    node = by_id[node_id]
    blockers: list[str] = []
    for dep_id in node.uses:
        dependency = by_id.get(dep_id)
        if dependency is None:
            blockers.append(f"{dep_id} (missing dependency)")
        elif dependency.status.formal not in {FormalStatus.FOUND, FormalStatus.PROVED}:
            blockers.append(f"{dep_id} (formal status: {dependency.status.formal.value})")
    return blockers


def _format_readiness_blockers(blockers: list[str]) -> str:
    shown = blockers[:5]
    suffix = "" if len(blockers) <= len(shown) else f", and {len(blockers) - len(shown)} more"
    return ", ".join(shown) + suffix
