from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.agents.memory import (
    AgentMemory,
    AgentMemoryAttempt,
    add_memory_attempt,
    load_agent_memory,
    node_input_hash,
    record_memory_attempt,
    summarize_node_memory,
)
from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str = "a") -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title="A",
        statement="stmt",
        isabelle=IsabelleRef(fact="Demo.a"),
        status=NodeStatus(formal=FormalStatus.MISSING),
    )


def test_record_and_load_agent_memory(tmp_path: Path):
    path = tmp_path / "agent-memory.json"
    attempt = record_memory_attempt(
        path,
        "a",
        outcome="failed",
        summary="simp looped",
        next_step="try induction",
        input_hash="abc",
    )

    loaded = load_agent_memory(path, strict=True)

    assert loaded.nodes["a"].attempts[0].summary == "simp looped"
    assert loaded.nodes["a"].attempts[0].timestamp == attempt.timestamp


def test_memory_attempts_are_capped():
    memory = AgentMemory()
    for index in range(3):
        add_memory_attempt(
            memory,
            "a",
            AgentMemoryAttempt(timestamp=str(index), outcome="note", summary=str(index)),
            max_attempts=2,
        )

    assert [a.summary for a in memory.nodes["a"].attempts] == ["1", "2"]


def test_memory_summary_marks_stale_input():
    memory = AgentMemory()
    add_memory_attempt(
        memory,
        "a",
        AgentMemoryAttempt(timestamp="t", outcome="failed", summary="old", input_hash="old"),
    )

    summary = summarize_node_memory(memory, "a", current_input_hash="new")

    assert summary is not None
    assert summary.stale is True
    assert summary.last_outcome == "failed"


def test_tasks_include_memory_summary():
    node = _node()
    memory = AgentMemory()
    add_memory_attempt(
        memory,
        "a",
        AgentMemoryAttempt(
            timestamp="t",
            outcome="blocked",
            summary="needs helper",
            next_step="prove helper",
            input_hash=node_input_hash(node),
        ),
    )

    task = generate_tasks(BlueprintProject.from_nodes("p", [node]), memory=memory)[0]

    assert task.memory is not None
    assert task.memory.last_summary == "needs helper"
    assert task.to_dict()["memory"]["next_step"] == "prove helper"


def test_unreadable_memory_warns_and_returns_empty(tmp_path: Path):
    path = tmp_path / "agent-memory.json"
    path.write_text("{", encoding="utf-8")

    with pytest.warns(UserWarning, match="ignoring unreadable agent memory"):
        memory = load_agent_memory(path)

    assert memory.nodes == {}


def test_unreadable_memory_raises_in_strict_mode(tmp_path: Path):
    path = tmp_path / "agent-memory.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(BlueprintError):
        load_agent_memory(path, strict=True)


def test_agent_memory_schema_shape(tmp_path: Path):
    path = tmp_path / "agent-memory.json"
    record_memory_attempt(path, "a", outcome="note", summary="hello")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["nodes"]["a"]["attempts"][0]["outcome"] == "note"
