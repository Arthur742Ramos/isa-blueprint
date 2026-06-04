from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.parser.markdown import parse_blueprint_text


def _make_session(tmp_path: Path) -> Path:
    (tmp_path / "ROOT").write_text(
        "session Demo = HOL +\n  theories\n    A\n    B\n", encoding="utf-8"
    )
    (tmp_path / "A.thy").write_text(
        "theory A\nimports Main\nbegin\n"
        'definition foo :: "nat" where "foo = 0"\n'
        'lemma base: "foo = 0" by (simp add: foo_def)\n'
        "end\n",
        encoding="utf-8",
    )
    (tmp_path / "B.thy").write_text(
        "theory B\nimports A\nbegin\n"
        'lemma uses_base: "foo = 0" using base sorry\n'
        "end\n",
        encoding="utf-8",
    )
    return tmp_path


def test_theory_index_summary(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "theories: 2" in out
    assert "entries:" in out
    assert "B: 1 entry imports A" in out


def test_theory_index_json(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert {t["name"] for t in data["theories"]} == {"A", "B"}
    assert data["has_import_cycle"] is False
    assert any(s["token"] == "sorry" for s in data["sorries"])


def test_theory_index_callers_callees(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    cli_main(["theory-index", "--root", str(root), "--callers", "base"])
    assert "B.uses_base" in capsys.readouterr().out
    cli_main(["theory-index", "--root", str(root), "--callees", "base"])
    assert "A.foo" in capsys.readouterr().out


def test_theory_index_sorry_and_deps(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    cli_main(["theory-index", "--root", str(root), "--sorry"])
    assert "sorry in uses_base" in capsys.readouterr().out
    cli_main(["theory-index", "--root", str(root), "--deps", "B"])
    out = capsys.readouterr().out
    assert "imports: A" in out


def test_theory_index_unreferenced(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    cli_main(["theory-index", "--root", str(root), "--unreferenced"])
    # uses_base is referenced by nothing -> the lone endpoint
    assert "B.uses_base" in capsys.readouterr().out


def test_import_theory_root_builds_valid_blueprint(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["import-theory", "--root", str(root), "--project-name", "Demo"])
    assert rc == 0
    text = capsys.readouterr().out
    # cross-theory dependency: B.uses_base depends on A.base
    assert "isabelle: B.uses_base" in text
    project = parse_blueprint_text(text, source="demo.md", project_name="Demo")
    report = project.validate()
    assert report.cycles == []
    assert report.missing_dependencies == []
    # the import spans both theories
    qualified = {node.isabelle.fact for node in project.nodes}
    assert "A.base" in qualified
    assert "B.uses_base" in qualified


def test_import_theory_rejects_cyclic_session(tmp_path: Path, capsys) -> None:
    (tmp_path / "ROOT").write_text(
        "session Demo = HOL +\n  theories\n    X\n    Y\n", encoding="utf-8"
    )
    (tmp_path / "X.thy").write_text(
        "theory X\nimports Y\nbegin\nlemma lx: \"True\" by simp\nend\n", encoding="utf-8"
    )
    (tmp_path / "Y.thy").write_text(
        "theory Y\nimports X\nbegin\nlemma ly: \"True\" by simp\nend\n", encoding="utf-8"
    )
    rc = cli_main(["import-theory", "--root", str(tmp_path)])
    assert rc == 1
    assert "cycle" in capsys.readouterr().err.lower()


def test_import_theory_single_file_unchanged(tmp_path: Path, capsys) -> None:
    thy = tmp_path / "Solo.thy"
    thy.write_text(
        "theory Solo imports Main begin\nlemma solo: \"True\" by simp\nend\n",
        encoding="utf-8",
    )
    rc = cli_main(["import-theory", str(thy)])
    assert rc == 0
    assert "isabelle: Solo.solo" in capsys.readouterr().out


def test_import_theory_missing_explicit_file_errors(tmp_path: Path, capsys) -> None:
    rc = cli_main(["import-theory", str(tmp_path / "Nope.thy")])
    assert rc == 1
    assert "theory file not found" in capsys.readouterr().err.lower()


def test_theory_index_unknown_session_errors(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--session", "Nope"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()
