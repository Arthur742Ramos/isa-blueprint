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

from enum import Enum


class BlueprintStatus(str, Enum):
    """How polished the informal blueprint text is."""

    STUB = "stub"
    WRITTEN = "written"
    REVIEWED = "reviewed"


class FormalStatus(str, Enum):
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


class AgentStatus(str, Enum):
    """Whether an autonomous or human agent should attempt this node next."""

    BLOCKED = "blocked"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    ATTEMPTED = "attempted"
    SOLVED = "solved"
    NEEDS_HUMAN = "needs_human"


# Mapping from status -> color used for graph nodes and badges
# (see roadmap section 7).
STATUS_COLORS: dict[FormalStatus, str] = {
    FormalStatus.MISSING: "#9ca3af",       # gray - only blueprint text exists
    FormalStatus.NAMED: "#f59e0b",         # orange - fact name assigned, unchecked
    FormalStatus.NOT_FOUND: "#ef4444",     # red - fact name assigned but not found
    FormalStatus.FOUND: "#3b82f6",         # blue - exists, dependencies may be incomplete
    FormalStatus.PROVED: "#10b981",        # green - exists and trusted
    FormalStatus.TAINTED: "#a855f7",       # purple - sorry/oracle suspected
    FormalStatus.STALE: "#fbbf24",         # amber - dependencies changed
    FormalStatus.BROKEN: "#dc2626",        # dark red - build failure
    FormalStatus.FAILED_CHECK: "#dc2626",
}
