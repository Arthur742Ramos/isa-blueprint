from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main

_PROJECT = """# stats-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.

Sketch.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

Depends on a.

Because a holds.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "stats-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_PROJECT, encoding="utf-8")


def _record(tmp_path: Path, node: str, outcome: str) -> None:
    rc = cli_main(
        [
            "memory",
            str(tmp_path),
            "--record",
            "--node",
            node,
            "--outcome",
            outcome,
            "--summary",
            f"{outcome} on {node}",
        ]
    )
    assert rc == 0


def test_stats_empty_memory(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["stats", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no attempts recorded" in out


def test_stats_json_aggregates_outcomes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    capsys.readouterr()
    _record(tmp_path, "a", "succeeded")
    _record(tmp_path, "a", "failed")
    _record(tmp_path, "b", "succeeded")
    capsys.readouterr()

    rc = cli_main(["stats", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)

    assert data["project"] == "stats-test"
    assert data["total_attempts"] == 3
    assert data["nodes_with_memory"] == 2
    assert data["outcomes"]["succeeded"] == 2
    assert data["outcomes"]["failed"] == 1
    # 2 succeeded out of 3 resolved (2 succeeded + 1 failed).
    assert data["success_rate"] == round(2 / 3, 4)

    kinds = {k["kind"]: k for k in data["per_kind"]}
    assert kinds["lemma"]["attempt_count"] == 2
    assert kinds["lemma"]["success_rate"] == 0.5
    assert kinds["theorem"]["success_rate"] == 1.0


def test_stats_text_render(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    capsys.readouterr()
    _record(tmp_path, "a", "succeeded")
    capsys.readouterr()

    rc = cli_main(["stats", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Agent memory stats for stats-test" in out
    assert "success rate" in out
    assert "succeeded" in out


def test_stats_markdown_render(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    capsys.readouterr()
    _record(tmp_path, "a", "succeeded")
    _record(tmp_path, "a", "failed")
    _record(tmp_path, "b", "succeeded")
    capsys.readouterr()

    rc = cli_main(["stats", str(tmp_path), "--markdown"])
    assert rc == 0
    out = capsys.readouterr().out

    assert "# Agent memory stats for stats-test" in out
    assert "## Summary" in out
    assert "| Total attempts | 3 |" in out
    assert "| Nodes with memory | 2 |" in out
    assert "## Outcomes" in out
    assert "| succeeded | 2 |" in out
    assert "| failed | 1 |" in out
    assert "## Per node" in out
    assert "| Node | Kind | Attempts | Last outcome |" in out
    assert "| a | lemma | 2 | failed |" in out
    assert "| b | theorem | 1 | succeeded |" in out


def test_stats_markdown_json_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["stats", str(tmp_path), "--markdown", "--json"])
