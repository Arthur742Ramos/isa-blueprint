from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

# Node "a" has a problem formal status (broken) so --fail-on can trip on it.
_BLUEPRINT = """# fail-on-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: broken

A statement.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "fail-on-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def test_status_fail_on_problem_trips(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--fail-on", "problem"])

    assert rc == 5
    err = capsys.readouterr().err
    assert "fail-on" in err


def test_status_fail_on_specific_status(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--fail-on", "broken"])

    assert rc == 5
    capsys.readouterr()


def test_status_fail_on_unmatched_status_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--fail-on", "proved"])

    assert rc == 0
    capsys.readouterr()


def test_report_fail_on_problem_trips(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["report", str(tmp_path), "--fail-on", "problem"])

    assert rc == 5
    capsys.readouterr()


def test_status_without_fail_on_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["status", str(tmp_path)])

    assert rc == 0
    capsys.readouterr()
