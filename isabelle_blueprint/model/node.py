"""Blueprint node data model."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus


class NodeKind(StrEnum):
    """Recognised blueprint node kinds.

    The parser is tolerant of unknown kinds (they are stored as :attr:`OTHER`),
    but the canonical set covers the workflow described in the roadmap.
    """

    DEFINITION = "definition"
    LEMMA = "lemma"
    THEOREM = "theorem"
    PROPOSITION = "proposition"
    COROLLARY = "corollary"
    CONSTRUCTION = "construction"
    REMARK = "remark"
    EXAMPLE = "example"
    NOTE = "note"
    OTHER = "other"

    @classmethod
    def parse(cls, value: str) -> NodeKind:
        value = (value or "").strip().lower()
        for member in cls:
            if member.value == value:
                return member
        return cls.OTHER


@dataclass
class IsabelleRef:
    """A reference to an Isabelle fact.

    Either ``fact`` (a fully-qualified ``Theory.fact_name``) or just a theory
    plus separate fact name. The parser accepts both ``isabelle: Theory.fact``
    shorthand and explicit ``session``/``theory``/``fact`` keys.
    """

    fact: str | None = None
    theory: str | None = None
    session: str | None = None

    def __post_init__(self) -> None:
        if self.fact and not self.theory and "." in self.fact:
            self.theory = self.fact.rsplit(".", 1)[0]

    @property
    def qualified_name(self) -> str | None:
        if self.fact:
            return self.fact
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"fact": self.fact, "theory": self.theory, "session": self.session}


@dataclass
class NodeStatus:
    """Combined status block carried by every node."""

    blueprint: BlueprintStatus = BlueprintStatus.STUB
    formal: FormalStatus = FormalStatus.MISSING
    agent: AgentStatus = AgentStatus.BLOCKED
    last_checked: str | None = None  # ISO-8601 timestamp
    check_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blueprint": self.blueprint.value,
            "formal": self.formal.value,
            "agent": self.agent.value,
            "last_checked": self.last_checked,
            "check_error": self.check_error,
        }


@dataclass
class BlueprintNode:
    """A single planning unit: definition, lemma, theorem, etc."""

    id: str
    kind: NodeKind
    title: str
    statement: str = ""
    informal_proof: str = ""
    uses: list[str] = field(default_factory=list)
    isabelle: IsabelleRef = field(default_factory=IsabelleRef)
    status: NodeStatus = field(default_factory=NodeStatus)
    tags: list[str] = field(default_factory=list)
    source_file: str | None = None
    source_line: int | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "statement": self.statement,
            "informal_proof": self.informal_proof,
            "uses": list(self.uses),
            "isabelle": self.isabelle.to_dict(),
            "status": self.status.to_dict(),
            "tags": list(self.tags),
            "source": {"file": self.source_file, "line": self.source_line},
        }
