"""Tests for agent-task generation."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from isabelle_blueprint.agents.memory import node_input_hash, record_memory_attempt
from isabelle_blueprint.agents.tasks import (
    _blocking_counts,
    _dependency_depths,
    generate_tasks,
    render_task_prompt,
    write_tasks,
)
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.isabelle.suggestions import suggest_missing_facts
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(
    node_id,
    fact,
    *,
    uses=None,
    formal=FormalStatus.MISSING,
    statement="",
    proof="",
    kind=NodeKind.LEMMA,
):
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        statement=statement,
        informal_proof=proof,
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=fact) if fact else IsabelleRef(),
        status=NodeStatus(formal=formal),
    )


def _chain_reversed(n: int):
    """n0 -> n1 -> ... -> n_{n-1} (earlier nodes depend on later ones)."""
    nodes = [_node(f"n{i}", f"Demo.n{i}", uses=[f"n{i + 1}"]) for i in range(n - 1)]
    nodes.append(_node(f"n{n - 1}", f"Demo.n{n - 1}"))
    return nodes


def _chain_natural(n: int):
    """n0 <- n1 <- ... <- n_{n-1} (later nodes depend on earlier ones).

    This is the realistic blueprint shape (later theorems depend on earlier
    lemmas) and is the pathological direction for _blocking_counts(), which
    walks the reverse-adjacency graph.
    """
    nodes = [_node("n0", "Demo.n0")]
    for i in range(1, n):
        nodes.append(_node(f"n{i}", f"Demo.n{i}", uses=[f"n{i - 1}"]))
    return nodes


def _big_cycle(n: int):
    """A single ring: n_i uses n_{(i+1) % n} for all i."""
    return [_node(f"n{i}", f"Demo.n{i}", uses=[f"n{(i + 1) % n}"]) for i in range(n)]


def test_dependency_depths_self_cycle():
    project = BlueprintProject.from_nodes("p", [_node("a", "Demo.a", uses=["a"])])
    assert _dependency_depths(project) == {"a": 1}


def test_dependency_depths_two_cycle():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", uses=["b"]), _node("b", "Demo.b", uses=["a"])]
    )
    assert _dependency_depths(project) == {"a": 2, "b": 1}


def test_dependency_depths_simple_chain():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", uses=["b"]), _node("b", "Demo.b")]
    )
    assert _dependency_depths(project) == {"a": 1, "b": 0}


def test_blocking_counts_linear_chain():
    """c -> b -> a (c depends on b, b depends on a): descendants(a) = {b, c}."""
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", "Demo.a"),
            _node("b", "Demo.b", uses=["a"]),
            _node("c", "Demo.c", uses=["b"]),
        ],
    )
    counts = _blocking_counts(project)
    assert counts == {"a": 2, "b": 1}


def test_blocking_counts_two_cycle():
    """a uses b, b uses a: descendants(a) = {a, b} (self-reachable via the
    cycle), descendants(b) = {a}."""
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", uses=["b"]), _node("b", "Demo.b", uses=["a"])]
    )
    counts = _blocking_counts(project)
    assert counts == {"a": 2, "b": 1}


def test_dependency_depths_deep_reversed_chain_no_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _chain_reversed(n))
    depths = _dependency_depths(project)
    assert len(depths) == n
    assert depths["n0"] == n - 1
    assert depths[f"n{n - 1}"] == 0


def test_dependency_depths_deep_cycle_no_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _big_cycle(n))
    depths = _dependency_depths(project)
    assert len(depths) == n


def test_blocking_counts_deep_natural_chain_no_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _chain_natural(n))
    counts = _blocking_counts(project)
    assert counts["n0"] == n - 1
    # The last node blocks nothing (nothing depends on it), so it's excluded
    # from the result entirely (blocking_count == 0 entries are dropped).
    assert f"n{n - 1}" not in counts
    assert len(counts) == n - 1


def test_blocking_counts_deep_cycle_no_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _big_cycle(n))
    counts = _blocking_counts(project)
    assert len(counts) == n


def test_generate_tasks_deep_natural_chain_only_first_dependent_ready():
    n = sys.getrecursionlimit() + 2000
    nodes = _chain_natural(n)
    nodes[0].status.formal = FormalStatus.PROVED
    project = BlueprintProject.from_nodes("p", nodes)
    tasks = generate_tasks(project)
    assert {t.node_id for t in tasks} == {"n1"}
    task = tasks[0]
    assert task.metadata is not None
    assert task.metadata.dependency_depth == 1
    assert task.metadata.blocking_count == n - 2


def test_validate_deep_reversed_chain_via_project_does_not_raise():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _chain_reversed(n))
    report = project.validate()
    assert report.ok


def test_generate_tasks_picks_ready_nodes_only():
    """Only nodes whose deps are all FOUND/PROVED should be tasks."""
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", "Demo.a", formal=FormalStatus.FOUND),
            _node("b", "Demo.b", uses=["a"], formal=FormalStatus.MISSING),  # ready
            _node("c", "Demo.c", uses=["b"], formal=FormalStatus.MISSING),  # blocked
        ],
    )
    tasks = generate_tasks(project)
    task_node_ids = {t.node_id for t in tasks}
    assert task_node_ids == {"b"}


def test_generate_tasks_skips_already_proved():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", formal=FormalStatus.PROVED)]
    )
    assert generate_tasks(project) == []


def test_generate_tasks_root_with_no_deps_is_ready():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", formal=FormalStatus.MISSING)]
    )
    tasks = generate_tasks(project)
    assert len(tasks) == 1
    assert tasks[0].target_fact == "Demo.a"
    assert tasks[0].id == "task-a"


def test_generate_tasks_blocked_when_dep_missing_from_project():
    """A node depending on a node that's not in the project is not 'ready'."""
    project = BlueprintProject.from_nodes("p", [_node("a", "Demo.a", uses=["nope"])])
    assert generate_tasks(project) == []


def test_generate_tasks_does_not_rebuild_index_per_node(monkeypatch):
    """generate_tasks must share one node index, not rebuild it per node.

    Rebuilding ``project.by_id()`` inside the per-node readiness check is an
    O(n^2) trap on a hot path (generate_tasks runs on status/report/portfolio
    /agent-context). This guards against the regression by asserting the number
    of ``by_id()`` rebuilds does not grow with the node count.
    """
    calls = {"n": 0}
    real_by_id = BlueprintProject.by_id

    def counting_by_id(self):
        calls["n"] += 1
        return real_by_id(self)

    monkeypatch.setattr(BlueprintProject, "by_id", counting_by_id)

    def chain(length):
        nodes = [_node("n0", "Demo.n0", formal=FormalStatus.PROVED)]
        for i in range(1, length):
            nodes.append(_node(f"n{i}", f"Demo.n{i}", uses=[f"n{i - 1}"]))
        return BlueprintProject.from_nodes("p", nodes)

    calls["n"] = 0
    generate_tasks(chain(5))
    small = calls["n"]

    calls["n"] = 0
    generate_tasks(chain(60))
    large = calls["n"]

    assert small == large, f"by_id() rebuilds scale with node count ({small} vs {large})"


def test_generated_task_contains_acceptance_criteria_and_deps():
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", "Demo.a", formal=FormalStatus.FOUND),
            _node("b", "Demo.b", uses=["a"], statement="if a then b", proof="apply a"),
        ],
    )
    task = generate_tasks(project)[0]
    assert task.informal_statement == "if a then b"
    assert task.informal_proof == "apply a"
    assert task.acceptance_criteria, "tasks should always carry acceptance criteria"
    assert any("sorry" in c for c in task.acceptance_criteria)
    assert len(task.dependencies) == 1
    assert task.dependencies[0].id == "a"
    assert task.dependencies[0].fact == "Demo.a"
    assert task.metadata is not None
    assert task.metadata.priority in {"low", "medium", "high"}
    assert task.metadata.dependency_depth == 1


def test_write_tasks_produces_json_md_and_prompts(tmp_path: Path):
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", "Demo.a", formal=FormalStatus.FOUND),
            _node("b", "Demo.b", uses=["a"], statement="stmt"),
        ],
    )
    paths = write_tasks(project, tmp_path)
    assert paths["json"].exists() and paths["md"].exists()
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["node_id"] == "b"
    assert data["suggested_next_task"] == "task-b"
    assert data["tasks"][0]["metadata"]["difficulty"] == "medium"
    # Prompt file is written for each task.
    prompt_file = paths["prompts"] / "task-b.md"
    assert prompt_file.exists()
    prompt_text = prompt_file.read_text(encoding="utf-8")
    assert "Demo.b" in prompt_text
    assert "Acceptance criteria" in prompt_text


def test_write_tasks_removes_prompts_for_tasks_that_are_no_longer_ready(tmp_path: Path):
    project = BlueprintProject.from_nodes("p", [_node("a", "Demo.a")])
    stale_prompt = tmp_path / "prompts" / "task-old.md"
    stale_prompt.parent.mkdir(parents=True)
    stale_prompt.write_text("old", encoding="utf-8")

    write_tasks(project, tmp_path)

    assert not stale_prompt.exists()
    assert (tmp_path / "prompts" / "task-a.md").exists()


def test_write_tasks_sanitizes_unsafe_node_ids_into_prompts_dir(tmp_path: Path):
    # An author-controlled node id with path separators / Windows-illegal chars
    # must not escape the prompts directory or fail to write. The clean sibling
    # keeps its verbatim ``task-<id>.md`` name.
    project = BlueprintProject.from_nodes(
        "p",
        [_node("a/b:c", "Demo.abc"), _node("plain", "Demo.plain")],
    )

    paths = write_tasks(project, tmp_path)
    prompts_dir = paths["prompts"]

    written = sorted(p.name for p in prompts_dir.glob("*.md"))
    # Every prompt file lives directly inside prompts_dir (no traversal).
    for p in prompts_dir.glob("*.md"):
        assert p.parent == prompts_dir
        assert ":" not in p.name and "/" not in p.name and "\\" not in p.name
    # The safe id is preserved verbatim; the unsafe id is slugified + hashed.
    assert "task-plain.md" in written
    assert any(name.startswith("task-a-b-c-") for name in written)


def test_write_tasks_unsafe_ids_are_not_treated_as_stale_on_rewrite(tmp_path: Path):
    # Regression: the stale-prompt sweep must use the same filename mapping as
    # the writer, or sanitized prompts would be deleted on every rewrite.
    project = BlueprintProject.from_nodes("p", [_node("a/b:c", "Demo.abc")])

    write_tasks(project, tmp_path)
    first = sorted(p.name for p in (tmp_path / "prompts").glob("*.md"))
    write_tasks(project, tmp_path)
    second = sorted(p.name for p in (tmp_path / "prompts").glob("*.md"))

    assert first == second
    assert len(second) == 1


def test_write_tasks_no_ready_tasks_still_writes_index(tmp_path: Path):
    project = BlueprintProject.from_nodes(
        "p", [_node("a", "Demo.a", formal=FormalStatus.PROVED)]
    )
    paths = write_tasks(project, tmp_path)
    md_text = paths["md"].read_text(encoding="utf-8")
    assert "No ready tasks" in md_text
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["tasks"] == []
    assert data["suggested_next_task"] is None


def test_cli_tasks_filters_task_artifacts_but_keeps_full_prompt_set(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["tasks", str(tmp_path), "--kind", "lemma"])

    assert rc == 0
    assert capsys.readouterr().err == ""
    data = json.loads((tmp_path / "build" / "tasks.json").read_text(encoding="utf-8"))
    assert [task["id"] for task in data["tasks"]] == ["task-helper"]
    assert data["suggested_next_task"] == "task-helper"
    assert data["filters"]["kind"] == ["lemma"]
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 1
    md_text = (tmp_path / "build" / "tasks.md").read_text(encoding="utf-8")
    assert "HELPER" in md_text
    assert "MAIN" not in md_text
    assert (tmp_path / "build" / "prompts" / "task-helper.md").exists()
    assert (tmp_path / "build" / "prompts" / "task-main.md").exists()


def test_cli_tasks_summary_prints_table_and_writes_no_files(tmp_path: Path, capsys):
    """--summary prints a compact ready-task table and writes nothing."""
    src = Path("examples/agent-workflow").resolve()
    example = tmp_path / "agent-workflow"
    shutil.copytree(src, example)
    # A leftover build/ from a prior local run must not mask the assertion below.
    shutil.rmtree(example / "build", ignore_errors=True)

    rc = cli_main(["tasks", str(example), "--summary"])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    # Header row with the documented columns.
    assert lines[0].split() == [
        "TASK",
        "NODE",
        "KIND",
        "PRIORITY",
        "DIFFICULTY",
        "BLOCKED_BY",
    ]
    # At least one ready task row appears.
    assert any(line.startswith("task-") for line in lines[1:])
    # No artifacts are written under build/ for the example project.
    assert not (example / "build").exists()


def test_cli_tasks_summary_composes_with_kind_filter(tmp_path: Path, capsys):
    """--summary respects selection filters and never writes files."""
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["tasks", str(tmp_path), "--summary", "--kind", "lemma"])

    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "task-helper" in out
    assert "task-main" not in out
    assert not (tmp_path / "build").exists()


def test_cli_tasks_summary_rejects_side_effect_flags(tmp_path: Path, capsys):
    """--summary errors when combined with write/side-effect flags."""
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["tasks", str(tmp_path), "--summary", "--tracker-export", "jira"])

    assert rc != 0
    captured = capsys.readouterr()
    assert "--summary" in captured.err
    assert "--tracker-export" in captured.err
    assert not (tmp_path / "build").exists()


def test_cli_tasks_filter_no_match_writes_truthful_empty_index(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["tasks", str(tmp_path), "--difficulty", "low"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "No ready tasks match the requested filters" in captured.err
    data = json.loads((tmp_path / "build" / "tasks.json").read_text(encoding="utf-8"))
    assert data["tasks"] == []
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 0
    md_text = (tmp_path / "build" / "tasks.md").read_text(encoding="utf-8")
    assert "No ready tasks match the requested filters" in md_text
    assert "complete or blocked" not in md_text
    assert (tmp_path / "build" / "prompts" / "task-helper.md").exists()
    assert (tmp_path / "build" / "prompts" / "task-main.md").exists()


def test_write_tasks_can_emit_github_issue_drafts(tmp_path: Path):
    project = BlueprintProject.from_nodes("p", [_node("a", "Demo.a", statement="stmt")])

    paths = write_tasks(
        project,
        tmp_path,
        github_issues=True,
        github_issue_labels=["proof-review"],
        github_issue_assignees=["alice"],
    )

    issue_path = paths["github_issues"]
    data = json.loads(issue_path.read_text(encoding="utf-8"))
    assert data["issues"][0]["title"] == "Formalize A"
    assert "agent-task" in data["issues"][0]["labels"]
    assert "difficulty:low" in data["issues"][0]["labels"]
    assert "proof-review" in data["issues"][0]["labels"]
    assert data["issues"][0]["assignees"] == ["alice"]


def test_cli_tasks_filters_github_issue_drafts(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["tasks", str(tmp_path), "--github-issues", "--kind", "lemma"])

    assert rc == 0
    assert capsys.readouterr().err == ""
    data = json.loads((tmp_path / "build" / "github-issues.json").read_text(encoding="utf-8"))
    assert [issue["task_id"] for issue in data["issues"]] == ["task-helper"]


def test_cli_next_prints_suggested_prompt(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    expected = render_task_prompt(
        generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0]
    )

    rc = cli_main(["next", str(tmp_path)])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == expected


def test_cli_next_json_includes_task_and_prompt(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    expected = render_task_prompt(
        generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0]
    )

    rc = cli_main(["next", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-main"
    assert data["prompt"] == expected
    assert data["prompt_path"] is None
    assert data["message"] == "Selected task-main."


def test_cli_next_output_writes_selected_prompt(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    expected = render_task_prompt(
        generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0]
    )
    output = tmp_path / "handoff" / "next.md"

    rc = cli_main(["next", str(tmp_path), "--output", str(output)])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == expected
    assert captured.err == f"next prompt -> {output.resolve()}\n"
    assert output.read_text(encoding="utf-8") == expected


def test_cli_next_output_json_includes_prompt_path(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    output = tmp_path / "handoff" / "next.md"

    rc = cli_main(["next", str(tmp_path), "--output", str(output), "--json"])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["prompt_path"] == str(output.resolve())
    assert output.read_text(encoding="utf-8") == data["prompt"]


def test_cli_next_output_is_not_written_when_no_task_exists(tmp_path: Path, capsys):
    project = BlueprintProject.from_nodes(
        "done", [_node("a", "Demo.a", formal=FormalStatus.PROVED)]
    )
    _write_next_project(tmp_path, project)
    output = tmp_path / "handoff" / "next.md"

    rc = cli_main(["next", str(tmp_path), "--output", str(output), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None
    assert data["prompt"] is None
    assert data["prompt_path"] is None
    assert not output.exists()


def test_cli_next_output_is_not_written_when_selector_is_rejected(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())
    output = tmp_path / "handoff" / "next.md"

    rc = cli_main(["next", str(tmp_path), "--node", "later", "--output", str(output)])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "node 'later' is not currently ready" in captured.err
    assert not output.exists()


def test_cli_attempt_writes_default_prompt_and_json(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["attempt", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-main"
    assert data["check"] is None
    prompt_path = Path(data["prompt_path"])
    assert prompt_path.name == "task-main.md"
    assert prompt_path.exists()
    assert "Task: MAIN" in prompt_path.read_text(encoding="utf-8")


def test_cli_attempt_records_memory_when_requested(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(
        [
            "attempt",
            str(tmp_path),
            "--node",
            "main",
            "--record-outcome",
            "failed",
            "--summary",
            "simp looped",
            "--json",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["memory"]["outcome"] == "failed"
    memory = json.loads(
        (tmp_path / ".isabelle-blueprint" / "agent-memory.json").read_text(
            encoding="utf-8"
        )
    )
    assert memory["nodes"]["main"]["attempts"][0]["summary"] == "simp looped"


def test_cli_attempt_rejects_blank_memory_summary(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(
        [
            "attempt",
            str(tmp_path),
            "--node",
            "main",
            "--record-outcome",
            "failed",
            "--summary",
            "   ",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--summary is required" in captured.err
    assert not (tmp_path / ".isabelle-blueprint" / "agent-memory.json").exists()


def test_cli_next_can_select_by_node_id_or_task_id(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--node", "helper"])
    helper_prompt = capsys.readouterr().out
    rc_task_id = cli_main(["next", str(tmp_path), "--node", "task-helper"])
    helper_task_prompt = capsys.readouterr().out

    assert rc == 0
    assert rc_task_id == 0
    assert helper_prompt == helper_task_prompt
    assert "# Task: HELPER" in helper_prompt


def test_cli_next_filters_ready_tasks_by_kind_priority_and_difficulty(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc_kind = cli_main(["next", str(tmp_path), "--kind", "lemma", "--json"])
    kind_payload = json.loads(capsys.readouterr().out)
    rc_priority = cli_main(["next", str(tmp_path), "--priority", "high", "--json"])
    priority_payload = json.loads(capsys.readouterr().out)
    rc_difficulty = cli_main(["next", str(tmp_path), "--difficulty", "medium", "--json"])
    difficulty_payload = json.loads(capsys.readouterr().out)

    assert rc_kind == 0
    assert kind_payload["task"]["id"] == "task-helper"
    assert kind_payload["filters"]["kind"] == ["lemma"]
    assert kind_payload["ready_task_count"] == 2
    assert kind_payload["filtered_ready_task_count"] == 1
    assert rc_priority == 0
    assert priority_payload["task"]["id"] == "task-main"
    assert priority_payload["filters"]["priority"] == ["high"]
    assert rc_difficulty == 0
    assert difficulty_payload["task"]["id"] == "task-main"
    assert difficulty_payload["filtered_ready_task_count"] == 2


def test_cli_next_filter_no_match_reports_excluded_ready_tasks(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--difficulty", "low", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 0
    assert data["filters"]["difficulty"] == ["low"]
    assert "No ready tasks match the requested filters" in data["message"]
    assert "2 ready tasks were excluded" in data["message"]


def test_cli_next_filters_ready_tasks_by_memory_state_and_last_outcome(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    record_memory_attempt(
        tmp_path / ".isabelle-blueprint" / "agent-memory.json",
        "main",
        outcome="failed",
        summary="simp looped",
        input_hash=node_input_hash(project.by_id()["main"]),
    )

    rc_fresh = cli_main(["next", str(tmp_path), "--memory-state", "fresh", "--json"])
    fresh_payload = json.loads(capsys.readouterr().out)
    rc_failed = cli_main(["next", str(tmp_path), "--last-outcome", "failed", "--json"])
    failed_payload = json.loads(capsys.readouterr().out)

    assert rc_fresh == 0
    assert fresh_payload["task"]["id"] == "task-helper"
    assert fresh_payload["filters"]["memory_state"] == ["fresh"]
    assert fresh_payload["filtered_ready_task_count"] == 1
    assert rc_failed == 0
    assert failed_payload["task"]["id"] == "task-main"
    assert failed_payload["filters"]["last_outcome"] == ["failed"]


def test_cli_next_can_exclude_ready_nodes_from_selection(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc_node = cli_main(["next", str(tmp_path), "--exclude-node", "main", "--json"])
    node_payload = json.loads(capsys.readouterr().out)
    rc_task = cli_main(["next", str(tmp_path), "--exclude-node", "task-main", "--json"])
    task_payload = json.loads(capsys.readouterr().out)

    assert rc_node == 0
    assert rc_task == 0
    assert node_payload["task"]["id"] == "task-helper"
    assert node_payload["filters"]["exclude_node"] == ["main"]
    assert node_payload["ready_task_count"] == 2
    assert node_payload["filtered_ready_task_count"] == 1
    assert task_payload["task"]["id"] == "task-helper"
    assert task_payload["filters"]["exclude_node"] == ["task-main"]


def test_cli_next_reports_excluded_explicit_selector(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--node", "helper", "--exclude-node", "helper"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ready task 'task-helper' was excluded by filters" in captured.err
    assert "excluded by --exclude-node=helper" in captured.err


def test_cli_next_filters_ready_tasks_by_stale_memory(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())
    record_memory_attempt(
        tmp_path / ".isabelle-blueprint" / "agent-memory.json",
        "main",
        outcome="failed",
        summary="old input",
        input_hash="older-blueprint-input",
    )

    rc = cli_main(["next", str(tmp_path), "--memory-state", "stale", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-main"
    assert data["task"]["memory"]["stale"] is True
    assert data["filters"]["memory_state"] == ["stale"]


def test_cli_next_last_outcome_filter_no_match_reports_excluded_tasks(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--last-outcome", "succeeded", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 0
    assert data["filters"]["last_outcome"] == ["succeeded"]
    assert "last-outcome=succeeded" in data["message"]


def test_cli_next_reports_filter_mismatch_for_explicit_selector(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--node", "helper", "--kind", "theorem"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ready task 'task-helper' was excluded by filters" in captured.err
    assert "kind=lemma does not match --kind=theorem" in captured.err


def test_cli_next_reports_last_outcome_mismatch_for_explicit_selector(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    record_memory_attempt(
        tmp_path / ".isabelle-blueprint" / "agent-memory.json",
        "main",
        outcome="failed",
        summary="simp looped",
        input_hash=node_input_hash(project.by_id()["main"]),
    )

    rc = cli_main(["next", str(tmp_path), "--node", "helper", "--last-outcome", "failed"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ready task 'task-helper' was excluded by filters" in captured.err
    assert "last-outcome=none does not match --last-outcome=failed" in captured.err


def test_cli_next_no_ready_tasks_is_success(tmp_path: Path, capsys):
    project = BlueprintProject.from_nodes(
        "done", [_node("a", "Demo.a", formal=FormalStatus.PROVED)]
    )
    _write_next_project(tmp_path, project)

    rc = cli_main(["next", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None
    assert data["prompt"] is None
    assert data["prompt_path"] is None
    assert "No ready tasks" in data["message"]


def test_cli_attempt_filters_default_ready_task(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["attempt", str(tmp_path), "--kind", "lemma", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-helper"
    assert data["filters"]["kind"] == ["lemma"]
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 1
    assert Path(data["prompt_path"]).name == "task-helper.md"


def test_cli_attempt_filters_default_ready_task_by_fresh_memory(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    record_memory_attempt(
        tmp_path / ".isabelle-blueprint" / "agent-memory.json",
        "main",
        outcome="failed",
        summary="simp looped",
        input_hash=node_input_hash(project.by_id()["main"]),
    )

    rc = cli_main(["attempt", str(tmp_path), "--memory-state", "fresh", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-helper"
    assert data["filters"]["memory_state"] == ["fresh"]
    assert Path(data["prompt_path"]).name == "task-helper.md"


def test_cli_attempt_can_exclude_default_ready_task(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["attempt", str(tmp_path), "--exclude-node", "task-main", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"]["id"] == "task-helper"
    assert data["filters"]["exclude_node"] == ["task-main"]
    assert data["filtered_ready_task_count"] == 1
    assert Path(data["prompt_path"]).name == "task-helper.md"


def test_cli_next_reports_known_but_blocked_node(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--node", "later"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "node 'later' is not currently ready" in captured.err
    assert "blocked by main (formal status: named)" in captured.err


def _next_project() -> BlueprintProject:
    return BlueprintProject.from_nodes(
        "next-test",
        [
            _node("base", "Demo.base", formal=FormalStatus.PROVED, statement="BASE."),
            _node(
                "main",
                "Demo.main",
                uses=["base"],
                formal=FormalStatus.NAMED,
                statement="MAIN.",
                kind=NodeKind.THEOREM,
            ),
            _node(
                "helper",
                "Demo.helper",
                uses=["base"],
                formal=FormalStatus.NAMED,
                statement="HELPER.",
            ),
            _node(
                "later",
                "Demo.later",
                uses=["main"],
                formal=FormalStatus.NAMED,
                statement="LATER.",
            ),
        ],
    )


def _write_next_project(tmp_path: Path, project: BlueprintProject) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{project.name}"\n',
        encoding="utf-8",
    )
    blocks = []
    for node in project.nodes:
        uses = ""
        if node.uses:
            uses = "uses:\n" + "\n".join(f"  - {dep_id}" for dep_id in node.uses) + "\n"
        blocks.append(
            f"""::: {node.kind.value} {{#{node.id}}}
title: {node.title}
isabelle: {node.isabelle.fact}
{uses}status:
  formal: {node.status.formal.value}

{node.title}.
:::
"""
        )
    (tmp_path / "blueprint.md").write_text("\n".join(blocks), encoding="utf-8")
