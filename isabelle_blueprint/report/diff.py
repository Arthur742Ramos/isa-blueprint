"""Compare a blueprint project against an earlier ``project.json`` snapshot.

``diff`` answers "what changed since the baseline, and did anything regress?".
It compares the *current* parsed-and-checked project against a previously
written ``build/project.json`` (the artefact ``report``/``check`` emit) and
classifies every node as added, removed, or changed.

Regression semantics are explicit rather than relying on an implicit ordering
of formal statuses (see :func:`_is_regression`):

* a node present in the baseline but missing now is always a regression;
* ``proved`` -> anything-but-``proved`` is a regression (a finished proof came
  undone);
* ``found`` -> a *problem* status (``not_found``/``broken``/``failed_check``/
  ``tainted``) is a regression;
* any non-problem status -> a problem status is a regression.

Everything else - blueprint/agent-only changes, forward progress such as
``named`` -> ``found`` -> ``proved``, or a problem status clearing up - counts
as a non-regressing change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES

_PROVED = FormalStatus.PROVED.value
_FOUND = FormalStatus.FOUND.value


@dataclass(frozen=True)
class NodeChange:
    """A node whose status differs between baseline and current."""

    node_id: str
    field: str  # one of "formal", "agent", "blueprint"
    before: str
    after: str
    regression: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "regression": self.regression,
        }


@dataclass(frozen=True)
class BlueprintDiff:
    """The structured result of comparing two project snapshots."""

    project: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changes: list[NodeChange] = field(default_factory=list)

    @property
    def regressions(self) -> list[NodeChange]:
        return [c for c in self.changes if c.regression]

    @property
    def has_regression(self) -> bool:
        return bool(self.removed) or any(c.regression for c in self.changes)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "added": list(self.added),
            "removed": list(self.removed),
            "changes": [c.to_dict() for c in self.changes],
            "regression_count": len(self.regressions) + len(self.removed),
            "has_regression": self.has_regression,
        }


def load_baseline(path: Path) -> dict[str, dict]:
    """Load a baseline ``project.json`` and index its nodes by id.

    Raises :class:`BlueprintError` if the file is missing or not a valid project
    report so the CLI can surface a clean error.
    """
    if not path.exists():
        raise BlueprintError(f"baseline not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlueprintError(f"could not read baseline {path}: {exc}") from exc
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise BlueprintError(
            f"baseline {path} does not look like a project report (no 'nodes' array)"
        )
    indexed: dict[str, dict] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            indexed[node["id"]] = node
    return indexed


def build_diff(baseline_nodes: dict[str, dict], project: BlueprintProject) -> BlueprintDiff:
    """Compare ``project`` against the indexed ``baseline_nodes`` mapping."""
    current = project.by_id()
    baseline_ids = set(baseline_nodes)
    current_ids = set(current)

    added = sorted(current_ids - baseline_ids)
    removed = sorted(baseline_ids - current_ids)

    changes: list[NodeChange] = []
    for node_id in sorted(baseline_ids & current_ids):
        before_status = baseline_nodes[node_id].get("status", {})
        after_status = current[node_id].status
        for field_name, before, after in (
            ("formal", _str(before_status.get("formal")), after_status.formal.value),
            ("agent", _str(before_status.get("agent")), after_status.agent.value),
            ("blueprint", _str(before_status.get("blueprint")), after_status.blueprint.value),
        ):
            if before == after or before == "":
                continue
            regression = field_name == "formal" and _is_regression(before, after)
            changes.append(
                NodeChange(
                    node_id=node_id,
                    field=field_name,
                    before=before,
                    after=after,
                    regression=regression,
                )
            )
    return BlueprintDiff(project=project.name, added=added, removed=removed, changes=changes)


# Healthy "confidence" ladder: a drop to a lower rank is a regression even when
# the destination is not itself a problem status (e.g. losing a located fact).
_CONFIDENCE_RANK = {
    FormalStatus.MISSING.value: 0,
    FormalStatus.NAMED.value: 1,
    FormalStatus.FOUND.value: 2,
    FormalStatus.PROVED.value: 3,
}


def _is_regression(before: str, after: str) -> bool:
    """Classify a formal-status transition as a regression or not."""
    if before == after:
        return False
    before_problem = before in PROBLEM_FORMAL_STATUSES
    after_problem = after in PROBLEM_FORMAL_STATUSES
    # A finished proof coming undone is always a regression.
    if before == _PROVED and after != _PROVED:
        return True
    # A located fact sliding into a problem status is a regression.
    if before == _FOUND and after_problem:
        return True
    # Any healthy status turning into a problem status is a regression.
    if not before_problem and after_problem:
        return True
    # A slide down the healthy confidence ladder (e.g. found -> named/missing,
    # losing an Isabelle reference) is a regression too.
    before_rank = _CONFIDENCE_RANK.get(before)
    after_rank = _CONFIDENCE_RANK.get(after)
    if before_rank is not None and after_rank is not None and after_rank < before_rank:
        return True
    return False


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def render_diff(diff: BlueprintDiff) -> str:
    """Render ``diff`` as a concise human-readable summary (trailing newline).

    Regression markers are painted red through :mod:`console` when colour is
    enabled; the plain-text output is byte-for-byte unchanged when it is not.
    """
    from isabelle_blueprint import console

    regression_tag = console.error("[regression]")
    lines = [f"{diff.project}: {_headline(diff)}"]
    for node_id in diff.added:
        lines.append(f"  + {node_id} (added)")
    for node_id in diff.removed:
        lines.append(f"  - {node_id} (removed) {regression_tag}")
    for change in diff.changes:
        marker = f" {regression_tag}" if change.regression else ""
        lines.append(
            f"  ~ {change.node_id} {change.field}: {change.before} -> {change.after}{marker}"
        )
    return "\n".join(lines) + "\n"


def _headline(diff: BlueprintDiff) -> str:
    from isabelle_blueprint import console

    if not diff.has_changes:
        return "no changes vs baseline"
    regressions = len(diff.regressions) + len(diff.removed)
    regression_text = f"{regressions} regression(s)"
    if regressions:
        regression_text = console.error(regression_text)
    return (
        f"{len(diff.added)} added, "
        f"{len(diff.removed)} removed, "
        f"{len(diff.changes)} changed, "
        f"{regression_text}"
    )
