"""Export ready agent tasks as tracker-importable CSV (``tasks --tracker-export``).

The ``tasks`` command already turns ready nodes into structured proof tasks; this
module reshapes those tasks into the column layout the two most common issue
trackers accept on CSV import:

* **Jira** - ``Summary``/``Issue Type``/``Priority``/``Labels``/``Story Points``/
  ``Description``. Jira splits the single ``Labels`` column on whitespace, so the
  labels we emit are whitespace-free (``priority:high`` etc.).
* **Linear** - ``Title``/``Description``/``Priority``/``Labels``/``Estimate``.
  Linear splits the ``Labels`` column on commas.

Everything is produced with the stdlib :mod:`csv` module and a fixed
``\\n`` line terminator so the output is stable and diff-friendly. No network
access is involved; the CSV is meant to be handed to the tracker's own importer.
"""

from __future__ import annotations

import csv
import io

from isabelle_blueprint.agents.tasks import AgentTask, render_task_prompt

SUPPORTED_TRACKERS = ("jira", "linear")

_PRIORITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}
_DIFFICULTY_ESTIMATE = {"low": 1, "medium": 3, "high": 5}


def _priority(task: AgentTask) -> str:
    raw = task.metadata.priority if task.metadata else "medium"
    return _PRIORITY_LABEL.get(raw, "Medium")


def _estimate(task: AgentTask) -> int:
    raw = task.metadata.difficulty if task.metadata else "medium"
    return _DIFFICULTY_ESTIMATE.get(raw, 3)


def _labels(task: AgentTask) -> list[str]:
    priority = task.metadata.priority if task.metadata else "medium"
    difficulty = task.metadata.difficulty if task.metadata else "medium"
    return [
        "isabelle-blueprint",
        "agent-task",
        f"kind:{task.kind}",
        f"priority:{priority}",
        f"difficulty:{difficulty}",
    ]


def _jira_row(task: AgentTask) -> dict[str, object]:
    return {
        "Summary": f"Formalize {task.title}",
        "Issue Type": "Task",
        "Priority": _priority(task),
        "Labels": " ".join(_labels(task)),
        "Story Points": _estimate(task),
        "Description": render_task_prompt(task),
    }


def _linear_row(task: AgentTask) -> dict[str, object]:
    return {
        "Title": f"Formalize {task.title}",
        "Description": render_task_prompt(task),
        "Priority": _priority(task),
        "Labels": ",".join(_labels(task)),
        "Estimate": _estimate(task),
    }


_TRACKERS = {
    "jira": (
        ["Summary", "Issue Type", "Priority", "Labels", "Story Points", "Description"],
        _jira_row,
    ),
    "linear": (
        ["Title", "Description", "Priority", "Labels", "Estimate"],
        _linear_row,
    ),
}


def render_tracker_csv(tasks: list[AgentTask], tracker: str) -> str:
    """Return the CSV text for ``tasks`` in ``tracker``'s import layout."""
    key = tracker.strip().lower()
    if key not in _TRACKERS:
        supported = ", ".join(SUPPORTED_TRACKERS)
        raise ValueError(f"unsupported tracker {tracker!r}; choose one of: {supported}")
    fieldnames, row_for = _TRACKERS[key]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for task in tasks:
        writer.writerow(row_for(task))
    return buffer.getvalue()
