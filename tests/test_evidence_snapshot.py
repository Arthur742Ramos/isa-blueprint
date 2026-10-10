"""Canonical snapshots preserve planning semantics and explain proof evidence."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime

import jsonschema
import pytest

from isabelle_blueprint.cli import main
from isabelle_blueprint.evidence import read_evidence_snapshot
from isabelle_blueprint.explain import explain_project
from isabelle_blueprint.isabelle import check_cache, check_context, checker, dump
from isabelle_blueprint.project_io import load_project, load_project_with_check
from isabelle_blueprint.schemas import read_schema


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "blueprint.md").write_text(
        "::: lemma {#a}\nisabelle: Demo.a\nstatus:\n  formal: proved\n\nA\n:::\n"
        "::: lemma {#b}\nisabelle: Demo.b\nuses: [a]\nstatus:\n  formal: named\n\nB\n:::\n",
        encoding="utf-8",
    )
    config, parsed = load_project(tmp_path)
    calls = []
    monkeypatch.setattr(
        check_context, "project_fingerprint", lambda *a, **k: calls.append(k) or "a" * 64
    )
    monkeypatch.setattr(checker, "run_check", lambda *a, **k: pytest.fail("read must not build"))
    result = checker.CheckResult(
        ran=True,
        return_code=0,
        proof_checked=True,
        source_fingerprint="a" * 64,
        node_fingerprints={
            n.id: check_cache.compute_node_hash(n, context="a" * 64) for n in parsed.nodes
        },
        facts=[
            checker.FactCheck(n.id, n.isabelle.fact, "Demo", True, proof_status="proved")
            for n in parsed.nodes
        ],
    )
    return config, result, calls


def _files(root):
    return {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def _stable(payload):
    return {k: v for k, v in payload.items() if k != "observed_at"}


def _validate(payload):
    jsonschema.validate(payload, json.loads(read_schema("snapshot")))


def test_authored_claims_without_evidence_keep_frozen_planning_metrics(project):
    config, _, calls = project
    before = _files(config.project_root)
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["state"] == "absent"
    assert payload["node_evidence"]["a"]["authored_formal_claim"] == "proved"
    assert payload["node_evidence"]["a"]["origin"] == "authored"
    assert payload["metrics"]["proved_count"] == 1 and payload["ready_task_ids"] == ["b"]
    assert not calls and _files(config.project_root) == before
    _validate(payload)


def test_current_evidence_probes_once_per_read_and_never_writes(project):
    config, result, calls = project
    checker.write_report(result, config.check_report_path)
    before = _files(config.project_root)
    payload = read_evidence_snapshot(config.project_root)
    assert len(calls) == 1
    assert payload["evidence"]["state"] == "current"
    assert payload["metrics"]["proved_count"] == 2 and not payload["ready_task_ids"]
    assert payload["evidence"]["checked_at"] == result.timestamp
    assert payload["observed_at"] != result.timestamp
    assert datetime.fromisoformat(payload["observed_at"]).tzinfo
    assert _files(config.project_root) == before
    read_evidence_snapshot(config.project_root)
    assert len(calls) == 2
    _validate(payload)


@pytest.mark.parametrize(
    "current,state", [(None, "probe_unavailable"), ("b" * 64, "source_changed")]
)
def test_changed_and_unavailable_native_contexts_are_distinct(project, monkeypatch, current, state):
    config, result, _ = project
    checker.write_report(result, config.check_report_path)
    monkeypatch.setattr(check_context, "project_fingerprint", lambda *a, **k: current)
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["state"] == state
    assert payload["metrics"]["stale_count"] == 2 and payload["metrics"]["proved_count"] == 0
    assert payload["ready_task_ids"] == ["a"]
    assert payload["node_evidence"]["a"]["checked_at"] == result.timestamp
    _, loaded = load_project_with_check(config.project_root)
    explained = explain_project(loaded)[0]
    assert payload["evidence"]["reason"] in explained.reasons
    if current is None:
        assert any("executable" in step for step in explained.next_steps)


@pytest.mark.parametrize("kind", ["legacy", "malformed", "incomplete"])
def test_saved_artifact_diagnostics_preserve_details(project, kind):
    config, result, _ = project
    if kind == "legacy":
        result.source_fingerprint = None
    elif kind == "incomplete":
        result.ran = False
        result.return_code = None
        result.error = "session failed: missing imported theory"
        for fact in result.facts:
            fact.exists = False
            fact.proof_status = None
    checker.write_report(result, config.check_report_path)
    if kind == "malformed":
        config.check_report_path.write_text("{ broken", encoding="utf-8")
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["state"] == kind
    assert payload["evidence"]["reason"]
    if kind == "malformed":
        assert "line 1" in payload["evidence"]["reason"]
    if kind == "incomplete":
        _, loaded = load_project_with_check(config.project_root)
        assert result.error in explain_project(loaded)[0].reasons


def test_changed_node_reference_does_not_taint_other_current_node(project):
    config, result, _ = project
    checker.write_report(result, config.check_report_path)
    source = config.blueprint_paths[0]
    source.write_text(
        source.read_text(encoding="utf-8").replace("Demo.b", "Demo.new"), encoding="utf-8"
    )
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["state"] == "node_changed"
    assert payload["node_evidence"]["a"]["state"] == "current"
    assert payload["node_evidence"]["a"]["reason"] is None
    assert payload["node_evidence"]["b"]["state"] == "node_changed"
    assert payload["node_evidence"]["b"]["checked_at"] is None


def test_offline_dump_remains_historical(project):
    config, _, _ = project
    result = dump.DumpResult(ran=False, facts=[dump.DumpFact("a", "Demo.a", "Demo", True)])
    dump.write_dump_report(result, config.dump_report_path)
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["origin"] == "dump" and payload["evidence"]["state"] == "offline"
    assert payload["project"]["nodes"][0]["status"]["formal"] == "stale"


def test_cli_mcp_tool_resource_and_schema_agree(project, capsys):
    from mcp.types import AnyUrl

    from isabelle_blueprint.mcp_server import build_server

    config, result, calls = project
    checker.write_report(result, config.check_report_path)
    assert main(["snapshot", str(config.project_root), "--json"]) == 0
    cli = json.loads(capsys.readouterr().out)
    server = build_server(config.project_root)
    _, mcp = asyncio.run(server.call_tool("evidence_snapshot", {}))
    resource = list(asyncio.run(server.read_resource(AnyUrl("blueprint://evidence"))))
    assert _stable(cli) == _stable(mcp) == _stable(json.loads(resource[0].content))
    assert len(calls) == 3
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools["evidence_snapshot"].annotations.readOnlyHint
    assert "schema_version" in tools["evidence_snapshot"].outputSchema["required"]
    _validate(mcp)


def test_stdio_transport_without_generated_artifacts(project):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    config, _, _ = project
    before = _files(config.project_root)

    async def client():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "isabelle_blueprint.mcp_server", "--project-dir", str(config.project_root)],
        )
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("evidence_snapshot", arguments={})
                    assert not result.isError
                    return result.structuredContent

    payload = asyncio.run(client())
    assert payload["evidence"]["state"] == "absent"
    _validate(payload)
    assert _files(config.project_root) == before


def test_unavailable_checker_preserves_diagnostic_and_no_evidence_time(project):
    config, result, _ = project
    result.ran = False
    result.return_code = None
    result.source_fingerprint = None
    result.error = "Isabelle executable 'missing' not found on PATH; skipped build"
    checker.write_report(result, config.check_report_path)
    payload = read_evidence_snapshot(config.project_root)
    assert payload["evidence"]["state"] == "incomplete"
    assert payload["evidence"]["reason"] == result.error
    assert payload["node_evidence"]["a"]["checked_at"] is None
    _, loaded = load_project_with_check(config.project_root)
    assert any("executable" in step for step in explain_project(loaded)[0].next_steps)
