"""Tests for the ``agent-run`` execution harness."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from isabelle_blueprint.agents.runner import (
    CommandResult,
    classify_run_outcome,
    default_run_summary,
    execute_agent_command,
    safe_prompt_filename,
    split_command_string,
    substitute_command,
    tail,
    validate_command_tokens,
)
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.isabelle._run import OutputLimitExceeded, RunResult, run_capture

_BLUEPRINT = """# agent-run-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "agent-run-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _memory(tmp_path: Path) -> dict:
    path = tmp_path / ".isabelle-blueprint" / "agent-memory.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Pure helpers


def test_substitute_command_keeps_values_with_spaces_as_one_token() -> None:
    argv = substitute_command(
        ["solver", "{prompt_file}", "{node_id}"],
        {"prompt_file": "C:\\a b\\p.md", "node_id": "node x"},
    )
    assert argv == ["solver", "C:\\a b\\p.md", "node x"]


def test_validate_command_tokens_rejects_unknown_placeholder() -> None:
    with pytest.raises(BlueprintError, match="unknown command placeholder"):
        validate_command_tokens(["solver", "{bogus}", "{prompt_file}"])


def test_validate_command_tokens_requires_prompt_placeholder() -> None:
    with pytest.raises(BlueprintError, match="prompt_file"):
        validate_command_tokens(["solver", "--quiet"])
    # ...unless explicitly allowed.
    validate_command_tokens(["solver", "--quiet"], require_prompt=False)


def test_split_command_string_rejects_empty() -> None:
    with pytest.raises(BlueprintError):
        split_command_string("   ")
    assert split_command_string("solver --in {prompt_file}") == [
        "solver",
        "--in",
        "{prompt_file}",
    ]


def test_safe_prompt_filename_sanitizes_unsafe_ids() -> None:
    name = safe_prompt_filename("../weird/id:name")
    assert "/" not in name and "\\" not in name and ":" not in name
    assert name.endswith(".md")
    # Distinct ids that slugify the same stay unique via the hash suffix.
    assert safe_prompt_filename("a/b") != safe_prompt_filename("a-b")


def test_classify_run_outcome_branches() -> None:
    ok = CommandResult(return_code=0, stdout="", stderr="")
    bad = CommandResult(return_code=2, stdout="", stderr="")
    timed = CommandResult(return_code=None, stdout="", stderr="", timed_out=True)
    spawn = CommandResult(return_code=None, stdout="", stderr="", spawn_error=True)
    limit = CommandResult(return_code=None, stdout="", stderr="", output_limit_exceeded=True)
    assert classify_run_outcome(ok) == "succeeded"
    assert classify_run_outcome(bad) == "failed"
    assert classify_run_outcome(timed) == "failed"
    assert classify_run_outcome(timed, failure_outcome="needs_human") == "needs_human"
    assert classify_run_outcome(spawn) == "blocked"
    assert classify_run_outcome(limit) == "failed"


def test_tail_bounds_lines_and_chars() -> None:
    assert tail("") == ""
    text = "\n".join(str(n) for n in range(100))
    out = tail(text, max_lines=3)
    assert out.splitlines() == ["97", "98", "99"]
    assert len(tail("x" * 5000, max_chars=100)) == 100


def test_default_run_summary_mentions_outcome() -> None:
    res = CommandResult(return_code=1, stdout="", stderr="")
    assert "failed" in default_run_summary(["solver"], res, "failed")
    spawn = CommandResult(return_code=None, stdout="", stderr="", spawn_error=True)
    assert "could not start" in default_run_summary(["solver"], spawn, "blocked")


# --------------------------------------------------------------------------- #
# execute_agent_command with an injected fake runner


def test_execute_agent_command_success_and_failure() -> None:
    def runner(argv, **_kwargs):
        return RunResult(args=argv, returncode=0, stdout="done", stderr="")

    result = execute_agent_command(["x"], runner=runner)
    assert result.return_code == 0 and result.ran and result.stdout == "done"
    assert result.duration_seconds is not None


def test_execute_agent_command_maps_timeout() -> None:
    def runner(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 1.0, output="partial", stderr="")

    result = execute_agent_command(["x"], timeout=1.0, runner=runner)
    assert result.timed_out and result.return_code is None
    assert result.stdout == "partial"


def test_execute_agent_command_maps_output_limit() -> None:
    def runner(argv, **_kwargs):
        raise OutputLimitExceeded(argv, 10, output="x" * 10, stderr="")

    result = execute_agent_command(["x"], runner=runner)
    assert result.output_limit_exceeded and result.return_code is None


def test_execute_agent_command_maps_spawn_error() -> None:
    def runner(argv, **_kwargs):
        raise FileNotFoundError(2, "missing")

    result = execute_agent_command(["x"], runner=runner)
    assert result.spawn_error and not result.ran
    assert "not found" in (result.error or "")


# --------------------------------------------------------------------------- #
# run_capture output cap (real subprocess)


def test_run_capture_enforces_output_cap() -> None:
    writer = "import sys, time; sys.stdout.write('x' * 50000); sys.stdout.flush(); time.sleep(30)"
    with pytest.raises(OutputLimitExceeded):
        run_capture([sys.executable, "-c", writer], timeout=15, max_output_bytes=1000)


def test_run_capture_enforces_cap_on_fast_burst() -> None:
    # The process floods output and exits immediately -- it may never trip the
    # 0.1s poll, so the cap must still be enforced after a clean exit.
    burst = "import sys; sys.stdout.write('x' * 50000); sys.stdout.flush()"
    with pytest.raises(OutputLimitExceeded):
        run_capture([sys.executable, "-c", burst], timeout=15, max_output_bytes=1000)


def test_run_capture_caps_exception_output_to_bounded_tail() -> None:
    # A single massive burst must not be read back in full when the cap trips:
    # the exception carries only a bounded tail so the cap actually bounds the
    # memory a runaway process can force the harness to allocate.
    burst = "import sys; sys.stdout.write('x' * 500000); sys.stdout.flush()"
    with pytest.raises(OutputLimitExceeded) as excinfo:
        run_capture([sys.executable, "-c", burst], timeout=15, max_output_bytes=1000)
    assert len(excinfo.value.output) <= 1000
    assert len(excinfo.value.stderr) <= 1000


def test_run_capture_without_cap_returns_normally() -> None:
    result = run_capture([sys.executable, "-c", "print('hi')"], timeout=30)
    assert result.returncode == 0
    assert "hi" in result.stdout


# --------------------------------------------------------------------------- #
# CLI integration (deterministic python -c commands)


def test_cli_agent_run_success_records_memory(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--exec",
            sys.executable,
            "--arg=-c",
            "--arg",
            "import sys; print(open(sys.argv[1]).read()[:3])",
            "--arg",
            "{prompt_file}",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "succeeded"
    assert payload["recorded"] is True
    assert payload["return_code"] == 0
    attempts = _memory(tmp_path)["nodes"]["a"]["attempts"]
    assert attempts[-1]["outcome"] == "succeeded"
    assert attempts[-1]["tool"] == sys.executable
    # The prompt file was written for the solver to read.
    assert Path(payload["prompt_path"]).exists()


def test_cli_agent_run_failure_with_fail_on_failure_exits_5(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c \"import sys; sys.exit(3)\" {{prompt_file}}",
            "--fail-on-failure",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload["outcome"] == "failed"
    assert payload["return_code"] == 3
    assert _memory(tmp_path)["nodes"]["a"]["attempts"][-1]["outcome"] == "failed"


def test_cli_agent_run_failure_outcome_override(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c \"import sys; sys.exit(1)\" {{prompt_file}}",
            "--failure-outcome",
            "needs_human",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "needs_human"


def test_cli_agent_run_spawn_error_not_recorded_exits_1(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--exec",
            "definitely-not-a-real-command-xyz",
            "--allow-missing-prompt",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["outcome"] == "blocked"
    assert payload["recorded"] is False
    # Spawn errors are config failures, not proof attempts: nothing recorded.
    assert _memory(tmp_path) == {}


def test_cli_agent_run_dry_run_does_not_execute_or_write(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            "solver {prompt_file}",
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["command"][0] == "solver"
    assert payload["recorded"] is False
    # Dry-run performs no writes and no recording.
    assert not (tmp_path / "build" / "agent-run").exists()
    assert _memory(tmp_path) == {}


def test_cli_agent_run_no_record(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c \"pass\" {{prompt_file}}",
            "--no-record",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "succeeded"
    assert payload["recorded"] is False
    assert _memory(tmp_path) == {}


def test_cli_agent_run_missing_prompt_placeholder_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(["agent-run", str(tmp_path), "--command", "solver --quiet"])
    assert code == 1
    assert "prompt_file" in capsys.readouterr().err


def test_cli_agent_run_requires_a_command(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(["agent-run", str(tmp_path)])
    assert code == 1
    assert "requires a solver command" in capsys.readouterr().err


def test_cli_agent_run_no_ready_task(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "agent-run-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        "# agent-run-test\n\n"
        "::: lemma {#a}\ntitle: A\nisabelle: Demo.a\nstatus:\n  formal: proved\n\nA.\n:::\n",
        encoding="utf-8",
    )
    code = cli_main(
        ["agent-run", str(tmp_path), "--command", "solver {prompt_file}", "--json"]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task"] is None
    assert payload["recorded"] is False


def test_cli_agent_run_timeout_records_failure(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c \"import time; time.sleep(5)\" {{prompt_file}}",
            "--timeout",
            "0.5",
            "--fail-on-failure",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload["timed_out"] is True
    assert payload["outcome"] == "failed"
    assert payload["return_code"] is None
    assert _memory(tmp_path)["nodes"]["a"]["attempts"][-1]["outcome"] == "failed"


def test_cli_agent_run_output_limit_records_failure(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    writer = "import sys, time; sys.stdout.write('x' * 200000); sys.stdout.flush(); time.sleep(5)"
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c {json.dumps(writer)} {{prompt_file}}",
            "--max-output-bytes",
            "1000",
            "--timeout",
            "15",
            "--fail-on-failure",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 5
    assert payload["output_limit_exceeded"] is True
    assert payload["outcome"] == "failed"
    assert _memory(tmp_path)["nodes"]["a"]["attempts"][-1]["outcome"] == "failed"


def test_cli_agent_run_relative_output_resolves_against_project(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--command",
            f"{_py()} -c \"pass\" {{prompt_file}}",
            "--output",
            "prompts/custom.md",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    expected = (tmp_path / "prompts" / "custom.md").resolve()
    assert Path(payload["prompt_path"]) == expected
    assert expected.exists()


def test_cli_agent_run_preserves_argv_tokens_with_spaces(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    # A prompt path containing spaces must reach the solver as exactly one argv
    # element -- proof that no shell re-splits the substituted value.
    code = cli_main(
        [
            "agent-run",
            str(tmp_path),
            "--exec",
            sys.executable,
            "--arg=-c",
            "--arg",
            "import sys, json; print(json.dumps(sys.argv))",
            "--arg",
            "{prompt_file}",
            "--output",
            "dir with spaces/prompt file.md",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    printed = json.loads(payload["stdout_tail"])
    assert printed[-1] == payload["prompt_path"]
    assert " " in printed[-1]


def _py() -> str:
    """Quote the interpreter path so it survives shlex tokenisation in --command."""

    return json.dumps(sys.executable)
