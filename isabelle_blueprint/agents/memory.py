"""Versioned memory for proof-task attempts.

The memory file is intentionally separate from generated ``build/`` artefacts:
it records human/agent experience that is useful across reruns, machines, and
CI jobs.  The default location is ``.isabelle-blueprint/agent-memory.json``.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.node import BlueprintNode

MEMORY_SCHEMA_VERSION = 1
DEFAULT_MAX_ATTEMPTS_PER_NODE = 20
VALID_OUTCOMES = {"note", "blocked", "failed", "succeeded", "needs_human"}


@dataclass
class AgentMemoryAttempt:
    timestamp: str
    outcome: str
    summary: str
    actor: str | None = None
    tool: str | None = None
    details: str = ""
    next_step: str | None = None
    input_hash: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentMemoryAttempt:
        return cls(
            timestamp=str(data.get("timestamp") or ""),
            outcome=str(data.get("outcome") or "note"),
            summary=str(data.get("summary") or ""),
            actor=data.get("actor"),
            tool=data.get("tool"),
            details=str(data.get("details") or ""),
            next_step=data.get("next_step"),
            input_hash=data.get("input_hash"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentNodeMemory:
    attempts: list[AgentMemoryAttempt] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentNodeMemory:
        attempts = [
            AgentMemoryAttempt.from_dict(item)
            for item in data.get("attempts", [])
            if isinstance(item, dict)
        ]
        return cls(attempts=attempts)

    def to_dict(self) -> dict[str, Any]:
        return {"attempts": [attempt.to_dict() for attempt in self.attempts]}


@dataclass
class AgentMemory:
    nodes: dict[str, AgentNodeMemory] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentMemory:
        version = data.get("schema_version")
        if version != MEMORY_SCHEMA_VERSION:
            raise BlueprintError(
                f"unsupported agent memory schema_version {version!r}; "
                f"expected {MEMORY_SCHEMA_VERSION}"
            )
        raw_nodes = data.get("nodes", {})
        if not isinstance(raw_nodes, dict):
            raise BlueprintError("agent memory `nodes` must be an object")
        return cls(
            nodes={
                str(node_id): AgentNodeMemory.from_dict(node_data)
                for node_id, node_data in raw_nodes.items()
                if isinstance(node_data, dict)
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "nodes": {
                node_id: node_memory.to_dict()
                for node_id, node_memory in sorted(self.nodes.items())
            },
        }


@dataclass
class NodeMemorySummary:
    attempt_count: int
    last_outcome: str | None = None
    last_summary: str | None = None
    last_timestamp: str | None = None
    next_step: str | None = None
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def node_input_hash(node: BlueprintNode) -> str:
    """Return a stable hash of the task-defining inputs for ``node``."""

    payload = {
        "id": node.id,
        "kind": node.kind.value,
        "statement": node.statement,
        "informal_proof": node.informal_proof,
        "uses": list(node.uses),
        "isabelle": node.isabelle.to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_agent_memory(path: Path, *, strict: bool = False) -> AgentMemory:
    if not path.exists():
        return AgentMemory()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise BlueprintError("agent memory must be a JSON object")
        return AgentMemory.from_dict(data)
    except (OSError, json.JSONDecodeError, BlueprintError) as exc:
        if strict:
            if isinstance(exc, BlueprintError):
                raise
            raise BlueprintError(f"could not read agent memory at {path}: {exc}") from exc
        warnings.warn(f"ignoring unreadable agent memory at {path}: {exc}", stacklevel=2)
        return AgentMemory()


def write_agent_memory(memory: AgentMemory, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp sibling then atomically rename, so a concurrent reader
    # (e.g. the MCP ``stats`` tool) never observes a half-written file and
    # treats it as corrupt.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(memory.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def add_memory_attempt(
    memory: AgentMemory,
    node_id: str,
    attempt: AgentMemoryAttempt,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS_PER_NODE,
) -> AgentMemory:
    if attempt.outcome not in VALID_OUTCOMES:
        raise BlueprintError(
            f"unknown memory outcome {attempt.outcome!r}; choose one of: "
            f"{', '.join(sorted(VALID_OUTCOMES))}"
        )
    node_memory = memory.nodes.setdefault(node_id, AgentNodeMemory())
    node_memory.attempts.append(attempt)
    if max_attempts > 0 and len(node_memory.attempts) > max_attempts:
        node_memory.attempts = node_memory.attempts[-max_attempts:]
    return memory


def record_memory_attempt(
    path: Path,
    node_id: str,
    *,
    outcome: str,
    summary: str,
    actor: str | None = None,
    tool: str | None = None,
    details: str = "",
    next_step: str | None = None,
    input_hash: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS_PER_NODE,
) -> AgentMemoryAttempt:
    if not summary.strip():
        raise BlueprintError("memory summary must not be empty")
    memory = load_agent_memory(path, strict=True)
    attempt = AgentMemoryAttempt(
        timestamp=now_timestamp(),
        outcome=outcome,
        summary=summary.strip(),
        actor=actor,
        tool=tool,
        details=details,
        next_step=next_step,
        input_hash=input_hash,
    )
    add_memory_attempt(memory, node_id, attempt, max_attempts=max_attempts)
    write_agent_memory(memory, path)
    return attempt


def summarize_node_memory(
    memory: AgentMemory,
    node_id: str,
    *,
    current_input_hash: str | None = None,
) -> NodeMemorySummary | None:
    attempts = memory.nodes.get(node_id, AgentNodeMemory()).attempts
    if not attempts:
        return None
    last = attempts[-1]
    stale = bool(current_input_hash and last.input_hash and last.input_hash != current_input_hash)
    return NodeMemorySummary(
        attempt_count=len(attempts),
        last_outcome=last.outcome,
        last_summary=last.summary,
        last_timestamp=last.timestamp,
        next_step=last.next_step,
        stale=stale,
    )


def summaries_by_node(
    memory: AgentMemory,
    nodes: list[BlueprintNode],
) -> dict[str, NodeMemorySummary]:
    summaries: dict[str, NodeMemorySummary] = {}
    for node in nodes:
        summary = summarize_node_memory(
            memory,
            node.id,
            current_input_hash=node_input_hash(node),
        )
        if summary is not None:
            summaries[node.id] = summary
    return summaries
