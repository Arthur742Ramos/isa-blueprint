"""Tests for :mod:`isabelle_blueprint.report.github_actions`."""
from __future__ import annotations

import re
from pathlib import Path

from isabelle_blueprint.report.github_actions import (
    build_summary_markdown,
    emit_step_outputs,
    emit_step_summary,
)


def test_emit_step_outputs_returns_false_when_env_var_missing():
    # No GITHUB_OUTPUT set -> silent no-op.
    assert emit_step_outputs({"coverage_percent": "42"}, env={}) is False


def test_emit_step_outputs_appends_scalar_key_value_lines(tmp_path: Path):
    out = tmp_path / "outputs"
    env = {"GITHUB_OUTPUT": str(out)}
    assert emit_step_outputs(
        {"coverage_percent": "42", "has_cycles": "false"}, env=env
    )
    body = out.read_text(encoding="utf-8")
    assert "coverage_percent=42" in body
    assert "has_cycles=false" in body


def test_emit_step_outputs_appends_rather_than_overwrites(tmp_path: Path):
    out = tmp_path / "outputs"
    out.write_text("prior=value\n", encoding="utf-8")
    env = {"GITHUB_OUTPUT": str(out)}
    emit_step_outputs({"coverage_percent": "10"}, env=env)
    body = out.read_text(encoding="utf-8")
    assert body.startswith("prior=value\n")
    assert "coverage_percent=10" in body


def test_emit_step_outputs_uses_uuid_heredoc_for_multiline_values(tmp_path: Path):
    out = tmp_path / "outputs"
    env = {"GITHUB_OUTPUT": str(out)}
    emit_step_outputs({"report": "line one\nline two"}, env=env)
    body = out.read_text(encoding="utf-8")
    # Heredoc delimiter must look like ghadelim_<hex> per our contract.
    match = re.search(r"^report<<(ghadelim_[0-9a-f]+)$", body, re.MULTILINE)
    assert match, body
    delim = match.group(1)
    # Body must be sandwiched between the opening and closing delimiter.
    assert f"\nline one\nline two\n{delim}\n" in body


def test_emit_step_outputs_swallows_oserror(tmp_path: Path, monkeypatch):
    out = tmp_path / "outputs"
    env = {"GITHUB_OUTPUT": str(out)}

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", boom)
    # Must return False, NOT raise - a misconfigured runner should never turn
    # a successful CLI invocation into a failed one.
    assert emit_step_outputs({"x": "1"}, env=env) is False


def test_emit_step_outputs_renders_bool_and_none(tmp_path: Path):
    out = tmp_path / "outputs"
    env = {"GITHUB_OUTPUT": str(out)}
    emit_step_outputs(
        {"flag_true": True, "flag_false": False, "nothing": None},
        env=env,
    )
    body = out.read_text(encoding="utf-8")
    assert "flag_true=true" in body
    assert "flag_false=false" in body
    assert "nothing=" in body


def test_emit_step_summary_appends_with_trailing_newline(tmp_path: Path):
    out = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(out)}
    assert emit_step_summary("## Hello", env=env)
    assert emit_step_summary("## World", env=env)
    body = out.read_text(encoding="utf-8")
    assert body == "## Hello\n## World\n"


def test_emit_step_summary_returns_false_when_env_var_missing():
    assert emit_step_summary("## anything", env={}) is False


def test_emit_step_summary_swallows_oserror(tmp_path: Path, monkeypatch):
    out = tmp_path / "summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(out)}

    def boom(*args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "open", boom)
    assert emit_step_summary("## x", env=env) is False


def test_build_summary_markdown_handles_missing_coverage():
    md = build_summary_markdown(
        "demo",
        {
            "coverage_percent": None,
            "proved_count": 0,
            "formal_target_count": 0,
            "node_count": 0,
            "found_count": 0,
            "problem_count": 0,
            "has_cycles": False,
        },
    )
    assert "## IsabelleBlueprint - demo" in md
    assert "_no formal targets yet_" in md
    assert "| Has cycles | no |" in md


def test_build_summary_markdown_renders_full_table():
    md = build_summary_markdown(
        "demo",
        {
            "coverage_percent": 75,
            "proved_count": 3,
            "formal_target_count": 4,
            "node_count": 4,
            "found_count": 0,
            "problem_count": 0,
            "has_cycles": True,
        },
    )
    assert "Coverage: **75%** (3/4 proved)" in md
    assert "| Nodes | 4 |" in md
    assert "| Formal targets | 4 |" in md
    assert "| Has cycles | yes |" in md


def test_build_summary_markdown_appends_extra_lines():
    md = build_summary_markdown(
        "demo",
        {
            "coverage_percent": 100,
            "proved_count": 1,
            "formal_target_count": 1,
            "node_count": 1,
            "found_count": 0,
            "problem_count": 0,
            "has_cycles": False,
        },
        extra_lines=["", "_See full report on GH Pages._"],
    )
    assert md.endswith("_See full report on GH Pages._")
