"""Roadmap planning for staged proof work."""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.agents.tasks import AgentTask
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.graph.dependency_graph import build_graph, dependency_levels
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.mermaid import mermaid_label, mermaid_node_id
from isabelle_blueprint.report.metrics import (
    PROBLEM_FORMAL_STATUSES,
    StatusMetrics,
    build_status_metrics,
)

ROADMAP_SCHEMA_VERSION = 1
ROADMAP_STATUSES = ("complete", "ready", "blocked", "problem", "stale")
COMPLETE_FORMAL_STATUSES = {FormalStatus.FOUND, FormalStatus.PROVED}


@dataclass(frozen=True)
class RoadmapFilters:
    statuses: tuple[str, ...] = ()
    stages: tuple[int, ...] = ()
    kinds: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.statuses or self.stages or self.kinds)

    def matches(self, item: RoadmapItem) -> bool:
        if self.statuses and item.status not in self.statuses:
            return False
        if self.stages and item.stage not in self.stages:
            return False
        if self.kinds and item.kind not in self.kinds:
            return False
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "status": list(self.statuses),
            "stage": list(self.stages),
            "kind": list(self.kinds),
        }


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
    uses: tuple[str, ...] = ()

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


@dataclass(frozen=True)
class RoadmapDiffEntry:
    node_id: str
    title: str | None
    kind: str | None
    previous_status: str | None
    current_status: str | None
    previous_stage: int | None
    current_stage: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "kind": self.kind,
            "previous_status": self.previous_status,
            "current_status": self.current_status,
            "previous_stage": self.previous_stage,
            "current_stage": self.current_stage,
        }


@dataclass(frozen=True)
class RoadmapDiff:
    previous_project: str | None
    current_project: str
    added: list[RoadmapDiffEntry]
    removed: list[RoadmapDiffEntry]
    newly_complete: list[RoadmapDiffEntry]
    newly_ready: list[RoadmapDiffEntry]
    newly_blocked: list[RoadmapDiffEntry]
    newly_problem: list[RoadmapDiffEntry]
    newly_stale: list[RoadmapDiffEntry]
    status_changed: list[RoadmapDiffEntry]

    @property
    def has_changes(self) -> bool:
        return any(self.category_counts().values())

    def category_counts(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "newly_complete": len(self.newly_complete),
            "newly_ready": len(self.newly_ready),
            "newly_blocked": len(self.newly_blocked),
            "newly_problem": len(self.newly_problem),
            "newly_stale": len(self.newly_stale),
            "status_changed": len(self.status_changed),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "previous_project": self.previous_project,
            "current_project": self.current_project,
            "counts": self.category_counts(),
            "added": [entry.to_dict() for entry in self.added],
            "removed": [entry.to_dict() for entry in self.removed],
            "newly_complete": [entry.to_dict() for entry in self.newly_complete],
            "newly_ready": [entry.to_dict() for entry in self.newly_ready],
            "newly_blocked": [entry.to_dict() for entry in self.newly_blocked],
            "newly_problem": [entry.to_dict() for entry in self.newly_problem],
            "newly_stale": [entry.to_dict() for entry in self.newly_stale],
            "status_changed": [entry.to_dict() for entry in self.status_changed],
        }


def build_roadmap(project: BlueprintProject, ready_tasks: Sequence[AgentTask]) -> RoadmapOverview:
    """Build staged proof-work planning data for ``project``."""

    validation = project.validate()
    cycles = validation.cycles
    cycle_nodes = {node_id for cycle in cycles for node_id in cycle}
    by_id = project.by_id()
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
            by_id=by_id,
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


def roadmap_payload(
    roadmap: RoadmapOverview,
    *,
    filters: RoadmapFilters | None = None,
    diff: RoadmapDiff | None = None,
) -> dict[str, object]:
    """Return roadmap JSON data with optional filtered stages and diff data."""

    filters = filters or RoadmapFilters()
    rendered = filter_roadmap(roadmap, filters) if filters.active else roadmap
    payload = rendered.to_dict()
    if filters.active:
        payload["filters"] = filters.to_dict()
    if diff is not None:
        payload["diff"] = diff.to_dict()
    return payload


def filter_roadmap(roadmap: RoadmapOverview, filters: RoadmapFilters) -> RoadmapOverview:
    """Return a view whose stages contain only matching items.

    Summary, metrics, cycles, and suggestions intentionally continue to describe
    the full roadmap so filters cannot hide CI-gating or planning context.
    """

    if not filters.active:
        return roadmap
    stages = [
        RoadmapStage(
            index=stage.index,
            items=[item for item in stage.items if filters.matches(item)],
        )
        for stage in roadmap.stages
    ]
    stages = [stage for stage in stages if stage.items]
    return RoadmapOverview(
        schema_version=roadmap.schema_version,
        project=roadmap.project,
        summary=roadmap.summary,
        metrics=roadmap.metrics,
        suggested_next_task=roadmap.suggested_next_task,
        suggested_path=roadmap.suggested_path,
        cycles=roadmap.cycles,
        stages=stages,
    )


def render_roadmap(
    roadmap: RoadmapOverview,
    *,
    filters: RoadmapFilters | None = None,
    diff: RoadmapDiff | None = None,
) -> str:
    """Render roadmap data as compact Markdown suitable for terminal or files."""

    filters = filters or RoadmapFilters()
    rendered = filter_roadmap(roadmap, filters) if filters.active else roadmap
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
    if filters.active:
        lines.extend([_render_filter_summary(filters), ""])
    if roadmap.cycles:
        lines.extend(["## Cycles", ""])
        for cycle in roadmap.cycles:
            lines.append("- " + " -> ".join(f"`{node_id}`" for node_id in cycle))
        lines.append("")

    if filters.active and not rendered.stages:
        lines.extend(["## Stages", "", "_(no matching roadmap items)_", ""])

    for stage in rendered.stages:
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
    if diff is not None:
        lines.extend(render_roadmap_diff(diff).splitlines())
        lines.append("")
    return "\n".join(lines)


def render_roadmap_mermaid(
    roadmap: RoadmapOverview,
    *,
    filters: RoadmapFilters | None = None,
) -> str:
    """Render the staged roadmap as a Mermaid ``flowchart``.

    Each dependency stage becomes a ``subgraph`` whose nodes are labelled by id,
    and every ``uses`` relationship (restricted to items visible in the diagram)
    is emitted as an edge -- including dependencies that are already complete, so
    the picture follows the full ``uses`` graph rather than only outstanding
    blockers. Honours the same ``--status``/``--stage``/``--kind`` filters as the
    Markdown rendering so the diagram mirrors what the user asked to see.
    """

    filters = filters or RoadmapFilters()
    rendered = filter_roadmap(roadmap, filters) if filters.active else roadmap
    visible_ids = {item.node_id for stage in rendered.stages for item in stage.items}
    lines = ["flowchart TB"]
    for stage in rendered.stages:
        lines.append(f"  subgraph stage{stage.index}[\"Stage {stage.index}\"]")
        for item in stage.items:
            lines.append(
                f'    {mermaid_node_id(item.node_id)}'
                f'["{mermaid_label(item.node_id, escape_pipe=False)}"]'
            )
        lines.append("  end")
    for stage in rendered.stages:
        for item in stage.items:
            for dep_id in item.uses:
                if dep_id in visible_ids:
                    lines.append(
                        f"  {mermaid_node_id(dep_id)} --> {mermaid_node_id(item.node_id)}"
                    )
    return "\n".join(lines) + "\n"


ROADMAP_CSV_COLUMNS = (
    "stage",
    "node_id",
    "kind",
    "formal_status",
    "agent_status",
    "blocked_by_count",
)


def render_roadmap_csv(
    roadmap: RoadmapOverview,
    *,
    filters: RoadmapFilters | None = None,
) -> str:
    """Render the staged roadmap as CSV, one row per node plus a header.

    Columns: stage index, node id, kind, formal status, agent status, and the
    number of outstanding blockers. Honours the same ``--status``/``--stage``/
    ``--kind`` filters as the other roadmap renderings.
    """

    filters = filters or RoadmapFilters()
    rendered = filter_roadmap(roadmap, filters) if filters.active else roadmap
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ROADMAP_CSV_COLUMNS)
    for stage in rendered.stages:
        for item in stage.items:
            writer.writerow(
                [
                    stage.index,
                    item.node_id,
                    item.kind,
                    item.formal_status,
                    item.agent_status,
                    len(item.blocked_by),
                ]
            )
    return buffer.getvalue()


ROADMAP_MARKDOWN_COLUMNS = (
    "id",
    "kind",
    "formal status",
    "agent status",
    "blocker count",
)


def render_roadmap_markdown(
    roadmap: RoadmapOverview,
    *,
    filters: RoadmapFilters | None = None,
) -> str:
    """Render the staged roadmap as Markdown: one section per stage.

    Each stage becomes a ``## Stage N`` heading followed by a table of that
    stage's nodes (id, kind, formal status, agent status, blocker count).
    Honours the same ``--status``/``--stage``/``--kind`` filters as the other
    roadmap renderings; ``|`` in cells is escaped.
    """

    filters = filters or RoadmapFilters()
    rendered = filter_roadmap(roadmap, filters) if filters.active else roadmap
    lines = [f"# {_md_cell(roadmap.project)} roadmap", ""]
    if not rendered.stages:
        lines.extend(["_(no matching roadmap items)_", ""])
        return "\n".join(lines)
    header = "| " + " | ".join(ROADMAP_MARKDOWN_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in ROADMAP_MARKDOWN_COLUMNS) + " |"
    for stage in rendered.stages:
        lines.extend([f"## Stage {stage.index}", ""])
        if not stage.items:
            lines.extend(["_(no nodes)_", ""])
            continue
        lines.extend([header, separator])
        for item in stage.items:
            cells = [
                _md_cell(item.node_id),
                _md_cell(item.kind),
                _md_cell(item.formal_status),
                _md_cell(item.agent_status),
                str(len(item.blocked_by)),
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def _md_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br/>")
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


def load_roadmap_payload(path: Path) -> dict[str, object]:
    """Load a previous roadmap JSON payload.

    ``path`` may point directly at a JSON file or at a directory containing
    ``roadmap.json``.
    """

    payload_path = path / "roadmap.json" if path.is_dir() else path
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BlueprintError(f"roadmap baseline not found at {payload_path}") from exc
    except json.JSONDecodeError as exc:
        raise BlueprintError(f"roadmap baseline is not valid JSON: {payload_path}") from exc
    if not isinstance(data, dict):
        raise BlueprintError(f"roadmap baseline must be a JSON object: {payload_path}")
    schema_version = data.get("schema_version")
    if schema_version != ROADMAP_SCHEMA_VERSION:
        raise BlueprintError(
            f"unsupported roadmap baseline schema_version {schema_version!r}; "
            f"expected {ROADMAP_SCHEMA_VERSION}"
        )
    if "filters" in data:
        raise BlueprintError(
            "roadmap baseline is filtered; use an unfiltered build/roadmap.json for --since"
        )
    return data


def diff_roadmaps(previous: dict[str, object], current: RoadmapOverview) -> RoadmapDiff:
    """Compare a previous roadmap payload against the current full roadmap."""

    previous_items = _items_by_node(previous)
    current_items = _current_items_by_node(current)
    added: list[RoadmapDiffEntry] = []
    removed: list[RoadmapDiffEntry] = []
    newly_complete: list[RoadmapDiffEntry] = []
    newly_ready: list[RoadmapDiffEntry] = []
    newly_blocked: list[RoadmapDiffEntry] = []
    newly_problem: list[RoadmapDiffEntry] = []
    newly_stale: list[RoadmapDiffEntry] = []
    status_changed: list[RoadmapDiffEntry] = []

    for node_id in sorted(current_items.keys() - previous_items.keys()):
        added.append(_diff_entry(node_id, previous_items.get(node_id), current_items[node_id]))
    for node_id in sorted(previous_items.keys() - current_items.keys()):
        removed.append(_diff_entry(node_id, previous_items[node_id], current_items.get(node_id)))
    for node_id in sorted(previous_items.keys() & current_items.keys()):
        previous_item = previous_items[node_id]
        current_item = current_items[node_id]
        previous_status = _string_value(previous_item.get("status"))
        current_status = current_item.status
        if previous_status == current_status:
            continue
        entry = _diff_entry(node_id, previous_item, current_item)
        if current_status == "complete":
            newly_complete.append(entry)
        elif current_status == "ready":
            newly_ready.append(entry)
        elif current_status == "blocked":
            newly_blocked.append(entry)
        elif current_status == "problem":
            newly_problem.append(entry)
        elif current_status == "stale":
            newly_stale.append(entry)
        else:
            status_changed.append(entry)

    return RoadmapDiff(
        previous_project=_string_value(previous.get("project")),
        current_project=current.project,
        added=added,
        removed=removed,
        newly_complete=newly_complete,
        newly_ready=newly_ready,
        newly_blocked=newly_blocked,
        newly_problem=newly_problem,
        newly_stale=newly_stale,
        status_changed=status_changed,
    )


def render_roadmap_diff(diff: RoadmapDiff) -> str:
    """Render a compact Markdown diff between roadmap snapshots."""

    lines = ["## Changes since previous roadmap", ""]
    if not diff.has_changes:
        return "\n".join(lines + ["No roadmap status changes.", ""])

    groups = [
        ("Added", diff.added),
        ("Removed", diff.removed),
        ("Newly complete", diff.newly_complete),
        ("Newly ready", diff.newly_ready),
        ("Newly blocked", diff.newly_blocked),
        ("Newly problem", diff.newly_problem),
        ("Newly stale", diff.newly_stale),
        ("Status changed", diff.status_changed),
    ]
    for title, entries in groups:
        if not entries:
            continue
        lines.extend([f"### {title}", ""])
        for entry in entries:
            previous = entry.previous_status or "none"
            current = entry.current_status or "none"
            lines.append(f"- `{entry.node_id}`: `{previous}` -> `{current}`")
        lines.append("")
    return "\n".join(lines)


def roadmap_strict_failures(roadmap: RoadmapOverview) -> list[str]:
    """Return strict-mode gate failures for the full roadmap."""

    failures: list[str] = []
    if roadmap.cycles:
        failures.append(f"[cycles] dependency cycles detected: {len(roadmap.cycles)}")
    problem_nodes = [
        item.node_id for item in _iter_items(roadmap) if item.status == "problem"
    ]
    if problem_nodes:
        failures.append("[problem] problem nodes: " + ", ".join(problem_nodes))
    stale_nodes = [item.node_id for item in _iter_items(roadmap) if item.status == "stale"]
    if stale_nodes:
        failures.append("[stale] stale nodes: " + ", ".join(stale_nodes))
    missing_dependencies = [
        f"{item.node_id}->{blocker.id}"
        for item in _iter_items(roadmap)
        for blocker in item.blocked_by
        if blocker.reason == "missing_dependency"
    ]
    if missing_dependencies:
        failures.append("[missing-deps] missing dependencies: " + ", ".join(missing_dependencies))
    return failures


def _render_filter_summary(filters: RoadmapFilters) -> str:
    parts: list[str] = []
    if filters.statuses:
        parts.append("status=" + ",".join(filters.statuses))
    if filters.stages:
        parts.append("stage=" + ",".join(str(stage) for stage in filters.stages))
    if filters.kinds:
        parts.append("kind=" + ",".join(filters.kinds))
    return "Filters: " + ("; ".join(parts) if parts else "none")


def _iter_items(roadmap: RoadmapOverview) -> Iterable[RoadmapItem]:
    for stage in roadmap.stages:
        yield from stage.items


def _items_by_node(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise BlueprintError("roadmap baseline is missing a `stages` array")
    items: dict[str, dict[str, object]] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_items = stage.get("items")
        if not isinstance(stage_items, list):
            continue
        for item in stage_items:
            if not isinstance(item, dict):
                continue
            node_id = _string_value(item.get("node_id"))
            if node_id is not None:
                items[node_id] = item
    return items


def _current_items_by_node(roadmap: RoadmapOverview) -> dict[str, RoadmapItem]:
    return {item.node_id: item for item in _iter_items(roadmap)}


def _diff_entry(
    node_id: str,
    previous: dict[str, object] | None,
    current: RoadmapItem | None,
) -> RoadmapDiffEntry:
    previous_title = _string_value(previous.get("title") if previous else None)
    previous_kind = _string_value(previous.get("kind") if previous else None)
    return RoadmapDiffEntry(
        node_id=node_id,
        title=current.title if current is not None else previous_title,
        kind=current.kind if current is not None else previous_kind,
        previous_status=_string_value(previous.get("status") if previous else None),
        current_status=current.status if current is not None else None,
        previous_stage=_int_value(previous.get("stage") if previous else None),
        current_stage=current.stage if current is not None else None,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None


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
    by_id: dict[str, BlueprintNode],
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
        blocked_by=_blockers_for(node, by_id, classifications, cycle_nodes),
        blocks=blocks,
        task_id=task.id if task is not None else None,
        priority=metadata.priority if metadata is not None else None,
        difficulty=metadata.difficulty if metadata is not None else None,
        suggested_order=metadata.suggested_order if metadata is not None else None,
        uses=tuple(node.uses),
    )


def _blockers_for(
    node: BlueprintNode,
    by_id: dict[str, BlueprintNode],
    classifications: dict[str, str],
    cycle_nodes: set[str],
) -> list[RoadmapBlocker]:
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
