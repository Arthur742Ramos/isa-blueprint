"""Roadmap planning for staged proof work."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.agents.tasks import AgentTask
from isabelle_blueprint.graph.dependency_graph import build_graph, dependency_levels
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import (
    PROBLEM_FORMAL_STATUSES,
    StatusMetrics,
    build_status_metrics,
)

ROADMAP_SCHEMA_VERSION = 1
COMPLETE_FORMAL_STATUSES = {FormalStatus.FOUND, FormalStatus.PROVED}


@dataclass(frozen=True)
class RoadmapBlocker:
    id: str
    title: str | None
    status: str
    formal_status: str | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "formal_status": self.formal_status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RoadmapItem:
    node_id: str
    title: str
    kind: str
    stage: int
    status: str
    formal_status: str
    agent_status: str
    target_fact: str | None
    blocked_by: list[RoadmapBlocker]
    blocks: int
    task_id: str | None = None
    priority: str | None = None
    difficulty: str | None = None
    suggested_order: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "kind": self.kind,
            "stage": self.stage,
            "status": self.status,
            "formal_status": self.formal_status,
            "agent_status": self.agent_status,
            "target_fact": self.target_fact,
            "blocked_by": [blocker.to_dict() for blocker in self.blocked_by],
            "blocks": self.blocks,
            "task_id": self.task_id,
            "priority": self.priority,
            "difficulty": self.difficulty,
            "suggested_order": self.suggested_order,
        }


@dataclass(frozen=True)
class RoadmapStage:
    index: int
    items: list[RoadmapItem]

    def to_dict(self) -> dict[str, object]:
        return {"index": self.index, "items": [item.to_dict() for item in self.items]}


@dataclass(frozen=True)
class RoadmapSummary:
    node_count: int
    complete_count: int
    ready_count: int
    blocked_count: int
    problem_count: int
    stale_count: int
    stage_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node_count": self.node_count,
            "complete_count": self.complete_count,
            "ready_count": self.ready_count,
            "blocked_count": self.blocked_count,
            "problem_count": self.problem_count,
            "stale_count": self.stale_count,
            "stage_count": self.stage_count,
        }


@dataclass(frozen=True)
class RoadmapOverview:
    schema_version: int
    project: str
    summary: RoadmapSummary
    metrics: StatusMetrics
    suggested_next_task: str | None
    suggested_path: list[str]
    cycles: list[list[str]]
    stages: list[RoadmapStage]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "summary": self.summary.to_dict(),
            "metrics": self.metrics.to_dict(),
            "suggested_next_task": self.suggested_next_task,
            "suggested_path": list(self.suggested_path),
            "cycles": [list(cycle) for cycle in self.cycles],
            "stages": [stage.to_dict() for stage in self.stages],
        }


def build_roadmap(project: BlueprintProject, ready_tasks: Sequence[AgentTask]) -> RoadmapOverview:
    """Build staged proof-work planning data for ``project``."""

    validation = project.validate()
    cycles = validation.cycles
    cycle_nodes = {node_id for cycle in cycles for node_id in cycle}
    ready_by_node = {task.node_id: task for task in ready_tasks}
    levels = dependency_levels(project)
    stage_by_id = {
        node_id: stage_index
        for stage_index, level in enumerate(levels, start=1)
        for node_id in level
    }
    downstream_counts = _downstream_incomplete_counts(project)

    classifications = {
        node.id: _classify_node(node, ready_by_node=ready_by_node, cycle_nodes=cycle_nodes)
        for node in project.nodes
    }
    items_by_id = {
        node.id: _roadmap_item(
            node,
            stage=stage_by_id.get(node.id, 0),
            status=classifications[node.id],
            task=ready_by_node.get(node.id),
            blocks=downstream_counts.get(node.id, 0),
            project=project,
            classifications=classifications,
            cycle_nodes=cycle_nodes,
        )
        for node in project.nodes
    }
    stages = [
        RoadmapStage(
            index=stage_index,
            items=[items_by_id[node_id] for node_id in level if node_id in items_by_id],
        )
        for stage_index, level in enumerate(levels, start=1)
    ]
    summary = _summary(items_by_id.values(), stage_count=len(stages))
    return RoadmapOverview(
        schema_version=ROADMAP_SCHEMA_VERSION,
        project=project.name,
        summary=summary,
        metrics=build_status_metrics(project, has_cycles=bool(cycles)),
        suggested_next_task=ready_tasks[0].id if ready_tasks else None,
        suggested_path=_suggested_path(project, ready_tasks, items_by_id),
        cycles=cycles,
        stages=stages,
    )


def render_roadmap(roadmap: RoadmapOverview) -> str:
    """Render roadmap data as compact Markdown suitable for terminal or files."""

    summary = roadmap.summary
    lines = [
        f"# {roadmap.project} roadmap",
        "",
        (
            "Summary: "
            f"{summary.complete_count} complete, "
            f"{summary.ready_count} ready, "
            f"{summary.blocked_count} blocked, "
            f"{summary.problem_count} problem, "
            f"{summary.stale_count} stale across "
            f"{summary.stage_count} stage(s)."
        ),
        f"Suggested next task: `{roadmap.suggested_next_task}`"
        if roadmap.suggested_next_task
        else "Suggested next task: none",
        "Suggested path: "
        + (" -> ".join(f"`{node_id}`" for node_id in roadmap.suggested_path) or "none"),
        "",
    ]
    if roadmap.cycles:
        lines.extend(["## Cycles", ""])
        for cycle in roadmap.cycles:
            lines.append("- " + " -> ".join(f"`{node_id}`" for node_id in cycle))
        lines.append("")

    for stage in roadmap.stages:
        lines.extend([f"## Stage {stage.index}", ""])
        if not stage.items:
            lines.extend(["_(no nodes)_", ""])
            continue
        for item in stage.items:
            details = [
                f"status `{item.status}`",
                f"formal `{item.formal_status}`",
                f"blocks `{item.blocks}`",
            ]
            if item.task_id:
                task_detail = f"task `{item.task_id}`"
                if item.priority:
                    task_detail += f", priority `{item.priority}`"
                details.append(task_detail)
            if item.target_fact:
                details.append(f"fact `{item.target_fact}`")
            if item.blocked_by:
                blockers = ", ".join(
                    f"`{blocker.id}` ({blocker.status})" for blocker in item.blocked_by
                )
                details.append(f"blocked by {blockers}")
            lines.append(f"- `{item.node_id}` - {item.title} ({'; '.join(details)})")
        lines.append("")
    return "\n".join(lines)


def write_roadmap(
    roadmap: RoadmapOverview,
    build_dir: Path,
    *,
    json_name: str = "roadmap.json",
    md_name: str = "roadmap.md",
) -> dict[str, Path]:
    """Write roadmap JSON and Markdown artifacts."""

    build_dir.mkdir(parents=True, exist_ok=True)
    json_path = build_dir / json_name
    md_path = build_dir / md_name
    json_path.write_text(json.dumps(roadmap.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_roadmap(roadmap), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def _classify_node(
    node: BlueprintNode,
    *,
    ready_by_node: dict[str, AgentTask],
    cycle_nodes: set[str],
) -> str:
    if node.id in cycle_nodes:
        return "problem"
    if node.status.formal.value in PROBLEM_FORMAL_STATUSES:
        return "problem"
    if node.status.formal == FormalStatus.STALE:
        return "stale"
    if node.status.formal in COMPLETE_FORMAL_STATUSES:
        return "complete"
    if node.id in ready_by_node:
        return "ready"
    return "blocked"


def _roadmap_item(
    node: BlueprintNode,
    *,
    stage: int,
    status: str,
    task: AgentTask | None,
    blocks: int,
    project: BlueprintProject,
    classifications: dict[str, str],
    cycle_nodes: set[str],
) -> RoadmapItem:
    metadata = task.metadata if task is not None else None
    return RoadmapItem(
        node_id=node.id,
        title=node.title,
        kind=node.kind.value,
        stage=stage,
        status=status,
        formal_status=node.status.formal.value,
        agent_status=node.status.agent.value,
        target_fact=node.isabelle.fact,
        blocked_by=_blockers_for(node, project, classifications, cycle_nodes),
        blocks=blocks,
        task_id=task.id if task is not None else None,
        priority=metadata.priority if metadata is not None else None,
        difficulty=metadata.difficulty if metadata is not None else None,
        suggested_order=metadata.suggested_order if metadata is not None else None,
    )


def _blockers_for(
    node: BlueprintNode,
    project: BlueprintProject,
    classifications: dict[str, str],
    cycle_nodes: set[str],
) -> list[RoadmapBlocker]:
    by_id = project.by_id()
    blockers: list[RoadmapBlocker] = []
    for dep_id in node.uses:
        dep = by_id.get(dep_id)
        if dep is None:
            blockers.append(
                RoadmapBlocker(
                    id=dep_id,
                    title=None,
                    status="missing",
                    formal_status=None,
                    reason="missing_dependency",
                )
            )
            continue
        if dep.id in cycle_nodes:
            blockers.append(_blocker(dep, status="problem", reason="cycle_dependency"))
        elif dep.status.formal.value in PROBLEM_FORMAL_STATUSES:
            blockers.append(_blocker(dep, status="problem", reason="problem_dependency"))
        elif dep.status.formal == FormalStatus.STALE:
            blockers.append(_blocker(dep, status="stale", reason="stale_dependency"))
        elif dep.status.formal not in COMPLETE_FORMAL_STATUSES:
            blockers.append(
                _blocker(
                    dep,
                    status=classifications.get(dep.id, "blocked"),
                    reason="incomplete_dependency",
                )
            )
    return blockers


def _blocker(dep: BlueprintNode, *, status: str, reason: str) -> RoadmapBlocker:
    return RoadmapBlocker(
        id=dep.id,
        title=dep.title,
        status=status,
        formal_status=dep.status.formal.value,
        reason=reason,
    )


def _downstream_incomplete_counts(project: BlueprintProject) -> dict[str, int]:
    graph = build_graph(project)
    by_id = project.by_id()
    memo: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def incomplete_descendants(node_id: str) -> set[str]:
        if node_id in memo:
            return memo[node_id]
        if node_id in visiting:
            return set()
        visiting.add(node_id)
        descendants: set[str] = set()
        for child_id in graph.reverse_edges.get(node_id, []):
            child = by_id.get(child_id)
            if child and child.status.formal not in COMPLETE_FORMAL_STATUSES:
                descendants.add(child_id)
            descendants.update(incomplete_descendants(child_id))
        visiting.discard(node_id)
        memo[node_id] = descendants
        return descendants

    return {node.id: len(incomplete_descendants(node.id)) for node in project.nodes}


def _summary(items: Iterable[RoadmapItem], *, stage_count: int) -> RoadmapSummary:
    items = list(items)
    counts = Counter(item.status for item in items)
    return RoadmapSummary(
        node_count=len(items),
        complete_count=counts.get("complete", 0),
        ready_count=counts.get("ready", 0),
        blocked_count=counts.get("blocked", 0),
        problem_count=counts.get("problem", 0),
        stale_count=counts.get("stale", 0),
        stage_count=stage_count,
    )


def _suggested_path(
    project: BlueprintProject,
    ready_tasks: Sequence[AgentTask],
    items_by_id: dict[str, RoadmapItem],
) -> list[str]:
    if not items_by_id:
        return []

    start_ids: list[str]
    if ready_tasks:
        start_ids = [ready_tasks[0].node_id]
    else:
        start_ids = [
            item.node_id
            for item in sorted(items_by_id.values(), key=lambda item: (item.stage, item.node_id))
            if item.status != "complete"
        ]
    if not start_ids:
        return []

    graph = build_graph(project)
    paths = [
        _downstream_path(start_id, graph.reverse_edges, items_by_id, visiting={start_id})
        for start_id in start_ids
        if start_id in items_by_id
    ]
    return _select_path(paths, items_by_id) if paths else []


def _downstream_path(
    node_id: str,
    reverse_edges: dict[str, list[str]],
    items_by_id: dict[str, RoadmapItem],
    *,
    visiting: set[str],
) -> list[str]:
    candidate_paths: list[list[str]] = []
    for child_id in sorted(reverse_edges.get(node_id, [])):
        child = items_by_id.get(child_id)
        if child is None or child.status == "complete" or child_id in visiting:
            continue
        candidate_paths.append(
            _downstream_path(
                child_id,
                reverse_edges,
                items_by_id,
                visiting=visiting | {child_id},
            )
        )
    if not candidate_paths:
        return [node_id]
    return [node_id] + _select_path(candidate_paths, items_by_id)


def _select_path(paths: Sequence[list[str]], items_by_id: dict[str, RoadmapItem]) -> list[str]:
    def sort_key(path: list[str]) -> tuple[int, int, list[str]]:
        blocks = sum(items_by_id[node_id].blocks for node_id in path if node_id in items_by_id)
        return (-len(path), -blocks, path)

    return sorted(paths, key=sort_key)[0]
