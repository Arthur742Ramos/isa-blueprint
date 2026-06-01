from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.doctor import run_doctor

_BLUEPRINT = """# Demo

::: lemma {#demo}
title: Demo
isabelle: Demo.demo
status: stub

Statement.
:::
"""


def test_doctor_reports_project_without_errors(tmp_path: Path) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")

    report = run_doctor(tmp_path)

    assert not report.has_errors
    assert any(check.name == "blueprints" and check.status == "ok" for check in report.checks)


def test_doctor_strict_fails_when_blueprint_missing(tmp_path: Path) -> None:
    rc = cli_main(["doctor", str(tmp_path), "--strict"])

    assert rc == 7


def test_doctor_json_output(tmp_path: Path, capsys) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")

    rc = cli_main(["doctor", str(tmp_path), "--json"])

    assert rc == 0
    out = capsys.readouterr().out
    assert '"checks"' in out
    assert '"project_dir"' in out

