"""Tests for the shared :mod:`isabelle_blueprint.report.metrics` helper."""
from __future__ import annotations

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report.metrics import (
    PROBLEM_FORMAL_STATUSES,
    build_status_metrics,
    output_values,
    stable_output_keys,
)


def _node(node_id: str, formal: FormalStatus, *, uses: list[str] | None = None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=uses or [],
        isabelle=IsabelleRef(fact=None if formal is FormalStatus.MISSING else f"Demo.{node_id}"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=formal),
    )


def _project(*nodes: BlueprintNode) -> BlueprintProject:
    return BlueprintProject.from_nodes("metrics-test", list(nodes))


def test_problem_statuses_exclude_stale_and_passing():
    # stale is intentionally not a "problem" - it just means deps moved.
    assert FormalStatus.STALE.value not in PROBLEM_FORMAL_STATUSES
    assert FormalStatus.PROVED.value not in PROBLEM_FORMAL_STATUSES
    assert FormalStatus.FOUND.value not in PROBLEM_FORMAL_STATUSES
    assert FormalStatus.NAMED.value not in PROBLEM_FORMAL_STATUSES
    # but all four actively-broken statuses are.
    for value in {"not_found", "broken", "failed_check", "tainted"}:
        assert value in PROBLEM_FORMAL_STATUSES


def test_empty_project_has_undefined_coverage():
    metrics = build_status_metrics(BlueprintProject.from_nodes("empty", []))
    assert metrics.node_count == 0
    assert metrics.formal_target_count == 0
    assert metrics.coverage_percent is None
    assert metrics.has_problems is False
    assert metrics.has_cycles is False


def test_all_missing_nodes_yields_undefined_coverage():
    project = _project(_node("a", FormalStatus.MISSING), _node("b", FormalStatus.MISSING))
    metrics = build_status_metrics(project)
    assert metrics.node_count == 2
    assert metrics.formal_target_count == 0
    # Denominator is undefined - must not report 0% (which would imply we
    # tried and failed to prove anything).
    assert metrics.coverage_percent is None


def test_mixed_project_coverage_excludes_missing_from_denominator():
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.FOUND),
        _node("c", FormalStatus.MISSING),
        _node("d", FormalStatus.NAMED),
    )
    metrics = build_status_metrics(project)
    assert metrics.node_count == 4
    assert metrics.formal_target_count == 3  # missing excluded
    assert metrics.proved_count == 1
    assert metrics.found_count == 1
    # 1 proved / 3 formal targets = 33%
    assert metrics.coverage_percent == 33
    assert metrics.has_problems is False


def test_all_proved_hits_one_hundred_percent():
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.PROVED),
    )
    metrics = build_status_metrics(project)
    assert metrics.coverage_percent == 100
    assert metrics.has_problems is False


def test_coverage_truncates_so_near_complete_is_not_false_one_hundred():
    # 2 proved / 3 targets = 66.67%: must report 66, never round up to 67 and
    # certainly never to 100. The 100% bucket is reserved for genuinely
    # all-proved projects (else `status` health falsely reads "complete").
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.PROVED),
        _node("c", FormalStatus.NAMED),
    )
    metrics = build_status_metrics(project)
    assert metrics.formal_target_count == 3
    assert metrics.proved_count == 2
    assert metrics.coverage_percent == 66


def test_coverage_truncates_so_barely_started_is_not_false_zero():
    # 1 proved / 3 targets = 33% here is exact; the floor guarantee matters most
    # at the boundaries, but verify a single proved target never reads as 0%.
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.NAMED),
        _node("c", FormalStatus.NAMED),
    )
    metrics = build_status_metrics(project)
    assert metrics.coverage_percent == 33


def test_problem_statuses_flip_has_problems():
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.BROKEN),
    )
    metrics = build_status_metrics(project)
    assert metrics.problem_count == 1
    assert metrics.has_problems is True


def test_stale_does_not_count_as_problem():
    project = _project(_node("a", FormalStatus.PROVED), _node("b", FormalStatus.STALE))
    metrics = build_status_metrics(project)
    assert metrics.stale_count == 1
    assert metrics.problem_count == 0
    assert metrics.has_problems is False


def test_cycles_detected_via_validate():
    project = _project(
        _node("a", FormalStatus.NAMED, uses=["b"]),
        _node("b", FormalStatus.NAMED, uses=["a"]),
    )
    metrics = build_status_metrics(project)
    assert metrics.has_cycles is True


def test_output_values_serializes_none_as_empty_string():
    project = BlueprintProject.from_nodes("empty", [])
    metrics = build_status_metrics(project)
    values = output_values(metrics)
    assert values["coverage_percent"] == ""
    assert values["has_cycles"] == "false"
    assert values["node_count"] == "0"


def test_output_values_uses_stable_key_set():
    project = _project(_node("a", FormalStatus.PROVED))
    values = output_values(build_status_metrics(project))
    # Every documented key must be present, and nothing else - the set is
    # the public contract for downstream Actions.
    assert set(values) == set(stable_output_keys())


def test_to_dict_round_trips_all_metric_fields():
    project = _project(
        _node("a", FormalStatus.PROVED),
        _node("b", FormalStatus.BROKEN),
    )
    data = build_status_metrics(project).to_dict()
    for key in (
        "node_count",
        "formal_target_count",
        "proved_count",
        "found_count",
        "problem_count",
        "stale_count",
        "has_cycles",
        "coverage_percent",
    ):
        assert key in data
