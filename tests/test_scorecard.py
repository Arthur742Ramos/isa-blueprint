from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report.scorecard import (
    ALL_GRADES,
    SCORECARD_SCHEMA_VERSION,
    build_scorecard,
    grade_for,
    grade_threshold,
    render_scorecard,
)


def _node(
    node_id: str,
    *,
    uses: list[str] | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
    blueprint: BlueprintStatus = BlueprintStatus.STUB,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(blueprint=blueprint, formal=formal),
    )


def _project(*nodes: BlueprintNode, name: str = "card") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _component(card, name: str):
    return next(component for component in card.components if component.name == name)


def test_grade_for_boundaries() -> None:
    assert grade_for(100) == "A+"
    assert grade_for(97) == "A+"
    assert grade_for(96) == "A"
    assert grade_for(90) == "A-"
    assert grade_for(60) == "D-"
    assert grade_for(59) == "F"
    assert grade_for(0) == "F"
    assert grade_for(None) == "n/a"


def test_empty_project_scores_none() -> None:
    card = build_scorecard(_project(name="empty"))

    assert card.project == "empty"
    assert card.score is None
    assert card.grade == "n/a"
    assert card.schema_version == SCORECARD_SCHEMA_VERSION
    # Every component is reported even when undefined.
    assert {c.name for c in card.components} == {
        "coverage",
        "integrity",
        "structure",
        "freshness",
        "documentation",
        "readiness",
    }
    assert all(c.score is None for c in card.components)


def test_perfect_project_scores_100() -> None:
    # All proved + reviewed + acyclic: every defined component is 1.0. Readiness
    # is undefined (no incomplete nodes) and drops out of the average.
    project = _project(
        _node("a", formal=FormalStatus.PROVED, blueprint=BlueprintStatus.REVIEWED),
        _node(
            "b",
            uses=["a"],
            formal=FormalStatus.PROVED,
            blueprint=BlueprintStatus.REVIEWED,
        ),
    )

    card = build_scorecard(project)

    assert card.score == 100
    assert card.grade == "A+"
    assert _component(card, "readiness").score is None


def test_problem_status_drags_integrity_and_coverage() -> None:
    project = _project(
        _node("a", formal=FormalStatus.PROVED, blueprint=BlueprintStatus.REVIEWED),
        _node("b", formal=FormalStatus.BROKEN, blueprint=BlueprintStatus.REVIEWED),
    )

    card = build_scorecard(project)

    # 2 targets, 1 proved -> coverage 0.5; 1 problem -> integrity 0.5.
    assert _component(card, "coverage").score == 0.5
    assert _component(card, "integrity").score == 0.5
    assert card.score is not None and card.score < 100


def test_structure_penalises_missing_dependency() -> None:
    # ``b`` references a dependency that is not a node -> structurally affected.
    project = _project(_node("a"), _node("b", uses=["ghost"]))

    card = build_scorecard(project)

    structure = _component(card, "structure")
    assert structure.score == 0.5
    assert "missing a dependency" in structure.detail


def test_readiness_counts_unblocked_incomplete_nodes() -> None:
    # ``a`` is proved; ``b`` is incomplete but all its deps are complete, so it
    # is actionable now -> readiness 1.0.
    project = _project(
        _node("a", formal=FormalStatus.PROVED),
        _node("b", uses=["a"], formal=FormalStatus.MISSING),
    )

    card = build_scorecard(project)

    readiness = _component(card, "readiness")
    assert readiness.score == 1.0
    assert "1/1" in readiness.detail


def test_render_contains_grade_and_components() -> None:
    project = _project(_node("a", formal=FormalStatus.PROVED))
    text = render_scorecard(build_scorecard(project))

    assert "scorecard" in text.lower()
    assert "Overall:" in text
    assert "Coverage" in text
    assert "Integrity" in text


def _write_project(tmp_path: Path, body: str, *, name: str = "card-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# card-test

::: definition {#a}
title: A
isabelle: Demo.a
status: reviewed

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: written
uses: a, ghost

Depends on a (and a missing 'ghost' node, so structure can never be perfect).

Sketch.
:::
"""


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "card-test scorecard" in out
    assert "Overall:" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "card-test"
    assert data["schema_version"] == SCORECARD_SCHEMA_VERSION
    assert set(data.keys()) >= {"project", "score", "grade", "components"}
    assert len(data["components"]) == 6
    assert isinstance(data["grade"], str) and data["grade"]
    # Without --min-grade there is no gate object.
    assert "gate" not in data


def test_grade_threshold_and_all_grades() -> None:
    assert grade_threshold("A+") == 97
    assert grade_threshold("B") == 83
    assert grade_threshold("F") == 0
    assert grade_threshold("n/a") is None
    assert grade_threshold("Z") is None
    # Best grade first, n/a sentinel excluded.
    assert ALL_GRADES[0] == "A+"
    assert ALL_GRADES[-1] == "F"
    assert "n/a" not in ALL_GRADES


def test_cli_min_grade_below_threshold_fails(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    # _BODY is a real, non-perfect project: it cannot reach A+ (>=97).
    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "A+"])

    assert rc == 5
    err = capsys.readouterr().err
    assert "min-grade policy triggered" in err


def test_cli_min_grade_met_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "F"])

    assert rc == 0
    assert "policy triggered" not in capsys.readouterr().err


def test_cli_min_grade_is_case_insensitive(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "a+", "--json"])

    assert rc == 5
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["min_grade"] == "A+"  # normalised to canonical form
    assert gate["meets_min_grade"] is False


def test_cli_min_grade_json_gate_present_when_met(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "F", "--json"])

    assert rc == 0
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["meets_min_grade"] is True
    assert gate["min_grade"] == "F"


def test_cli_min_grade_ungradeable_project_does_not_fail(tmp_path: Path, capsys) -> None:
    # A project with no nodes is ungradeable (score None); the gate must not fire.
    _write_project(tmp_path, "# empty project\n", name="empty")

    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "A"])

    assert rc == 0
    assert "not enforced" in capsys.readouterr().err


def test_cli_min_grade_invalid_value_is_usage_error(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    try:
        rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "Z"])
    except SystemExit as exc:  # argparse raises SystemExit(2) on bad choice
        rc = exc.code
    assert rc == 2
    assert "invalid grade" in capsys.readouterr().err


def test_cli_min_score_below_threshold_fails(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    # _BODY is a real, non-perfect project: it cannot reach a score of 100.
    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "100"])

    assert rc == 5
    err = capsys.readouterr().err
    assert "min-score policy triggered" in err


def test_cli_min_score_met_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "0"])

    assert rc == 0
    assert "policy triggered" not in capsys.readouterr().err


def test_cli_min_score_json_gate_present(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "100", "--json"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    gate = data["gate"]
    assert gate["min_score"] == 100
    assert gate["meets_min_score"] is False
    assert gate["score"] == data["score"]
    assert gate["grade"] == data["grade"]
    # No --min-grade, so grade keys are absent.
    assert "min_grade" not in gate
    assert "meets_min_grade" not in gate


def test_cli_min_score_json_gate_met(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "0", "--json"])

    assert rc == 0
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["meets_min_score"] is True
    assert gate["min_score"] == 0


def test_cli_min_score_ungradeable_project_does_not_fail(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# empty project\n", name="empty")

    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "50"])

    assert rc == 0
    err = capsys.readouterr().err
    assert "min-score 50 not enforced" in err


def test_cli_min_score_ungradeable_json_gate_null(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# empty project\n", name="empty")

    rc = cli_main(["scorecard", str(tmp_path), "--min-score", "50", "--json"])

    assert rc == 0
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["meets_min_score"] is None
    assert gate["score"] is None


def test_cli_min_score_invalid_value_is_usage_error(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    try:
        rc = cli_main(["scorecard", str(tmp_path), "--min-score", "150"])
    except SystemExit as exc:  # argparse raises SystemExit(2) on bad value
        rc = exc.code
    assert rc == 2
    assert "invalid score" in capsys.readouterr().err


def test_cli_min_score_non_integer_is_usage_error(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    try:
        rc = cli_main(["scorecard", str(tmp_path), "--min-score", "B+"])
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2
    assert "invalid score" in capsys.readouterr().err


def test_cli_min_score_composes_with_min_grade(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    # Grade gate is met (F), but score gate (100) is not -> overall failure.
    rc = cli_main(
        ["scorecard", str(tmp_path), "--min-grade", "F", "--min-score", "100", "--json"]
    )

    assert rc == 5
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["meets_min_grade"] is True
    assert gate["meets_min_score"] is False
    # Both gates' keys present in the same object.
    assert gate["min_grade"] == "F"
    assert gate["min_score"] == 100


def test_cli_min_score_composes_both_met(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(
        ["scorecard", str(tmp_path), "--min-grade", "F", "--min-score", "0"]
    )

    assert rc == 0
    assert "policy triggered" not in capsys.readouterr().err


def test_cli_min_grade_gate_byte_identical_without_min_score(tmp_path: Path, capsys) -> None:
    # Guard the frozen v1 contract: --min-grade alone must emit exactly the
    # original gate keys in order, with no min_score leakage.
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--min-grade", "A+", "--json"])

    assert rc == 5
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert list(gate.keys()) == ["min_grade", "score", "grade", "meets_min_grade"]


