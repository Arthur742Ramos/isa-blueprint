from __future__ import annotations

from pathlib import Path

from isabelle_blueprint import console
from isabelle_blueprint.cli import main as cli_main


def _write_project(tmp_path: Path, body: str, *, name: str = "color-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BROKEN = """# broken

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: ghost

A statement.

Sketch.
:::
"""


def teardown_function() -> None:
    console.set_enabled(False)


def test_color_never_keeps_output_plain(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN)
    rc = cli_main(["lint", str(tmp_path), "--color", "never"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" not in out


def test_color_always_colourises_lint(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN)
    rc = cli_main(["lint", str(tmp_path), "--color", "always"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" in out


def test_no_color_flag_disables(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN)
    rc = cli_main(["lint", str(tmp_path), "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" not in out


def test_color_accepted_before_subcommand(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN)
    rc = cli_main(["--color", "always", "lint", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" in out


def test_json_output_is_never_colourised(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN)
    rc = cli_main(["lint", str(tmp_path), "--json", "--color", "always"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" not in out
