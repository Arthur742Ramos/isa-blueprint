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
        'theory B\nimports A\nbegin\nlemma uses_base: "foo = 0" using base sorry\nend\n',
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


def test_theory_index_unreferenced_empty_has_no_blank_line(tmp_path: Path, capsys) -> None:
    # When every entry is referenced, the section prints only its message with
    # no trailing blank line.
    (tmp_path / "ROOT").write_text("session Demo = HOL +\n  theories\n    M\n", encoding="utf-8")
    (tmp_path / "M.thy").write_text(
        "theory M imports Main begin\n"
        'lemma alpha: "True" using beta by simp\n'
        'lemma beta: "True" using alpha by simp\n'
        "end\n",
        encoding="utf-8",
    )
    rc = cli_main(["theory-index", "--root", str(tmp_path), "--unreferenced"])
    assert rc == 0
    assert capsys.readouterr().out == "(no unreferenced entries)\n"


def test_theory_index_counts_text(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--counts"])
    assert rc == 0
    out = capsys.readouterr().out
    # two theories (A, B), three entries (foo, base, uses_base)
    assert "theories:    2" in out
    assert "entries:     3" in out
    # uses_base carries a sorry; B imports A is the single import edge
    assert "sorry/oops entries: 1" in out
    assert "import edges: 1" in out


def test_theory_index_counts_json(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--counts", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == {
        "theories": 2,
        "entries": 3,
        "sorry_entries": 1,
        "unreferenced": 1,
        "import_edges": 1,
    }


def test_theory_index_counts_dedupes_repeated_import(tmp_path: Path, capsys) -> None:
    # A theory whose imports clause repeats the same in-project dependency must
    # contribute a single import edge, not one per repetition.
    (tmp_path / "ROOT").write_text(
        "session Demo = HOL +\n  theories\n    A\n    B\n", encoding="utf-8"
    )
    (tmp_path / "A.thy").write_text(
        'theory A\nimports Main\nbegin\nlemma base: "True" by simp\nend\n',
        encoding="utf-8",
    )
    (tmp_path / "B.thy").write_text(
        'theory B\nimports A A\nbegin\nlemma uses_base: "True" using base by simp\nend\n',
        encoding="utf-8",
    )
    rc = cli_main(["theory-index", "--root", str(tmp_path), "--counts", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # B imports A twice but it is a single (B -> A) edge.
    assert data["counts"]["import_edges"] == 1


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
        'theory X\nimports Y\nbegin\nlemma lx: "True" by simp\nend\n', encoding="utf-8"
    )
    (tmp_path / "Y.thy").write_text(
        'theory Y\nimports X\nbegin\nlemma ly: "True" by simp\nend\n', encoding="utf-8"
    )
    rc = cli_main(["import-theory", "--root", str(tmp_path)])
    assert rc == 1
    assert "cycle" in capsys.readouterr().err.lower()


def test_import_theory_single_file_unchanged(tmp_path: Path, capsys) -> None:
    thy = tmp_path / "Solo.thy"
    thy.write_text(
        'theory Solo imports Main begin\nlemma solo: "True" by simp\nend\n',
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


def test_theory_index_mermaid(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--mermaid"])
    assert rc == 0
    out = capsys.readouterr().out
    # a flowchart header, a node per theory, and the A -> B import edge
    assert "flowchart" in out
    assert "A" in out
    assert "B" in out
    assert "t_A --> t_B" in out


def test_theory_index_mermaid_rejects_json(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--mermaid", "--json"])
    assert rc == 1
    assert "mutually exclusive" in capsys.readouterr().err.lower()


def test_theory_index_mermaid_rejects_mode_flags(tmp_path: Path, capsys) -> None:
    root = _make_session(tmp_path)
    rc = cli_main(["theory-index", "--root", str(root), "--mermaid", "--sorry"])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "--mermaid" in err
    assert "--sorry" in err
    assert "standalone" in err
