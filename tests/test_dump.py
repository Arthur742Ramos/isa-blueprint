"""Tests for PIDE dump inspection."""
from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.isabelle.dump import apply_dump_report, inspect_dump_dir
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str, fact: str) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(),
    )


def _project() -> BlueprintProject:
    return BlueprintProject.from_nodes(
        "p",
        [
            _node("clean", "Demo.clean"),
            _node("tainted", "Demo.tainted"),
            _node("missing", "Demo.missing"),
        ],
    )


def test_inspect_dump_dir_marks_proved_and_tainted_facts(tmp_path: Path):
    theory_dir = tmp_path / "Demo.Demo" / "theory"
    theory_dir.mkdir(parents=True)
    theory_dir.joinpath("thms").write_text(
        "\x05\x06entity\x06name=Demo.clean\x06xname=clean\x05"
        "\x05\x06entity\x06name=Demo.tainted\x06xname=tainted\x05"
        "Pure.skip_proof",
        encoding="utf-8",
    )

    result = inspect_dump_dir(_project(), tmp_path)
    by_fact = {fact.fact: fact for fact in result.facts}
    assert by_fact["Demo.clean"].exists is True
    assert by_fact["Demo.clean"].proof_status == "proved"
    assert by_fact["Demo.tainted"].proof_status == "tainted"
    assert by_fact["Demo.tainted"].oracles == ["Pure.skip_proof"]
    assert by_fact["Demo.missing"].exists is False


def test_apply_dump_report_updates_project_status(tmp_path: Path):
    theory_dir = tmp_path / "Demo.Demo" / "theory"
    theory_dir.mkdir(parents=True)
    theory_dir.joinpath("thms").write_text(
        "\x05\x06entity\x06name=Demo.clean\x06xname=clean\x05",
        encoding="utf-8",
    )
    project = _project()
    result = inspect_dump_dir(project, tmp_path)
    apply_dump_report(project, result)
    by_id = project.by_id()
    assert by_id["clean"].status.formal == FormalStatus.PROVED
    assert by_id["missing"].status.formal == FormalStatus.NOT_FOUND
