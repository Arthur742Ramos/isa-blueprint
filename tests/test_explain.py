from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.explain import (
    explain_project,
    render_explanations,
    render_explanations_markdown,
)
from isabelle_blueprint.isabelle.suggestions import FactSuggestion
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


def test_explain_covers_every_formal_status_branch():
    cases = {
        FormalStatus.MISSING: ("info", "No formal target"),
        FormalStatus.NAMED: ("warning", "named but unchecked"),
        FormalStatus.FOUND: ("ok", "proof trust"),
        FormalStatus.PROVED: ("ok", "proved"),
        FormalStatus.STALE: ("warning", "stale"),
        FormalStatus.BROKEN: ("error", "failed"),
    }
    for status, (severity, needle) in cases.items():
        node = _node("n", status)
        if status == FormalStatus.MISSING:
            node.isabelle = IsabelleRef()  # no fact -> genuinely missing
        explanation = explain_project(BlueprintProject.from_nodes("p", [node]))[0]
        assert explanation.severity == severity, status
        assert needle.lower() in explanation.summary.lower(), status


def test_explain_broken_uses_check_error_when_present():
    node = _node("n", FormalStatus.BROKEN, error="theorem foo failed")
    explanation = explain_project(BlueprintProject.from_nodes("p", [node]))[0]
    assert any("theorem foo failed" in reason for reason in explanation.reasons)


def test_explain_reports_dependency_cycle():
    a = _node("a", FormalStatus.NAMED, uses=["b"])
    b = _node("b", FormalStatus.NAMED, uses=["a"])
    project = BlueprintProject.from_nodes("p", [a, b])

    explanations = explain_project(project)

    assert any(
        any("cycle" in reason.lower() for reason in e.reasons) for e in explanations
    )


def test_explain_not_found_includes_fact_suggestions():
    node = _node("a", FormalStatus.NOT_FOUND)
    project = BlueprintProject.from_nodes("p", [node])
    suggestions = [
        FactSuggestion(node_id="a", target_fact="Demo.a", suggestions=["Demo.alpha"])
    ]

    explanation = explain_project(project, fact_suggestions=suggestions)[0]

    assert any("Demo.alpha" in s for s in explanation.suggestions)


def test_explain_taint_provenance_points_at_upstream():
    base = _node("base", FormalStatus.TAINTED)
    top = _node("top", FormalStatus.TAINTED, uses=["base"])
    project = BlueprintProject.from_nodes("p", [base, top])

    by_id = {e.node_id: e for e in explain_project(project)}

    assert any(
        "undermined by upstream" in r and "`base`" in r for r in by_id["top"].reasons
    )
    assert any("tainted/broken upstream" in s for s in by_id["top"].next_steps)


def test_explain_found_lists_unproved_dependencies():
    dep = _node("dep", FormalStatus.NAMED)
    node = _node("n", FormalStatus.FOUND, uses=["dep"])
    project = BlueprintProject.from_nodes("p", [dep, node])

    explanation = {e.node_id: e for e in explain_project(project)}["n"]

    assert any("not proved yet" in r and "`dep`" in r for r in explanation.reasons)


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


def test_render_explanations_markdown_has_heading_and_status():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", FormalStatus.NAMED, uses=["dep"])]
    )

    md = render_explanations_markdown(explain_project(project), project)

    assert "# a:" in md
    assert "- Formal: `named`" in md
    assert "- Blueprint:" in md
    assert "- `dep`" in md


def test_cli_explain_markdown_emits_document(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["explain", str(tmp_path), "--node", "a", "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# a:")
    assert "## Status" in out
    assert "- Formal: `" in out


def test_cli_explain_markdown_and_json_are_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)

    with pytest.raises(SystemExit):
        cli_main(["explain", str(tmp_path), "--markdown", "--json"])
