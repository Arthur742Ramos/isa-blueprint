"""Structural and quality lint checks for a blueprint project.

``lint`` complements ``check``: where ``check`` talks to Isabelle to confirm
facts exist, ``lint`` inspects the *blueprint itself* for hygiene problems that
are visible without a prover - dangling dependencies, cycles, empty statements,
proof-bearing nodes with no informal proof, isolated nodes, and formal statuses
that signal something is actively broken.

Findings carry a severity:

* ``error``   - structural problems that make the blueprint inconsistent
                (duplicate ids, missing dependencies, cycles) or a formal
                target that is actively broken.
* ``warning`` - quality issues worth fixing soon (empty statement, a stale
                proof that needs re-checking).
* ``info``    - gentle suggestions (a lemma with no informal proof, a node that
                nothing else depends on, a node with no Isabelle fact yet).

The set of checks is deliberately conservative so the command stays useful as a
CI gate via ``--strict`` (which fails when any ``error`` finding is present).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from isabelle_blueprint import console
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

# Node kinds that are expected to carry an informal proof sketch.
_PROOF_BEARING_KINDS = frozenset(
    {
        NodeKind.LEMMA,
        NodeKind.THEOREM,
        NodeKind.PROPOSITION,
        NodeKind.COROLLARY,
    }
)


@dataclass(frozen=True)
class LintFinding:
    """A single lint result."""

    code: str
    severity: str
    message: str
    node_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "node_id": self.node_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class LintReport:
    """The aggregate result of linting a project."""

    project: str
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_INFO)

    @property
    def ok(self) -> bool:
        """True when no ``error``-severity findings are present."""
        return self.error_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "ok": self.ok,
            "counts": {
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
                "total": len(self.findings),
            },
            "findings": [f.to_dict() for f in self.findings],
        }


def build_lint_report(project: BlueprintProject) -> LintReport:
    """Run every lint check against ``project`` and collect the findings.

    Findings are sorted by descending severity (errors first), then by node id
    so the output is stable across runs.
    """
    findings: list[LintFinding] = []
    findings.extend(_structural_findings(project))
    findings.extend(_self_dependency_findings(project))
    findings.extend(_quality_findings(project))
    findings.extend(_duplicate_title_findings(project))
    findings.extend(_singleton_tag_findings(project))
    findings.extend(_tag_case_collision_findings(project))

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), f.node_id or "", f.code))
    return LintReport(project=project.name, findings=findings)


def _structural_findings(project: BlueprintProject) -> list[LintFinding]:
    report = project.validate()
    findings: list[LintFinding] = []
    for dup in report.duplicate_ids:
        findings.append(
            LintFinding(
                code="duplicate-id",
                severity=SEVERITY_ERROR,
                node_id=dup,
                message=f"duplicate node id {dup!r}",
            )
        )
    for node_id, missing in report.missing_dependencies:
        msg = f"depends on undefined node {missing!r}"
        hints = report.suggestions.get(missing)
        if hints:
            quoted = " or ".join(repr(h) for h in hints)
            msg += f" (did you mean {quoted}?)"
        findings.append(
            LintFinding(
                code="missing-dependency",
                severity=SEVERITY_ERROR,
                node_id=node_id,
                message=msg,
            )
        )
    for cycle in report.cycles:
        findings.append(
            LintFinding(
                code="cycle",
                severity=SEVERITY_ERROR,
                node_id=cycle[0] if cycle else None,
                message="dependency cycle: " + " -> ".join(cycle),
            )
        )
    return findings


def _self_dependency_findings(project: BlueprintProject) -> list[LintFinding]:
    """Flag any node whose ``uses`` list references its own id."""
    findings: list[LintFinding] = []
    for node in project.nodes:
        if node.id in node.uses:
            findings.append(
                LintFinding(
                    code="self-dependency",
                    severity=SEVERITY_ERROR,
                    node_id=node.id,
                    message=f"node {node.id!r} depends on itself",
                )
            )
    return findings


def _quality_findings(project: BlueprintProject) -> list[LintFinding]:
    findings: list[LintFinding] = []
    # Build the set of ids that something else depends on, for isolation checks.
    depended_on: set[str] = set()
    for node in project.nodes:
        depended_on.update(node.uses)

    multi_node = len(project.nodes) > 1
    for node in project.nodes:
        formal = node.status.formal

        if formal.value in PROBLEM_FORMAL_STATUSES:
            findings.append(
                LintFinding(
                    code="broken-formal-status",
                    severity=SEVERITY_ERROR,
                    node_id=node.id,
                    message=f"formal status is {formal.value!r}",
                )
            )
        elif formal == FormalStatus.STALE:
            findings.append(
                LintFinding(
                    code="stale-formal-status",
                    severity=SEVERITY_WARNING,
                    node_id=node.id,
                    message="formal status is 'stale'; re-run check after dependency changes",
                )
            )

        if not node.statement.strip():
            findings.append(
                LintFinding(
                    code="empty-statement",
                    severity=SEVERITY_WARNING,
                    node_id=node.id,
                    message="node has no statement text",
                )
            )

        if node.kind in _PROOF_BEARING_KINDS and not node.informal_proof.strip():
            findings.append(
                LintFinding(
                    code="missing-informal-proof",
                    severity=SEVERITY_INFO,
                    node_id=node.id,
                    message=f"{node.kind.value} has no informal proof sketch",
                )
            )

        if (
            node.status.formal == FormalStatus.MISSING
            and node.isabelle.qualified_name is None
            and node.kind != NodeKind.REMARK
            and node.kind != NodeKind.NOTE
            and node.kind != NodeKind.EXAMPLE
        ):
            findings.append(
                LintFinding(
                    code="no-isabelle-fact",
                    severity=SEVERITY_INFO,
                    node_id=node.id,
                    message="no Isabelle fact assigned yet",
                )
            )

        if multi_node and not node.uses and node.id not in depended_on:
            findings.append(
                LintFinding(
                    code="isolated-node",
                    severity=SEVERITY_INFO,
                    node_id=node.id,
                    message="node has no dependencies and nothing depends on it",
                )
            )

    return findings


def _duplicate_title_findings(project: BlueprintProject) -> list[LintFinding]:
    """Flag nodes that share an identical (case-insensitive, trimmed) title."""
    groups: dict[str, list[str]] = {}
    for node in project.nodes:
        key = node.title.strip().casefold()
        if not key:
            continue
        groups.setdefault(key, []).append(node.id)

    findings: list[LintFinding] = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        ordered = sorted(ids)
        for node_id in ordered:
            others = ", ".join(repr(other) for other in ordered if other != node_id)
            findings.append(
                LintFinding(
                    code="duplicate-title",
                    severity=SEVERITY_WARNING,
                    node_id=node_id,
                    message=f"title duplicates node(s) {others}",
                )
            )
    return findings


def _singleton_tag_findings(project: BlueprintProject) -> list[LintFinding]:
    """Flag tags carried by exactly one node (likely typos or orphan categories)."""
    users: dict[str, list[str]] = {}
    for node in project.nodes:
        for tag in dict.fromkeys(node.tags):
            users.setdefault(tag, []).append(node.id)

    findings: list[LintFinding] = []
    for tag in sorted(users):
        ids = users[tag]
        if len(ids) != 1:
            continue
        node_id = ids[0]
        findings.append(
            LintFinding(
                code="singleton-tag",
                severity=SEVERITY_INFO,
                node_id=node_id,
                message=f"tag {tag!r} is used by only one node {node_id!r}",
            )
        )
    return findings


def _tag_case_collision_findings(project: BlueprintProject) -> list[LintFinding]:
    """Flag tags that differ only by case across the blueprint.

    Tags whose spellings agree under case-folding but disagree literally (e.g.
    ``"Algebra"`` and ``"algebra"``) fragment the tag rollup into separate
    buckets. One ``info`` finding is emitted per colliding fold key, listing the
    colliding spellings with an example node for each.
    """
    spellings: dict[str, dict[str, str]] = {}
    for node in project.nodes:
        for tag in dict.fromkeys(node.tags):
            key = tag.casefold()
            seen = spellings.setdefault(key, {})
            seen.setdefault(tag, node.id)

    findings: list[LintFinding] = []
    for key in sorted(spellings):
        seen = spellings[key]
        if len(seen) < 2:
            continue
        parts = ", ".join(
            f"{tag!r} (e.g. node {node_id!r})" for tag, node_id in sorted(seen.items())
        )
        findings.append(
            LintFinding(
                code="tag-case-collision",
                severity=SEVERITY_INFO,
                node_id=None,
                message=f"tags differ only by case: {parts}",
            )
        )
    return findings


def render_lint_report(report: LintReport) -> str:
    """Render ``report`` as a concise human-readable summary (trailing newline)."""
    lines = [f"{report.project}: {_headline(report)}"]
    for finding in report.findings:
        location = f" [{finding.node_id}]" if finding.node_id else ""
        severity = _paint_severity(finding.severity)
        lines.append(f"  {severity}: {finding.code}{location} - {finding.message}")
    return "\n".join(lines) + "\n"


def _escape_cell(text: str) -> str:
    """Flatten newlines and escape ``|`` so a value cannot break a table row."""

    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


def render_lint_markdown(report: LintReport) -> str:
    """Render ``report`` as a standalone Markdown document (trailing newline).

    A heading, a one-line summary count, and a table of findings (code,
    severity, node, message). Message cells are escaped so a literal ``|`` in a
    message cannot break the table.
    """

    lines = [
        f"# {report.project} lint",
        "",
        f"{_headline(report)}.",
        "",
    ]
    if report.findings:
        lines.extend(
            [
                "| Code | Severity | Node | Message |",
                "| --- | --- | --- | --- |",
            ]
        )
        for finding in report.findings:
            node = finding.node_id or "-"
            lines.append(
                f"| {_escape_cell(finding.code)} | {_escape_cell(finding.severity)} | "
                f"{_escape_cell(node)} | {_escape_cell(finding.message)} |"
            )
    return "\n".join(lines) + "\n"


def _paint_severity(severity: str) -> str:
    if severity == SEVERITY_ERROR:
        return console.error(severity)
    if severity == SEVERITY_WARNING:
        return console.warning(severity)
    return console.info(severity)


def _headline(report: LintReport) -> str:
    if not report.findings:
        return "no lint findings"
    return (
        f"{report.error_count} error(s), "
        f"{report.warning_count} warning(s), "
        f"{report.info_count} info"
    )
