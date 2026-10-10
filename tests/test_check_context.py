"""Conservative source/installation fingerprints without running Isabelle."""

from __future__ import annotations

import subprocess

import pytest

from isabelle_blueprint.isabelle import check_context
from isabelle_blueprint.isabelle._run import RunResult


@pytest.fixture
def probe(tmp_path, monkeypatch):
    executable = tmp_path / "isabelle"
    executable.write_text("shim-v1", encoding="utf-8")
    response = RunResult([], 0, "ISABELLE_BLUEPRINT_CONTEXT\t" + "a" * 40 + "\n", "")
    calls = []

    def capture(command, **kwargs):
        calls.append((command, kwargs))
        return response

    monkeypatch.setattr(check_context, "run_capture", capture)

    def run():
        return check_context.session_fingerprint(
            str(executable), sessions=["Demo"], directories=[tmp_path], timeout=7
        )

    return executable, response, calls, run


def test_fingerprint_changes_for_native_sources_or_executable(probe):
    executable, response, calls, run = probe
    original = run()
    assert original is not None and run() == original
    response.stdout = "ISABELLE_BLUEPRINT_CONTEXT\t" + "b" * 40 + "\n"
    assert run() != original
    response.stdout = "ISABELLE_BLUEPRINT_CONTEXT\t" + "a" * 40 + "\n"
    executable.write_text("shim-v2", encoding="utf-8")
    assert run() != original
    assert calls[0][0][1:3] == ["scala", "-e"]
    assert calls[0][1]["timeout"] == 7


@pytest.mark.parametrize(
    "output",
    [
        "",
        "noise",
        "ISABELLE_BLUEPRINT_CONTEXT\tbad",
        "ISABELLE_BLUEPRINT_CONTEXT\t" + "a" * 40 + "\nISABELLE_BLUEPRINT_CONTEXT\t" + "a" * 40,
    ],
)
def test_missing_malformed_or_duplicate_markers_disable_reuse(probe, output):
    _, response, _, run = probe
    response.stdout = output
    assert run() is None


def test_nonzero_probe_disables_reuse(probe):
    _, response, _, run = probe
    response.returncode = 1
    assert run() is None


@pytest.mark.parametrize("error", [OSError("missing"), subprocess.TimeoutExpired("scala", 7)])
def test_probe_failure_disables_reuse(probe, monkeypatch, error):
    _, _, _, run = probe

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(check_context, "run_capture", fail)
    assert run() is None


def test_missing_executable_disables_reuse(probe):
    executable, _, calls, run = probe
    executable.unlink()
    assert run() is None
    assert calls == []
