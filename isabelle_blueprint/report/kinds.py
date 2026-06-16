"""Per-kind coverage roll-up: progress sliced by node ``kind``.

``kinds`` groups nodes by their declared :class:`~isabelle_blueprint.model.node.NodeKind`
(definition/lemma/theorem/proposition/corollary/construction/remark/example/note/other)
and reports, for each kind present, how many nodes carry it and how that slice
is progressing formally (targets, proved, found, problems, and a per-kind
coverage percentage). Each node carries exactly one kind, so the per-kind node
counts sum to the project total; kinds with no nodes are omitted.

Coverage per kind mirrors :func:`isabelle_blueprint.report.metrics.build_status_metrics`:
"formal targets" are nodes whose formal status is anything other than
``missing``, and coverage is the proved share of that target count (truncated,
with a sub-1% non-zero ratio clamped up to 1, and ``None`` when the kind has no
formal targets). No Isabelle invocation is required.
"""
from __future__ import annotations

from dataclasses import dataclass

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES, coverage_percent

KINDS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class KindStat:
    """Aggregate counts for a single node kind."""

    kind: str
    node_count: int
    formal_target_count: int
    proved_count: int
    found_count: int
    problem_count: int
    coverage_percent: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "node_count": self.node_count,
            "formal_target_count": self.formal_target_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "coverage_percent": self.coverage_percent,
        }


@dataclass(frozen=True)
class KindReport:
    """Per-kind roll-up across a :class:`BlueprintProject`."""

    project: str
    total_nodes: int
    kinds: tuple[KindStat, ...]
    schema_version: int = KINDS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "total_nodes": self.total_nodes,
            "kind_count": len(self.kinds),
            "kinds": [kind.to_dict() for kind in self.kinds],
        }


@dataclass
class _Bucket:
    nodes: int = 0
    targets: int = 0
    proved: int = 0
    found: int = 0
    problems: int = 0


def build_kind_report(project: BlueprintProject) -> KindReport:
    """Compute the per-kind coverage roll-up for ``project``.

    Each node contributes to the bucket for its single ``kind``; only kinds that
    are actually present produce a row. Buckets are ordered by descending node
    count, ties broken alphabetically by kind name for stable output.
    """

    buckets: dict[str, _Bucket] = {}
    for node in project.nodes:
        kind = node.kind.value
        bucket = buckets.setdefault(kind, _Bucket())
        bucket.nodes += 1
        formal = node.status.formal.value
        if formal != FormalStatus.MISSING.value:
            bucket.targets += 1
            if formal == FormalStatus.PROVED.value:
                bucket.proved += 1
            elif formal == FormalStatus.FOUND.value:
                bucket.found += 1
            if formal in PROBLEM_FORMAL_STATUSES:
                bucket.problems += 1

    stats = tuple(
        KindStat(
            kind=kind,
            node_count=bucket.nodes,
            formal_target_count=bucket.targets,
            proved_count=bucket.proved,
            found_count=bucket.found,
            problem_count=bucket.problems,
            coverage_percent=coverage_percent(bucket.proved, bucket.targets),
        )
        for kind, bucket in buckets.items()
    )
    # Most-populous kinds first; ties broken alphabetically for stable output.
    stats = tuple(sorted(stats, key=lambda stat: (-stat.node_count, stat.kind)))

    return KindReport(
        project=project.name,
        total_nodes=len(project.nodes),
        kinds=stats,
    )


def render_kind_report(report: KindReport) -> str:
    """Render the roll-up as a compact Markdown table for the terminal."""

    lines = [
        f"# {report.project} kinds",
        "",
        f"{report.total_nodes} node(s) across {len(report.kinds)} kind(s).",
        "",
    ]
    if not report.kinds:
        lines.append("_(no nodes)_")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Kind | Nodes | Targets | Proved | Found | Problems | Coverage |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for stat in report.kinds:
        coverage = "n/a" if stat.coverage_percent is None else f"{stat.coverage_percent}%"
        lines.append(
            f"| {stat.kind} | {stat.node_count} | {stat.formal_target_count} | "
            f"{stat.proved_count} | {stat.found_count} | {stat.problem_count} | {coverage} |"
        )
    return "\n".join(lines) + "\n"
