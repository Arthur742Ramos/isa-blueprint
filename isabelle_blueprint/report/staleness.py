"""Logical staleness analysis: "which trusted facts rest on shaky ground?".

``staleness`` is the project-wide inverse of ``impact``. Where ``impact`` walks
*downstream* from one node to find everything that would break if it changed,
``staleness`` scans every currently-**trusted** node (formal status ``found`` or
``proved``) and walks *upstream* over its dependencies to decide whether that
trust is actually justified. A ``proved`` lemma whose own dependency is
``broken``, ``named`` (unproven), missing, or simply re-checked more recently
cannot really be relied upon - its green status is *stale*.

Each offending dependency becomes a **cause** with one of these reasons (listed
strongest-first):

* ``missing``    - a ``uses:`` entry points at a node id that does not exist.
* ``cycle``      - the trusted node participates in a dependency cycle.
* ``problem``    - a transitive dependency is ``not_found``/``broken``/
  ``tainted``/``failed_check`` (actively wrong).
* ``incomplete`` - a transitive dependency is ``named``/``missing`` (no proof
  yet), so the trusted node rests on something unproven.
* ``stale_dep``  - a transitive dependency is itself marked ``stale``.
* ``outdated``   - a transitive dependency's ``last_checked`` is strictly newer
  than this node's, so this node was verified *before* that dependency moved.

Reasons collapse into three severity buckets for the headline counts:
``problem`` (``missing``/``cycle``/``problem``), ``incomplete`` (``incomplete``),
and ``outdated`` (``stale_dep``/``outdated``). A node's severity is the strongest
bucket among its causes.

The JSON form carries a ``schema_version`` but, like the other analytics
payloads, is not part of the frozen v1.0 contract surface and may grow.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from isabelle_blueprint.graph.dependency_graph import DependencyGraph, build_graph
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES
from isabelle_blueprint.report.roadmap import COMPLETE_FORMAL_STATUSES

STALENESS_SCHEMA_VERSION = 1

# Reason ordering, strongest first - used to pick a node's single dominant cause
# and to sort causes within a node.
REASON_ORDER = ("missing", "cycle", "problem", "incomplete", "stale_dep", "outdated")
_REASON_RANK = {reason: len(REASON_ORDER) - i for i, reason in enumerate(REASON_ORDER)}

# Map each granular reason to one of three headline severity buckets.
_REASON_BUCKET = {
    "missing": "problem",
    "cycle": "problem",
    "problem": "problem",
    "incomplete": "incomplete",
    "stale_dep": "outdated",
    "outdated": "outdated",
}
SEVERITY_ORDER = ("problem", "incomplete", "outdated")
_SEVERITY_RANK = {severity: len(SEVERITY_ORDER) - i for i, severity in enumerate(SEVERITY_ORDER)}


@dataclass(frozen=True)
class StaleCause:
    """A single reason a trusted node's status is not fully justified."""

    dep_id: str
    dep_title: str
    formal_status: str
    distance: int
    reason: str

    @property
    def severity(self) -> str:
        return _REASON_BUCKET[self.reason]

    def to_dict(self) -> dict[str, object]:
        return {
            "dep_id": self.dep_id,
            "dep_title": self.dep_title,
            "formal_status": self.formal_status,
            "distance": self.distance,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class StaleNode:
    """A currently-trusted node whose trust rests on shaky dependencies."""

    node_id: str
    title: str
    formal_status: str
    severity: str
    in_cycle: bool
    nearest_distance: int
    cause_count: int
    causes: list[StaleCause] = field(default_factory=list)

    def to_dict(self, *, max_causes: int | None = None) -> dict[str, object]:
        causes = self.causes if max_causes is None else self.causes[:max_causes]
        return {
            "node_id": self.node_id,
            "title": self.title,
            "formal_status": self.formal_status,
            "severity": self.severity,
            "in_cycle": self.in_cycle,
            "nearest_distance": self.nearest_distance,
            "cause_count": self.cause_count,
            "causes": [cause.to_dict() for cause in causes],
        }


@dataclass(frozen=True)
class StalenessReport:
    """Project-wide roll-up of trusted nodes resting on shaky dependencies."""

    project: str
    node_count: int
    trusted_count: int
    stale_count: int
    problem_count: int
    incomplete_count: int
    outdated_count: int
    trusted_without_last_checked: int
    has_cycles: bool
    stale_nodes: list[StaleNode] = field(default_factory=list)
    schema_version: int = STALENESS_SCHEMA_VERSION

    def to_dict(self, *, max_causes: int | None = None) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "node_count": self.node_count,
            "trusted_count": self.trusted_count,
            "stale_count": self.stale_count,
            "problem_count": self.problem_count,
            "incomplete_count": self.incomplete_count,
            "outdated_count": self.outdated_count,
            "trusted_without_last_checked": self.trusted_without_last_checked,
            "has_cycles": self.has_cycles,
            "stale_nodes": [node.to_dict(max_causes=max_causes) for node in self.stale_nodes],
        }


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 ``last_checked`` value, normalising to aware UTC.

    Naive timestamps are assumed to be UTC so that comparisons never raise. Any
    unparseable value yields ``None`` (freshness is treated as unknown for that
    edge rather than crashing the whole report).
    """

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_newer(dep_value: str | None, node_value: str | None) -> bool:
    """True when ``dep_value`` is a strictly newer timestamp than ``node_value``."""

    dep_ts = _parse_timestamp(dep_value)
    node_ts = _parse_timestamp(node_value)
    if dep_ts is None or node_ts is None:
        return False
    return dep_ts > node_ts


def _dependency_distances(graph: DependencyGraph, start: str) -> dict[str, int]:
    """BFS shortest-hop distances over forward edges (dependencies of ``start``).

    Excludes ``start`` itself; the visited guard keeps the walk finite even when
    ``start`` sits inside a dependency cycle.
    """

    distances: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque(
        (dep, 1) for dep in graph.edges.get(start, [])
    )
    while queue:
        node_id, dist = queue.popleft()
        if node_id == start:
            continue
        existing = distances.get(node_id)
        if existing is not None and existing <= dist:
            continue
        distances[node_id] = dist
        for child in graph.edges.get(node_id, []):
            queue.append((child, dist + 1))
    return distances


def _resolve_reason(dep: BlueprintNode, node: BlueprintNode) -> str | None:
    """Classify how a single transitive dependency undermines ``node``'s trust."""

    status = dep.status.formal
    if status.value in PROBLEM_FORMAL_STATUSES:
        return "problem"
    if status in (FormalStatus.NAMED, FormalStatus.MISSING):
        return "incomplete"
    if status == FormalStatus.STALE:
        return "stale_dep"
    if status in COMPLETE_FORMAL_STATUSES and _is_newer(
        dep.status.last_checked, node.status.last_checked
    ):
        return "outdated"
    return None


def _node_causes(
    node: BlueprintNode,
    by_id: dict[str, BlueprintNode],
    graph: DependencyGraph,
    in_cycle: bool,
) -> list[StaleCause]:
    """Collect every reason ``node``'s trusted status is not justified."""

    causes: list[StaleCause] = []

    # Direct ``uses:`` entries that do not resolve to a real node. build_graph
    # silently drops these, so detect them straight from the raw dependency list.
    for dep_id in node.uses:
        if dep_id not in by_id:
            causes.append(
                StaleCause(
                    dep_id=dep_id,
                    dep_title="",
                    formal_status="missing",
                    distance=1,
                    reason="missing",
                )
            )

    if in_cycle:
        causes.append(
            StaleCause(
                dep_id=node.id,
                dep_title=node.title,
                formal_status=node.status.formal.value,
                distance=0,
                reason="cycle",
            )
        )

    for dep_id, distance in _dependency_distances(graph, node.id).items():
        dep = by_id.get(dep_id)
        if dep is None:
            continue
        reason = _resolve_reason(dep, node)
        if reason is None:
            continue
        causes.append(
            StaleCause(
                dep_id=dep_id,
                dep_title=dep.title,
                formal_status=dep.status.formal.value,
                distance=distance,
                reason=reason,
            )
        )

    causes.sort(key=lambda cause: (-_REASON_RANK[cause.reason], cause.distance, cause.dep_id))
    return causes


def build_staleness_report(project: BlueprintProject) -> StalenessReport:
    """Scan every trusted node for dependencies that undermine its status."""

    by_id = project.by_id()
    graph = build_graph(project)
    cycles = project.validate().cycles
    cycle_nodes = {node_id for cycle in cycles for node_id in cycle}

    trusted_count = 0
    trusted_without_last_checked = 0
    stale_nodes: list[StaleNode] = []

    for node in project.nodes:
        if node.status.formal not in COMPLETE_FORMAL_STATUSES:
            continue
        trusted_count += 1
        if not node.status.last_checked:
            trusted_without_last_checked += 1

        causes = _node_causes(node, by_id, graph, node.id in cycle_nodes)
        if not causes:
            continue

        severity = max(
            (cause.severity for cause in causes),
            key=lambda sev: _SEVERITY_RANK[sev],
        )
        stale_nodes.append(
            StaleNode(
                node_id=node.id,
                title=node.title,
                formal_status=node.status.formal.value,
                severity=severity,
                in_cycle=node.id in cycle_nodes,
                nearest_distance=min(cause.distance for cause in causes),
                cause_count=len(causes),
                causes=causes,
            )
        )

    stale_nodes.sort(
        key=lambda item: (-_SEVERITY_RANK[item.severity], item.nearest_distance, item.node_id)
    )

    problem_count = sum(1 for item in stale_nodes if item.severity == "problem")
    incomplete_count = sum(1 for item in stale_nodes if item.severity == "incomplete")
    outdated_count = sum(1 for item in stale_nodes if item.severity == "outdated")

    return StalenessReport(
        project=project.name,
        node_count=len(project.nodes),
        trusted_count=trusted_count,
        stale_count=len(stale_nodes),
        problem_count=problem_count,
        incomplete_count=incomplete_count,
        outdated_count=outdated_count,
        trusted_without_last_checked=trusted_without_last_checked,
        has_cycles=bool(cycles),
        stale_nodes=stale_nodes,
    )


def staleness_payload(
    report: StalenessReport,
    *,
    top: int | None = None,
    max_causes: int | None = None,
) -> dict[str, object]:
    """Return the JSON payload, optionally limiting nodes and causes-per-node."""

    payload = report.to_dict(max_causes=max_causes)
    if top is not None:
        payload["stale_nodes"] = payload["stale_nodes"][:top]  # type: ignore[index]
    return payload


_SEVERITY_LABEL = {
    "problem": "rests on broken/missing/cyclic dependencies",
    "incomplete": "rests on unproven dependencies",
    "outdated": "verified before a dependency moved",
}


def render_staleness_report(
    report: StalenessReport, *, top: int = 10, max_causes: int = 5
) -> str:
    """Render the staleness scan as compact Markdown."""

    from isabelle_blueprint import console

    lines = [f"# {report.project} staleness", ""]
    if report.trusted_count == 0:
        lines.append(console.dim("No trusted (found/proved) nodes to audit yet."))
        return "\n".join(lines).rstrip("\n") + "\n"

    if report.stale_count == 0:
        lines.append(
            console.success(
                f"All {report.trusted_count} trusted node(s) rest on trusted, "
                "up-to-date dependencies."
            )
        )
        if report.trusted_without_last_checked:
            lines.append(
                console.dim(
                    f"({report.trusted_without_last_checked} trusted node(s) have no "
                    "last_checked timestamp, so freshness is unknown.)"
                )
            )
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.append(
        f"{report.stale_count} of {report.trusted_count} trusted node(s) are stale: "
        f"{report.problem_count} problem, {report.incomplete_count} incomplete, "
        f"{report.outdated_count} outdated."
    )
    if report.trusted_without_last_checked:
        lines.append(
            console.dim(
                f"{report.trusted_without_last_checked} trusted node(s) have no "
                "last_checked timestamp (freshness unknown)."
            )
        )
    lines.append("")

    for item in report.stale_nodes[:top]:
        header = (
            f"- `{item.node_id}` - {item.title} "
            f"(formal `{item.formal_status}`, severity `{item.severity}`"
        )
        if item.in_cycle:
            header += ", in cycle"
        header += ")"
        lines.append(console.warning(header) if item.severity == "problem" else header)
        for cause in item.causes[:max_causes]:
            if cause.reason == "cycle":
                lines.append("    - participates in a dependency cycle")
            elif cause.reason == "missing":
                lines.append(f"    - depends on missing node `{cause.dep_id}`")
            else:
                lines.append(
                    f"    - `{cause.dep_id}` ({cause.reason}, formal "
                    f"`{cause.formal_status}`, distance {cause.distance})"
                )
        hidden = item.cause_count - max_causes
        if hidden > 0:
            lines.append(console.dim(f"    ... and {hidden} more cause(s)"))

    hidden_nodes = report.stale_count - top
    if hidden_nodes > 0:
        lines.append(console.dim(f"  ... and {hidden_nodes} more stale node(s)"))

    return "\n".join(lines).rstrip("\n") + "\n"


def _markdown_cause(cause: StaleCause) -> str:
    """Render a single cause as a compact, table-cell-safe phrase."""

    if cause.reason == "cycle":
        return "participates in a dependency cycle"
    if cause.reason == "missing":
        return f"missing `{cause.dep_id}`"
    return f"`{cause.dep_id}` ({cause.reason}, `{cause.formal_status}`, d{cause.distance})"


def render_staleness_markdown(
    report: StalenessReport, *, top: int = 10, max_causes: int = 5
) -> str:
    """Render the staleness scan as a portable Markdown table (no colour)."""

    lines = [f"# {report.project} staleness", ""]
    if report.trusted_count == 0:
        lines.append("No trusted (found/proved) nodes to audit yet.")
        return "\n".join(lines).rstrip("\n") + "\n"

    if report.stale_count == 0:
        lines.append(
            f"All {report.trusted_count} trusted node(s) rest on trusted, "
            "up-to-date dependencies."
        )
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.append(
        f"{report.stale_count} of {report.trusted_count} trusted node(s) are stale: "
        f"{report.problem_count} problem, {report.incomplete_count} incomplete, "
        f"{report.outdated_count} outdated."
    )
    lines.append("")
    lines.append("| Node | Title | Formal | Severity | Causes |")
    lines.append("| --- | --- | --- | --- | --- |")

    for item in report.stale_nodes[:top]:
        causes = [_markdown_cause(cause) for cause in item.causes[:max_causes]]
        hidden = item.cause_count - max_causes
        if hidden > 0:
            causes.append(f"... +{hidden} more")
        severity = item.severity + (", cycle" if item.in_cycle else "")
        lines.append(
            f"| `{item.node_id}` | {item.title} | `{item.formal_status}` "
            f"| {severity} | {'; '.join(causes)} |"
        )

    hidden_nodes = report.stale_count - top
    if hidden_nodes > 0:
        lines.append("")
        lines.append(f"... and {hidden_nodes} more stale node(s)")

    return "\n".join(lines).rstrip("\n") + "\n"
