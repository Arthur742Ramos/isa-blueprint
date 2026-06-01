"""GitHub issue synchronization for generated proof tasks."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from isabelle_blueprint.errors import BlueprintError

ISSUE_MARKER = "<!-- isabelle-blueprint:task node_id={node_id} -->"


@dataclass
class GitHubSyncAction:
    node_id: str
    action: str
    title: str
    issue_number: int | None = None
    url: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubIssueClient(Protocol):
    def search_issue(self, repo: str, node_id: str) -> dict[str, Any] | None: ...

    def create_issue(self, repo: str, draft: dict[str, Any]) -> dict[str, Any]: ...

    def update_issue(self, repo: str, issue_number: int, draft: dict[str, Any]) -> dict[str, Any]: ...


class GitHubApiClient:
    def __init__(self, token: str, *, api_url: str = "https://api.github.com") -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")

    def search_issue(self, repo: str, node_id: str) -> dict[str, Any] | None:
        query = f'repo:{repo} type:issue "isabelle-blueprint:task" "{node_id}"'
        payload = self._request("GET", f"/search/issues?q={urllib.parse.quote(query)}")
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return items[0] if items else None

    def create_issue(self, repo: str, draft: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/repos/{repo}/issues", _issue_payload(draft))

    def update_issue(self, repo: str, issue_number: int, draft: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/repos/{repo}/issues/{issue_number}", _issue_payload(draft))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.api_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "isabelle-blueprint",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise BlueprintError(f"GitHub API {method} {path} failed with {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise BlueprintError(f"GitHub API {method} {path} failed: {exc.reason}") from exc


def sync_github_issues(
    drafts: list[dict[str, Any]],
    *,
    repo: str | None,
    state_path: Path,
    token_env: str = "GITHUB_TOKEN",
    confirm: bool = False,
    client: GitHubIssueClient | None = None,
) -> list[GitHubSyncAction]:
    """Create/update one issue per task draft.

    Without ``confirm`` this is a local dry-run and performs no network calls.
    """

    state = _load_state(state_path)
    if not confirm:
        return [
            GitHubSyncAction(
                node_id=str(draft["node_id"]),
                action="would_update" if str(draft["node_id"]) in state else "would_create",
                issue_number=state.get(str(draft["node_id"])),
                title=str(draft["title"]),
                reason="dry-run; pass --github-sync-confirm to call GitHub",
            )
            for draft in drafts
        ]

    if not repo:
        raise BlueprintError("--repo is required for --github-sync-confirm (or set GITHUB_REPOSITORY)")
    token = os.environ.get(token_env)
    if not token:
        raise BlueprintError(f"{token_env} is not set; refusing to sync GitHub issues")
    active_client = client or GitHubApiClient(token)
    actions: list[GitHubSyncAction] = []

    for draft in drafts:
        node_id = str(draft["node_id"])
        issue_number = state.get(node_id)
        if issue_number is None:
            found = active_client.search_issue(repo, node_id)
            if found is not None and "number" in found:
                issue_number = int(found["number"])
        body = body_with_marker(str(draft["body"]), node_id)
        sync_draft = {**draft, "body": body}
        if issue_number is None:
            result = active_client.create_issue(repo, sync_draft)
            action = "created"
        else:
            result = active_client.update_issue(repo, issue_number, sync_draft)
            action = "updated"
        number = int(result.get("number") or issue_number or 0)
        state[node_id] = number
        actions.append(
            GitHubSyncAction(
                node_id=node_id,
                action=action,
                issue_number=number,
                title=str(draft["title"]),
                url=result.get("html_url"),
            )
        )

    _write_state(state_path, state)
    return actions


def body_with_marker(body: str, node_id: str) -> str:
    marker = ISSUE_MARKER.format(node_id=node_id)
    if marker in body:
        return body
    return f"{marker}\n\n{body}"


def _issue_payload(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": draft["title"],
        "body": draft["body"],
        "labels": list(draft.get("labels", [])),
    }


def _load_state(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlueprintError(f"could not read GitHub sync state at {path}: {exc}") from exc
    nodes = data.get("nodes", {}) if isinstance(data, dict) else {}
    if not isinstance(nodes, dict):
        raise BlueprintError("GitHub sync state `nodes` must be an object")
    state: dict[str, int] = {}
    for node_id, item in nodes.items():
        if isinstance(item, dict) and isinstance(item.get("issue_number"), int):
            state[str(node_id)] = int(item["issue_number"])
    return state


def _write_state(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "nodes": {
            node_id: {"issue_number": issue_number}
            for node_id, issue_number in sorted(state.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
