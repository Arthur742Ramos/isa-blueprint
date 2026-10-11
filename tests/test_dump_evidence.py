"""Dump observations must never substitute for current native proof evidence."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace

import pytest

from isabelle_blueprint.cli import main
from isabelle_blueprint.isabelle import check_cache, check_context, checker, dump
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import load_project, load_project_with_check


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "blueprint.md").write_text(
        "::: lemma {#a}\nisabelle: Demo.a\nstatus:\n  formal: named\n\nA\n:::\n",
        encoding="utf-8",
    )
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname="dump"\n[isabelle]\nsession="Demo"\n', encoding="utf-8"
    )
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: "a" * 64)
    return load_project(tmp_path)


def _verified(project):
    return checker.CheckResult(
        ran=True,
        return_code=0,
        proof_checked=True,
        source_fingerprint="a" * 64,
        node_fingerprints={
            n.id: check_cache.compute_node_hash(n, context="a" * 64) for n in project.nodes
        },
        facts=[checker.FactCheck("a", "Demo.a", "Demo", True, proof_status="proved")],
    )


def _raw(config, project):
    directory = config.build_dir / "imported"
    directory.mkdir(parents=True)
    (directory / "thms").write_text("\x05\x06entity\x06name=Demo.a\x05", encoding="utf-8")
    return dump.inspect_dump_dir(project, directory)


def test_zero_output_success_never_reuses_old_tree(project, monkeypatch):
    config, parsed = project
    old = _raw(config, parsed)
    monkeypatch.setattr(dump.shutil, "which", lambda _: "/fake/isabelle")
    commands = []

    def capture(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dump, "run_capture", capture)
    monkeypatch.setattr(checker, "run_check", lambda *a, **k: pytest.fail("no observations"))
    result = dump.run_dump(parsed, output_dir=config.build_dir, session_name="Demo")
    assert result.inspected_dir != old.inspected_dir
    assert commands[0][commands[0].index("-O") + 1] == result.inspected_dir
    assert result.verification is None and not any(f.exists for f in result.facts)
    assert "no matching" in result.evidence_reason
    assert (config.build_dir / "imported" / "thms").exists()
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.NAMED


def test_generated_dump_delegates_to_native_proof_checker(project, monkeypatch):
    config, parsed = project
    monkeypatch.setattr(dump.shutil, "which", lambda _: "/fake/isabelle")

    def capture(command, **kwargs):
        from pathlib import Path

        directory = Path(command[command.index("-O") + 1])
        (directory / "thms").write_text("\x05\x06entity\x06name=Demo.a\x05", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    calls = []

    def native(project, **kwargs):
        calls.append(kwargs)
        return _verified(project)

    monkeypatch.setattr(dump, "run_capture", capture)
    monkeypatch.setattr(checker, "run_check", native)
    result = dump.run_dump(parsed, output_dir=config.build_dir, session_name="Demo")
    assert calls[0]["proof_status"] is True
    assert result.proof_metadata_complete
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.PROVED
    dump.write_dump_report(result, config.dump_report_path)
    _, restored = load_project_with_check(config.project_root)
    assert restored.to_dict() == parsed.to_dict()


@pytest.mark.parametrize("changed", [None, "b" * 64])
def test_dump_context_change_cannot_promote_native_results(project, monkeypatch, changed):
    config, parsed = project
    monkeypatch.setattr(dump.shutil, "which", lambda _: "/fake/isabelle")
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: changed)

    def capture(command, **kwargs):
        from pathlib import Path

        (Path(command[command.index("-O") + 1]) / "thms").write_text(
            "\x05\x06entity\x06name=Demo.a\x05", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(dump, "run_capture", capture)
    monkeypatch.setattr(checker, "run_check", lambda p, **k: _verified(p))
    result = dump.run_dump(parsed, output_dir=config.build_dir, session_name="Demo")
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.STALE
    assert not result.proof_metadata_complete
    dump.write_dump_report(result, config.dump_report_path)
    _, restored = load_project_with_check(config.project_root)
    assert restored.to_dict() == parsed.to_dict()


@pytest.mark.parametrize(
    "field,value",
    [("node_id", "other"), ("fact", "Demo.other"), ("theory", "Other"), ("session", "Other")],
)
def test_raw_identity_cannot_leak_between_nodes(project, field, value):
    config, parsed = project
    result = _raw(config, parsed)
    result.facts[0] = replace(result.facts[0], **{field: value})
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.NAMED
    assert parsed.nodes[0].status.last_checked is None


@pytest.mark.parametrize("kind", ["offline", "failed", "malformed"])
def test_latest_dump_supersedes_old_proof_and_new_check_supersedes_dump(project, kind):
    config, parsed = project
    verified = _verified(parsed)
    checker.write_report(verified, config.check_report_path)
    result = _raw(config, parsed)
    result.previous_checked = {"a": verified.timestamp}
    result.previous_statuses = {"a": "proved"}
    if kind == "failed":
        result.error = "build failed"
    dump.write_dump_report(result, config.dump_report_path)
    if kind == "malformed":
        config.dump_report_path.write_text('{"ran": "true"}', encoding="utf-8")
    # Force a deterministic order on filesystems with coarse write timestamps.
    os.utime(config.check_report_path, ns=(1, 1))
    _, restored = load_project_with_check(config.project_root)
    assert restored.nodes[0].status.formal is (
        FormalStatus.NAMED if kind == "malformed" else FormalStatus.STALE
    )
    assert restored.nodes[0].status.last_checked == (
        None if kind == "malformed" else verified.timestamp
    )
    checker.write_report(verified, config.check_report_path)
    os.utime(config.dump_report_path, ns=(1, 1))
    _, current = load_project_with_check(config.project_root)
    assert current.nodes[0].status.formal is FormalStatus.PROVED


def test_offline_cli_reload_and_mcp_agree(project, capsys):
    from isabelle_blueprint.mcp_server import _SnapshotCache

    config, parsed = project
    raw = _raw(config, parsed)
    assert main(["dump", str(config.project_root), "--from", raw.inspected_dir, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["facts"][0]["proof_status"] is None
    immediate = json.loads(config.project_json_path.read_text(encoding="utf-8"))
    _, restored = load_project_with_check(config.project_root)
    cached = _SnapshotCache().get(config.project_root).project
    assert immediate == restored.to_dict() == cached.to_dict()


@pytest.mark.parametrize(
    "data",
    [
        {"ran": "false"},
        {"ran": False, "facts": ["wrong"]},
        {"ran": False, "previous_statuses": {"a": []}},
        {"ran": False, "verification": {"ran": True, "return_code": "0"}},
    ],
)
def test_malformed_dump_is_rejected(data):
    assert dump.parse_dump_report(data) is None


def test_conflicting_raw_records_are_rejected(project):
    config, parsed = project
    result = _raw(config, parsed)
    data = result.to_dict()
    data["facts"].append({**data["facts"][0], "exists": False})
    assert dump.parse_dump_report(data) is None


@pytest.mark.parametrize(
    "record",
    [
        "\x05\x06entity\x06name=Demo.a\x05",
        "\x05\x06entity\x06name=Demo.a\x06unsupported=proof",
        "\x05\x06entity\x06name=Demo.a\x05oracle Custom.oracle",
    ],
)
def test_incomplete_or_unsupported_metadata_never_proves(project, record):
    config, parsed = project
    directory = config.build_dir / "raw"
    directory.mkdir(parents=True)
    (directory / "thms").write_text(record, encoding="utf-8")
    result = dump.inspect_dump_dir(parsed, directory)
    assert result.facts[0].exists
    assert result.facts[0].proof_status != "proved"
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.STALE


def test_legacy_dump_proved_is_only_historical(project):
    config, parsed = project
    result = _raw(config, parsed)
    result.facts[0].proof_status = "proved"
    dump.write_dump_report(result, config.dump_report_path)
    _, restored = load_project_with_check(config.project_root)
    assert restored.nodes[0].status.formal is FormalStatus.STALE


def test_unreadable_dump_is_inspectable_failure_without_proof(project):
    config, parsed = project
    directory = config.build_dir / "raw"
    directory.mkdir(parents=True)
    (directory / "thms").write_bytes(b"\xff")
    result = dump.inspect_dump_dir(parsed, directory)
    assert "cannot read" in result.error
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.formal is FormalStatus.NAMED


def test_mcp_revalidates_dump_only_proof_on_each_read(project, monkeypatch):
    from isabelle_blueprint.mcp_server import _SnapshotCache

    config, parsed = project
    result = _raw(config, parsed)
    result.ran = True
    result.return_code = 0
    result.verification = _verified(parsed).to_dict()
    dump.write_dump_report(result, config.dump_report_path)
    cache = _SnapshotCache()
    first = cache.get(config.project_root)
    assert first.project.nodes[0].status.formal is FormalStatus.PROVED
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: "b" * 64)
    second = cache.get(config.project_root)
    assert second is not first
    assert second.project.nodes[0].status.formal is FormalStatus.STALE


@pytest.mark.parametrize("outcome", ["not_run", "failed", "invalidated", "missing_context"])
@pytest.mark.parametrize("changed", [None, "node_id", "fact", "theory", "session"])
def test_unsuccessful_verification_keeps_only_exact_reference_history(project, outcome, changed):
    from isabelle_blueprint.evidence import read_evidence_snapshot

    config, parsed = project
    result = _raw(config, parsed)
    result.ran = True
    result.return_code = 0
    historical = "2020-01-01T00:00:00+00:00"
    result.previous_checked = {"a": historical}
    verified = _verified(parsed)
    verified.error = "verification did not complete"
    verified.facts[0].exists = False
    verified.facts[0].proof_status = None
    if outcome == "not_run":
        verified.ran = False
        verified.return_code = None
    elif outcome == "failed":
        verified.return_code = 1
    elif outcome == "invalidated":
        verified.source_context_changed = True
        verified.source_fingerprint = None
    else:
        verified.source_fingerprint = None
    result.verification = verified.to_dict()
    if changed:
        result.facts[0] = replace(result.facts[0], **{changed: "other"})
    expected = None if changed else historical
    dump.apply_dump_report(parsed, result)
    assert parsed.nodes[0].status.last_checked == expected
    dump.write_dump_report(result, config.dump_report_path)
    _, restored = load_project_with_check(config.project_root)
    assert restored.nodes[0].status.last_checked == expected
    snapshot = read_evidence_snapshot(config.project_root)
    assert snapshot["evidence"]["checked_at"] == expected
    assert snapshot["evidence"]["state"] != "current"


@pytest.mark.parametrize("changed", [None, "node_id", "fact", "theory", "session"])
def test_offline_snapshot_time_uses_only_matching_references(project, changed):
    from isabelle_blueprint.evidence import read_evidence_snapshot

    config, parsed = project
    result = _raw(config, parsed)
    historical = "2020-01-01T00:00:00+00:00"
    result.previous_checked = {"a": historical}
    if changed:
        result.facts[0] = replace(result.facts[0], **{changed: "other"})
    dump.write_dump_report(result, config.dump_report_path)
    snapshot = read_evidence_snapshot(config.project_root)
    assert snapshot["evidence"]["checked_at"] == (None if changed else historical)
