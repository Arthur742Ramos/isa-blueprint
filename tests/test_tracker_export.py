from __future__ import annotations

import csv
import io
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_BP = """# Tracker

::: definition {#base}
title: Base def
isabelle: Demo.base
status:
  blueprint: written
  formal: found
:::

Base.
:::

::: theorem {#main}
title: Main theorem
isabelle: Demo.main
uses:
  - base
status:
  blueprint: written
:::

Main statement.

## Proof

By base.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Tracker"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BP, encoding="utf-8")


def test_tasks_tracker_export_jira(tmp_path: Path) -> None:
    _write_project(tmp_path)

    rc = cli_main(["tasks", str(tmp_path), "--tracker-export", "jira"])

    assert rc == 0
    csv_path = tmp_path / "build" / "tasks-jira.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
    assert rows
    assert set(rows[0]) == {
        "Summary",
        "Issue Type",
        "Priority",
        "Labels",
        "Story Points",
        "Description",
    }
    main_row = next(r for r in rows if "Main theorem" in r["Summary"])
    assert main_row["Issue Type"] == "Task"
    assert main_row["Priority"] in {"High", "Medium", "Low"}
    assert "isabelle-blueprint" in main_row["Labels"]


def test_tasks_tracker_export_linear(tmp_path: Path) -> None:
    _write_project(tmp_path)

    rc = cli_main(["tasks", str(tmp_path), "--tracker-export", "linear"])

    assert rc == 0
    csv_path = tmp_path / "build" / "tasks-linear.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
    assert rows
    assert set(rows[0]) == {"Title", "Description", "Priority", "Labels", "Estimate"}
    main_row = next(r for r in rows if "Main theorem" in r["Title"])
    assert int(main_row["Estimate"]) >= 1
    assert "," in main_row["Labels"]


def test_tracker_export_rejects_unknown_tracker(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    import pytest

    with pytest.raises(SystemExit) as exc:
        cli_main(["tasks", str(tmp_path), "--tracker-export", "asana"])

    assert exc.value.code == 2
    assert "asana" in capsys.readouterr().err
