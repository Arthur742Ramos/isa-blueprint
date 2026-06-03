from __future__ import annotations

from pathlib import Path

import isabelle_blueprint.cli as cli
from isabelle_blueprint.cli import main as cli_main

_PROJECT = """# watch-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.

Sketch.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "watch-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_PROJECT, encoding="utf-8")


def _stop_after_first(monkeypatch) -> None:
    # The watch loop calls time.sleep between polls; raising there exits the
    # loop deterministically after the initial run, exactly like Ctrl-C.
    def _raise(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", _raise)


def test_report_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["report", str(tmp_path), "--watch", "--interval", "0.01"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err
    assert "stopped" in err


def test_status_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["status", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err


def test_tasks_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["tasks", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err


def test_report_without_watch_is_single_shot(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["report", str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" not in err
