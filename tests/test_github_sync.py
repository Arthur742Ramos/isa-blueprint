from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.github_sync import (
    ISSUE_MARKER,
    GitHubIssueState,
    body_with_marker,
    pull_github_issue_states,
    sync_github_issues,
)
from isabelle_blueprint.errors import BlueprintError


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
    # A real recovered issue carries the marker this tool injects.
    client.found = {"number": 8, "body": ISSUE_MARKER.format(node_id="a")}

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=tmp_path / "state.json",
        confirm=True,
        client=client,
    )

    assert actions[0].action == "updated"
    assert client.updated[0][1] == 8


def test_github_sync_ignores_unmarked_search_match(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    client = FakeClient()
    # An unrelated issue that merely mentions the node id (no marker) must not be
    # adopted — otherwise sync would clobber a foreign issue.
    client.found = {"number": 99, "body": "Discussion about node a, unrelated."}

    actions = sync_github_issues(
        [_draft()],
        repo="owner/repo",
        state_path=tmp_path / "state.json",
        confirm=True,
        client=client,
    )

    assert actions[0].action == "created"
    assert client.updated == []
    assert client.created and client.created[0][0] == "owner/repo"


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


class _PullClient:
    def __init__(self, issues: dict):
        self.issues = issues

    def get_issue(self, repo: str, issue_number: int):
        item = self.issues.get(issue_number)
        if item is None:
            raise BlueprintError(f"issue {issue_number} not found")
        return item


def _write_state_file(path: Path, mapping: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "nodes": {nid: {"issue_number": n} for nid, n in mapping.items()},
            }
        ),
        encoding="utf-8",
    )


def test_pull_returns_empty_without_state(tmp_path: Path):
    states = pull_github_issue_states(
        tmp_path / "absent.json", repo="owner/repo", client=_PullClient({})
    )
    assert states == []


def test_pull_reports_open_closed_and_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    state_path = tmp_path / "state.json"
    _write_state_file(state_path, {"a": 1, "b": 2, "gone": 3})
    client = _PullClient(
        {
            1: {"state": "open", "html_url": "https://example/1"},
            2: {"state": "closed", "html_url": "https://example/2"},
            # issue 3 is absent -> get_issue raises -> "missing"
        }
    )

    states = pull_github_issue_states(state_path, repo="owner/repo", client=client)

    by_id = {s.node_id: s for s in states}
    assert by_id["a"].state == "open"
    assert by_id["b"].state == "closed"
    assert by_id["b"].url == "https://example/2"
    assert by_id["gone"].state == "missing"
    assert isinstance(states[0], GitHubIssueState)


def test_pull_requires_repo(tmp_path: Path):
    state_path = tmp_path / "state.json"
    _write_state_file(state_path, {"a": 1})

    try:
        pull_github_issue_states(state_path, repo=None, client=_PullClient({1: {"state": "open"}}))
    except BlueprintError as exc:
        assert "repo" in str(exc).lower()
    else:  # pragma: no cover - guard
        raise AssertionError("expected BlueprintError when repo is missing")


def test_pull_requires_token(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    state_path = tmp_path / "state.json"
    _write_state_file(state_path, {"a": 1})

    try:
        pull_github_issue_states(
            state_path, repo="owner/repo", client=_PullClient({1: {"state": "open"}})
        )
    except BlueprintError as exc:
        assert "GITHUB_TOKEN" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected BlueprintError when token is missing")
