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

from isabelle_blueprint.agents.memory import AgentMemory, NodeMemorySummary, summaries_by_node
from isabelle_blueprint.agents.runner import prompt_filename
from isabelle_blueprint.isabelle.suggestions import FactSuggestion, suggestions_by_node
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
class AgentTaskMetadata:
    priority: str
    difficulty: str
    dependency_depth: int
    blocking_count: int
    suggested_order: int
    suggested_facts: list[str] = field(default_factory=list)


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
    metadata: AgentTaskMetadata | None = None
    memory: NodeMemorySummary | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dependencies"] = [asdict(dep) for dep in self.dependencies]
        return d


def _is_ready(
    node: BlueprintNode,
    project: BlueprintProject,
    by_id: dict[str, BlueprintNode] | None = None,
) -> bool:
    if node.status.formal in {FormalStatus.FOUND, FormalStatus.PROVED}:
        return False
    # A fresh ``by_id()`` copy is an O(n) rebuild-or-copy on every call; accept
    # a shared mapping (or fall back to the project's cached, zero-copy
    # internal index) so callers iterating over every node don't pay it once
    # per node (an O(n^2) trap on the hot generate_tasks path, which runs on
    # status/report/portfolio/agent-context).
    if by_id is None:
        by_id = project._by_id_index()
    for dep_id in node.uses:
        dep = by_id.get(dep_id)
        if dep is None:
            return False
        if dep.status.formal not in {FormalStatus.FOUND, FormalStatus.PROVED}:
            return False
    return True


def generate_tasks(
    project: BlueprintProject,
    *,
    fact_suggestions: list[FactSuggestion] | None = None,
    memory: AgentMemory | None = None,
) -> list[AgentTask]:
    tasks: list[AgentTask] = []
    by_id = project._by_id_index()
    depths = _dependency_depths(project)
    blocking_counts = _blocking_counts(project)
    suggestion_index = suggestions_by_node(fact_suggestions or [])
    memory_summaries = summaries_by_node(memory, project.nodes) if memory is not None else {}
    for node in project.nodes:
        if not _is_ready(node, project, by_id):
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
        suggested_facts = (
            suggestion_index[node.id].suggestions if node.id in suggestion_index else []
        )
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
                metadata=AgentTaskMetadata(
                    priority=_priority_for(node, blocking_counts.get(node.id, 0)),
                    difficulty=_difficulty_for(node),
                    dependency_depth=depths.get(node.id, 0),
                    blocking_count=blocking_counts.get(node.id, 0),
                    suggested_order=0,
                    suggested_facts=suggested_facts,
                ),
                memory=memory_summaries.get(node.id),
            )
        )
    tasks.sort(key=_task_sort_key)
    for index, task in enumerate(tasks, start=1):
        if task.metadata is not None:
            task.metadata.suggested_order = index
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
    fact_suggestions: list[FactSuggestion] | None = None,
    memory: AgentMemory | None = None,
    tasks: list[AgentTask] | None = None,
    prompt_tasks: list[AgentTask] | None = None,
    payload_metadata: dict[str, object] | None = None,
    empty_message: str | None = None,
    github_issues: bool = False,
    github_issues_name: str = "github-issues.json",
    github_issue_labels: list[str] | None = None,
    github_issue_assignees: list[str] | None = None,
) -> dict[str, Path]:
    """Write ``tasks.json``, ``tasks.md`` and ``prompts/<task-id>.md`` files."""
    build_dir.mkdir(parents=True, exist_ok=True)
    generated_tasks: list[AgentTask] | None = None
    if tasks is None or prompt_tasks is None:
        generated_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    if tasks is None:
        tasks = generated_tasks or []
    if prompt_tasks is None:
        prompt_tasks = generated_tasks or []

    json_path = build_dir / json_name
    md_path = build_dir / md_name
    prompts_dir = build_dir / prompt_dir_name
    prompts_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "tasks": [t.to_dict() for t in tasks],
        "suggested_next_task": tasks[0].id if tasks else None,
    }
    if payload_metadata:
        payload.update(payload_metadata)
    json_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(_render_tasks_index(tasks, empty_message=empty_message), encoding="utf-8")

    _remove_stale_task_prompts(prompts_dir, prompt_tasks)
    for task in prompt_tasks:
        prompt_name = prompt_filename(task.id)
        (prompts_dir / prompt_name).write_text(render_task_prompt(task), encoding="utf-8")

    written = {"json": json_path, "md": md_path, "prompts": prompts_dir}
    if github_issues:
        issues_path = build_dir / github_issues_name
        write_github_issue_drafts(
            tasks,
            issues_path,
            extra_labels=github_issue_labels,
            assignees=github_issue_assignees,
        )
        written["github_issues"] = issues_path
    return written


def _remove_stale_task_prompts(prompts_dir: Path, tasks: list[AgentTask]) -> None:
    current_prompt_names = {prompt_filename(task.id) for task in tasks}
    for prompt_path in prompts_dir.glob("task-*.md"):
        if prompt_path.name not in current_prompt_names:
            prompt_path.unlink()


def _render_tasks_index(tasks: list[AgentTask], *, empty_message: str | None = None) -> str:
    if not tasks:
        message = empty_message or "No ready tasks - every node is either complete or blocked."
        return f"# Agent tasks\n\n{message}\n"
    lines = ["# Agent tasks", ""]
    lines.append(f"Suggested next task: `{tasks[0].id}`.")
    lines.append("")
    for task in tasks:
        target = task.target_fact or "(no Isabelle ref)"
        metadata = task.metadata
        detail = ""
        if metadata is not None:
            detail = (
                f" — priority `{metadata.priority}`, difficulty `{metadata.difficulty}`, "
                f"depth `{metadata.dependency_depth}`, blocks `{metadata.blocking_count}`"
            )
        lines.append(f"- **{task.title}** (`{task.node_id}`) -> `{target}`{detail}")
    lines.append("")
    lines.append(f"Total: {len(tasks)} ready task(s).")
    return "\n".join(lines) + "\n"


def render_tasks_summary(tasks: list[AgentTask]) -> str:
    """Render ``tasks`` as a compact aligned table (trailing newline).

    Columns: task id, node id, kind, priority, difficulty, and the number of
    dependencies the task is blocked by. Intended for a quick at-a-glance view
    of the ready queue without writing any files.
    """
    if not tasks:
        return "No ready tasks.\n"
    headers = ("TASK", "NODE", "KIND", "PRIORITY", "DIFFICULTY", "BLOCKED_BY")
    rows: list[tuple[str, str, str, str, str, str]] = []
    for task in tasks:
        priority = task.metadata.priority if task.metadata is not None else "-"
        difficulty = task.metadata.difficulty if task.metadata is not None else "-"
        rows.append(
            (
                task.id,
                task.node_id,
                task.kind,
                priority,
                difficulty,
                str(len(task.dependencies)),
            )
        )
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt(cols: tuple[str, str, str, str, str, str]) -> str:
        return "  ".join(
            cols[i].ljust(widths[i]) if i < len(cols) - 1 else cols[i] for i in range(len(cols))
        ).rstrip()

    lines = [_fmt(headers)]
    lines.extend(_fmt(row) for row in rows)
    return "\n".join(lines) + "\n"


def render_task_prompt(task: AgentTask) -> str:
    """Render the Markdown prompt for a ready proof task."""

    parts: list[str] = []
    parts.append(f"# Task: {task.title}")
    parts.append("")
    parts.append(f"- **Blueprint id**: `{task.node_id}`")
    parts.append(f"- **Kind**: `{task.kind}`")
    if task.target_fact:
        parts.append(f"- **Target Isabelle fact**: `{task.target_fact}`")
    if task.target_theory:
        parts.append(f"- **Theory**: `{task.target_theory}`")
    if task.metadata is not None:
        parts.append(f"- **Priority**: `{task.metadata.priority}`")
        parts.append(f"- **Difficulty**: `{task.metadata.difficulty}`")
        parts.append(f"- **Dependency depth**: `{task.metadata.dependency_depth}`")
        parts.append(f"- **Blocks**: `{task.metadata.blocking_count}` downstream node(s)")
        if task.metadata.suggested_facts:
            parts.append(
                "- **Suggested nearby facts**: "
                + ", ".join(f"`{fact}`" for fact in task.metadata.suggested_facts)
            )
    if task.memory is not None:
        parts.append(f"- **Previous attempts**: `{task.memory.attempt_count}`")
        if task.memory.last_outcome:
            stale = " (from an older task input)" if task.memory.stale else ""
            parts.append(f"- **Last outcome**: `{task.memory.last_outcome}`{stale}")
        if task.memory.last_summary:
            parts.append(f"- **Last note**: {task.memory.last_summary}")
        if task.memory.next_step:
            parts.append(f"- **Suggested next step**: {task.memory.next_step}")
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


def _sledgehammer_lemma_name(task: AgentTask) -> str:
    if task.target_fact:
        return task.target_fact.rsplit(".", 1)[-1]
    return task.node_id


def render_sledgehammer_appendix(task: AgentTask) -> str:
    """Render a Sledgehammer-first guidance block to append to a task prompt.

    The block walks the agent through trying Isabelle's automation before a
    manual proof, seeded with the task's own target fact name and the Isabelle
    facts of its dependencies so the hints are concrete.
    """
    name = _sledgehammer_lemma_name(task)
    dep_facts = [dep.fact for dep in task.dependencies if dep.fact]
    parts: list[str] = []
    parts.append("## Sledgehammer-first strategy")
    parts.append("")
    parts.append("Before writing a manual proof, let Isabelle's automation try to close the goal:")
    parts.append("")
    parts.append("1. State the lemma and replace the proof body with `sledgehammer`:")
    parts.append("")
    parts.append("   ```isabelle")
    parts.append(f"   lemma {name}:")
    parts.append('     "<your formal statement>"')
    parts.append("     sledgehammer")
    parts.append("   ```")
    parts.append("")
    parts.append(
        "2. If it suggests a one-liner, prefer a structured `by (simp add: ...)`, "
        "`by auto`, or `by fastforce` over a raw `by (metis ...)` when one works."
    )
    if dep_facts:
        hint = " ".join(dep_facts)
        parts.append(
            f"3. Seed the search with this node's dependencies: `sledgehammer (add: {hint})`."
        )
    else:
        parts.append(
            "3. Seed the search with nearby simp lemmas: `sledgehammer (add: <relevant facts>)`."
        )
    parts.append(
        "4. On a timeout, widen the provers and budget: "
        "`sledgehammer [provers = cvc4 z3 e spass, timeout = 60]`."
    )
    parts.append("5. If automation still fails, fall back to `try0`, then an Isar skeleton:")
    parts.append("")
    parts.append("   ```isabelle")
    parts.append(f"   lemma {name}:")
    parts.append('     "<your formal statement>"')
    parts.append("   proof -")
    parts.append("     show ?thesis sorry")
    parts.append("   qed")
    parts.append("   ```")
    parts.append("")
    parts.append(
        "Replace every `sorry`/`sledgehammer` placeholder before committing - the "
        "acceptance criteria forbid `sorry`, `oops`, and oracles."
    )
    parts.append("")
    return "\n".join(parts)


def write_github_issue_drafts(
    tasks: list[AgentTask],
    path: Path,
    *,
    extra_labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> Path:
    """Write GitHub issue drafts for ready tasks without touching the network."""

    issues = github_issue_drafts(tasks, extra_labels=extra_labels, assignees=assignees)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"issues": issues}, indent=2), encoding="utf-8")
    return path


def github_issue_drafts(
    tasks: list[AgentTask],
    *,
    extra_labels: list[str] | None = None,
    assignees: list[str] | None = None,
) -> list[dict[str, object]]:
    """Return GitHub issue draft dictionaries for ``tasks``."""

    issues: list[dict[str, object]] = []
    clean_extra_labels = [label for label in dict.fromkeys(extra_labels or []) if label]
    clean_assignees = [assignee for assignee in dict.fromkeys(assignees or []) if assignee]
    for task in tasks:
        body = render_task_prompt(task)
        if len(body) > 60000:
            body = body[:59900] + "\n\n_(Prompt truncated to stay under GitHub issue limits.)_\n"
        labels = [
            "isabelle-blueprint",
            "agent-task",
            f"priority:{task.metadata.priority if task.metadata else 'medium'}",
            f"difficulty:{task.metadata.difficulty if task.metadata else 'medium'}",
        ]
        issue: dict[str, object] = {
            "title": f"Formalize {task.title}",
            "body": body,
            "labels": list(dict.fromkeys(labels + clean_extra_labels)),
            "node_id": task.node_id,
            "task_id": task.id,
        }
        if clean_assignees:
            issue["assignees"] = clean_assignees
        issues.append(issue)
    return issues


def _dependency_depths(project: BlueprintProject) -> dict[str, int]:
    by_id = project._by_id_index()
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def push(
        node_id: str,
        ids_stack: list[str],
        deps_stack: list[list[str]],
        idx_stack: list[int],
        max_stack: list[int],
    ) -> None:
        visiting.add(node_id)
        node = by_id.get(node_id)
        deps = [dep_id for dep_id in node.uses if dep_id in by_id] if node is not None else []
        ids_stack.append(node_id)
        deps_stack.append(deps)
        idx_stack.append(0)
        max_stack.append(-1)

    def ensure(root: str) -> None:
        if root in memo:
            return
        # Iterative post-order DFS mirroring the original recursive `depth()`,
        # to avoid RecursionError on deep or reversed dependency chains.
        # Parallel stacks emulate the call stack:
        #   ids_stack[i]  - node id at this depth
        #   deps_stack[i] - its filtered (existing) dependency ids
        #   idx_stack[i]  - index of the next dependency still to examine
        #   max_stack[i]  - running max of dependency depths seen so far,
        #                   mirroring `max(..., default=-1)`
        ids_stack: list[str] = []
        deps_stack: list[list[str]] = []
        idx_stack: list[int] = []
        max_stack: list[int] = []
        push(root, ids_stack, deps_stack, idx_stack, max_stack)

        while ids_stack:
            node_id = ids_stack[-1]
            deps = deps_stack[-1]
            idx = idx_stack[-1]
            if idx >= len(deps):
                # equivalent to falling off the end of depth(node_id)
                value = 1 + max_stack[-1] if deps else 0
                visiting.discard(node_id)
                memo[node_id] = value
                ids_stack.pop()
                deps_stack.pop()
                idx_stack.pop()
                max_stack.pop()
                if max_stack:
                    max_stack[-1] = max(max_stack[-1], value)
                continue
            idx_stack[-1] = idx + 1
            dep_id = deps[idx]
            if dep_id in memo:
                max_stack[-1] = max(max_stack[-1], memo[dep_id])
            elif dep_id in visiting:
                # cycle: the recursive call short-circuits to 0, which still
                # feeds into the max(...) accumulator.
                max_stack[-1] = max(max_stack[-1], 0)
            else:
                push(dep_id, ids_stack, deps_stack, idx_stack, max_stack)

    for node in project.nodes:
        ensure(node.id)

    return {node.id: memo[node.id] for node in project.nodes}


def _blocking_counts(project: BlueprintProject) -> dict[str, int]:
    by_id = project._by_id_index()
    reverse: dict[str, list[str]] = {node.id: [] for node in project.nodes}
    for node in project.nodes:
        for dep_id in node.uses:
            if dep_id in reverse:
                reverse[dep_id].append(node.id)

    # Memoised transitive-dependent (reverse-reachable) set per node. Without
    # the memo this is an independent DFS for every node — O(N*(N+E)) on the hot
    # generate_tasks path; sharing sub-results makes it near-linear. Mirrors the
    # descendants() memoisation in report.critical_path, including the visiting
    # guard that breaks dependency cycles. Implemented iteratively (explicit
    # stack) so deep or reversed dependency chains don't raise RecursionError.
    descendants_memo: dict[str, set[str]] = {}
    visiting: set[str] = set()

    def ensure(root: str) -> None:
        if root in descendants_memo:
            return
        # Iterative post-order DFS mirroring the original recursive
        # `descendants()`. Parallel stacks emulate the call stack:
        #   ids_stack[i]   - node id at this depth
        #   idx_stack[i]   - index of the next child still to examine
        #   found_stack[i] - the "found" set being accumulated at this depth
        ids_stack: list[str] = [root]
        idx_stack: list[int] = [0]
        found_stack: list[set[str]] = [set()]
        visiting.add(root)

        while ids_stack:
            node_id = ids_stack[-1]
            children = reverse.get(node_id, [])
            idx = idx_stack[-1]
            if idx >= len(children):
                # equivalent to falling off the end of descendants(node_id)
                visiting.discard(node_id)
                value = found_stack[-1]
                descendants_memo[node_id] = value
                ids_stack.pop()
                idx_stack.pop()
                found_stack.pop()
                if found_stack:
                    found_stack[-1] |= value
                continue
            idx_stack[-1] = idx + 1
            child = children[idx]
            # `found.add(child)` happens unconditionally in the recursive
            # version, regardless of memo/visiting/unvisited status below.
            found_stack[-1].add(child)
            if child in descendants_memo:
                found_stack[-1] |= descendants_memo[child]
            elif child in visiting:
                # cycle: descendants(child) short-circuits to an empty set,
                # a no-op for the union (found.add(child) above already
                # captured the direct edge).
                pass
            else:
                ids_stack.append(child)
                idx_stack.append(0)
                found_stack.append(set())
                visiting.add(child)

    def descendants(node_id: str) -> set[str]:
        ensure(node_id)
        return descendants_memo.get(node_id, set())

    complete_statuses = {FormalStatus.FOUND, FormalStatus.PROVED}
    counts: dict[str, int] = {}
    for node in project.nodes:
        count = 0
        for dependent in descendants(node.id):
            dependent_node = by_id.get(dependent)
            if dependent_node and dependent_node.status.formal not in complete_statuses:
                count += 1
        if count:
            counts[node.id] = count
    return counts


def _priority_for(node: BlueprintNode, blocking_count: int) -> str:
    if blocking_count >= 3 or node.kind.value in {"theorem", "corollary"}:
        return "high"
    if blocking_count >= 1 or node.kind.value in {"lemma", "proposition"}:
        return "medium"
    return "low"


def _difficulty_for(node: BlueprintNode) -> str:
    body_size = len(node.statement) + len(node.informal_proof)
    if len(node.uses) >= 3 or body_size > 1600:
        return "high"
    if len(node.uses) >= 1 or body_size > 400:
        return "medium"
    return "low"


def _task_sort_key(task: AgentTask) -> tuple[int, int, int, str]:
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    difficulty_rank = {"low": 0, "medium": 1, "high": 2}
    metadata = task.metadata
    if metadata is None:
        return (1, 1, 0, task.node_id)
    return (
        priority_rank.get(metadata.priority, 1),
        difficulty_rank.get(metadata.difficulty, 1),
        metadata.dependency_depth,
        task.node_id,
    )
