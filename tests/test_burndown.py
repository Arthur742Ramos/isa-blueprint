from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.report.burndown import (
    build_burndown_report,
    burndown_payload,
    render_burndown_markdown,
    render_burndown_report,
)

_BLUEPRINT = """# burndown-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "burndown-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _write_trends(tmp_path: Path, entries: list[dict]) -> None:
    build = tmp_path / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "trends.json").write_text(json.dumps(entries), encoding="utf-8")


def _entry(day: int, proved: int, target: int, **extra: object) -> dict:
    entry = {
        "timestamp": f"2024-01-{day:02d}T00:00:00Z",
        "proved_count": proved,
        "formal_target_count": target,
    }
    entry.update(extra)
    return entry


def _series(specs: list[tuple[int, int, int]]) -> list[dict]:
    return [_entry(day, proved, target) for day, proved, target in specs]


# --------------------------------------------------------------------------- #
# Core classification


def test_no_history() -> None:
    report = build_burndown_report([])
    assert report.status == "no_history"
    assert report.entry_count == 0
    assert report.eta_days is None
    assert report.eta_date is None


def test_on_track_forecasts_eta() -> None:
    # proved 0,2,4,6,8 over five days -> remaining 10..2, slope -2/day.
    report = build_burndown_report(
        _series([(1, 0, 10), (2, 2, 10), (3, 4, 10), (4, 6, 10), (5, 8, 10)])
    )
    assert report.status == "on_track"
    assert report.remaining == 2
    assert report.forecast is not None
    assert report.forecast.remaining_per_day == -2.0
    assert report.forecast.net_burndown_per_day == 2.0
    assert report.forecast.proved_per_day == 2.0
    assert report.forecast.target_per_day == 0.0
    # remaining 2 / 2 per day = 1 day after the last snapshot (2024-01-05).
    assert report.eta_days == 1.0
    assert report.eta_date == "2024-01-06"


def test_complete_when_no_remaining() -> None:
    report = build_burndown_report(_series([(1, 5, 10), (2, 10, 10)]))
    assert report.status == "complete"
    assert report.remaining == 0
    assert report.eta_days == 0.0
    assert report.eta_date == "2024-01-02"


def test_stalled_when_flat() -> None:
    report = build_burndown_report(_series([(1, 5, 10), (2, 5, 10), (3, 5, 10)]))
    assert report.status == "stalled"
    assert report.eta_days is None
    assert report.eta_date is None


def test_regressing_when_remaining_grows_and_proofs_fall() -> None:
    report = build_burndown_report(_series([(1, 5, 10), (2, 4, 10), (3, 3, 10)]))
    assert report.status == "regressing"
    assert report.eta_date is None


def test_scope_growing_when_target_outpaces_proofs() -> None:
    # proved climbs +2/day but the target climbs +4/day, so remaining grows.
    report = build_burndown_report(_series([(1, 2, 10), (2, 4, 14), (3, 6, 18)]))
    assert report.status == "scope_growing"
    assert report.forecast is not None
    assert report.forecast.proved_per_day == 2.0
    assert report.forecast.remaining_per_day == 2.0
    assert report.eta_date is None


def test_no_targets() -> None:
    report = build_burndown_report(_series([(1, 0, 0), (2, 0, 0)]))
    assert report.status == "no_targets"


def test_single_point_is_insufficient() -> None:
    report = build_burndown_report(_series([(1, 1, 10)]))
    assert report.status == "insufficient_history"
    assert report.entry_count == 1


def test_beyond_horizon_for_tiny_velocity() -> None:
    report = build_burndown_report(
        _series([(1, 0, 1_000_000), (2, 1, 1_000_000)])
    )
    assert report.status == "beyond_horizon"
    assert report.eta_date is None
    assert report.eta_days is not None and report.eta_days > 36500


# --------------------------------------------------------------------------- #
# Usable-point hygiene


def test_malformed_points_are_skipped() -> None:
    entries = [
        _entry(1, 1, 10),
        {"timestamp": "not-a-date", "proved_count": 2, "formal_target_count": 10},
        {"timestamp": "2024-01-03T00:00:00Z", "proved_count": -1, "formal_target_count": 10},
        {"timestamp": "2024-01-04T00:00:00Z", "proved_count": 5, "formal_target_count": 3},
        {"timestamp": "2024-01-05T00:00:00Z", "proved_count": True, "formal_target_count": 10},
        _entry(6, 3, 10),
    ]
    report = build_burndown_report(entries)
    # Only the two clean entries (day 1 and day 6) survive.
    assert report.entry_count == 2
    assert report.total_entries == 6


def test_duplicate_timestamps_collapse_keeping_latest() -> None:
    entries = [
        _entry(1, 1, 10),
        _entry(1, 3, 10),  # same timestamp, later in list -> wins
        _entry(2, 5, 10),
    ]
    report = build_burndown_report(entries)
    assert report.entry_count == 2
    assert report.points[0].completed == 3


# --------------------------------------------------------------------------- #
# Payload + render


def test_payload_limit_trims_points_not_velocity() -> None:
    report = build_burndown_report(
        _series([(1, 0, 10), (2, 2, 10), (3, 4, 10), (4, 6, 10)])
    )
    payload = burndown_payload(report, limit=2)
    assert len(payload["points"]) == 2
    # Velocity still derived from the full series.
    assert payload["forecast"]["remaining_per_day"] == -2.0
    assert payload["schema_version"] == 1
    assert payload["status"] == "on_track"


def test_render_smoke() -> None:
    report = build_burndown_report(
        _series([(1, 0, 10), (2, 2, 10), (3, 4, 10)])
    )
    text = render_burndown_report(report)
    assert "Burndown forecast:" in text
    assert "ETA:" in text
    assert text.endswith("\n")


def test_render_no_history() -> None:
    text = render_burndown_report(build_burndown_report([]))
    assert "No coverage history yet" in text


def test_render_markdown_on_track() -> None:
    report = build_burndown_report(
        _series([(1, 0, 10), (2, 2, 10), (3, 4, 10), (4, 6, 10), (5, 8, 10)])
    )
    md = render_burndown_markdown(report)
    assert md.startswith("# Burndown forecast")
    assert "| Status | Remaining | ETA (days) | ETA date | Forecast |" in md
    assert "`on_track`" in md
    assert "2024-01-06" in md  # eta_date
    assert "1.0" in md  # eta_days
    assert md.endswith("\n")


def test_render_markdown_stalled_has_note() -> None:
    report = build_burndown_report(_series([(1, 5, 10), (2, 5, 10), (3, 5, 10)]))
    md = render_burndown_markdown(report)
    assert "`stalled`" in md
    assert "**Note:**" in md



# --------------------------------------------------------------------------- #
# CLI integration


def test_cli_burndown_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(
        tmp_path, _series([(1, 0, 10), (2, 2, 10), (3, 4, 10), (4, 6, 10), (5, 8, 10)])
    )

    rc = cli_main(["burndown", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "on_track"
    assert data["eta_date"] == "2024-01-06"
    assert data["trends_path"].endswith("trends.json")


def test_cli_burndown_empty(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["burndown", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "no_history"


def test_cli_burndown_fail_when_stalled(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(tmp_path, _series([(1, 5, 10), (2, 5, 10), (3, 5, 10)]))

    rc = cli_main(["burndown", str(tmp_path), "--fail-when-stalled"])

    assert rc == 5
    assert "Stalled" in capsys.readouterr().out


def test_cli_burndown_markdown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(
        tmp_path, _series([(1, 0, 10), (2, 2, 10), (3, 4, 10), (4, 6, 10), (5, 8, 10)])
    )

    rc = cli_main(["burndown", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# Burndown forecast")
    assert "| Status | Remaining | ETA (days) | ETA date | Forecast |" in out
    assert "`on_track`" in out
    assert "2024-01-06" in out


def test_cli_burndown_markdown_stalled_note(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    _write_trends(tmp_path, _series([(1, 5, 10), (2, 5, 10), (3, 5, 10)]))

    rc = cli_main(["burndown", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "`stalled`" in out
    assert "**Note:**" in out


def test_cli_burndown_markdown_and_json_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["burndown", str(tmp_path), "--markdown", "--json"])
