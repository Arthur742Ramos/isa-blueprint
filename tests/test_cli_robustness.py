"""Tests for parser/CLI robustness fixes.

Covers:
- malformed isabelle-blueprint.toml yielding a clean ``error:`` line (not a
  traceback) for config-only subcommands routed through ``load_config_checked``;
- ``main()`` translating BrokenPipeError/OSError into clean exits instead of
  leaking a traceback;
- ``check`` printing a one-line "building session ..." status to stderr only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.errors import BlueprintError

_BLUEPRINT = """# Demo

::: lemma {#lem-one}
title: One
:::

Body.
:::
"""

# Unterminated string -> tomllib.TOMLDecodeError (a ValueError subclass).
_BAD_TOML = '[project]\nname = "unterminated\n'


def _write_bad_config(tmp_path: Path) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text(_BAD_TOML, encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    [
        ["history"],
        ["burndown"],
        ["compat"],
    ],
)
def test_malformed_config_yields_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    _write_bad_config(tmp_path)

    rc = cli_main([*argv, str(tmp_path)])

    captured = capsys.readouterr()
    assert rc != 0
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_new_append_malformed_config_yields_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bad_config(tmp_path)

    rc = cli_main(["new", "lemma", "lem-two", str(tmp_path), "--append"])

    captured = capsys.readouterr()
    assert rc != 0
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_main_translates_oserror_to_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import isabelle_blueprint.cli as cli

    def _boom(args: object) -> int:
        raise OSError("No space left on device")

    # Hijack an existing subcommand's handler so main()'s try/except runs.
    monkeypatch.setattr(cli, "cmd_history", _boom)

    rc = cli_main(["history", "."])

    captured = capsys.readouterr()
    assert rc != 0
    assert captured.err.startswith("error: ")
    assert "No space left on device" in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_broken_pipe_cleanly() -> None:
    # main()'s BrokenPipeError handler redirects the stdout fd to devnull, which
    # would clobber pytest's captured fd in-process, so exercise it in a fresh
    # interpreter (mirroring the real `... | head` scenario).
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from isabelle_blueprint import cli\n"
        "def _broken(args):\n"
        "    raise BrokenPipeError()\n"
        "cli.cmd_history = _broken\n"
        "sys.exit(cli.main(['history', '.']))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )

    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
    assert "BrokenPipeError" not in proc.stderr


def test_main_still_reports_blueprint_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import isabelle_blueprint.cli as cli

    def _boom(args: object) -> int:
        raise BlueprintError("something went wrong")

    monkeypatch.setattr(cli, "cmd_history", _boom)

    rc = cli_main(["history", "."])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.startswith("error: something went wrong")


def test_check_prints_build_status_to_stderr_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Demo"\n\n[isabelle]\nsession = "Demo_Session"\n',
        encoding="utf-8",
    )

    cli_main(["check", str(tmp_path)])

    captured = capsys.readouterr()
    assert "building session Demo_Session with isabelle..." in captured.err
    # Status must not pollute stdout.
    assert "building session" not in captured.out
