"""GitHub issue synchronization for generated proof tasks."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast

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
    labels: list[str] | None = None
    assignees: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GitHubIssueState:
    """Current upstream state of one tracked issue (read-only reconciliation)."""

    node_id: str
    issue_number: int
    state: str  # "open", "closed", or "missing"
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubIssueClient(Protocol):
    def search_issue(self, repo: str, node_id: str) -> dict[str, Any] | None: ...

    def create_issue(self, repo: str, draft: dict[str, Any]) -> dict[str, Any]: ...

    def update_issue(
        self, repo: str, issue_number: int, draft: dict[str, Any]
    ) -> dict[str, Any]: ...

    def close_issue(self, repo: str, issue_number: int) -> dict[str, Any]: ...

    def get_issue(self, repo: str, issue_number: int) -> dict[str, Any]: ...


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

    def close_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            {"state": "closed", "state_reason": "completed"},
        )

    def get_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repo}/issues/{issue_number}")

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
                decoded = json.loads(response.read().decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise BlueprintError(
                        f"GitHub API {method} {path} returned a non-object response"
                    )
                return cast(dict[str, Any], decoded)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise BlueprintError(
                f"GitHub API {method} {path} failed with {exc.code}: {body}"
            ) from exc
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
    completed_node_ids: set[str] | None = None,
) -> list[GitHubSyncAction]:
    """Create/update one issue per task draft.

    Without ``confirm`` this is a local dry-run and performs no network calls.
    """

    state = _load_state(state_path)
    completed_node_ids = set(completed_node_ids or set())
    draft_node_ids = {str(draft["node_id"]) for draft in drafts}
    if not confirm:
        dry_run_actions = [
            GitHubSyncAction(
                node_id=str(draft["node_id"]),
                action="would_update" if str(draft["node_id"]) in state else "would_create",
                issue_number=state.get(str(draft["node_id"])),
                title=str(draft["title"]),
                reason="dry-run; pass --github-sync-confirm to call GitHub",
                labels=[str(label) for label in draft.get("labels", [])],
                assignees=[str(assignee) for assignee in draft.get("assignees", [])],
            )
            for draft in drafts
        ]
        dry_run_actions.extend(
            GitHubSyncAction(
                node_id=node_id,
                action="would_close",
                issue_number=state[node_id],
                title=f"Close completed task {node_id}",
                reason="node is complete and no ready-task draft remains",
            )
            for node_id in sorted(completed_node_ids & set(state) - draft_node_ids)
        )
        return dry_run_actions

    if not repo:
        raise BlueprintError(
            "--repo is required for --github-sync-confirm (or set GITHUB_REPOSITORY)"
        )
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
            if _issue_matches_node(found, node_id):
                assert found is not None  # narrowed by _issue_matches_node
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
                labels=[str(label) for label in draft.get("labels", [])],
                assignees=[str(assignee) for assignee in draft.get("assignees", [])],
            )
        )

    for node_id in sorted(completed_node_ids & set(state) - draft_node_ids):
        issue_number = state[node_id]
        result = active_client.close_issue(repo, issue_number)
        actions.append(
            GitHubSyncAction(
                node_id=node_id,
                action="closed",
                issue_number=issue_number,
                title=f"Close completed task {node_id}",
                url=result.get("html_url"),
                reason="node is complete and no ready-task draft remains",
            )
        )
        del state[node_id]

    _write_state(state_path, state)
    return actions


def pull_github_issue_states(
    state_path: Path,
    *,
    repo: str | None,
    token_env: str = "GITHUB_TOKEN",
    client: GitHubIssueClient | None = None,
) -> list[GitHubIssueState]:
    """Fetch the current open/closed state of every tracked issue from GitHub.

    This is the read side of the sync and is strictly **read-only**: it never
    mutates GitHub issues or the blueprint. It reconciles the persistent
    node->issue map against GitHub so callers can see which proof tasks have been
    closed (done) upstream — a deleted/unreachable issue is reported as
    ``"missing"`` rather than raising.
    """
    state = _load_state(state_path)
    if not state:
        return []
    if not repo:
        raise BlueprintError(
            "--repo is required to pull GitHub issue state (or set GITHUB_REPOSITORY)"
        )
    token = os.environ.get(token_env)
    if not token:
        raise BlueprintError(f"{token_env} is not set; refusing to query GitHub issues")
    active_client = client or GitHubApiClient(token)

    results: list[GitHubIssueState] = []
    for node_id, issue_number in sorted(state.items()):
        try:
            issue = active_client.get_issue(repo, issue_number)
        except BlueprintError:
            results.append(GitHubIssueState(node_id, issue_number, "missing"))
            continue
        if not isinstance(issue, dict):
            results.append(GitHubIssueState(node_id, issue_number, "missing"))
            continue
        state_value = str(issue.get("state") or "missing")
        url = issue.get("html_url")
        results.append(
            GitHubIssueState(
                node_id,
                issue_number,
                state_value,
                url if isinstance(url, str) else None,
            )
        )
    return results


def body_with_marker(body: str, node_id: str) -> str:
    marker = ISSUE_MARKER.format(node_id=node_id)
    if marker in body:
        return body
    return f"{marker}\n\n{body}"


def _issue_matches_node(issue: dict[str, Any] | None, node_id: str) -> bool:
    """Return ``True`` only when a searched issue is safe to adopt for ``node_id``.

    GitHub's free-text issue search matches anywhere in the title/body, so it can
    return an unrelated issue that merely mentions the node id (or the literal
    ``isabelle-blueprint:task`` string). Reusing such an issue would update — or,
    once the node completes, *close* — a foreign issue. We therefore only adopt
    an issue whose body carries the exact machine marker this tool injects.
    """
    if not isinstance(issue, dict) or "number" not in issue:
        return False
    marker = ISSUE_MARKER.format(node_id=node_id)
    return marker in (issue.get("body") or "")


def _issue_payload(draft: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "title": draft["title"],
        "body": draft["body"],
        "labels": list(draft.get("labels", [])),
    }
    assignees = list(draft.get("assignees", []))
    if assignees:
        payload["assignees"] = assignees
    return payload


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
    # Write to a temp sibling then atomically rename, so a concurrent reader
    # never observes a half-written file (mirrors write_agent_memory /
    # write_assignments).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
