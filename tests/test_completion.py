from __future__ import annotations

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.completion import render_completion


def test_bash_completion_lists_commands_and_registers_complete() -> None:
    script = render_completion("bash", "isabelle-blueprint", ["lint", "status"])
    assert "complete -F" in script
    assert "lint status" in script
    assert "isabelle-blueprint" in script


def test_zsh_completion_uses_compdef() -> None:
    script = render_completion("zsh", "isabelle-blueprint", ["lint"])
    assert script.startswith("#compdef isabelle-blueprint")
    assert "compdef" in script


def test_fish_completion_emits_per_command_lines() -> None:
    script = render_completion("fish", "isabelle-blueprint", ["lint", "status"])
    assert "complete -c isabelle-blueprint" in script
    assert "-a lint" in script
    assert "-a status" in script


def test_unsupported_shell_raises() -> None:
    try:
        render_completion("powershell", "isabelle-blueprint", ["lint"])
    except ValueError as exc:
        assert "powershell" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_cli_completion_includes_real_subcommands(capsys) -> None:
    rc = cli_main(["completion", "bash"])
    assert rc == 0
    out = capsys.readouterr().out
    # A few stable subcommands must appear in the generated script.
    assert "lint" in out
    assert "status" in out
    assert "completion" in out
    assert "version" in out


def test_cli_completion_rejects_unknown_shell(capsys) -> None:
    try:
        cli_main(["completion", "tcsh"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("argparse should reject an unknown shell")
