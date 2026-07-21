from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.isabelle.suggestions import suggest_missing_facts, write_fact_suggestions
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str, fact: str, formal: FormalStatus) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(formal=formal),
    )


def test_suggest_missing_facts_uses_nearby_known_refs() -> None:
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("target", "Demo.add_commm", FormalStatus.NOT_FOUND),
            _node("known", "Demo.add_comm", FormalStatus.PROVED),
        ],
    )

    suggestions = suggest_missing_facts(project)

    assert suggestions[0].node_id == "target"
    assert "Demo.add_comm" in suggestions[0].suggestions


def test_suggest_missing_facts_reads_dump_report_candidates(tmp_path: Path) -> None:
    dump_report = tmp_path / "dump_report.json"
    dump_report.write_text(
        json.dumps({"facts": [{"fact": "Demo.mul_comm", "exists": True}]}),
        encoding="utf-8",
    )
    project = BlueprintProject.from_nodes(
        "p",
        [_node("target", "Demo.mul_com", FormalStatus.NOT_FOUND)],
    )

    suggestions = suggest_missing_facts(project, dump_report_path=dump_report)

    assert suggestions[0].suggestions == ["Demo.mul_comm"]


def test_write_fact_suggestions(tmp_path: Path) -> None:
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("target", "Demo.add_commm", FormalStatus.NOT_FOUND),
            _node("known", "Demo.add_comm", FormalStatus.PROVED),
        ],
    )
    path = write_fact_suggestions(suggest_missing_facts(project), tmp_path / "facts.json")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["suggestions"][0]["target_fact"] == "Demo.add_commm"
