"""Tests for the ``reconcile`` / ``deps-audit`` dependency-audit feature.

The mocked tests are CI-safe: they never invoke the real ``isabelle`` binary --
a fake ``run_capture`` writes the expected deps TSV into the build directory.
One gated test runs the genuine end-to-end flow against a tiny custom session
and is skipped unless an ``isabelle`` executable is on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.isabelle import reconcile as rec_module
from isabelle_blueprint.isabelle._run import RunResult
from isabelle_blueprint.isabelle.reconcile import (
    ReconcileResult,
    parse_deps_tsv,
    reconcile_diff,
    reconcile_payload,
    run_reconcile,
)
from isabelle_blueprint.isabelle.reconcile_theory import (
    DEPS_MARKER,
    generate_reconcile_theory,
)
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject


def _fact_node(node_id: str, fact: str, *, uses=None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(),
    )


def _project() -> BlueprintProject:
    return BlueprintProject.from_nodes(
        "p",
        [
            _fact_node("a", "Demo.lemma_A"),
            _fact_node("c", "Demo.lemma_C"),
            _fact_node("b", "Demo.lemma_B", uses=["a", "c"]),
        ],
    )


# ---------------------------------------------------------------------------
# parse_deps_tsv
# ---------------------------------------------------------------------------


def test_parse_deps_tsv_basic() -> None:
    text = f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A,Demo.lemma_X\n"
    assert parse_deps_tsv(text) == {"b": ["Demo.lemma_A", "Demo.lemma_X"]}


def test_parse_deps_tsv_empty_deps_column() -> None:
    text = f"{DEPS_MARKER}\ta\tDemo.lemma_A\t\n"
    assert parse_deps_tsv(text) == {"a": []}


def test_parse_deps_tsv_dash_is_empty() -> None:
    text = f"{DEPS_MARKER}\ta\tDemo.lemma_A\t-\n"
    assert parse_deps_tsv(text) == {"a": []}


def test_parse_deps_tsv_ignores_noise_lines() -> None:
    text = f"Building Demo ...\n{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A\nFinished.\n"
    assert parse_deps_tsv(text) == {"b": ["Demo.lemma_A"]}


def test_parse_deps_tsv_blank() -> None:
    assert parse_deps_tsv("") == {}


def test_parse_deps_tsv_last_wins() -> None:
    text = (
        f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A\n"
        f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_C\n"
    )
    assert parse_deps_tsv(text) == {"b": ["Demo.lemma_C"]}


# ---------------------------------------------------------------------------
# reconcile_diff (pure)
# ---------------------------------------------------------------------------


def test_reconcile_diff_undeclared_and_unused() -> None:
    project = _project()
    # b really depends on lemma_A (declared) but NOT on lemma_C (declared -> unused).
    deps = {"b": ["Demo.lemma_A"]}
    diffs = reconcile_diff(project, deps)
    assert len(diffs) == 1
    d = diffs[0]
    assert d.node_id == "b"
    assert d.actual_dep_node_ids == ["a"]
    assert d.declared_dep_node_ids == ["a", "c"]
    assert d.used_but_undeclared == []
    assert d.declared_but_unused == ["c"]


def test_reconcile_diff_used_but_undeclared() -> None:
    # b declares only c, but really uses a -> a is a STRONG missing edge.
    project = BlueprintProject.from_nodes(
        "p",
        [
            _fact_node("a", "Demo.lemma_A"),
            _fact_node("c", "Demo.lemma_C"),
            _fact_node("b", "Demo.lemma_B", uses=["c"]),
        ],
    )
    diffs = reconcile_diff(project, {"b": ["Demo.lemma_A"]})
    d = diffs[0]
    assert d.used_but_undeclared == ["a"]
    assert d.declared_but_unused == ["c"]


def test_reconcile_diff_self_dep_dropped() -> None:
    project = BlueprintProject.from_nodes("p", [_fact_node("a", "Demo.lemma_A")])
    # A proof reporting itself as a dep must not become an actual edge.
    diffs = reconcile_diff(project, {"a": ["Demo.lemma_A"]})
    assert diffs[0].actual_dep_node_ids == []


def test_reconcile_diff_unknown_fact_dep_ignored() -> None:
    project = _project()
    # A dep fact that is not mapped to any blueprint node is dropped.
    diffs = reconcile_diff(project, {"b": ["Demo.lemma_A", "Pure.protectI"]})
    d = next(x for x in diffs if x.node_id == "b")
    assert d.actual_dep_node_ids == ["a"]


def test_reconcile_diff_clean_match() -> None:
    project = BlueprintProject.from_nodes(
        "p",
        [
            _fact_node("a", "Demo.lemma_A"),
            _fact_node("b", "Demo.lemma_B", uses=["a"]),
        ],
    )
    diffs = reconcile_diff(project, {"b": ["Demo.lemma_A"]})
    d = diffs[0]
    assert d.used_but_undeclared == []
    assert d.declared_but_unused == []


# ---------------------------------------------------------------------------
# reconcile_payload
# ---------------------------------------------------------------------------


def test_reconcile_payload_shape() -> None:
    project = _project()
    result = ReconcileResult(ran=True, isabelle_available=True, return_code=0)
    result.deps = {"b": ["Demo.lemma_A"], "a": [], "c": []}
    payload = reconcile_payload(project, result)
    assert payload["schema"] == "reconcile"
    assert payload["ran"] is True
    assert payload["summary"]["nodes_analyzed"] == 3
    assert payload["summary"]["nodes_with_unused"] == 1
    assert payload["summary"]["total_unused_edges"] == 1
    assert payload["summary"]["nodes_with_undeclared"] == 0
    b = next(n for n in payload["nodes"] if n["node_id"] == "b")
    assert b["declared_but_unused"] == ["c"]


# ---------------------------------------------------------------------------
# Theory generation
# ---------------------------------------------------------------------------


def test_generate_reconcile_theory_basic() -> None:
    text = generate_reconcile_theory(_project(), deps_file="R.tsv", default_import_session="Demo")
    assert text is not None
    assert "theory Blueprint_Deps" in text
    assert "Thm_Deps.thm_deps thy" in text
    assert "Symset.make" in text
    assert 'File.write (Path.explode "R.tsv")' in text
    # Every blueprint fact appears in the known-set / rows.
    assert '"Demo.lemma_A"' in text
    assert '"Demo.lemma_B"' in text
    assert '"Demo.lemma_C"' in text
    # Session-qualified import of the node theory.
    assert '"Demo.Demo"' in text
    assert DEPS_MARKER in text


def test_generate_reconcile_theory_none_without_facts() -> None:
    node = BlueprintNode(id="n", kind=NodeKind.NOTE, title="n", status=NodeStatus())
    project = BlueprintProject.from_nodes("p", [node])
    assert generate_reconcile_theory(project, deps_file="R.tsv") is None


def test_generate_reconcile_theory_includes_nonce() -> None:
    text = generate_reconcile_theory(
        _project(), deps_file="R.tsv", default_import_session="Demo", nonce="xyz-1"
    )
    assert text is not None
    assert "Run nonce: xyz-1" in text


# ---------------------------------------------------------------------------
# run_reconcile with mocked isabelle
# ---------------------------------------------------------------------------


def _fake_run_factory(tsv: str):
    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        (Path(cwd) / "Blueprint_Deps.tsv").write_text(tsv, encoding="utf-8")
        return RunResult(args=cmd, returncode=0, stdout="", stderr="")

    return fake_run


def test_run_reconcile_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    tsv = (
        f"{DEPS_MARKER}\ta\tDemo.lemma_A\t\n"
        f"{DEPS_MARKER}\tc\tDemo.lemma_C\t\n"
        f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A\n"
    )
    monkeypatch.setattr(rec_module, "run_capture", _fake_run_factory(tsv))
    result = run_reconcile(_project(), build_dir=tmp_path, session_name="Demo")
    assert result.ran is True
    assert result.return_code == 0
    assert result.deps["b"] == ["Demo.lemma_A"]
    diffs = reconcile_diff(_project(), result.deps)
    b = next(d for d in diffs if d.node_id == "b")
    assert b.declared_but_unused == ["c"]


def test_run_reconcile_isabelle_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    result = run_reconcile(
        _project(),
        build_dir=tmp_path,
        session_name="Demo",
        isabelle_executable="definitely-not-a-real-binary",
    )
    assert result.ran is False
    assert result.isabelle_available is False
    assert "not found on PATH" in (result.error or "")


def test_run_reconcile_no_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    result = run_reconcile(_project(), build_dir=tmp_path, session_name=None)
    assert result.ran is False
    assert "No Isabelle session" in (result.error or "")


def test_run_reconcile_no_eligible_nodes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    node = BlueprintNode(id="n", kind=NodeKind.NOTE, title="n", status=NodeStatus())
    project = BlueprintProject.from_nodes("p", [node])
    result = run_reconcile(project, build_dir=tmp_path, session_name="Demo")
    assert result.ran is False
    assert "no PROVED-eligible nodes" in (result.error or "")


def test_run_reconcile_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")

    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(rec_module, "run_capture", fake_run)
    result = run_reconcile(_project(), build_dir=tmp_path, session_name="Demo", timeout=5)
    assert result.ran is False
    assert "timed out" in (result.error or "").lower()


def test_run_reconcile_build_failure_no_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")

    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        return RunResult(args=cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(rec_module, "run_capture", fake_run)
    result = run_reconcile(_project(), build_dir=tmp_path, session_name="Demo")
    assert result.ran is True
    assert "without writing a deps file" in (result.error or "")


def test_reconcile_result_to_dict_round_trips() -> None:
    r = ReconcileResult(ran=True, return_code=0)
    r.deps = {"b": ["Demo.lemma_A"]}
    d = r.to_dict()
    assert d["ran"] is True
    assert d["deps"] == {"b": ["Demo.lemma_A"]}
    assert "timestamp" in d


# ---------------------------------------------------------------------------
# CLI integration (mocked isabelle)
# ---------------------------------------------------------------------------

_BP = """# Demo

::: lemma {#a}
title: A
isabelle: Demo.lemma_A
:::

A.
:::

::: lemma {#c}
title: C
isabelle: Demo.lemma_C
:::

C.
:::

::: lemma {#b}
title: B
isabelle: Demo.lemma_B
uses:
  - a
  - c
:::

B.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Demo"\n\n[isabelle]\nsession = "Demo"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BP, encoding="utf-8")


def test_cli_reconcile_json(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    tsv = f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A\n"
    monkeypatch.setattr(rec_module, "run_capture", _fake_run_factory(tsv))

    rc = cli_main(["reconcile", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "reconcile"
    b = next(n for n in payload["nodes"] if n["node_id"] == "b")
    assert b["declared_but_unused"] == ["c"]
    assert b["actual_dep_node_ids"] == ["a"]


def test_cli_reconcile_human_flags_unused(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    tsv = f"{DEPS_MARKER}\tb\tDemo.lemma_B\tDemo.lemma_A\n"
    monkeypatch.setattr(rec_module, "run_capture", _fake_run_factory(tsv))

    rc = cli_main(["reconcile", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "declared-but-unused (advisory): c" in out


def test_cli_deps_audit_alias_skips_when_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: None)

    rc = cli_main(["deps-audit", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "reconcile: skipped" in out


# ---------------------------------------------------------------------------
# Real Isabelle smoke (skipped without an isabelle binary)
# ---------------------------------------------------------------------------

_DEMO_THY = """theory Demo
  imports Main
begin

lemma lemma_A: "True"
  by simp

lemma lemma_C: "True"
  by simp

lemma lemma_B: "True"
  by (rule lemma_A)

end
"""


@pytest.mark.skipif(shutil.which("isabelle") is None, reason="isabelle not on PATH")
def test_real_reconcile_sees_real_dep(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Demo"\n\n[isabelle]\nsession = "Demo"\n', encoding="utf-8"
    )
    (tmp_path / "ROOT").write_text(
        'session "Demo" = HOL +\n  theories\n    Demo\n', encoding="utf-8"
    )
    (tmp_path / "Demo.thy").write_text(_DEMO_THY, encoding="utf-8")
    (tmp_path / "blueprint.md").write_text(_BP, encoding="utf-8")

    rc = cli_main(["reconcile", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ran"] is True, payload
    assert payload["return_code"] == 0, payload
    b = next(n for n in payload["nodes"] if n["node_id"] == "b")
    # The kernel really records lemma_A among lemma_B's immediate deps.
    assert "a" in b["actual_dep_node_ids"], b
    # The deliberately-declared spurious 'uses: c' edge surfaces as advisory-unused.
    assert "c" in b["declared_but_unused"], b
