"""Tests for agent-task generation."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.tasks import generate_tasks, write_tasks
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id, fact, *, uses=None, formal=FormalStatus.MISSING, statement="", proof=""):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
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
