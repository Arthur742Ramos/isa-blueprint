from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.report.lint import (
    SEVERITY_ERROR,
    LintFinding,
    LintReport,
)
from isabelle_blueprint.report.sarif import build_sarif

_BROKEN = """# broken

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: ghost

A statement.

Sketch.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "sarif-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BROKEN, encoding="utf-8")


def test_build_sarif_basic_shape() -> None:
    report = LintReport(
        project="p",
        findings=[
            LintFinding(
                code="missing-dependency",
                severity=SEVERITY_ERROR,
                message="node 'a' depends on undefined 'ghost'",
                node_id="a",
            )
        ],
    )
    doc = build_sarif(report)

    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-2.1.0.json")
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "isabelle-blueprint"
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert "missing-dependency" in rule_ids
    result = run["results"][0]
    assert result["ruleId"] == "missing-dependency"
    assert result["level"] == "error"
    assert result["message"]["text"]
    assert result["partialFingerprints"]["isabelleBlueprint/v1"]
    # No project supplied -> logical location only.
    assert result["locations"][0]["logicalLocations"][0]["name"] == "a"


def test_severity_maps_to_sarif_levels() -> None:
    report = LintReport(
        project="p",
        findings=[
            LintFinding(code="cycle", severity="error", message="m", node_id="x"),
            LintFinding(code="empty-statement", severity="warning", message="m", node_id="y"),
            LintFinding(code="isolated-node", severity="info", message="m", node_id="z"),
        ],
    )
    levels = {r["ruleId"]: r["level"] for r in build_sarif(report)["runs"][0]["results"]}
    assert levels == {"cycle": "error", "empty-statement": "warning", "isolated-node": "note"}


def test_cli_lint_format_sarif(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["lint", str(tmp_path), "--format", "sarif"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0"
    codes = {r["ruleId"] for r in doc["runs"][0]["results"]}
    assert "missing-dependency" in codes
    # Findings carry physical locations sourced from the blueprint file.
    located = [
        r
        for r in doc["runs"][0]["results"]
        if "locations" in r and "physicalLocation" in r["locations"][0]
    ]
    assert located, "expected at least one finding with a physical location"


def test_cli_lint_json_and_format_conflict(tmp_path: Path) -> None:
    _write_project(tmp_path)
    rc = cli_main(["lint", str(tmp_path), "--json", "--format", "sarif"])
    assert rc == 1


def test_cli_lint_json_alias_agrees_with_format_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["lint", str(tmp_path), "--json", "--format", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "findings" in data
