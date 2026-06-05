from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.explain import explain_project, render_explanations
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

_BLUEPRINT = """# explain-cli

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: [missing]

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "explain-cli"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _node(node_id: str, formal: FormalStatus, *, uses=None, error=None):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal, check_error=error),
    )


def test_explain_not_found_suggests_spelling():
    project = BlueprintProject.from_nodes("p", [_node("a", FormalStatus.NOT_FOUND)])

    explanation = explain_project(project)[0]

    assert explanation.severity == "error"
    assert "not found" in explanation.summary.lower()
    assert explanation.next_steps


def test_explain_missing_dependency():
    project = BlueprintProject.from_nodes("p", [_node("a", FormalStatus.NAMED, uses=["missing"])])

    explanation = explain_project(project)[0]

    assert any("undefined dependencies" in reason for reason in explanation.reasons)


def test_explain_unknown_node():
    project = BlueprintProject.from_nodes("p", [])

    explanation = explain_project(project, node_id="nope")[0]

    assert explanation.node_id == "nope"
    assert explanation.severity == "error"


def test_render_explanations_is_human_readable():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", FormalStatus.TAINTED, error="uses sorry")]
    )

    text = render_explanations(explain_project(project))

    assert "a:" in text
    assert "uses sorry" in text


def test_cli_explain_json_emits_explanations_list(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["explain", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data["explanations"], list)
    # The single node has an undefined dependency, so it is explained.
    assert any(item["node_id"] == "a" for item in data["explanations"])


def test_cli_explain_text_mode_is_human_readable(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["explain", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "a:" in out


def test_cli_explain_single_node_selector(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["explain", str(tmp_path), "--node", "a", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [item["node_id"] for item in data["explanations"]] == ["a"]
