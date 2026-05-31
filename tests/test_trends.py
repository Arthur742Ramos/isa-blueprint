"""Tests for the v0.8 trend history store."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report import trends as trends_mod
from isabelle_blueprint.report.trends import (
    MAX_TREND_ENTRIES,
    TREND_SCHEMA_VERSION,
    append_trend_entry,
    load_trends,
)


def _project():
    a = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        isabelle=IsabelleRef(fact="Demo.a"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    b = BlueprintNode(
        id="lem-b",
        kind=NodeKind.LEMMA,
        title="B",
        uses=["def-a"],
        isabelle=IsabelleRef(fact="Demo.b"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.PROVED),
    )
    return BlueprintProject.from_nodes("smoke", [a, b])


def test_load_trends_returns_empty_when_file_missing(tmp_path: Path):
    assert load_trends(tmp_path / "missing.json") == []


def test_load_trends_returns_empty_when_file_malformed(tmp_path: Path):
    path = tmp_path / "trends.json"
    path.write_text("not json{", encoding="utf-8")
    assert load_trends(path) == []


def test_load_trends_accepts_bare_list_legacy_payload(tmp_path: Path):
    path = tmp_path / "trends.json"
    entry = {"timestamp": "2025-01-01T00:00:00Z", "coverage_percent": 10}
    path.write_text(json.dumps([entry]), encoding="utf-8")
    assert load_trends(path) == [entry]


def test_append_trend_entry_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    path = tmp_path / "trends.json"

    entry = append_trend_entry(
        _project(),
        path,
        commit_sha="abc1234",
        branch="main",
        now="2025-02-03T04:05:06Z",
    )

    assert entry["commit_sha"] == "abc1234"
    assert entry["branch"] == "main"
    assert entry["timestamp"] == "2025-02-03T04:05:06Z"
    # Metric pass-through.
    assert entry["node_count"] == 2
    assert entry["proved_count"] == 1
    assert "coverage_percent" in entry

    loaded = load_trends(path)
    assert loaded == [entry]

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == TREND_SCHEMA_VERSION


def test_append_trend_entry_dedupes_by_commit_and_branch(tmp_path: Path):
    path = tmp_path / "trends.json"
    project = _project()

    first = append_trend_entry(
        project,
        path,
        commit_sha="sha1",
        branch="main",
        now="2025-01-01T00:00:00Z",
    )
    second = append_trend_entry(
        project,
        path,
        commit_sha="sha1",
        branch="main",
        now="2025-01-01T01:00:00Z",
    )
    other = append_trend_entry(
        project,
        path,
        commit_sha="sha2",
        branch="main",
        now="2025-01-01T02:00:00Z",
    )

    loaded = load_trends(path)
    # Only the latest (sha1, main) entry survives, plus sha2.
    assert [e["timestamp"] for e in loaded] == [second["timestamp"], other["timestamp"]]
    assert first not in loaded


def test_append_trend_entry_dedupe_only_when_commit_present(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    path = tmp_path / "trends.json"
    project = _project()

    append_trend_entry(project, path, now="2025-01-01T00:00:00Z")
    append_trend_entry(project, path, now="2025-01-01T01:00:00Z")

    loaded = load_trends(path)
    # No commit SHA => no dedupe; both entries kept.
    assert len(loaded) == 2


def test_append_trend_entry_caps_history(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trends_mod, "MAX_TREND_ENTRIES", 5)
    path = tmp_path / "trends.json"
    project = _project()

    for i in range(7):
        append_trend_entry(
            project,
            path,
            commit_sha=f"sha-{i}",
            branch="main",
            now=f"2025-01-01T00:00:0{i}Z",
        )

    loaded = load_trends(path)
    assert len(loaded) == 5
    # The two earliest entries (sha-0, sha-1) were dropped.
    shas = [e["commit_sha"] for e in loaded]
    assert shas == ["sha-2", "sha-3", "sha-4", "sha-5", "sha-6"]


def test_append_trend_entry_reads_github_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "envsha")
    monkeypatch.setenv("GITHUB_REF_NAME", "envbranch")
    path = tmp_path / "trends.json"

    entry = append_trend_entry(_project(), path, now="2025-03-01T00:00:00Z")

    assert entry["commit_sha"] == "envsha"
    assert entry["branch"] == "envbranch"


def test_max_trend_entries_default_is_500():
    """Guard against an accidental change to the default cap."""
    assert MAX_TREND_ENTRIES == 500
