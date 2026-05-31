"""Post or update a Pull Request status comment.

This module is deliberately self-contained: it uses only the standard
library (``urllib``) so the runtime dependency footprint stays at PyYAML
+ Jinja2. When ``GITHUB_TOKEN`` / ``GH_TOKEN`` and the GitHub event
payload are available, ``post_or_update_pr_comment`` posts a single,
idempotent status comment on the current pull request, keyed by a
hidden HTML marker. When the context is missing, it returns a
``ResultStatus`` instead of raising — running the CLI locally must not
fail just because there's no PR in scope.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics

#: HTML marker hidden inside the comment body so that subsequent runs can
#: locate and update the same comment instead of spamming new ones.
COMMENT_MARKER = "<!-- isabelle-blueprint:status -->"

#: Status indicating why a comment was (not) posted.
ResultKind = str  # "posted" | "updated" | "skipped"


@dataclass(frozen=True)
class CommentResult:
    """Outcome of a ``post_or_update_pr_comment`` invocation."""

    status: ResultKind
    reason: str = ""
    url: str | None = None


def _read_event_pr_number(event_path: str | None) -> int | None:
    """Extract the PR number from the GitHub Actions event payload."""
    if not event_path:
        return None
    try:
        with open(event_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    pr = data.get("pull_request")
    if isinstance(pr, dict):
        number = pr.get("number")
        if isinstance(number, int):
            return number
    issue = data.get("issue")
    if isinstance(issue, dict) and isinstance(issue.get("pull_request"), dict):
        number = issue.get("number")
        if isinstance(number, int):
            return number
    number = data.get("number")
    return number if isinstance(number, int) else None


def build_comment_body(
    project: BlueprintProject,
    metrics: StatusMetrics | None = None,
    *,
    commit_sha: str | None = None,
) -> str:
    """Build the markdown body for the status comment.

    Always starts with :data:`COMMENT_MARKER` so the update path can
    locate the previous comment in subsequent runs.
    """
    if metrics is None:
        metrics = build_status_metrics(project)
    coverage = "n/a" if metrics.coverage_percent is None else f"{metrics.coverage_percent}%"
    lines: list[str] = [
        COMMENT_MARKER,
        f"## 📐 IsabelleBlueprint status — `{project.name}`",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Nodes | {metrics.node_count} |",
        f"| Formal targets | {metrics.formal_target_count} |",
        f"| Proved | {metrics.proved_count} |",
        f"| Found (not yet proved) | {metrics.found_count} |",
        f"| Problems | {metrics.problem_count} |",
        f"| Stale | {metrics.stale_count} |",
        f"| Coverage | {coverage} |",
    ]
    if metrics.has_cycles:
        lines.append("")
        lines.append("> ⚠️ Dependency graph has cycles.")
    if metrics.has_problems:
        lines.append("")
        lines.append("> ❌ One or more formal targets are in a problem state.")
    if commit_sha:
        lines.append("")
        lines.append(f"<sub>commit `{commit_sha[:8]}`</sub>")
    return "\n".join(lines) + "\n"


def _gh_request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Make a single GitHub REST request and return ``(status, json|None)``."""
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "isabelle-blueprint",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read().decode("utf-8") or "null"
            return resp.status, json.loads(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, payload


def _find_existing_comment(
    repo: str, pr_number: int, token: str, opener=_gh_request
) -> int | None:
    """Page through the PR's issue comments looking for our marker."""
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
            f"?per_page=100&page={page}"
        )
        status, body = opener(url, token, method="GET")
        if status != 200 or not isinstance(body, list):
            return None
        for comment in body:
            if not isinstance(comment, dict):
                continue
            text = comment.get("body") or ""
            if COMMENT_MARKER in text:
                cid = comment.get("id")
                if isinstance(cid, int):
                    return cid
        if len(body) < 100:
            return None
        page += 1


def post_or_update_pr_comment(
    project: BlueprintProject,
    *,
    repo: str | None = None,
    pr_number: int | None = None,
    token: str | None = None,
    event_path: str | None = None,
    commit_sha: str | None = None,
    opener=_gh_request,
) -> CommentResult:
    """Post or update the status comment on a pull request.

    All arguments fall back to environment variables when missing:

    * ``repo``         -> ``GITHUB_REPOSITORY``
    * ``token``        -> ``GITHUB_TOKEN`` then ``GH_TOKEN``
    * ``event_path``   -> ``GITHUB_EVENT_PATH`` (used to derive ``pr_number``)
    * ``commit_sha``   -> ``GITHUB_SHA``

    Missing context produces a ``CommentResult(status="skipped", reason=...)``
    rather than raising; the caller can decide whether to treat that as an
    error. ``opener`` is injectable to make the function testable without
    network access.
    """
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    event_path = event_path or os.environ.get("GITHUB_EVENT_PATH")
    commit_sha = commit_sha or os.environ.get("GITHUB_SHA")
    if pr_number is None:
        pr_number = _read_event_pr_number(event_path)

    if not repo:
        return CommentResult(status="skipped", reason="missing GITHUB_REPOSITORY")
    if not token:
        return CommentResult(status="skipped", reason="missing GITHUB_TOKEN / GH_TOKEN")
    if not pr_number:
        return CommentResult(status="skipped", reason="no pull request number resolved")

    body = build_comment_body(project, commit_sha=commit_sha)
    existing = _find_existing_comment(repo, pr_number, token, opener=opener)

    if existing is None:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        status, payload = opener(url, token, method="POST", body={"body": body})
        if status in (200, 201) and isinstance(payload, dict):
            return CommentResult(
                status="posted",
                url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
            )
        return CommentResult(status="skipped", reason=f"create failed ({status})")

    url = f"https://api.github.com/repos/{repo}/issues/comments/{existing}"
    status, payload = opener(url, token, method="PATCH", body={"body": body})
    if status in (200, 201) and isinstance(payload, dict):
        return CommentResult(
            status="updated",
            url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
        )
    return CommentResult(status="skipped", reason=f"update failed ({status})")


def write_pr_comment_preview(project: BlueprintProject, path: Path) -> Path:
    """Write the would-be PR comment body to ``path`` for offline inspection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = build_comment_body(project, commit_sha=os.environ.get("GITHUB_SHA"))
    path.write_text(body, encoding="utf-8")
    return path
