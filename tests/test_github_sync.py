from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.github_sync import body_with_marker, sync_github_issues


class FakeClient:
    def __init__(self):
        self.created = []
        self.updated = []
        self.found = None

    def search_issue(self, repo: str, node_id: str):
        return self.found

    def create_issue(self, repo: str, draft):
        self.created.append((repo, draft))
        return {"number": 10, "html_url": "https://example/10"}

    def update_issue(self, repo: str, issue_number: int, draft):
        self.updated.append((repo, issue_number, draft))
        return {"number": issue_number, "html_url": f"https://example/{issue_number}"}

    def close_issue(self, repo: str, issue_number: int):
        return {"number": issue_number, "html_url": f"https://example/{issue_number}"}


def _draft(node_id="a"):
    return {
        "node_id": node_id,
        "task_id": f"task-{node_id}",
        "title": "Formalize A",
        "body": "body",
        "labels": [],
    }


def test_github_sync_dry_run_makes_no_network_calls(tmp_path: Path):
    client = FakeClient()

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=tmp_path / "state.json",
        confirm=False,
        client=client,
    )

    assert actions[0].action == "would_create"
    assert client.created == []
    assert client.updated == []


def test_github_sync_updates_state_after_create(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    client = FakeClient()
    state_path = tmp_path / "state.json"

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=state_path,
        confirm=True,
        client=client,
    )

    assert actions[0].action == "created"
    assert body_with_marker("body", "a") == client.created[0][1]["body"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["nodes"]["a"]["issue_number"] == 10


def test_github_sync_uses_existing_state_for_update(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "nodes": {"a": {"issue_number": 7}}}),
        encoding="utf-8",
    )
    client = FakeClient()

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=state_path,
        confirm=True,
        client=client,
    )

    assert actions[0].action == "updated"
    assert client.updated[0][1] == 7


def test_github_sync_recovers_by_search_when_state_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    client = FakeClient()
    client.found = {"number": 8}

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=tmp_path / "state.json",
        confirm=True,
        client=client,
    )

    assert actions[0].action == "updated"
    assert client.updated[0][1] == 8


def test_github_sync_dry_run_surfaces_completed_issue_close_hint(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "nodes": {"done": {"issue_number": 7}}}),
        encoding="utf-8",
    )

    actions = sync_github_issues(
        [],
        repo="owner/repo",
        state_path=state_path,
        confirm=False,
        completed_node_ids={"done"},
    )

    assert actions[0].action == "would_close"
    assert actions[0].issue_number == 7


def test_github_sync_confirmed_close_removes_completed_issue_from_state(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "nodes": {"done": {"issue_number": 7}}}),
        encoding="utf-8",
    )

    actions = sync_github_issues(
        [],
        repo="owner/repo",
        state_path=state_path,
        confirm=True,
        client=FakeClient(),
        completed_node_ids={"done"},
    )

    assert actions[0].action == "closed"
    assert actions[0].issue_number == 7
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["nodes"] == {}
