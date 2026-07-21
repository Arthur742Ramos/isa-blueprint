"""Per-tag coverage roll-up: progress sliced by ``tags``.

``tags`` groups nodes by their declared ``tags`` and reports, for each tag, how
many nodes carry it and how that slice is progressing formally (targets,
proved, found, problems, and a per-tag coverage percentage). A node with
several tags is counted under each of them, so the per-tag node counts can sum
to more than the project total; nodes with no tags are reported separately as
``untagged``.

Coverage per tag mirrors :func:`isabelle_blueprint.report.metrics.build_status_metrics`:
"formal targets" are nodes whose formal status is anything other than
``missing``, and coverage is the proved share of that target count (truncated,
with a sub-1% non-zero ratio clamped up to 1, and ``None`` when the tag has no
formal targets). No Isabelle invocation is required.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report._markdown import md_cell as _escape_cell
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES

TAGS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TagStat:
    """Aggregate counts for a single tag."""

    tag: str
    node_count: int
    formal_target_count: int
    proved_count: int
    found_count: int
    problem_count: int
    coverage_percent: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "tag": self.tag,
            "node_count": self.node_count,
            "formal_target_count": self.formal_target_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "coverage_percent": self.coverage_percent,
        }


@dataclass(frozen=True)
class TagReport:
    """Per-tag roll-up across a :class:`BlueprintProject`."""

    project: str
    total_nodes: int
    untagged_count: int
    tags: tuple[TagStat, ...]
    schema_version: int = TAGS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "total_nodes": self.total_nodes,
            "untagged_count": self.untagged_count,
            "tag_count": len(self.tags),
            "tags": [tag.to_dict() for tag in self.tags],
        }


@dataclass(frozen=True)
class TagGate:
    """Outcome of a per-tag ``--fail-under`` coverage gate.

    ``failing_tags`` lists the gated tags whose ``coverage_percent`` is below
    ``fail_under``, in the report's own (most-used-first) order. Tags with no
    formal targets (``coverage_percent`` is ``None``) carry nothing to prove and
    are never counted as failing. ``ok`` is ``True`` when no tag fails.
    """

    fail_under: int
    failing_tags: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failing_tags

    def to_dict(self) -> dict[str, object]:
        return {
            "fail_under": self.fail_under,
            "failing_tags": list(self.failing_tags),
            "ok": self.ok,
        }


TAG_SORT_KEYS = ("name", "nodes", "coverage")


def sort_tag_report(report: TagReport, sort_key: str | None) -> TagReport:
    """Return ``report`` with its ``tags`` reordered by ``sort_key``.

    ``name`` orders tags alphabetically (ascending); ``nodes`` and ``coverage``
    order descending (highest first), with the tag name as an ascending
    tie-break for stable output. A tag with no formal targets sorts last under
    ``coverage`` (its ``coverage_percent`` is ``None``). Any other key (including
    the ``None`` default) leaves the report's own ordering untouched.
    """

    if sort_key == "name":
        ordered = sorted(report.tags, key=lambda stat: stat.tag)
    elif sort_key == "nodes":
        ordered = sorted(report.tags, key=lambda stat: (-stat.node_count, stat.tag))
    elif sort_key == "coverage":
        ordered = sorted(
            report.tags,
            key=lambda stat: (
                stat.coverage_percent is None,
                -(stat.coverage_percent or 0),
                stat.tag,
            ),
        )
    else:
        return report
    return TagReport(
        project=report.project,
        total_nodes=report.total_nodes,
        untagged_count=report.untagged_count,
        tags=tuple(ordered),
        schema_version=report.schema_version,
    )


def build_tag_gate(report: TagReport, fail_under: int) -> TagGate:
    """Evaluate the per-tag coverage gate over ``report``'s (already filtered) tags."""

    failing = tuple(
        stat.tag
        for stat in report.tags
        if stat.coverage_percent is not None and stat.coverage_percent < fail_under
    )
    return TagGate(fail_under=fail_under, failing_tags=failing)


@dataclass
class _Bucket:
    nodes: int = 0
    targets: int = 0
    proved: int = 0
    found: int = 0
    problems: int = 0


def build_tag_report(project: BlueprintProject, only: Iterable[str] | None = None) -> TagReport:
    """Compute the per-tag coverage roll-up for ``project``.

    When ``only`` is given, the roll-up is restricted to those tag names. Each
    requested tag is reported (an unknown one yields a zero/empty row rather than
    being dropped), and tags outside the set are omitted from the table/JSON. The
    project-wide ``total_nodes`` and ``untagged_count`` are unaffected by the
    filter, so the surrounding structure stays consistent.
    """

    requested = list(dict.fromkeys(only)) if only is not None else None

    buckets: dict[str, _Bucket] = {}
    if requested is not None:
        for tag in requested:
            buckets.setdefault(tag, _Bucket())
    untagged = 0
    for node in project.nodes:
        # De-duplicate tags within a node so a repeated tag is not double-counted.
        node_tags = list(dict.fromkeys(node.tags))
        if not node_tags:
            untagged += 1
            continue
        formal = node.status.formal.value
        for tag in node_tags:
            if requested is not None and tag not in buckets:
                continue
            bucket = buckets.setdefault(tag, _Bucket())
            bucket.nodes += 1
            if formal != FormalStatus.MISSING.value:
                bucket.targets += 1
                if formal == FormalStatus.PROVED.value:
                    bucket.proved += 1
                elif formal == FormalStatus.FOUND.value:
                    bucket.found += 1
                if formal in PROBLEM_FORMAL_STATUSES:
                    bucket.problems += 1

    stats = tuple(
        TagStat(
            tag=tag,
            node_count=bucket.nodes,
            formal_target_count=bucket.targets,
            proved_count=bucket.proved,
            found_count=bucket.found,
            problem_count=bucket.problems,
            coverage_percent=_coverage(bucket.proved, bucket.targets),
        )
        for tag, bucket in buckets.items()
    )
    # Most-used tags first; ties broken alphabetically for stable output.
    stats = tuple(sorted(stats, key=lambda stat: (-stat.node_count, stat.tag)))

    return TagReport(
        project=project.name,
        total_nodes=len(project.nodes),
        untagged_count=untagged,
        tags=stats,
    )


def render_tag_report(report: TagReport) -> str:
    """Render the roll-up as a compact Markdown table for the terminal."""

    lines = [
        f"# {report.project} tags",
        "",
        (
            f"{report.total_nodes} node(s) across {len(report.tags)} tag(s); "
            f"{report.untagged_count} untagged."
        ),
        "",
    ]
    if not report.tags:
        lines.append("_(no tagged nodes)_")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Tag | Nodes | Targets | Proved | Found | Problems | Coverage |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for stat in report.tags:
        coverage = "n/a" if stat.coverage_percent is None else f"{stat.coverage_percent}%"
        lines.append(
            f"| {stat.tag} | {stat.node_count} | {stat.formal_target_count} | "
            f"{stat.proved_count} | {stat.found_count} | {stat.problem_count} | {coverage} |"
        )
    return "\n".join(lines) + "\n"


def render_tags_markdown(report: TagReport) -> str:
    """Render the roll-up as a standalone Markdown document.

    Columns: tag, nodes, formal targets, proved, found, problems, and
    proved-coverage%. Tag cells are escaped so a ``|`` in a tag name cannot
    break the table. An untagged-count line follows the table.
    """

    lines = [
        f"# {report.project} tags",
        "",
    ]
    if report.tags:
        lines.extend(
            [
                "| Tag | Nodes | Formal targets | Proved | Found | Problems | Proved-coverage% |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for stat in report.tags:
            coverage = "n/a" if stat.coverage_percent is None else f"{stat.coverage_percent}%"
            lines.append(
                f"| {_escape_cell(stat.tag)} | {stat.node_count} | "
                f"{stat.formal_target_count} | {stat.proved_count} | "
                f"{stat.found_count} | {stat.problem_count} | {coverage} |"
            )
    else:
        lines.append("_(no tagged nodes)_")
    lines.extend(["", f"Untagged nodes: {report.untagged_count}"])
    return "\n".join(lines) + "\n"


TAGS_CSV_COLUMNS = (
    "tag",
    "nodes",
    "formal_targets",
    "proved",
    "found",
    "problems",
    "proved_coverage_percent",
)


def render_tags_csv(report: TagReport) -> str:
    """Render the roll-up as CSV: a header plus one row per tag.

    Columns: tag, nodes, formal_targets, proved, found, problems, and
    proved_coverage_percent (blank when the tag has no formal targets). A final
    ``(untagged)`` row carries the project-wide untagged node count in the
    ``nodes`` column; its target/coverage columns are left blank.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TAGS_CSV_COLUMNS)
    for stat in report.tags:
        coverage = "" if stat.coverage_percent is None else stat.coverage_percent
        writer.writerow(
            [
                stat.tag,
                stat.node_count,
                stat.formal_target_count,
                stat.proved_count,
                stat.found_count,
                stat.problem_count,
                coverage,
            ]
        )
    writer.writerow(["(untagged)", report.untagged_count, "", "", "", "", ""])
    return buffer.getvalue()


def _coverage(proved: int, targets: int) -> int | None:
    if targets == 0:
        return None
    # Truncate (not round) so 100 means genuinely all proved; clamp a non-zero
    # but sub-1% ratio up to 1. Mirrors report.metrics.build_status_metrics.
    percent = proved * 100 // targets
    if percent == 0 and proved > 0:
        percent = 1
    return percent
