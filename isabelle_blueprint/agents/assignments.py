"""Ownership tracking for blueprint proof tasks.

A lightweight store mapping a node id to the person/agent responsible for it,
plus an optional free-form note and a timestamp. Like agent memory and the
GitHub sync state, this lives outside generated ``build/`` artefacts (default
``.isabelle-blueprint/assignments.json``) so ownership survives reruns and is
shared via version control if the team wants.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from isabelle_blueprint.errors import BlueprintError

ASSIGNMENTS_SCHEMA_VERSION = 1


def now_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Assignment:
    """A single node-id -> owner record."""

    owner: str
    note: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Assignment:
        return cls(
            owner=str(data.get("owner") or ""),
            note=str(data.get("note") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssignmentStore:
    """All node assignments keyed by node id."""

    nodes: dict[str, Assignment] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssignmentStore:
        version = data.get("schema_version")
        if version != ASSIGNMENTS_SCHEMA_VERSION:
            raise BlueprintError(
                f"unsupported assignments schema_version {version!r}; "
                f"expected {ASSIGNMENTS_SCHEMA_VERSION}"
            )
        raw_nodes = data.get("nodes", {})
        if not isinstance(raw_nodes, dict):
            raise BlueprintError("assignments `nodes` must be an object")
        return cls(
            nodes={
                str(node_id): Assignment.from_dict(node_data)
                for node_id, node_data in raw_nodes.items()
                if isinstance(node_data, dict)
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ASSIGNMENTS_SCHEMA_VERSION,
            "nodes": {
                node_id: assignment.to_dict()
                for node_id, assignment in sorted(self.nodes.items())
            },
        }


def load_assignments(path: Path, *, strict: bool = False) -> AssignmentStore:
    if not path.exists():
        return AssignmentStore()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise BlueprintError("assignments must be a JSON object")
        return AssignmentStore.from_dict(data)
    except (OSError, json.JSONDecodeError, BlueprintError) as exc:
        if strict:
            if isinstance(exc, BlueprintError):
                raise
            raise BlueprintError(f"could not read assignments at {path}: {exc}") from exc
        warnings.warn(f"ignoring unreadable assignments at {path}: {exc}", stacklevel=2)
        return AssignmentStore()


def write_assignments(store: AssignmentStore, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp sibling then atomically rename, so a concurrent reader
    # (e.g. the MCP ``list_assignments`` tool / resource) never observes a
    # half-written file and treats it as corrupt.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def set_assignment(
    store: AssignmentStore, node_id: str, owner: str, *, note: str = ""
) -> Assignment:
    """Create or overwrite the assignment for ``node_id`` and return it."""
    assignment = Assignment(owner=owner, note=note, updated_at=now_timestamp())
    store.nodes[node_id] = assignment
    return assignment


def clear_assignment(store: AssignmentStore, node_id: str) -> bool:
    """Remove the assignment for ``node_id``; return ``True`` if one existed."""
    return store.nodes.pop(node_id, None) is not None
