"""Tests for the real Sledgehammer-run feature and the node ``goal`` field.

The mocked tests are CI-safe: they never invoke the real ``isabelle`` binary.
One gated test runs the genuine end-to-end flow and is skipped unless an
``isabelle`` executable is on PATH.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.isabelle import sledgehammer as sh_module
from isabelle_blueprint.isabelle._run import RunResult
from isabelle_blueprint.isabelle.sledgehammer import (
    SledgehammerResult,
    extract_proof,
    parse_sledgehammer_tsv,
    run_sledgehammer,
)
from isabelle_blueprint.isabelle.theory_gen import (
    _thy_inner_string,
    generate_sledgehammer_theory,
    sledgehammer_imports,
)
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.parser.markdown import parse_blueprint_text

_BP = """# Sledge

::: definition {#base}
title: Base def
isabelle: Demo.base
status:
  blueprint: written
  formal: found
:::

Base.
:::

::: theorem {#main}
title: Main theorem
isabelle: Demo.main_thm
uses:
  - base
status:
  blueprint: written
:::

Main statement.

## Proof

By base.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sledge"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BP, encoding="utf-8")


# ---------------------------------------------------------------------------
# Static --sledgehammer appendix (unchanged behaviour, kept for regression)
# ---------------------------------------------------------------------------


def test_attempt_sledgehammer_appends_block(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["attempt", str(tmp_path), "--node", "main", "--sledgehammer", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    prompt_path = Path(payload["prompt_path"])
    text = prompt_path.read_text(encoding="utf-8")
    assert "## Sledgehammer-first strategy" in text
    # Seeded with the unqualified target fact name and the dependency fact.
    assert "lemma main_thm:" in text
    assert "sledgehammer (add: Demo.base)" in text


def test_attempt_without_sledgehammer_has_no_block(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["attempt", str(tmp_path), "--node", "main", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    text = Path(payload["prompt_path"]).read_text(encoding="utf-8")
    assert "Sledgehammer-first strategy" not in text


# ---------------------------------------------------------------------------
# Pure helpers: extract_proof / parse_sledgehammer_tsv / inner-syntax escaper
# ---------------------------------------------------------------------------


def test_extract_proof_strips_try_this_and_timing() -> None:
    assert extract_proof("Try this: by simp (0.0 ms)") == "by simp"
    assert extract_proof("Try this: by (metis foo bar) (1.2 s)") == "by (metis foo bar)"


def test_extract_proof_tolerates_missing_timing() -> None:
    assert extract_proof("Try this: by auto") == "by auto"


def test_extract_proof_without_prefix() -> None:
    assert extract_proof("by blast (3 ms)") == "by blast"
    assert extract_proof("by force") == "by force"


def test_extract_proof_empty_is_none() -> None:
    assert extract_proof("") is None
    assert extract_proof("   ") is None
    assert extract_proof(None) is None


def test_parse_tsv_success() -> None:
    found, tag, proof = parse_sledgehammer_tsv("SOME\tsome\tTry this: by simp (0.0 ms)\n")
    assert found is True
    assert tag == "some"
    assert proof == "by simp"


def test_parse_tsv_no_proof() -> None:
    found, tag, proof = parse_sledgehammer_tsv("NONE\tnone\t\n")
    assert found is False
    assert tag == "none"
    assert proof is None


def test_parse_tsv_blank() -> None:
    assert parse_sledgehammer_tsv("") == (False, None, None)


def test_thy_inner_string_escapes_backslash_and_quote() -> None:
    assert _thy_inner_string('a "b" c') == 'a \\"b\\" c'
    # An Isabelle symbol's backslash must survive doubling.
    assert _thy_inner_string("\\<forall>x. P x") == "\\\\<forall>x. P x"


# ---------------------------------------------------------------------------
# Theory generation golden assertions
# ---------------------------------------------------------------------------


def _goal_node(node_id: str, goal: str) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.THEOREM,
        title=node_id,
        goal=goal,
        status=NodeStatus(),
    )


def _fact_node(node_id: str, fact: str, *, uses=None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(),
    )


def test_generate_theory_goal_field_source() -> None:
    project = BlueprintProject.from_nodes("p", [_goal_node("g", "x + 0 = (x::nat)")])
    text = generate_sledgehammer_theory(
        project, node_id="g", result_file="R.tsv", timeout=10
    )
    assert text is not None
    assert "theory Blueprint_Sledgehammer" in text
    assert 'Syntax.read_prop ctxt "x + 0 = (x::nat)"' in text
    assert "Sledgehammer.run_sledgehammer" in text
    assert 'File.write (Path.explode "R.tsv")' in text
    assert '("timeout", "10")' in text
    # No fact reference, so only Main is imported.
    assert '"Main"' in text


def test_generate_theory_reprove_source() -> None:
    project = BlueprintProject.from_nodes("p", [_fact_node("f", "Demo.thm")])
    text = generate_sledgehammer_theory(
        project, node_id="f", result_file="R.tsv", timeout=5
    )
    assert text is not None
    assert 'Proof_Context.get_thm ctxt "Demo.thm"' in text
    assert "Syntax.read_prop" not in text
    assert '"Demo"' in text  # the node's theory is imported


def test_generate_theory_imports_dependency_theories() -> None:
    project = BlueprintProject.from_nodes(
        "p",
        [
            _fact_node("base", "Base.b"),
            _fact_node("main", "Main_T.m", uses=["base"]),
        ],
    )
    imports = sledgehammer_imports(project, node_id="main")
    assert "Main" in imports
    assert "Main_T" in imports
    assert "Base" in imports


def test_generate_theory_none_when_no_goal_or_fact() -> None:
    node = BlueprintNode(id="empty", kind=NodeKind.NOTE, title="empty", status=NodeStatus())
    project = BlueprintProject.from_nodes("p", [node])
    assert (
        generate_sledgehammer_theory(project, node_id="empty", result_file="R.tsv", timeout=1)
        is None
    )


def test_generate_theory_includes_nonce_when_given() -> None:
    project = BlueprintProject.from_nodes("p", [_goal_node("g", "True")])
    text = generate_sledgehammer_theory(
        project, node_id="g", result_file="R.tsv", timeout=1, nonce="abc-123"
    )
    assert text is not None
    assert "Run nonce: abc-123" in text


# ---------------------------------------------------------------------------
# run_sledgehammer with mocked isabelle
# ---------------------------------------------------------------------------


def _goal_project() -> BlueprintProject:
    return BlueprintProject.from_nodes("p", [_goal_node("g", "x + 0 = (x::nat)")])


def _fake_run_factory(tsv: str):
    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        (Path(cwd) / "Blueprint_Sledgehammer.tsv").write_text(tsv, encoding="utf-8")
        return RunResult(args=cmd, returncode=0, stdout="", stderr="")

    return fake_run


def test_run_sledgehammer_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(
        sh_module, "run_capture", _fake_run_factory("SOME\tsome\tTry this: by simp (0.0 ms)\n")
    )
    result = run_sledgehammer(
        _goal_project(), node_id="g", build_dir=tmp_path, session_name="HOL"
    )
    assert result.ran is True
    assert result.found is True
    assert result.proof_line == "by simp"
    assert result.outcome_tag == "some"
    assert result.error is None


def test_run_sledgehammer_no_proof(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(sh_module, "run_capture", _fake_run_factory("NONE\tnone\t\n"))
    result = run_sledgehammer(
        _goal_project(), node_id="g", build_dir=tmp_path, session_name="HOL"
    )
    assert result.ran is True
    assert result.found is False
    assert result.proof_line is None


def test_run_sledgehammer_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")

    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(sh_module, "run_capture", fake_run)
    result = run_sledgehammer(
        _goal_project(), node_id="g", build_dir=tmp_path, session_name="HOL", timeout=5
    )
    assert result.ran is False
    assert result.found is False
    assert "timed out" in (result.error or "").lower()


def test_run_sledgehammer_isabelle_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    result = run_sledgehammer(
        _goal_project(),
        node_id="g",
        build_dir=tmp_path,
        session_name="HOL",
        isabelle_executable="definitely-not-a-real-binary",
    )
    assert result.ran is False
    assert result.isabelle_available is False
    assert "not found on PATH" in (result.error or "")


def test_run_sledgehammer_no_goal_or_fact_does_not_build(tmp_path: Path, monkeypatch) -> None:
    called = {"n": 0}

    def fake_run(*a, **k):  # pragma: no cover - must never run
        called["n"] += 1
        return RunResult(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(sh_module, "run_capture", fake_run)
    node = BlueprintNode(id="e", kind=NodeKind.NOTE, title="e", status=NodeStatus())
    project = BlueprintProject.from_nodes("p", [node])
    result = run_sledgehammer(project, node_id="e", build_dir=tmp_path, session_name="HOL")
    assert result.ran is False
    assert called["n"] == 0
    assert "neither" in (result.error or "")


def test_sledgehammer_result_to_dict_round_trips() -> None:
    r = SledgehammerResult(ran=True, found=True, proof_line="by simp", node_id="g")
    d = r.to_dict()
    assert d["found"] is True
    assert d["proof_line"] == "by simp"
    assert d["node_id"] == "g"
    assert "timestamp" in d


# ---------------------------------------------------------------------------
# CLI integration (mocked isabelle) + memory recording
# ---------------------------------------------------------------------------


def _write_goal_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sh"\n\n[isabelle]\nsession = "HOL"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        "# Sh\n\n::: theorem {#t1}\ntitle: T\ngoal: x + 0 = (x::nat)\n:::\n\nStmt.\n:::\n",
        encoding="utf-8",
    )


def test_cli_sledgehammer_run_records_success(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_goal_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(
        sh_module, "run_capture", _fake_run_factory("SOME\tsome\tTry this: by simp (0.0 ms)\n")
    )

    rc = cli_main(["attempt", str(tmp_path), "--node", "t1", "--sledgehammer-run", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    sh = payload["sledgehammer"]
    assert sh["found"] is True
    assert sh["proof_line"] == "by simp"
    assert sh["summary_line"] == "sledgehammer: found  by simp"

    memory = json.loads(
        (tmp_path / ".isabelle-blueprint" / "agent-memory.json").read_text(encoding="utf-8")
    )
    attempts = memory["nodes"]["t1"]["attempts"]
    assert attempts[-1]["tool"] == "sledgehammer"
    assert attempts[-1]["outcome"] == "succeeded"
    assert attempts[-1]["details"] == "by simp"
    assert attempts[-1]["input_hash"]


def test_cli_sledgehammer_run_skipped_when_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_goal_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: None)

    rc = cli_main(["attempt", str(tmp_path), "--node", "t1", "--sledgehammer-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sledgehammer: skipped (Isabelle unavailable)" in out

    memory = json.loads(
        (tmp_path / ".isabelle-blueprint" / "agent-memory.json").read_text(encoding="utf-8")
    )
    assert memory["nodes"]["t1"]["attempts"][-1]["outcome"] == "blocked"


# ---------------------------------------------------------------------------
# Model / parser / schema: the new goal field
# ---------------------------------------------------------------------------


def test_parser_reads_goal_metadata() -> None:
    project = parse_blueprint_text(
        "# P\n\n::: theorem {#t}\ntitle: T\ngoal: x + 0 = (x::nat)\n:::\n\nStmt.\n:::\n"
    )
    node = project.by_id()["t"]
    assert node.goal == "x + 0 = (x::nat)"
    assert node.to_dict()["goal"] == "x + 0 = (x::nat)"


def test_parser_goal_absent_is_none() -> None:
    project = parse_blueprint_text("# P\n\n::: theorem {#t}\ntitle: T\n:::\n\nStmt.\n:::\n")
    node = project.by_id()["t"]
    assert node.goal is None
    assert node.to_dict()["goal"] is None


def test_node_goal_default_backward_compatible() -> None:
    node = BlueprintNode(id="x", kind=NodeKind.LEMMA, title="x")
    assert node.goal is None
    assert "goal" in node.to_dict()


def test_project_json_with_goal_validates_against_schema() -> None:
    import pytest

    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator

    from isabelle_blueprint.schemas import read_schema

    schema = json.loads(read_schema("project"))
    project = BlueprintProject.from_nodes("p", [_goal_node("g", "True")])
    Draft202012Validator(schema).validate(project.to_dict())


# ---------------------------------------------------------------------------
# Real Isabelle smoke (skipped without an isabelle binary)
# ---------------------------------------------------------------------------


def test_real_sledgehammer_run_finds_proof(tmp_path: Path, capsys) -> None:
    import pytest

    if shutil.which("isabelle") is None:
        pytest.skip("isabelle not on PATH")

    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sh"\n\n[isabelle]\nsession = "HOL"\n', encoding="utf-8"
    )
    # ``isabelle build -d <project_root>`` needs a valid (possibly empty) ROOT.
    (tmp_path / "ROOT").write_text("", encoding="utf-8")
    (tmp_path / "blueprint.md").write_text(
        "# Sh\n\n::: theorem {#t1}\ntitle: T\ngoal: x + 0 = (x::nat)\n:::\n\nStmt.\n:::\n",
        encoding="utf-8",
    )

    rc = cli_main(["attempt", str(tmp_path), "--node", "t1", "--sledgehammer-run", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    sh = payload["sledgehammer"]
    assert sh["found"] is True, sh
    assert sh["proof_line"].startswith("by")
