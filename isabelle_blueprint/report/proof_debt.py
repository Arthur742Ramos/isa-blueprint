"""Proof-debt scoring: one weighted figure for remaining proof work.

Where :mod:`isabelle_blueprint.report.effort` splits formal-target effort into a
proved/found/remaining view, ``proof-debt`` answers a single CI-shaped question:
*how much proof work is still outstanding?* It sums the ``effort`` weight of
every formal-target node that is **not yet proved** (formal status anything other
than ``missing`` or ``proved``), defaulting to :data:`DEFAULT_EFFORT` when a node
carries no explicit estimate, and attributes that debt to status buckets so a
reviewer can see *where* the debt sits:

* ``named``   - a fact name is assigned but never checked.
* ``found``   - the fact exists (or went stale) but is not trusted-proved yet.
* ``problem`` - something is actively wrong (not found / build broken / tainted).
* ``missing`` - informational only: nodes with no Isabelle reference at all. These
  are *not* formal targets, so they never count toward :attr:`total_debt`.

The buckets ``named``/``found``/``problem`` partition the remaining formal
targets, so their debts sum to :attr:`total_debt`. A ``--fail-over N`` ceiling
turns the figure into a gate: CI fails once accumulated debt exceeds ``N``.
"""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.effort import DEFAULT_EFFORT
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES

PROOF_DEBT_SCHEMA_VERSION = 1

#: Bucket names, in the fixed order used by the table and the JSON payload.
BUCKET_NAMES = ("named", "found", "problem", "missing")

#: Map a formal-status string to its debt bucket. ``proved`` is intentionally
#: absent: proved nodes carry no debt and are excluded entirely.
_STATUS_BUCKET: dict[str, str] = {
    FormalStatus.MISSING.value: "missing",
    FormalStatus.NAMED.value: "named",
    FormalStatus.FOUND.value: "found",
    FormalStatus.STALE.value: "found",
}
for _status in PROBLEM_FORMAL_STATUSES:
    _STATUS_BUCKET[_status] = "problem"


@dataclass(frozen=True)
class DebtBucket:
    """Weighted remaining work attributed to one status bucket.

    ``node_count`` is how many nodes fell in the bucket and ``debt`` is the sum
    of their effort weights. The ``missing`` bucket is informational only and is
    excluded from :attr:`ProofDebtReport.total_debt`.
    """

    name: str
    node_count: int
    debt: int


@dataclass(frozen=True)
class ProofDebtReport:
    """A single proof-debt figure with per-bucket attribution.

    ``total_debt`` is the effort-weighted remaining proof work over all
    non-proved formal targets; ``remaining_node_count`` is how many such nodes
    there are. ``default_effort_used`` records whether any counted node fell back
    to :data:`DEFAULT_EFFORT` because it had no explicit ``effort``.
    """

    project: str
    total_debt: int
    remaining_node_count: int
    default_effort_used: bool
    buckets: tuple[DebtBucket, ...]
    schema_version: int = PROOF_DEBT_SCHEMA_VERSION

    def bucket(self, name: str) -> DebtBucket:
        for b in self.buckets:
            if b.name == name:
                return b
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "total_debt": self.total_debt,
            "remaining_node_count": self.remaining_node_count,
            "buckets": {b.name: b.debt for b in self.buckets},
            "default_effort_used": self.default_effort_used,
        }


def _weight(node: BlueprintNode) -> int:
    return node.effort if node.effort is not None else DEFAULT_EFFORT


def build_proof_debt_report(project: BlueprintProject) -> ProofDebtReport:
    """Compute the :class:`ProofDebtReport` for ``project``.

    Each node's formal status is mapped to a bucket via :data:`_STATUS_BUCKET`;
    ``proved`` nodes carry no debt and are skipped. The ``named``/``found``/
    ``problem`` buckets partition the non-proved formal targets, so their debts
    sum to ``total_debt``; the ``missing`` bucket is reported alongside but kept
    out of the total because such nodes have no formal target yet.
    """
    counts: dict[str, int] = {name: 0 for name in BUCKET_NAMES}
    debts: dict[str, int] = {name: 0 for name in BUCKET_NAMES}
    default_used = False

    for node in project.nodes:
        status = node.status.formal.value
        if status == FormalStatus.PROVED.value:
            continue
        bucket = _STATUS_BUCKET.get(status, "problem")
        weight = _weight(node)
        counts[bucket] += 1
        debts[bucket] += weight
        if node.effort is None and bucket != "missing":
            default_used = True

    buckets = tuple(
        DebtBucket(name=name, node_count=counts[name], debt=debts[name])
        for name in BUCKET_NAMES
    )
    total_debt = sum(debts[name] for name in BUCKET_NAMES if name != "missing")
    remaining = sum(counts[name] for name in BUCKET_NAMES if name != "missing")

    return ProofDebtReport(
        project=project.name,
        total_debt=total_debt,
        remaining_node_count=remaining,
        default_effort_used=default_used,
        buckets=buckets,
    )


def build_proof_debt_gate(report: ProofDebtReport, fail_over: int) -> dict[str, object]:
    """Evaluate ``report`` against a ``--fail-over`` debt ceiling.

    Returns an additive ``gate`` payload ``{fail_over, total_debt, exceeds}``.
    ``exceeds`` is true when ``total_debt`` is strictly greater than ``fail_over``
    (the ceiling is inclusive: debt equal to the ceiling still passes).
    """
    return {
        "fail_over": fail_over,
        "total_debt": report.total_debt,
        "exceeds": report.total_debt > fail_over,
    }


def render_proof_debt_report(report: ProofDebtReport) -> str:
    """Render ``report`` as a short plain-text summary with a per-bucket table."""
    lines = [
        f"# Proof debt: {report.total_debt}",
        "",
        f"- Total debt: {report.total_debt} (effort-weighted remaining proof work)",
        f"- Remaining nodes: {report.remaining_node_count}",
        (
            "- Default effort applied to some nodes"
            if report.default_effort_used
            else "- Every counted node had an explicit effort"
        ),
        "",
        "| Bucket | Nodes | Debt |",
        "| --- | ---: | ---: |",
    ]
    for b in report.buckets:
        suffix = " (not counted in total)" if b.name == "missing" else ""
        lines.append(f"| {b.name}{suffix} | {b.node_count} | {b.debt} |")
    return "\n".join(lines) + "\n"
