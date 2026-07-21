"""Deterministic performance-regression tests for large projects.

These tests intentionally avoid wall-clock timing thresholds (which are
flaky across CI runners) and instead assert *algorithmic* properties that
would regress if a hot path went back to doing repeated O(n) work:

  - ``by_id()``'s cached index is not rebuilt across repeated calls when the
    node list hasn't been mutated.
  - ``generate_tasks()`` and ``project.validate()`` complete without raising
    ``RecursionError`` on 1k/10k-node deep dependency chains and produce the
    exact expected (small, deterministic) output shape.
"""
from __future__ import annotations

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

_SIZES = (1_000, 10_000)


def _node(node_id: str, *, uses=None, formal=FormalStatus.MISSING) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
    )


def _chain_natural(n: int) -> list[BlueprintNode]:
    """n0 <- n1 <- ... <- n_{n-1}: the realistic blueprint shape where each
    node depends on the single node declared immediately before it."""
    nodes = [_node("n0", formal=FormalStatus.PROVED)]
    for i in range(1, n):
        nodes.append(_node(f"n{i}", uses=[f"n{i - 1}"]))
    return nodes


def _chain_reversed(n: int) -> list[BlueprintNode]:
    """n0 -> n1 -> ... -> n_{n-1}: earlier nodes depend on later ones."""
    nodes = [_node(f"n{i}", uses=[f"n{i + 1}"]) for i in range(n - 1)]
    nodes.append(_node(f"n{n - 1}"))
    return nodes


def test_by_id_cache_not_rebuilt_across_repeated_calls_at_scale():
    """A concrete algorithmic proxy for 'no repeated O(n) reconstruction':
    the cached index object itself must be the *same* dict across many
    repeated by_id() calls on an unmutated project, at both 1k and 10k
    node scale."""
    for size in _SIZES:
        project = BlueprintProject.from_nodes("p", _chain_natural(size))
        project.by_id()
        cache = project._id_index_cache
        assert cache is not None
        cached_index = cache[2]
        for _ in range(50):
            project.by_id()
            assert project._id_index_cache is cache
            assert project._id_index_cache[2] is cached_index


def test_generate_tasks_completes_on_large_natural_chains():
    """generate_tasks() must not raise RecursionError and must produce the
    exact expected deterministic shape: only the single direct dependent of
    the already-PROVED root node is ready."""
    for size in _SIZES:
        project = BlueprintProject.from_nodes("p", _chain_natural(size))
        tasks = generate_tasks(project)
        assert {t.node_id for t in tasks} == {"n1"}
        task = tasks[0]
        assert task.metadata is not None
        assert task.metadata.dependency_depth == 1
        assert task.metadata.blocking_count == size - 2


def test_validate_completes_on_large_reversed_chains():
    """project.validate() must not raise RecursionError on deep reversed
    chains and must correctly report no cycles."""
    for size in _SIZES:
        project = BlueprintProject.from_nodes("p", _chain_reversed(size))
        report = project.validate()
        assert report.ok
        assert report.cycles == []


def test_validate_completes_on_large_ring_cycles():
    """project.validate() must not raise RecursionError on a large single
    cycle and must report exactly one canonicalised cycle covering every
    node."""
    for size in _SIZES:
        nodes = [_node(f"n{i}", uses=[f"n{(i + 1) % size}"]) for i in range(size)]
        project = BlueprintProject.from_nodes("p", nodes)
        report = project.validate()
        assert not report.ok
        assert len(report.cycles) == 1
        assert len(report.cycles[0]) == size + 1
