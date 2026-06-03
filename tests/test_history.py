from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_BLUEPRINT = """# history-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "history-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _write_trends(tmp_path: Path, entries: list[dict]) -> None:
    build = tmp_path / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "trends.json").write_text(json.dumps(entries), encoding="utf-8")


def test_history_empty(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["history", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entry_count"] == 0
    assert data["entries"] == []


def test_history_summarizes_delta(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(
        tmp_path,
        [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "coverage_percent": 10.0,
                "proved_count": 1,
                "found_count": 0,
                "problem_count": 0,
                "stale_count": 0,
                "formal_target_count": 10,
                "node_count": 10,
            },
            {
                "timestamp": "2024-01-02T00:00:00Z",
                "coverage_percent": 20.0,
                "proved_count": 2,
                "found_count": 0,
                "problem_count": 0,
                "stale_count": 0,
                "formal_target_count": 10,
                "node_count": 10,
            },
        ],
    )

    rc = cli_main(["history", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entry_count"] == 2
    deltas = {d["metric"]: d["delta"] for d in data["deltas"]}
    assert deltas["proved_count"] == 1
    # Float metrics keep their decimal type instead of being truncated to int.
    assert deltas["coverage_percent"] == 10.0
    assert isinstance(deltas["coverage_percent"], float)


def test_history_limit(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(
        tmp_path,
        [
            {"timestamp": f"2024-01-0{i}T00:00:00Z", "proved_count": i}
            for i in range(1, 4)
        ],
    )

    rc = cli_main(["history", str(tmp_path), "--json", "--limit", "1"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entry_count"] == 3
    assert len(data["entries"]) == 1
