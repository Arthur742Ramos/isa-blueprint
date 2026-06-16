"""Effort-weighted progress metrics.

Each node may carry an optional ``effort`` weight (a story-point-style estimate
of how much work the formal proof is expected to take). This module aggregates
those weights into a weighted view of formalization progress, complementing the
unweighted coverage in :mod:`isabelle_blueprint.report.metrics`.

The weighting mirrors :func:`build_status_metrics`: "formal targets" are nodes
whose formal status is anything other than ``missing``, and weighted coverage is
the proved share of that target effort. Nodes without an explicit ``effort`` are
treated as weight :data:`DEFAULT_EFFORT` so the figure stays meaningful while a
project is still adopting effort estimates incrementally.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import coverage_percent

DEFAULT_EFFORT = 1

#: Bucket label used for nodes that carry no tags.
UNTAGGED = "(untagged)"


@dataclass(frozen=True)
class TagEffort:
    """Effort-weighted progress for the nodes sharing one tag.

    A node with several tags contributes its weight to *each* of its tags, so the
    per-tag totals need not sum to the project total. ``percent`` is the proved
    share of ``total_effort`` (``None`` when the tag holds no effort).
    """

    tag: str
    node_count: int
    total_effort: int
    proved_effort: int
    remaining_effort: int
    percent: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "tag": self.tag,
            "node_count": self.node_count,
            "total_effort": self.total_effort,
            "proved_effort": self.proved_effort,
            "remaining_effort": self.remaining_effort,
            "percent": self.percent,
        }


@dataclass(frozen=True)
class EffortReport:
    """Effort-weighted aggregate derived from a :class:`BlueprintProject`.

    ``coverage_percent`` is ``None`` when the denominator is undefined - either
    the project has no nodes, or no node has been assigned an Isabelle reference
    yet. Callers should treat ``None`` as "unknown" rather than 0%.
    """

    node_count: int
    explicit_effort_count: int
    total_effort: int
    formal_target_effort: int
    proved_effort: int
    found_effort: int
    remaining_effort: int
    coverage_percent: int | None
    by_tag: tuple[TagEffort, ...] = field(default_factory=tuple)

    def to_dict(self, *, include_by_tag: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "node_count": self.node_count,
            "explicit_effort_count": self.explicit_effort_count,
            "total_effort": self.total_effort,
            "formal_target_effort": self.formal_target_effort,
            "proved_effort": self.proved_effort,
            "found_effort": self.found_effort,
            "remaining_effort": self.remaining_effort,
            "coverage_percent": self.coverage_percent,
            "default_effort": DEFAULT_EFFORT,
        }
        if include_by_tag:
            result["by_tag"] = [t.to_dict() for t in self.by_tag]
        return result


def _weight(node: BlueprintNode) -> int:
    return node.effort if node.effort is not None else DEFAULT_EFFORT


def build_effort_report(
    project: BlueprintProject, *, include_by_tag: bool = False
) -> EffortReport:
    """Compute effort-weighted progress for ``project``.

    The per-tag breakdown is only computed when ``include_by_tag`` is set; by
    default ``by_tag`` stays an empty tuple so the common path does no extra work.
    """
    node_count = len(project.nodes)
    explicit = 0
    total = 0
    formal_target = 0
    proved = 0
    found = 0
    for node in project.nodes:
        weight = _weight(node)
        total += weight
        if node.effort is not None:
            explicit += 1
        formal = node.status.formal
        if formal != FormalStatus.MISSING:
            formal_target += weight
            if formal == FormalStatus.PROVED:
                proved += weight
            elif formal == FormalStatus.FOUND:
                found += weight

    coverage = coverage_percent(proved, formal_target)

    return EffortReport(
        node_count=node_count,
        explicit_effort_count=explicit,
        total_effort=total,
        formal_target_effort=formal_target,
        proved_effort=proved,
        found_effort=found,
        remaining_effort=formal_target - proved,
        coverage_percent=coverage,
        by_tag=_build_by_tag(project) if include_by_tag else (),
    )


def _build_by_tag(project: BlueprintProject) -> tuple[TagEffort, ...]:
    """Group effort per tag, with an untagged bucket.

    Nodes carrying several tags count under each of them; untagged nodes fall
    into the :data:`UNTAGGED` bucket. The bucket is always present (with zeros
    when every node is tagged) so consumers can rely on a stable output shape.
    ``total_effort`` here is *all* effort under the tag (not just formal targets)
    so a tag's progress is judged against its whole scope. Tags are returned
    alphabetically, with the untagged bucket last.
    """
    counts: dict[str, int] = {UNTAGGED: 0}
    totals: dict[str, int] = {UNTAGGED: 0}
    proved: dict[str, int] = {UNTAGGED: 0}
    for node in project.nodes:
        weight = _weight(node)
        is_proved = node.status.formal == FormalStatus.PROVED
        keys = list(dict.fromkeys(node.tags)) if node.tags else [UNTAGGED]
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
            totals[key] = totals.get(key, 0) + weight
            if is_proved:
                proved[key] = proved.get(key, 0) + weight

    def _sort_key(tag: str) -> tuple[int, str]:
        return (1, "") if tag == UNTAGGED else (0, tag)

    out: list[TagEffort] = []
    for tag in sorted(counts, key=_sort_key):
        total = totals[tag]
        done = proved.get(tag, 0)
        out.append(
            TagEffort(
                tag=tag,
                node_count=counts[tag],
                total_effort=total,
                proved_effort=done,
                remaining_effort=total - done,
                percent=coverage_percent(done, total),
            )
        )
    return tuple(out)


def build_effort_gate(report: EffortReport, fail_under: float) -> dict[str, object]:
    """Evaluate ``report`` against a ``--fail-under`` coverage threshold.

    Returns an additive ``gate`` payload ``{fail_under, effort_percent, meets}``.
    ``effort_percent`` mirrors ``report.coverage_percent`` (``None`` when the
    weighted coverage is undefined). An undefined coverage never meets the gate,
    matching the "or undefined" convention of the ``gate`` command.
    """
    percent = report.coverage_percent
    meets = percent is not None and percent >= fail_under
    return {
        "fail_under": fail_under,
        "effort_percent": percent,
        "meets": meets,
    }


def render_effort_report(report: EffortReport, *, by_tag: bool = False) -> str:
    """Render ``report`` as a short Markdown summary.

    When ``by_tag`` is set, a per-tag effort table is appended beneath the
    summary (one row per tag plus an untagged bucket).
    """
    coverage = "n/a" if report.coverage_percent is None else f"{report.coverage_percent}%"
    lines = [
        "# Effort-weighted progress",
        "",
        f"- Weighted coverage: {coverage} (proved effort / formal-target effort)",
        f"- Proved effort: {report.proved_effort}",
        f"- Found effort: {report.found_effort}",
        f"- Remaining effort: {report.remaining_effort}",
        f"- Formal-target effort: {report.formal_target_effort}",
        f"- Total effort: {report.total_effort}",
        (
            f"- Nodes with explicit effort: {report.explicit_effort_count} of "
            f"{report.node_count} (others weighted as {DEFAULT_EFFORT})"
        ),
    ]
    if by_tag:
        lines += ["", "## Effort by tag", ""]
        if not report.by_tag:
            lines.append("- (no nodes)")
        else:
            lines.append("| Tag | Nodes | Total | Proved | Remaining | Percent |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
            for t in report.by_tag:
                pct = "n/a" if t.percent is None else f"{t.percent}%"
                lines.append(
                    f"| {t.tag} | {t.node_count} | {t.total_effort} | "
                    f"{t.proved_effort} | {t.remaining_effort} | {pct} |"
                )
    return "\n".join(lines) + "\n"


#: Column headers for the summary CSV (no ``--by-tag``).
EFFORT_CSV_COLUMNS = (
    "total_effort",
    "formal_target_effort",
    "proved_effort",
    "found_effort",
    "remaining_effort",
    "coverage_percent",
)

#: Column headers for the per-tag CSV (``--by-tag``).
EFFORT_BY_TAG_CSV_COLUMNS = (
    "tag",
    "total_effort",
    "proved_effort",
    "remaining_effort",
    "coverage_percent",
)


def render_effort_csv(report: EffortReport, *, by_tag: bool = False) -> str:
    """Render ``report`` as CSV.

    Without ``by_tag`` a single summary row is emitted under
    :data:`EFFORT_CSV_COLUMNS`. With ``by_tag`` one row per tag (plus the
    untagged bucket) is emitted under :data:`EFFORT_BY_TAG_CSV_COLUMNS`. A
    ``None`` coverage is rendered as a blank cell. The writer pins
    ``lineterminator="\\n"`` so no ``\\r`` ever appears in the output.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if by_tag:
        writer.writerow(EFFORT_BY_TAG_CSV_COLUMNS)
        for t in report.by_tag:
            pct = "" if t.percent is None else t.percent
            writer.writerow(
                [t.tag, t.total_effort, t.proved_effort, t.remaining_effort, pct]
            )
    else:
        writer.writerow(EFFORT_CSV_COLUMNS)
        coverage = "" if report.coverage_percent is None else report.coverage_percent
        writer.writerow(
            [
                report.total_effort,
                report.formal_target_effort,
                report.proved_effort,
                report.found_effort,
                report.remaining_effort,
                coverage,
            ]
        )
    return buffer.getvalue()


def _md_cell(text: str) -> str:
    """Escape a value for safe inclusion in a Markdown table cell.

    A literal ``|`` would otherwise start a new column and a newline would
    terminate the row, so both are neutralised.
    """
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


def render_effort_markdown(report: EffortReport, *, by_tag: bool = False) -> str:
    """Render ``report`` as a Markdown document with summary tables.

    A heading is followed by a summary table of total/proved/remaining effort and
    weighted coverage. When ``by_tag`` is set, a per-tag effort table is appended
    beneath the summary (one row per tag plus an untagged bucket).
    """
    coverage = "n/a" if report.coverage_percent is None else f"{report.coverage_percent}%"
    lines = [
        "# Effort-weighted progress",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total effort | {report.total_effort} |",
        f"| Proved effort | {report.proved_effort} |",
        f"| Remaining effort | {report.remaining_effort} |",
        f"| Coverage percent | {coverage} |",
    ]
    if by_tag:
        lines += ["", "## Effort by tag", ""]
        if not report.by_tag:
            lines.append("- (no nodes)")
        else:
            lines.append("| Tag | Nodes | Total | Proved | Remaining | Percent |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
            for t in report.by_tag:
                pct = "n/a" if t.percent is None else f"{t.percent}%"
                lines.append(
                    f"| {_md_cell(t.tag)} | {t.node_count} | {t.total_effort} | "
                    f"{t.proved_effort} | {t.remaining_effort} | {pct} |"
                )
    return "\n".join(lines) + "\n"
