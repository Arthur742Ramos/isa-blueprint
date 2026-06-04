from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.isabelle.root import (
    ROOT_ENV_VAR,
    default_session_dir,
    discover_roots,
    iter_sessions,
    iter_thy_files,
    parse_root_directories,
    parse_root_sessions,
    parse_root_theories,
    parse_thy_imports,
    resolve_session_theory,
    resolve_thy_file,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_root_theories_basic(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        "session Demo = HOL +\n  theories\n    Alpha\n    Beta\n    Gamma\n",
    )
    assert parse_root_theories(root) == ["Alpha", "Beta", "Gamma"]


def test_parse_root_theories_stops_at_next_block(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        "session Demo = HOL +\n"
        "  theories\n    Alpha\n    Beta\n"
        "  document_files\n    root.tex\n",
    )
    assert parse_root_theories(root) == ["Alpha", "Beta"]


def test_parse_root_directories(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        'session Demo = HOL +\n  directories "src" "proofs"\n  theories\n    Alpha\n',
    )
    assert parse_root_directories(root) == ["src", "proofs"]


def test_parse_thy_imports_plain_and_quoted(tmp_path: Path) -> None:
    thy = _write(
        tmp_path / "A.thy",
        'theory A\nimports Main "HOL-Library.FuncSet" B\nbegin\nend\n',
    )
    assert parse_thy_imports(thy) == ["Main", "HOL-Library.FuncSet", "B"]


def test_parse_thy_imports_missing_clause(tmp_path: Path) -> None:
    thy = _write(tmp_path / "A.thy", "theory A\nbegin\nend\n")
    assert parse_thy_imports(thy) == []


def test_parse_thy_imports_long_header_before_clause(tmp_path: Path) -> None:
    # A licence/header comment longer than the old 50-line cap must not hide
    # the real imports clause.
    header = "(*\n" + "\n".join(f" * licence line {i}" for i in range(80)) + "\n*)\n"
    thy = _write(
        tmp_path / "A.thy",
        header + 'theory A\nimports Main "HOL-Library.FuncSet" B\nbegin\nend\n',
    )
    assert parse_thy_imports(thy) == ["Main", "HOL-Library.FuncSet", "B"]


def test_parse_thy_imports_ignores_commented_clause(tmp_path: Path) -> None:
    # A commented-out imports clause must not inject phantom imports; the real
    # clause that follows wins.
    thy = _write(
        tmp_path / "A.thy",
        "(* imports Ghost begin *)\ntheory A\nimports Main B\nbegin\nend\n",
    )
    assert parse_thy_imports(thy) == ["Main", "B"]


def test_resolve_thy_file_searches_directories(tmp_path: Path) -> None:
    _write(
        tmp_path / "ROOT",
        'session Demo = HOL +\n  directories "src"\n  theories\n    Alpha\n',
    )
    (tmp_path / "src").mkdir()
    target = _write(tmp_path / "src" / "Alpha.thy", "theory Alpha\nbegin\nend\n")
    assert resolve_thy_file("Alpha", t_dir=tmp_path) == target
    assert resolve_thy_file("Missing", t_dir=tmp_path) is None


def test_iter_thy_files_single_root_order(tmp_path: Path) -> None:
    _write(tmp_path / "ROOT", "session Demo = HOL +\n  theories\n    Beta\n    Alpha\n")
    _write(tmp_path / "Alpha.thy", "theory Alpha\nbegin\nend\n")
    _write(tmp_path / "Beta.thy", "theory Beta\nbegin\nend\n")
    files = iter_thy_files(tmp_path)
    assert [p.name for p in files] == ["Beta.thy", "Alpha.thy"]


def test_parse_root_sessions_multi_session_parent_and_subdir(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        "session Base = HOL +\n"
        "  theories\n    Core\n"
        "\n"
        "session Ext = Base +\n"
        "  description {* a legacy description *}\n"
        "  options [document = false]\n"
        "  sessions\n    Base\n"
        "  directories \"lib\"\n"
        "  theories\n    Tools\n    Helpers in \"lib\"\n",
    )
    sessions = parse_root_sessions(root)
    names = [s.name for s in sessions]
    assert names == ["Base", "Ext"]

    ext = sessions[1]
    assert ext.parent == "Base"
    assert ext.used_sessions == ["Base"]
    assert ext.directories == ["lib"]
    assert ext.theories == [("Tools", None), ("Helpers", "lib")]


def test_parse_root_sessions_session_in_subdir(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        'session Demo in "sub" = HOL +\n  theories\n    Alpha\n',
    )
    (session,) = parse_root_sessions(root)
    assert session.in_subdir == "sub"
    assert session.session_dir == tmp_path / "sub"


def test_parse_root_sessions_ignores_comments_and_cartouches(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        "session Demo = HOL +\n"
        "  (* session Fake = HOL + theories Nope *)\n"
        "  description \\<open>cartouche text\\<close>\n"
        "  theories\n    Real\n",
    )
    (session,) = parse_root_sessions(root)
    assert session.name == "Demo"
    assert session.theories == [("Real", None)]


def test_resolve_session_theory_with_dir_override(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "ROOT",
        'session Demo = HOL +\n  theories\n    Helpers in "lib"\n',
    )
    (tmp_path / "lib").mkdir()
    target = _write(tmp_path / "lib" / "Helpers.thy", "theory Helpers\nbegin\nend\n")
    (session,) = parse_root_sessions(root)
    assert resolve_session_theory(session, session.theories[0]) == target


def test_discover_and_iter_sessions_multi_root(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _write(tmp_path / "a" / "ROOT", "session A = HOL +\n  theories\n    Alpha\n")
    _write(tmp_path / "b" / "ROOT", "session B = HOL +\n  theories\n    Beta\n")
    _write(tmp_path / "a" / "Alpha.thy", "theory Alpha\nbegin\nend\n")
    _write(tmp_path / "b" / "Beta.thy", "theory Beta\nbegin\nend\n")

    roots = discover_roots(tmp_path)
    assert len(roots) == 2
    sessions = iter_sessions(tmp_path)
    assert sorted(s.name for s in sessions) == ["A", "B"]
    files = iter_thy_files(tmp_path)
    assert sorted(p.name for p in files) == ["Alpha.thy", "Beta.thy"]


def test_default_session_dir_prefers_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path))
    assert default_session_dir() == tmp_path.resolve()


def test_default_session_dir_finds_nearest_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    _write(tmp_path / "ROOT", "session Demo = HOL +\n  theories\n    Alpha\n")
    nested = tmp_path / "deep" / "deeper"
    nested.mkdir(parents=True)
    assert default_session_dir(nested) == tmp_path.resolve()
