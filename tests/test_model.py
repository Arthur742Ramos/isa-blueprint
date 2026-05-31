"""Tests for the data model (validation, graph layering, status recomputation)."""
from __future__ import annotations

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus


def _node(node_id: str, *, uses=None, formal=FormalStatus.MISSING, agent=AgentStatus.BLOCKED):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=formal, agent=agent),
    )


def test_validate_ok_for_dag():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b", uses=["a"])])
    report = project.validate()
    assert report.ok
    assert report.issues() == []


def test_duplicate_ids_detected():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("a")])
    report = project.validate()
    assert "a" in report.duplicate_ids
    assert not report.ok


def test_missing_dependency_detected():
    project = BlueprintProject.from_nodes("p", [_node("a", uses=["nope"])])
    report = project.validate()
    assert ("a", "nope") in report.missing_dependencies


def test_cycle_detected():
    project = BlueprintProject.from_nodes(
        "p",
        [_node("a", uses=["b"]), _node("b", uses=["a"])],
    )
    report = project.validate()
    assert report.cycles, "expected at least one cycle"
    # Each cycle is reported once thanks to canonicalisation.
    assert len({tuple(sorted(c)) for c in report.cycles}) == 1


def test_self_cycle_detected():
    project = BlueprintProject.from_nodes("p", [_node("a", uses=["a"])])
    report = project.validate()
    assert any("a" in c for c in report.cycles)


def test_missing_dependency_suggests_close_match():
    """A typo'd dependency id offers a 'did you mean?' suggestion."""
    project = BlueprintProject.from_nodes(
        "p",
        [_node("add-zero-right"), _node("a", uses=["add-zero-rihgt"])],
    )
    report = project.validate()
    assert ("a", "add-zero-rihgt") in report.missing_dependencies
    assert "add-zero-right" in report.suggestions.get("add-zero-rihgt", [])
    # The hint is surfaced in the human-readable issue text.
    assert any("did you mean" in msg for msg in report.issues())


def test_recompute_agent_status_ready_when_deps_complete():
    a = _node("a", formal=FormalStatus.FOUND, agent=AgentStatus.SOLVED)
    b = _node("b", uses=["a"])  # default BLOCKED
    project = BlueprintProject.from_nodes("p", [a, b])
    project.recompute_agent_status()
    assert b.status.agent == AgentStatus.READY


def test_recompute_agent_status_blocked_when_dep_unproved():
    a = _node("a", formal=FormalStatus.NAMED)
    b = _node("b", uses=["a"])
    project = BlueprintProject.from_nodes("p", [a, b])
    project.recompute_agent_status()
    assert b.status.agent == AgentStatus.BLOCKED


def test_recompute_agent_status_no_deps_is_ready():
    """A leaf node with no deps and a not-yet-proved formal status should be ready."""
    a = _node("a", formal=FormalStatus.NAMED)
    project = BlueprintProject.from_nodes("p", [a])
    project.recompute_agent_status()
    assert a.status.agent == AgentStatus.READY


def test_recompute_preserves_manual_overrides():
    a = _node("a", formal=FormalStatus.FOUND)
    b = _node("b", uses=["a"], agent=AgentStatus.IN_PROGRESS)
    project = BlueprintProject.from_nodes("p", [a, b])
    project.recompute_agent_status()
    assert b.status.agent == AgentStatus.IN_PROGRESS  # preserved


def test_recompute_proved_node_becomes_solved():
    a = _node("a", formal=FormalStatus.PROVED, agent=AgentStatus.BLOCKED)
    project = BlueprintProject.from_nodes("p", [a])
    project.recompute_agent_status()
    assert a.status.agent == AgentStatus.SOLVED


def test_to_dict_roundtrip_shape():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b", uses=["a"])])
    d = project.to_dict()
    assert d["name"] == "p"
    assert len(d["nodes"]) == 2
    assert d["nodes"][1]["uses"] == ["a"]
    assert "status" in d["nodes"][0]
    assert "formal" in d["nodes"][0]["status"]
