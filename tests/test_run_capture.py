"""Behavioural tests for the cross-platform subprocess helper.

``isabelle_blueprint.isabelle._run.run_capture`` is the anti-hang shim every
Isabelle invocation goes through. It is tricky, platform-specific code (temp-file
capture instead of pipes, process-tree kill on timeout, an output-size cap), so
these tests drive it against *real* short-lived ``python -c`` subprocesses --
exercising the timeout, output-cap, stdin-EOF, and decoding paths directly,
without needing Isabelle installed.
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from isabelle_blueprint.isabelle._run import OutputLimitExceeded, RunResult, run_capture


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_happy_path_captures_streams_and_returncode() -> None:
    result = run_capture(
        _py("import sys; sys.stdout.write('hello out'); sys.stderr.write('hello err')")
    )
    assert isinstance(result, RunResult)
    assert result.returncode == 0
    assert result.stdout == "hello out"
    assert result.stderr == "hello err"


def test_nonzero_exit_code_is_propagated() -> None:
    result = run_capture(_py("import sys; sys.exit(3)"))
    assert result.returncode == 3


def test_stdin_is_devnull_so_readers_get_eof_and_do_not_hang() -> None:
    # If stdin were inherited this would block forever; DEVNULL yields EOF.
    result = run_capture(_py("import sys; sys.stdout.write(repr(sys.stdin.read()))"))
    assert result.returncode == 0
    assert result.stdout == "''"


def test_invalid_utf8_bytes_are_replaced_not_crashed() -> None:
    result = run_capture(
        _py(r"import sys; sys.stdout.buffer.write(b'\xff\xfe' + b'tail')")
    )
    assert result.returncode == 0
    assert result.stdout.endswith("tail")
    assert "\ufffd" in result.stdout  # the undecodable bytes became U+FFFD


def test_timeout_kills_tree_and_raises_promptly() -> None:
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_capture(_py("import time; time.sleep(30)"), timeout=2)
    elapsed = time.monotonic() - start
    # The whole point of the temp-file design is that the timeout actually fires
    # instead of hanging in communicate(); allow generous slack for tree-kill.
    assert elapsed < 25, f"timeout took {elapsed:.1f}s -- it should fire near 2s"


def test_output_limit_kills_flooding_process() -> None:
    code = "import sys\nwhile True:\n sys.stdout.write('x' * 8192); sys.stdout.flush()"
    with pytest.raises(OutputLimitExceeded) as excinfo:
        run_capture(_py(code), timeout=20, max_output_bytes=64_000)
    exc = excinfo.value
    assert exc.limit == 64_000
    # The captured tail must stay bounded -- only stdout floods here.
    assert len(exc.output) <= 64_000


def test_output_limit_caught_after_clean_exit() -> None:
    # A burst that finishes before the size poll still must trip the cap on the
    # post-exit re-check, not slip through.
    with pytest.raises(OutputLimitExceeded):
        run_capture(
            _py("import sys; sys.stdout.write('x' * 200000)"),
            timeout=20,
            max_output_bytes=1_000,
        )


def test_output_limit_under_cap_returns_normally() -> None:
    result = run_capture(
        _py("import sys; sys.stdout.write('small payload')"),
        timeout=20,
        max_output_bytes=1_000_000,
    )
    assert result.returncode == 0
    assert result.stdout == "small payload"


def test_timeout_fires_even_with_output_cap_enabled() -> None:
    # Exercises the deadline branch of the polling loop (cap set, no flood).
    with pytest.raises(subprocess.TimeoutExpired):
        run_capture(
            _py("import time; time.sleep(30)"),
            timeout=2,
            max_output_bytes=1_000_000,
        )
