"""Tests for the data model (validation, graph layering, status recomputation)."""
from __future__ import annotations

import sys

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


def _chain_reversed(n: int) -> list[BlueprintNode]:
    """n0 -> n1 -> ... -> n_{n-1} (earlier nodes depend on later ones).

    This is the pathological direction for validate()'s cycle-detection DFS:
    the outer loop visits n0 first, whose dependency chain descends all the
    way to the leaf n_{n-1} before any node is already-visited.
    """
    nodes = [_node(f"n{i}", uses=[f"n{i + 1}"]) for i in range(n - 1)]
    nodes.append(_node(f"n{n - 1}"))
    return nodes


def _big_cycle(n: int) -> list[BlueprintNode]:
    """A single ring: n_i uses n_{(i+1) % n} for all i."""
    return [_node(f"n{i}", uses=[f"n{(i + 1) % n}"]) for i in range(n)]


def test_validate_deep_reversed_chain_does_not_raise_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _chain_reversed(n))
    report = project.validate()
    assert report.ok
    assert report.cycles == []


def test_validate_deep_cycle_does_not_raise_recursion_error():
    n = sys.getrecursionlimit() + 2000
    project = BlueprintProject.from_nodes("p", _big_cycle(n))
    report = project.validate()
    assert not report.ok
    assert len(report.cycles) == 1
    cycle = report.cycles[0]
    assert len(cycle) == n + 1
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == {f"n{i}" for i in range(n)}


def test_validate_small_reversed_chain_depths_are_correct_shape():
    """Sanity check on a small reversed chain before trusting the deep variant."""
    project = BlueprintProject.from_nodes("p", _chain_reversed(4))
    report = project.validate()
    assert report.ok
    assert report.cycles == []


def test_validate_small_cycle_ring_reports_single_cycle():
    project = BlueprintProject.from_nodes("p", _big_cycle(5))
    report = project.validate()
    assert not report.ok
    assert len(report.cycles) == 1
    cycle = report.cycles[0]
    assert len(cycle) == 6
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == {f"n{i}" for i in range(5)}


def test_by_id_cache_reused_across_calls_without_mutation():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b", uses=["a"])])
    project.by_id()
    cached = project._id_index_cache
    assert cached is not None
    project.by_id()
    project.by_id()
    assert project._id_index_cache is cached, "cache should not be rebuilt when unmutated"


def test_by_id_returns_independent_dict_each_call():
    project = BlueprintProject.from_nodes("p", [_node("a")])
    first = project.by_id()
    second = project.by_id()
    assert first == second
    assert first is not second
    first["b"] = _node("b")
    assert "b" not in project.by_id()


def test_by_id_cache_invalidated_on_append():
    project = BlueprintProject.from_nodes("p", [_node("a")])
    assert set(project.by_id()) == {"a"}
    project.nodes.append(_node("b"))
    assert set(project.by_id()) == {"a", "b"}


def test_by_id_cache_invalidated_on_extend():
    project = BlueprintProject.from_nodes("p", [_node("a")])
    assert set(project.by_id()) == {"a"}
    project.nodes.extend([_node("b"), _node("c")])
    assert set(project.by_id()) == {"a", "b", "c"}


def test_by_id_cache_invalidated_on_insert():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("c")])
    assert set(project.by_id()) == {"a", "c"}
    project.nodes.insert(1, _node("b"))
    assert set(project.by_id()) == {"a", "b", "c"}
    assert [n.id for n in project.nodes] == ["a", "b", "c"]


def test_by_id_cache_invalidated_on_remove():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b")])
    assert set(project.by_id()) == {"a", "b"}
    project.nodes.remove(project.nodes[0])
    assert set(project.by_id()) == {"b"}


def test_by_id_cache_invalidated_on_pop():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b")])
    assert set(project.by_id()) == {"a", "b"}
    project.nodes.pop()
    assert set(project.by_id()) == {"a"}


def test_by_id_cache_invalidated_on_del():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b")])
    assert set(project.by_id()) == {"a", "b"}
    del project.nodes[0]
    assert set(project.by_id()) == {"b"}


def test_by_id_cache_invalidated_on_clear():
    project = BlueprintProject.from_nodes("p", [_node("a"), _node("b")])
    assert set(project.by_id()) == {"a", "b"}
    project.nodes.clear()
    assert project.by_id() == {}


def test_by_id_cache_invalidated_on_wholesale_reassignment():
    project = BlueprintProject.from_nodes("p", [_node("a")])
    assert set(project.by_id()) == {"a"}
    project.nodes = [_node("x"), _node("y")]
    assert set(project.by_id()) == {"x", "y"}


def test_by_id_reflects_in_place_attribute_mutation_without_needing_invalidation():
    """Mutating a node's attributes in place must be visible through by_id()
    even though it doesn't change list identity/length (the index still maps
    to the same node objects)."""
    a = _node("a")
    project = BlueprintProject.from_nodes("p", [a])
    project.by_id()  # warm the cache
    a.title = "Changed"
    assert project.by_id()["a"].title == "Changed"


def test_by_id_cache_does_not_leak_across_instances_from_from_nodes():
    project1 = BlueprintProject.from_nodes("p1", [_node("a")])
    project2 = BlueprintProject.from_nodes("p2", [_node("b")])
    assert set(project1.by_id()) == {"a"}
    assert set(project2.by_id()) == {"b"}
    # Re-check after warming both caches to ensure no cross-contamination.
    assert set(project1.by_id()) == {"a"}
    assert set(project2.by_id()) == {"b"}


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


def test_status_enums_stringify_to_their_values():
    """StrEnum members stringify to their value (locks the v1.0 JSON contract)."""
    assert str(NodeKind.LEMMA) == "lemma"
    assert f"{NodeKind.THEOREM}" == "theorem"
    assert str(BlueprintStatus.WRITTEN) == BlueprintStatus.WRITTEN.value
    assert f"{FormalStatus.FOUND}" == FormalStatus.FOUND.value
    assert f"{AgentStatus.READY}" == AgentStatus.READY.value
    # Still plain strings for comparison and dict keys.
    assert NodeKind.LEMMA == "lemma"
    assert {NodeKind.LEMMA: 1}["lemma"] == 1
