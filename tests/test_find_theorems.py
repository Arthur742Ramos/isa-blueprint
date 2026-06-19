"""Tests for ``search-facts --isabelle`` (Isabelle ``find_theorems``).

The mocked tests are CI-safe: they never invoke the real ``isabelle`` binary.
One gated test runs the genuine end-to-end flow and is skipped unless an
``isabelle`` executable is on PATH.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.isabelle import find_theorems as ft_module
from isabelle_blueprint.isabelle._run import RunResult
from isabelle_blueprint.isabelle.find_theorems import (
    FindTheoremsResult,
    generate_find_theorems_theory,
    normalize_query,
    parse_find_theorems_tsv,
    render_find_theorems,
    run_find_theorems,
)
from isabelle_blueprint.model.project import BlueprintProject


def _empty_project() -> BlueprintProject:
    return BlueprintProject.from_nodes("p", [])


# ---------------------------------------------------------------------------
# Pure TSV parser
# ---------------------------------------------------------------------------


def test_parse_tsv_basic() -> None:
    hits = parse_find_theorems_tsv("Nat.add_0_right\tNat\t?m + 0 = ?m\n")
    assert hits == [{"name": "Nat.add_0_right", "theory": "Nat", "prop": "?m + 0 = ?m"}]


def test_parse_tsv_multiple_rows_in_order() -> None:
    text = "A.one\tA\tp\nB.two\tB\tq\n"
    hits = parse_find_theorems_tsv(text)
    assert [h["name"] for h in hits] == ["A.one", "B.two"]
    assert hits[1] == {"name": "B.two", "theory": "B", "prop": "q"}


def test_parse_tsv_skips_blank_lines() -> None:
    hits = parse_find_theorems_tsv("\n\nX.y\tX\tz\n\n")
    assert hits == [{"name": "X.y", "theory": "X", "prop": "z"}]


def test_parse_tsv_tolerates_missing_columns() -> None:
    # No proposition column, and a name-only line.
    hits = parse_find_theorems_tsv("X.y\tX\nZ.w\n")
    assert hits == [
        {"name": "X.y", "theory": "X", "prop": ""},
        {"name": "Z.w", "theory": "", "prop": ""},
    ]


def test_parse_tsv_blank_is_empty() -> None:
    assert parse_find_theorems_tsv("") == []
    assert parse_find_theorems_tsv("   \n  \n") == []


def test_parse_tsv_drops_nameless_rows() -> None:
    assert parse_find_theorems_tsv("\tNat\tprop\n") == []


# ---------------------------------------------------------------------------
# Query normalization
# ---------------------------------------------------------------------------


def test_normalize_bare_pattern_is_quoted() -> None:
    assert normalize_query("_ + 0 = _") == '"_ + 0 = _"'


def test_normalize_named_criterion_passes_through() -> None:
    assert normalize_query("name: add_0") == "name: add_0"
    assert normalize_query("intro") == "intro"
    assert normalize_query("simp: foo") == "simp: foo"


def test_normalize_already_quoted_passes_through() -> None:
    assert normalize_query('"_ + 0 = _"') == '"_ + 0 = _"'
    assert normalize_query('name: add "_ + _"') == 'name: add "_ + _"'


def test_normalize_blank_is_blank() -> None:
    assert normalize_query("   ") == ""


# ---------------------------------------------------------------------------
# Theory generation golden assertions
# ---------------------------------------------------------------------------


def test_generate_theory_has_required_ml() -> None:
    text = generate_find_theorems_theory(
        "name: add_0", limit=20, result_file="R.tsv"
    )
    assert "theory Blueprint_Search" in text
    assert "Find_Theorems.read_query Position.none" in text
    assert "Find_Theorems.find_theorems_cmd ctxt NONE (SOME 20) true criteria" in text
    assert 'File.write (Path.explode "R.tsv")' in text
    assert "Thm_Name.print thm_name" in text
    assert "Thm.theory_name {long=false} thm" in text
    # The query is embedded as an escaped ML string literal.
    assert '"name: add_0"' in text


def test_generate_theory_escapes_query_quotes() -> None:
    """A pattern query carrying inner-syntax double quotes is escaped, not broken."""
    text = generate_find_theorems_theory(
        '"_ + 0 = _"', limit=5, result_file="R.tsv"
    )
    # The embedded SML literal escapes the inner quotes.
    assert '"\\"_ + 0 = _\\""' in text
    assert "(SOME 5)" in text


def test_generate_theory_wraps_bare_pattern() -> None:
    """A bare term query is wrapped in quotes so read_query parses it as a pattern."""
    text = generate_find_theorems_theory("_ + 0 = _", limit=20, result_file="R.tsv")
    assert 'Find_Theorems.read_query Position.none "\\"_ + 0 = _\\""' in text


def test_generate_theory_does_not_double_isabelle_symbol_backslash() -> None:
    """A query naming a symbolic operator (``\\<le>``) keeps a single backslash.

    Doubling it would survive Isabelle's symbol layer as a stray ``\\`` before the
    glyph and crash the SML lexer ("bad escape character"), breaking the build for
    every symbolic query. The literal must therefore embed ``\\<le>`` verbatim.
    """
    text = generate_find_theorems_theory("_ \\<le> _", limit=20, result_file="R.tsv")
    assert 'Find_Theorems.read_query Position.none "\\"_ \\<le> _\\""' in text
    assert "\\\\<le>" not in text


def test_generate_theory_includes_nonce_when_given() -> None:
    text = generate_find_theorems_theory(
        "x", limit=3, result_file="R.tsv", nonce="abc-123"
    )
    assert "Run nonce: abc-123" in text


def test_generate_theory_defaults_to_main_import() -> None:
    text = generate_find_theorems_theory("x", limit=3, result_file="R.tsv")
    assert '"Main"' in text


# ---------------------------------------------------------------------------
# run_find_theorems with mocked isabelle
# ---------------------------------------------------------------------------


def _fake_run_factory(tsv: str):
    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        (Path(cwd) / "Blueprint_Search.tsv").write_text(tsv, encoding="utf-8")
        return RunResult(args=cmd, returncode=0, stdout="", stderr="")

    return fake_run


def test_run_find_theorems_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(
        ft_module,
        "run_capture",
        _fake_run_factory("Nat.add_0_right\tNat\t?m + 0 = ?m\n"),
    )
    result = run_find_theorems(
        _empty_project(),
        query="_ + 0 = _",
        limit=20,
        build_dir=tmp_path,
        session_name="HOL",
    )
    assert result.ran is True
    assert result.found_count == 1
    assert result.hits[0]["name"] == "Nat.add_0_right"
    assert result.hits[0]["prop"] == "?m + 0 = ?m"
    assert result.error is None


def test_run_find_theorems_no_hits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(ft_module, "run_capture", _fake_run_factory("\n"))
    result = run_find_theorems(
        _empty_project(),
        query="nonexistent_pattern_xyz",
        limit=20,
        build_dir=tmp_path,
        session_name="HOL",
    )
    assert result.ran is True
    assert result.found_count == 0
    assert result.hits == []
    assert result.error is None


def test_run_find_theorems_build_error_sets_error(tmp_path: Path, monkeypatch) -> None:
    """A non-zero build that writes no TSV surfaces an error, not a clean miss."""
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")

    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        return RunResult(args=cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(ft_module, "run_capture", fake_run)
    result = run_find_theorems(
        _empty_project(),
        query="bad",
        limit=20,
        build_dir=tmp_path,
        session_name="HOL",
    )
    assert result.ran is True
    assert "returned 1" in (result.error or "")


def test_run_find_theorems_isabelle_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    result = run_find_theorems(
        _empty_project(),
        query="x",
        limit=20,
        build_dir=tmp_path,
        session_name="HOL",
        isabelle_executable="definitely-not-a-real-binary",
    )
    assert result.ran is False
    assert result.isabelle_available is False
    assert "not found on PATH" in (result.error or "")


def test_run_find_theorems_no_session(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    result = run_find_theorems(
        _empty_project(),
        query="x",
        limit=20,
        build_dir=tmp_path,
        session_name=None,
    )
    assert result.ran is False
    assert "No Isabelle session configured" in (result.error or "")


def test_find_theorems_result_to_dict_round_trips() -> None:
    r = FindTheoremsResult(ran=True, found_count=1, query="x", hits=[{"name": "A.b"}])
    d = r.to_dict()
    assert d["found_count"] == 1
    assert d["query"] == "x"
    assert d["hits"][0]["name"] == "A.b"
    assert "timestamp" in d


def test_render_find_theorems_human() -> None:
    r = FindTheoremsResult(
        ran=True,
        query="_ + 0 = _",
        hits=[{"name": "Nat.add_0_right", "theory": "Nat", "prop": "?m + 0 = ?m"}],
        found_count=1,
    )
    out = render_find_theorems(r)
    assert "Nat.add_0_right" in out
    assert "[Nat]" in out


def test_render_find_theorems_skipped() -> None:
    r = FindTheoremsResult(ran=False, query="x", error="Isabelle not found")
    out = render_find_theorems(r)
    assert "skipped" in out


# ---------------------------------------------------------------------------
# CLI integration (mocked isabelle)
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sf"\n\n[isabelle]\nsession = "HOL"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        "# Sf\n\n::: theorem {#t1}\ntitle: T\nisabelle: Demo.t1\n:::\n\nStmt.\n:::\n",
        encoding="utf-8",
    )


def test_cli_search_facts_isabelle_json(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(
        ft_module,
        "run_capture",
        _fake_run_factory("Nat.add_0_right\tNat\t?m + 0 = ?m\n"),
    )
    rc = cli_main(
        ["search-facts", str(tmp_path), "--isabelle", "--query", "_ + 0 = _", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ran"] is True
    assert payload["hits"][0]["name"] == "Nat.add_0_right"


def test_cli_search_facts_isabelle_human(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    monkeypatch.setattr(
        ft_module,
        "run_capture",
        _fake_run_factory("Nat.add_0_right\tNat\t?m + 0 = ?m\n"),
    )
    rc = cli_main(
        ["search-facts", str(tmp_path), "--isabelle", "--query", "_ + 0 = _"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Nat.add_0_right" in out


def test_cli_search_facts_isabelle_requires_query(tmp_path: Path) -> None:
    _write_project(tmp_path)
    rc = cli_main(["search-facts", str(tmp_path), "--isabelle"])
    assert rc == 2


def test_cli_search_facts_isabelle_unavailable_is_noop(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    rc = cli_main(
        ["search-facts", str(tmp_path), "--isabelle", "--query", "x", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ran"] is False
    assert payload["hits"] == []


def test_cli_search_facts_default_path_unchanged(tmp_path: Path, monkeypatch, capsys) -> None:
    """Without --isabelle the command never touches run_find_theorems."""
    _write_project(tmp_path)
    (tmp_path / "Demo.thy").write_text(
        "theory Demo\nimports Main\nbegin\nlemma t1: \"True\" by simp\nend\n",
        encoding="utf-8",
    )

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("run_find_theorems must not run on the default path")

    monkeypatch.setattr(ft_module, "run_find_theorems", boom)
    rc = cli_main(
        ["search-facts", str(tmp_path), "--query", "t1", "--theory", str(tmp_path / "Demo.thy")]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "t1" in out


# ---------------------------------------------------------------------------
# Real Isabelle smoke (skipped without an isabelle binary)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("isabelle") is None, reason="isabelle not on PATH")
def test_real_find_theorems_over_hol(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sf"\n\n[isabelle]\nsession = "HOL"\n', encoding="utf-8"
    )
    (tmp_path / "ROOT").write_text("", encoding="utf-8")
    (tmp_path / "blueprint.md").write_text(
        "# Sf\n\n::: theorem {#t1}\ntitle: T\n:::\n\nStmt.\n:::\n",
        encoding="utf-8",
    )

    rc = cli_main(
        ["search-facts", str(tmp_path), "--isabelle", "--query", "_ + 0 = _", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ran"] is True, payload
    assert payload["return_code"] == 0, payload
    assert payload["found_count"] >= 1, payload
    names = [h["name"] for h in payload["hits"]]
    assert any(n.endswith("add_0_right") for n in names), names
