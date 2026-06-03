from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import load_project_with_check

_BLUEPRINT = """# Project IO test

::: theorem {#main}
title: Main
isabelle: Demo.main
status:
  formal: named

MAIN.
:::
"""


@pytest.mark.parametrize(
    "report",
    [
        [],
        "not a report",
        {"ran": True, "facts": ["not a fact record"]},
        {"facts": []},
    ],
)
def test_load_project_with_check_ignores_invalid_stored_check_report(
    tmp_path: Path,
    report: object,
) -> None:
    _write_project(tmp_path)
    report_path = tmp_path / "build" / "check_report.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(report), encoding="utf-8")

    _config, project = load_project_with_check(tmp_path)

    assert project.by_id()["main"].status.formal is FormalStatus.NAMED


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "project-io-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
