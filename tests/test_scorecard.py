from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint import console
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


_BODY_COV = """# card-test

::: definition {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: named
uses: a

B depends on a, but is not proved -> coverage 1/2 = 50%.

Sketch.
:::
"""


_BODY_COV_NEAR = """# card-test

::: definition {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: proved
uses: a

B is proved.

Sketch.
:::

::: lemma {#c}
title: C
isabelle: Demo.c
status:
  formal: named
uses: a

C is not proved -> coverage 2/3 = 66.67% (rounds to 67).

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



def test_cli_markdown_writes_file(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--markdown"])

    assert rc == 0
    md_path = tmp_path / "build" / "scorecard.md"
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    assert "# card-test scorecard" in text
    assert "Overall:" in text
    # stdout is byte-identical to a run without --markdown.
    out = capsys.readouterr().out
    cli_main(["scorecard", str(tmp_path)])
    assert out == capsys.readouterr().out


def test_cli_markdown_stdout_unchanged(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    cli_main(["scorecard", str(tmp_path)])
    plain = capsys.readouterr().out

    cli_main(["scorecard", str(tmp_path), "--markdown"])
    captured = capsys.readouterr()
    assert captured.out == plain
    # The artifact path note is on stderr, never stdout.
    assert "scorecard.md" in captured.err


def test_cli_markdown_composes_with_min_grade_gate(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--markdown", "--min-grade", "A+"])

    # Gate still controls the exit code, and the file is still written.
    assert rc == 5
    assert (tmp_path / "build" / "scorecard.md").is_file()


def test_cli_markdown_no_ansi_when_colour_forced_on(tmp_path: Path, capsys) -> None:
    # Regression: the file render must never leak ANSI escapes, even when the
    # console has colour forced on. pytest stdout is non-TTY, so colour is
    # normally off and this path goes untested without `--color always`.
    _write_project(tmp_path, _BODY)
    was_enabled = console.is_enabled()
    try:
        rc = cli_main(["--color", "always", "scorecard", str(tmp_path), "--markdown"])
    finally:
        console.set_enabled(was_enabled)

    assert rc == 0
    # Stdout was coloured (proves colour was on for this run), but the file is not.
    assert "\x1b" in capsys.readouterr().out
    text = (tmp_path / "build" / "scorecard.md").read_text(encoding="utf-8")
    assert "\x1b" not in text


def test_cli_min_component_below_threshold_fails(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_COV)

    # _BODY_COV has 1 proved of 2 targets -> coverage 50%, below 80.
    rc = cli_main(["scorecard", str(tmp_path), "--min-component", "coverage=80"])

    assert rc == 5
    err = capsys.readouterr().err
    assert "min-component policy triggered: coverage" in err


def test_cli_min_component_raw_below_rounded_threshold_fails(
    tmp_path: Path, capsys
) -> None:
    # Coverage is 2/3 = 66.67%, which ROUNDS to 67 for display. A gate at =67
    # must still trip on the raw ratio (66.67 < 67); a rounded comparison would
    # wrongly pass it.
    _write_project(tmp_path, _BODY_COV_NEAR)

    rc = cli_main(
        ["scorecard", str(tmp_path), "--min-component", "coverage=67", "--json"]
    )

    assert rc == 5
    gate = json.loads(capsys.readouterr().out)["component_gates"][0]
    assert gate["score"] == 67  # rounded display value
    assert gate["meets"] is False  # but the raw ratio fails the gate


def test_cli_min_component_met_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_COV)

    rc = cli_main(["scorecard", str(tmp_path), "--min-component", "coverage=50"])

    assert rc == 0
    assert "policy triggered" not in capsys.readouterr().err


def test_cli_min_component_json_gates(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_COV)

    rc = cli_main(
        ["scorecard", str(tmp_path), "--min-component", "coverage=80", "--json"]
    )

    assert rc == 5
    gates = json.loads(capsys.readouterr().out)["component_gates"]
    assert gates == [
        {"component": "coverage", "threshold": 80, "score": 50, "meets": False}
    ]


def test_cli_min_component_repeatable_and_composes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_COV)

    rc = cli_main(
        [
            "scorecard",
            str(tmp_path),
            "--min-component",
            "coverage=0",
            "--min-component",
            "coverage=80",
            "--min-grade",
            "F",
            "--json",
        ]
    )

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    gates = data["component_gates"]
    assert gates[0]["meets"] is True
    assert gates[1]["meets"] is False
    # Composes with the existing grade gate object.
    assert data["gate"]["meets_min_grade"] is True


def test_cli_min_component_undefined_score_never_fails(tmp_path: Path, capsys) -> None:
    # An empty project has no defined component scores, so the gate is inert.
    _write_project(tmp_path, "# empty project\n", name="empty")

    rc = cli_main(
        ["scorecard", str(tmp_path), "--min-component", "coverage=80", "--json"]
    )

    assert rc == 0
    gate = json.loads(capsys.readouterr().out)["component_gates"][0]
    assert gate["score"] is None
    assert gate["meets"] is None


def test_cli_min_component_unknown_name_is_usage_error(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    try:
        rc = cli_main(["scorecard", str(tmp_path), "--min-component", "bogus=50"])
    except SystemExit as exc:  # argparse raises SystemExit(2) on bad value
        rc = exc.code
    assert rc == 2
    assert "invalid component" in capsys.readouterr().err


def test_cli_min_component_out_of_range_is_usage_error(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    try:
        rc = cli_main(["scorecard", str(tmp_path), "--min-component", "coverage=150"])
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2
    assert "invalid percentage" in capsys.readouterr().err


def test_cli_min_component_absent_unchanged(tmp_path: Path, capsys) -> None:
    # No --min-component: no component_gates key, exit unchanged.
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--json"])

    assert rc == 0
    assert "component_gates" not in json.loads(capsys.readouterr().out)


# --- --since trend delta -----------------------------------------------------

_BODY_BASELINE = """# card-test

::: definition {#a}
title: A
isabelle: Demo.a
status:
  formal: named

A base, not yet proved.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: named
uses: a

B, not yet proved -> coverage 0/2 = 0%.

Sketch.
:::
"""

_BODY_IMPROVED = """# card-test

::: definition {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A base, now proved.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: proved
uses: a

B, now proved -> coverage 2/2 = 100%.

Sketch.
:::
"""


def _save_baseline(tmp_path: Path, capsys) -> Path:
    """Run ``scorecard --json`` and persist the payload as a baseline file."""

    assert cli_main(["scorecard", str(tmp_path), "--json"]) == 0
    baseline = tmp_path / "baseline.json"
    baseline.write_text(capsys.readouterr().out, encoding="utf-8")
    return baseline


def test_cli_since_reports_positive_delta(tmp_path: Path, capsys) -> None:
    # Save a weak baseline, then improve the project: the delta is positive.
    _write_project(tmp_path, _BODY_BASELINE)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_IMPROVED)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Overall:" in out
    assert "+" in out and "since baseline" in out
    # The headline carries a positive signed delta.
    overall_line = next(line for line in out.splitlines() if line.startswith("Overall:"))
    assert "[+" in overall_line


def test_cli_since_json_delta_shape_and_sign(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_BASELINE)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_IMPROVED)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    delta = data["delta"]
    assert set(delta.keys()) == {"baseline_score", "score_change", "component_changes"}
    # The project strictly improved: overall delta and coverage change are > 0.
    assert delta["baseline_score"] is not None
    assert data["score"] is not None
    assert delta["score_change"] == data["score"] - delta["baseline_score"]
    assert delta["score_change"] > 0
    assert delta["component_changes"]["coverage"] == 100  # 0% -> 100%
    assert delta["component_changes"]["coverage"] > 0


def test_cli_since_json_negative_delta(tmp_path: Path, capsys) -> None:
    # Save a strong baseline, then regress: the delta is negative.
    _write_project(tmp_path, _BODY_IMPROVED)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_BASELINE)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline), "--json"])

    assert rc == 0
    delta = json.loads(capsys.readouterr().out)["delta"]
    assert delta["score_change"] < 0
    assert delta["component_changes"]["coverage"] == -100  # 100% -> 0%


def test_cli_since_conforms_to_schema(tmp_path: Path, capsys) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from isabelle_blueprint.schemas import read_schema

    _write_project(tmp_path, _BODY_BASELINE)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_IMPROVED)
    assert cli_main(["scorecard", str(tmp_path), "--since", str(baseline), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "delta" in data
    jsonschema.Draft202012Validator(json.loads(read_schema("scorecard"))).validate(data)


def test_cli_without_since_has_no_delta(tmp_path: Path, capsys) -> None:
    # The delta is strictly opt-in: no --since means no 'delta' key and the text
    # carries no 'since baseline' suffix.
    _write_project(tmp_path, _BODY)

    assert cli_main(["scorecard", str(tmp_path), "--json"]) == 0
    assert "delta" not in json.loads(capsys.readouterr().out)

    assert cli_main(["scorecard", str(tmp_path)]) == 0
    assert "since baseline" not in capsys.readouterr().out


def test_cli_since_missing_file_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["scorecard", str(tmp_path), "--since", str(tmp_path / "nope.json")])

    assert rc == 1
    err = capsys.readouterr().err
    assert "scorecard baseline not found" in err


def test_cli_since_invalid_json_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    rc = cli_main(["scorecard", str(tmp_path), "--since", str(bad)])

    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_since_composes_with_gate(tmp_path: Path, capsys) -> None:
    # --since composes with --min-grade: the gate still controls the exit code,
    # and the delta object is present alongside the gate.
    _write_project(tmp_path, _BODY_BASELINE)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_IMPROVED)
    rc = cli_main(
        ["scorecard", str(tmp_path), "--since", str(baseline), "--min-grade", "A+", "--json"]
    )

    assert rc == 5  # _BODY_IMPROVED still cannot reach A+
    data = json.loads(capsys.readouterr().out)
    assert data["gate"]["meets_min_grade"] is False
    assert data["delta"]["score_change"] > 0


def test_cli_since_markdown_records_delta(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY_BASELINE)
    baseline = _save_baseline(tmp_path, capsys)

    _write_project(tmp_path, _BODY_IMPROVED)
    rc = cli_main(
        ["scorecard", str(tmp_path), "--since", str(baseline), "--markdown"]
    )

    assert rc == 0
    text = (tmp_path / "build" / "scorecard.md").read_text(encoding="utf-8")
    assert "since baseline" in text
    assert "[+" in text


def test_since_baseline_directory_lookup(tmp_path: Path, capsys) -> None:
    # A directory path resolves to scorecard.json inside it (mirrors roadmap).
    _write_project(tmp_path, _BODY_BASELINE)
    assert cli_main(["scorecard", str(tmp_path), "--json"]) == 0
    out_dir = tmp_path / "snap"
    out_dir.mkdir()
    (out_dir / "scorecard.json").write_text(capsys.readouterr().out, encoding="utf-8")

    _write_project(tmp_path, _BODY_IMPROVED)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(out_dir), "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["delta"]["score_change"] > 0


def _corrupt_baseline(tmp_path: Path, capsys, mutate) -> Path:
    """Save a real baseline, mutate its parsed payload, and rewrite it."""

    assert cli_main(["scorecard", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    mutate(payload)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(payload), encoding="utf-8")
    return baseline


def test_cli_since_null_grade_errors(tmp_path: Path, capsys) -> None:
    # A baseline whose 'grade' is null must fail fast rather than coerce to "None".
    _write_project(tmp_path, _BODY)

    def _null_grade(payload: dict) -> None:
        payload["grade"] = None

    baseline = _corrupt_baseline(tmp_path, capsys, _null_grade)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "'grade' must be a string" in err
    assert str(baseline) in err


def test_cli_since_component_missing_score_errors(tmp_path: Path, capsys) -> None:
    # A component without a 'score' key is a malformed baseline; expect a clear error.
    _write_project(tmp_path, _BODY)

    def _drop_score(payload: dict) -> None:
        del payload["components"][0]["score"]

    baseline = _corrupt_baseline(tmp_path, capsys, _drop_score)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "weight" in err or "score" in err
    assert str(baseline) in err


def test_cli_since_component_score_out_of_range_errors(tmp_path: Path, capsys) -> None:
    # Component scores are ratios in [0, 1]; an out-of-range value is rejected.
    _write_project(tmp_path, _BODY)

    def _out_of_range(payload: dict) -> None:
        payload["components"][0]["score"] = 1.5

    baseline = _corrupt_baseline(tmp_path, capsys, _out_of_range)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "out of range" in err
    assert str(baseline) in err


def test_cli_since_schema_mismatch_names_path(tmp_path: Path, capsys) -> None:
    # The schema_version-mismatch error includes the baseline file path.
    _write_project(tmp_path, _BODY)

    def _bump_version(payload: dict) -> None:
        payload["schema_version"] = SCORECARD_SCHEMA_VERSION + 1

    baseline = _corrupt_baseline(tmp_path, capsys, _bump_version)
    rc = cli_main(["scorecard", str(tmp_path), "--since", str(baseline)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "schema_version" in err
    assert str(baseline) in err

