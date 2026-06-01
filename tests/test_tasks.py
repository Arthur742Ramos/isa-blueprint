"""Tests for agent-task generation."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.tasks import generate_tasks, render_task_prompt, write_tasks
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


def test_write_tasks_can_emit_github_issue_drafts(tmp_path: Path):
    project = BlueprintProject.from_nodes("p", [_node("a", "Demo.a", statement="stmt")])

    paths = write_tasks(project, tmp_path, github_issues=True)

    issue_path = paths["github_issues"]
    data = json.loads(issue_path.read_text(encoding="utf-8"))
    assert data["issues"][0]["title"] == "Formalize A"
    assert "agent-task" in data["issues"][0]["labels"]


def test_cli_next_prints_suggested_prompt(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    expected = render_task_prompt(generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0])

    rc = cli_main(["next", str(tmp_path)])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == expected


def test_cli_next_json_includes_task_and_prompt(tmp_path: Path, capsys):
    project = _next_project()
    _write_next_project(tmp_path, project)
    expected = render_task_prompt(generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0])

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
    expected = render_task_prompt(generate_tasks(project, fact_suggestions=suggest_missing_facts(project))[0])
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
    project = BlueprintProject.from_nodes("done", [_node("a", "Demo.a", formal=FormalStatus.PROVED)])
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


def test_cli_next_no_ready_tasks_is_success(tmp_path: Path, capsys):
    project = BlueprintProject.from_nodes("done", [_node("a", "Demo.a", formal=FormalStatus.PROVED)])
    _write_next_project(tmp_path, project)

    rc = cli_main(["next", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task"] is None
    assert data["prompt"] is None
    assert data["prompt_path"] is None
    assert "No ready tasks" in data["message"]


def test_cli_next_reports_known_but_blocked_node(tmp_path: Path, capsys):
    _write_next_project(tmp_path, _next_project())

    rc = cli_main(["next", str(tmp_path), "--node", "later"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "node 'later' is not currently ready" in captured.err


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
            _node("helper", "Demo.helper", uses=["base"], formal=FormalStatus.NAMED, statement="HELPER."),
            _node("later", "Demo.later", uses=["main"], formal=FormalStatus.NAMED, statement="LATER."),
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
