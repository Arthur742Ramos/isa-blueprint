from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report.scorecard import (
    SCORECARD_SCHEMA_VERSION,
    build_scorecard,
    grade_for,
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
uses: a

Depends on a.

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
