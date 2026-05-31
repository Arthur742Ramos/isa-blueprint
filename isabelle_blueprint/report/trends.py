"""Trend history storage for v0.8 trend charts.

Each run of ``isabelle-blueprint report`` (and ``web``) appends an entry to
``build/trends.json`` so the static site can render a line chart of how
coverage and the problem count are moving over time.

The store is intentionally dumb:

* JSON list, newest-first.
* Bounded to 500 entries; older entries are dropped on insert.
* Deduped by ``(commit_sha, branch)`` keeping the most recently observed run.
  This way a CI matrix that re-runs the same commit replaces rather than
  duplicates the entry.

CI metadata (``commit_sha`` / ``branch``) is auto-detected from
``GITHUB_SHA`` / ``GITHUB_REF_NAME`` when not supplied. When neither is
available we keep the entry but tag it as ``local``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import build_status_metrics

MAX_TREND_ENTRIES = 500
TREND_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ci_meta(
    *, commit_sha: str | None, branch: str | None
) -> tuple[str | None, str | None]:
    sha = commit_sha if commit_sha is not None else os.environ.get("GITHUB_SHA")
    ref = branch if branch is not None else os.environ.get("GITHUB_REF_NAME")
    return (sha or None, ref or None)


def load_trends(path: Path) -> list[dict[str, Any]]:
    """Read the trend history from ``path``.

    Returns an empty list when the file does not exist or contains malformed
    content; the report pipeline is best-effort and must never blow up on a
    corrupted history file written by an older version.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        entries = data.get("entries")
    else:
        entries = data
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _entry_key(entry: dict[str, Any]) -> tuple[str, str] | None:
    sha = entry.get("commit_sha")
    branch = entry.get("branch")
    if isinstance(sha, str) and sha:
        return (sha, branch or "")
    return None


def append_trend_entry(
    project: BlueprintProject,
    path: Path,
    *,
    commit_sha: str | None = None,
    branch: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Append a single trend entry for ``project`` to ``path``.

    Returns the entry that was written. Older entries with the same
    ``(commit_sha, branch)`` key are removed first so a re-run of the same
    commit on the same branch overwrites the previous data point.
    """
    metrics = build_status_metrics(project)
    sha, ref = _ci_meta(commit_sha=commit_sha, branch=branch)
    timestamp = now or _now_iso()
    entry: dict[str, Any] = {
        "timestamp": timestamp,
        "commit_sha": sha,
        "branch": ref,
        "coverage_percent": metrics.coverage_percent,
        "node_count": metrics.node_count,
        "formal_target_count": metrics.formal_target_count,
        "proved_count": metrics.proved_count,
        "found_count": metrics.found_count,
        "problem_count": metrics.problem_count,
        "stale_count": metrics.stale_count,
        "has_cycles": metrics.has_cycles,
    }

    history = load_trends(path)
    key = _entry_key(entry)
    if key is not None:
        history = [e for e in history if _entry_key(e) != key]
    history.append(entry)

    if len(history) > MAX_TREND_ENTRIES:
        history = history[-MAX_TREND_ENTRIES:]

    payload = {
        "schema_version": TREND_SCHEMA_VERSION,
        "entries": history,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return entry
