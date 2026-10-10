from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.isabelle import check_cache, check_context
from isabelle_blueprint.isabelle.checker import CheckResult, FactCheck, write_report
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import load_project, load_project_with_check

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


def _stored_report(tmp_path, monkeypatch):
    _write_project(tmp_path)
    config, project = load_project(tmp_path)
    fingerprint = "a" * 64
    result = CheckResult(
        ran=True,
        return_code=0,
        isabelle_available=True,
        proof_checked=True,
        facts=[FactCheck("main", "Demo.main", "Demo", True, proof_status="proved")],
        source_fingerprint=fingerprint,
        node_fingerprints={
            "main": check_cache.compute_node_hash(project.nodes[0], context=fingerprint)
        },
    )
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: fingerprint)
    write_report(result, config.check_report_path)
    return config, result


def test_current_stored_proof_restores_status_without_building(tmp_path, monkeypatch):
    _stored_report(tmp_path, monkeypatch)
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.PROVED
    assert project.nodes[0].status.check_error is None


@pytest.mark.parametrize("current", ["b" * 64, None])
def test_changed_or_unverifiable_sources_make_stored_proofs_stale(tmp_path, monkeypatch, current):
    _stored_report(tmp_path, monkeypatch)
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: current)
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.STALE
    assert "rerun check" in project.nodes[0].status.check_error


def test_legacy_report_is_historical_evidence_not_current_proof(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    result.source_fingerprint = None
    result.node_fingerprints = {}
    write_report(result, config.check_report_path)
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.STALE
    assert "no source provenance" in project.nodes[0].status.check_error


def test_changed_blueprint_dependencies_make_matching_fact_stale(tmp_path, monkeypatch):
    _stored_report(tmp_path, monkeypatch)
    path = tmp_path / "blueprint.md"
    path.write_text(
        _BLUEPRINT.replace("title: Main", "title: Main\nuses: [dependency]"), encoding="utf-8"
    )
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.STALE
    assert "node inputs changed" in project.nodes[0].status.check_error


def test_new_reference_does_not_inherit_previous_check_timestamp_or_error(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    result.return_code = 1
    result.proof_checked = False
    result.facts[0].exists = False
    result.facts[0].proof_status = None
    result.facts[0].error = 'Undefined fact: "Demo.main"'
    write_report(result, config.check_report_path)
    (tmp_path / "blueprint.md").write_text(
        _BLUEPRINT.replace("Demo.main", "Demo.new"), encoding="utf-8"
    )
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED
    assert project.nodes[0].status.last_checked is None
    assert "Undefined fact" not in project.nodes[0].status.check_error


def test_missing_fact_diagnostic_expires_after_source_change(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    result.return_code = 1
    result.proof_checked = False
    result.facts[0].exists = False
    result.facts[0].proof_status = None
    result.facts[0].error = 'Undefined fact: "Demo.main"'
    write_report(result, config.check_report_path)
    _, current = load_project_with_check(tmp_path)
    assert current.nodes[0].status.formal == FormalStatus.NOT_FOUND
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: "b" * 64)
    _, changed = load_project_with_check(tmp_path)
    assert changed.nodes[0].status.formal == FormalStatus.STALE
    assert "Undefined fact" not in changed.nodes[0].status.check_error


def test_latest_incomplete_check_replaces_previous_proof_and_diagnostic(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    result.ran = False
    result.return_code = None
    result.proof_checked = False
    result.error = "build timed out"
    result.facts[0].exists = False
    result.facts[0].proof_status = None
    write_report(result, config.check_report_path)
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED
    assert project.nodes[0].status.check_error == "build timed out"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ran", "true"),
        ("proof_checked", 1),
        ("source_fingerprint", []),
        ("node_fingerprints", []),
        ("source_context_changed", "false"),
    ],
)
def test_malformed_report_metadata_cannot_promote_status(tmp_path, monkeypatch, field, value):
    config, result = _stored_report(tmp_path, monkeypatch)
    data = result.to_dict()
    data[field] = value
    config.check_report_path.write_text(json.dumps(data), encoding="utf-8")
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED


def test_invalid_utf8_report_is_ignored(tmp_path):
    _write_project(tmp_path)
    path = tmp_path / "build" / "check_report.json"
    path.parent.mkdir()
    path.write_bytes(b"\xff")
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED


@pytest.mark.parametrize(
    "fields",
    [
        {"exists": "false"},
        {"exists": True, "error": "failed"},
        {"proof_status": []},
        {"oracles": "Pure.skip_proof"},
        {"fact": []},
    ],
)
def test_malformed_fact_evidence_cannot_promote_status(tmp_path, monkeypatch, fields):
    config, result = _stored_report(tmp_path, monkeypatch)
    data = result.to_dict()
    data["facts"][0].update(fields)
    config.check_report_path.write_text(json.dumps(data), encoding="utf-8")
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED


def test_contradictory_duplicate_fact_records_cannot_promote_status(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    data = result.to_dict()
    data["facts"].insert(0, {**data["facts"][0], "proof_status": "tainted"})
    config.check_report_path.write_text(json.dumps(data), encoding="utf-8")
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.NAMED


def test_missing_timestamp_does_not_invent_a_recent_historical_check(tmp_path, monkeypatch):
    config, result = _stored_report(tmp_path, monkeypatch)
    data = result.to_dict()
    del data["timestamp"]
    config.check_report_path.write_text(json.dumps(data), encoding="utf-8")
    _, project = load_project_with_check(tmp_path)
    assert project.nodes[0].status.formal == FormalStatus.STALE
    assert project.nodes[0].status.last_checked is None
