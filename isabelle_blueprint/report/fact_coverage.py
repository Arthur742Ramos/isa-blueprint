"""Per-theory fact coverage: progress sliced by the Isabelle theory a node leans on.

``fact-coverage`` groups nodes by the **theory** of their Isabelle fact - the
``Theory`` part of a ``Theory.fact`` qualified name (``node.isabelle.theory``) -
and reports, for each theory, how many nodes reference it and how that slice is
progressing formally (proved, found, problems, and a per-theory coverage
percentage). It answers "which Isabelle theories does this blueprint lean on,
and how complete is each?". Nodes with no Isabelle fact are grouped under the
``(no fact)`` label.

Coverage per theory mirrors
:func:`isabelle_blueprint.report.metrics.build_status_metrics`: "formal targets"
are nodes whose formal status is anything other than ``missing``, and coverage
is the proved share of that target count (truncated, with a sub-1% non-zero
ratio clamped up to 1, and ``None`` when the theory has no formal targets). No
Isabelle invocation is required.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES

FACT_COVERAGE_SCHEMA_VERSION = 1

# Label for nodes carrying no Isabelle theory (no fact, or an unqualified fact).
NO_FACT_LABEL = "(no fact)"

# Column order for the CSV per-theory roll-up. The Markdown table uses its own
# title-case display headers, so this constant is CSV-only.
FACT_COVERAGE_CSV_COLUMNS = (
    "theory",
    "node_count",
    "proved_count",
    "found_count",
    "problem_count",
    "coverage_percent",
)


@dataclass(frozen=True)
class TheoryStat:
    """Aggregate fact-coverage counts for a single Isabelle theory."""

    theory: str
    node_count: int
    proved_count: int
    found_count: int
    problem_count: int
    coverage_percent: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "theory": self.theory,
            "node_count": self.node_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "coverage_percent": self.coverage_percent,
        }


@dataclass(frozen=True)
class FactCoverageReport:
    """Per-theory fact-coverage roll-up across a :class:`BlueprintProject`."""

    project: str
    total_nodes: int
    theories: tuple[TheoryStat, ...]
    schema_version: int = FACT_COVERAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "total_nodes": self.total_nodes,
            "theory_count": len(self.theories),
            "theories": [theory.to_dict() for theory in self.theories],
        }


@dataclass
class _Bucket:
    nodes: int = 0
    targets: int = 0
    proved: int = 0
    found: int = 0
    problems: int = 0


def build_fact_coverage_report(project: BlueprintProject) -> FactCoverageReport:
    """Compute the per-theory fact-coverage roll-up for ``project``.

    Every node is grouped by ``node.isabelle.theory`` (derived from a
    ``Theory.fact`` qualified name); a node with no Isabelle theory falls under
    :data:`NO_FACT_LABEL`. Theories are ordered most-used-first, ties broken
    alphabetically for stable output.
    """

    buckets: dict[str, _Bucket] = {}
    for node in project.nodes:
        theory = node.isabelle.theory or NO_FACT_LABEL
        bucket = buckets.setdefault(theory, _Bucket())
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
        TheoryStat(
            theory=theory,
            node_count=bucket.nodes,
            proved_count=bucket.proved,
            found_count=bucket.found,
            problem_count=bucket.problems,
            coverage_percent=_coverage(bucket.proved, bucket.targets),
        )
        for theory, bucket in buckets.items()
    )
    stats = tuple(sorted(stats, key=lambda stat: (-stat.node_count, stat.theory)))

    return FactCoverageReport(
        project=project.name,
        total_nodes=len(project.nodes),
        theories=stats,
    )


def _escape_cell(text: str) -> str:
    """Neutralise Markdown table delimiters in a user-controlled cell.

    A literal ``|`` would otherwise start a new column and a newline would
    terminate the row, so both are flattened.
    """

    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


def render_fact_coverage_report(report: FactCoverageReport) -> str:
    """Render the roll-up as a compact Markdown table for the terminal."""

    lines = [
        f"# {report.project} fact coverage",
        "",
        (
            f"{report.total_nodes} node(s) across {len(report.theories)} "
            "theory(s)."
        ),
        "",
    ]
    if not report.theories:
        lines.append("_(no nodes)_")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Theory | Nodes | Proved | Found | Problems | Coverage |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for stat in report.theories:
        coverage = "n/a" if stat.coverage_percent is None else f"{stat.coverage_percent}%"
        lines.append(
            f"| {_escape_cell(stat.theory)} | {stat.node_count} | "
            f"{stat.proved_count} | {stat.found_count} | {stat.problem_count} | {coverage} |"
        )
    return "\n".join(lines) + "\n"


def render_fact_coverage_csv(report: FactCoverageReport) -> str:
    """Render the roll-up as CSV: one row per theory under
    :data:`FACT_COVERAGE_CSV_COLUMNS`.

    A ``None`` coverage is rendered as a blank cell. The writer pins
    ``lineterminator="\\n"`` so no ``\\r`` ever appears in the output.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FACT_COVERAGE_CSV_COLUMNS)
    for stat in report.theories:
        coverage = "" if stat.coverage_percent is None else stat.coverage_percent
        writer.writerow(
            [
                stat.theory,
                stat.node_count,
                stat.proved_count,
                stat.found_count,
                stat.problem_count,
                coverage,
            ]
        )
    return buffer.getvalue()


def render_fact_coverage_markdown(report: FactCoverageReport) -> str:
    """Render the per-theory roll-up as a Markdown document with a table.

    Identical to :func:`render_fact_coverage_report`; delegates so the table
    format has a single source of truth.
    """

    return render_fact_coverage_report(report)


def _coverage(proved: int, targets: int) -> int | None:
    if targets == 0:
        return None
    # Truncate (not round) so 100 means genuinely all proved; clamp a non-zero
    # but sub-1% ratio up to 1. Mirrors report.metrics.build_status_metrics.
    percent = proved * 100 // targets
    if percent == 0 and proved > 0:
        percent = 1
    return percent
