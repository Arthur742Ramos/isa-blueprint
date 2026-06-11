from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main

_BLUEPRINT = """# diff-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "diff-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _write_baseline(tmp_path: Path, nodes: list[dict]) -> Path:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"nodes": nodes}), encoding="utf-8")
    return path


def test_diff_no_changes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    # Build a baseline that matches the current node exactly.
    rc = cli_main(["report", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()
    baseline = tmp_path / "build" / "project.json"

    rc = cli_main(["diff", str(baseline), str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["added"] == []
    assert data["removed"] == []
    assert data["has_regression"] is False


def test_diff_detects_removed_and_regression(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    baseline = _write_baseline(
        tmp_path,
        [
            {"id": "a", "status": {"formal": "proved", "agent": "idle", "blueprint": "stub"}},
            {"id": "gone", "status": {"formal": "proved", "agent": "idle", "blueprint": "stub"}},
        ],
    )

    rc = cli_main(["diff", str(baseline), str(tmp_path), "--json", "--fail-on-regression"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    assert "gone" in data["removed"]
    assert data["has_regression"] is True
    # Two regressions: node `a` downgraded proved->stub (a change) AND `gone`
    # was removed. The JSON count must include removed nodes -- previously it
    # counted only `changes` (would report 1 here), contradicting
    # has_regression and the rendered "N regression(s)" headline.
    assert data["regression_count"] == 2


def test_diff_regression_without_flag_returns_zero(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    baseline = _write_baseline(
        tmp_path,
        [{"id": "a", "status": {"formal": "proved", "agent": "idle", "blueprint": "stub"}}],
    )

    rc = cli_main(["diff", str(baseline), str(tmp_path), "--json"])

    assert rc == 0
    capsys.readouterr()


def test_diff_missing_baseline_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["diff", str(tmp_path / "nope.json"), str(tmp_path)])

    assert rc == 1


def test_is_regression_confidence_ladder() -> None:
    from isabelle_blueprint.report.diff import _is_regression

    # Losing a located fact is a regression even without a problem status.
    assert _is_regression("found", "named") is True
    assert _is_regression("found", "missing") is True
    assert _is_regression("named", "missing") is True
    # Forward progress along the ladder is never a regression.
    assert _is_regression("named", "found") is False
    assert _is_regression("missing", "proved") is False
    assert _is_regression("found", "found") is False


def test_load_baseline_rejects_duplicate_ids(tmp_path: Path) -> None:
    """A real report has unique node ids; duplicates mean a corrupted snapshot.
    Silently keeping the last one (the old behaviour) could mask a regression on
    the dropped node, so the loader must fail loudly instead."""
    from isabelle_blueprint.errors import BlueprintError
    from isabelle_blueprint.report.diff import load_baseline

    path = _write_baseline(
        tmp_path,
        [
            {"id": "dup", "status": {"formal": "proved"}},
            {"id": "dup", "status": {"formal": "missing"}},
        ],
    )

    with pytest.raises(BlueprintError, match="duplicate node id"):
        load_baseline(path)
