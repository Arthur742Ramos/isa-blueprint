"""Status enums used to describe blueprint nodes from three perspectives.

The roadmap (sections 4 and 12) is explicit that a single ``done``/``not done``
status is too coarse. Each node carries three independent dimensions:

* :class:`BlueprintStatus` - quality of the *informal* writeup.
* :class:`FormalStatus`    - state of the formal Isabelle artefact.
* :class:`AgentStatus`     - whether an AI/human agent can pick the node up next.

A separate :class:`FormalStatus.PROVED` value is reserved for facts that are
known to exist *and* show no detected ``sorry``/oracle taint; mere existence
maps to :class:`FormalStatus.FOUND` per the README disclaimer
"fact exists != proof trusted" (roadmap section 12).
"""
from __future__ import annotations

from enum import StrEnum
from typing import TypeVar


class BlueprintStatus(StrEnum):
    """How polished the informal blueprint text is."""

    STUB = "stub"
    WRITTEN = "written"
    REVIEWED = "reviewed"


class FormalStatus(StrEnum):
    """State of the corresponding Isabelle fact."""

    MISSING = "missing"          # No isabelle ref assigned.
    NAMED = "named"              # Ref assigned but never checked.
    NOT_FOUND = "not_found"      # Checker could not resolve the ref.
    FOUND = "found"              # Fact exists in Isabelle.
    PROVED = "proved"            # Fact exists, no detected sorry/oracle.
    TAINTED = "tainted"          # Fact exists but appears to rely on sorry/oracle.
    STALE = "stale"              # Dependencies changed since the last successful check.
    BROKEN = "broken"            # Isabelle build failed.
    FAILED_CHECK = "failed_check"  # Generic check failure (kept for forward compat).


class AgentStatus(StrEnum):
    """Whether an autonomous or human agent should attempt this node next."""

    BLOCKED = "blocked"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    ATTEMPTED = "attempted"
    SOLVED = "solved"
    NEEDS_HUMAN = "needs_human"


# Mapping from status -> color used for graph nodes and badges
# (see roadmap section 7).
# Templates look these up by the enum's string value (e.g. ``node.status.formal.value``)
# so we key the table by those same strings rather than by enum members.
STATUS_COLORS: dict[str, str] = {
    FormalStatus.MISSING.value: "#9ca3af",       # gray - only blueprint text exists
    FormalStatus.NAMED.value: "#f59e0b",         # orange - fact name assigned, unchecked
    FormalStatus.NOT_FOUND.value: "#ef4444",     # red - fact name assigned but not found
    FormalStatus.FOUND.value: "#3b82f6",         # blue - exists, dependencies may be incomplete
    FormalStatus.PROVED.value: "#10b981",        # green - exists and trusted
    FormalStatus.TAINTED.value: "#a855f7",       # purple - sorry/oracle suspected
    FormalStatus.STALE.value: "#fbbf24",         # amber - dependencies changed
    FormalStatus.BROKEN.value: "#dc2626",        # dark red - build failure
    FormalStatus.FAILED_CHECK.value: "#dc2626",
}


_StatusEnumT = TypeVar("_StatusEnumT", BlueprintStatus, FormalStatus, AgentStatus)

_AXIS_NAMES: dict[type, str] = {
    BlueprintStatus: "blueprint",
    FormalStatus: "formal",
    AgentStatus: "agent",
}


def coerce_status(enum_cls: type[_StatusEnumT], value: object) -> _StatusEnumT:
    """Coerce a raw token to a status enum member.

    Tokens are normalised (stripped + lower-cased) before lookup. An
    unrecognised token raises :class:`ValueError` whose message lists the valid
    values, so the Markdown/LaTeX parsers can surface a clean
    :class:`~isabelle_blueprint.errors.ParseError` instead of leaking a bare
    enum ``ValueError`` (and its traceback) to the CLI/MCP boundary.
    """
    token = str(value).strip().lower()
    try:
        return enum_cls(token)
    except ValueError:
        axis = _AXIS_NAMES.get(enum_cls, enum_cls.__name__)
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(
            f"invalid {axis} status {token!r}; expected one of: {valid}"
        ) from None
