from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.report.history import render_trend_summary, summarize_trends

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


def test_render_trend_summary_empty():
    text = render_trend_summary(summarize_trends([]))
    assert text == (
        "No trend history yet. Run `isabelle-blueprint report` to record a snapshot.\n"
    )


def test_render_trend_summary_single_entry_has_no_delta():
    text = render_trend_summary(
        summarize_trends([{"timestamp": "2024-01-01T00:00:00Z", "proved_count": 1}])
    )
    assert "Trend history (1 entry):" in text
    assert "Latest change: (need at least two entries to compute a delta)" in text


def test_render_trend_summary_reports_delta_and_commit():
    text = render_trend_summary(
        summarize_trends(
            [
                {"timestamp": "2024-01-01T00:00:00Z", "proved_count": 1},
                {
                    "timestamp": "2024-01-02T00:00:00Z",
                    "proved_count": 3,
                    "coverage_percent": 50.0,
                    "commit_sha": "abcdef1234567890",
                },
            ]
        )
    )
    assert "Trend history (2 entries):" in text
    assert "abcdef12" in text
    assert "proved_count: 1 -> 3 (+2)" in text
    assert "coverage_percent: n/a -> 50.0" in text


def test_render_trend_summary_negative_and_no_change_deltas():
    text = render_trend_summary(
        summarize_trends(
            [
                {"timestamp": "t1", "proved_count": 3, "problem_count": 2},
                {"timestamp": "t2", "proved_count": 3, "problem_count": 1},
            ]
        )
    )
    assert "proved_count: 3 -> 3 (no change)" in text
    assert "problem_count: 2 -> 1 (-1)" in text


def test_summarize_trends_ignores_non_numeric_metric():
    summary = summarize_trends(
        [
            {"timestamp": "t1", "proved_count": "oops"},
            {"timestamp": "t2", "proved_count": "still-bad"},
        ]
    )
    proved = next(d for d in summary.deltas if d.metric == "proved_count")
    assert proved.before is None and proved.after is None and proved.delta is None


def test_history_csv_header_and_rows(tmp_path: Path, capsys) -> None:
    import csv
    import io

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

    rc = cli_main(["history", str(tmp_path), "--csv"])

    assert rc == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == [
        "timestamp",
        "coverage_percent",
        "proved_count",
        "found_count",
        "problem_count",
        "stale_count",
        "formal_target_count",
        "node_count",
    ]
    # Header + one row per snapshot.
    assert len(rows) == 3
    assert rows[1][0] == "2024-01-01T00:00:00Z"
    assert rows[1][2] == "1"
    assert rows[2][1] == "20.0"


def test_history_csv_respects_limit(tmp_path: Path, capsys) -> None:
    import csv
    import io

    _write_project(tmp_path)
    _write_trends(
        tmp_path,
        [
            {"timestamp": f"2024-01-0{i}T00:00:00Z", "proved_count": i}
            for i in range(1, 4)
        ],
    )

    rc = cli_main(["history", str(tmp_path), "--csv", "--limit", "1"])

    assert rc == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    # Header + the single most-recent snapshot.
    assert len(rows) == 2
    assert rows[1][0] == "2024-01-03T00:00:00Z"


def test_history_csv_and_json_mutually_exclusive(tmp_path: Path) -> None:
    import pytest

    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["history", str(tmp_path), "--csv", "--json"])


def test_history_markdown_header_and_rows(tmp_path: Path, capsys) -> None:
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

    rc = cli_main(["history", str(tmp_path), "--markdown"])

    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "| timestamp | coverage_percent | proved_count | found_count "
        "| problem_count | stale_count | formal_target_count | node_count |"
    )
    assert lines[1] == "| --- | --- | --- | --- | --- | --- | --- | --- |"
    # Header + separator + one row per snapshot.
    assert len(lines) == 4
    assert lines[2].startswith("| 2024-01-01T00:00:00Z | 10.0 | 1 |")
    assert lines[3].startswith("| 2024-01-02T00:00:00Z | 20.0 | 2 |")


def test_history_markdown_respects_limit(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(
        tmp_path,
        [
            {"timestamp": f"2024-01-0{i}T00:00:00Z", "proved_count": i}
            for i in range(1, 4)
        ],
    )

    rc = cli_main(["history", str(tmp_path), "--markdown", "--limit", "1"])

    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    # Header + separator + the single most-recent snapshot.
    assert len(lines) == 3
    assert lines[2].startswith("| 2024-01-03T00:00:00Z |")


def test_history_markdown_and_json_mutually_exclusive(tmp_path: Path) -> None:
    import pytest

    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["history", str(tmp_path), "--markdown", "--json"])


def test_history_markdown_and_csv_mutually_exclusive(tmp_path: Path) -> None:
    import pytest

    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["history", str(tmp_path), "--markdown", "--csv"])
