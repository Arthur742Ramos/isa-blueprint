"""A single, explainable CI gate over a blueprint project.

``gate`` rolls the most common "should CI fail?" checks into one command so a
pipeline does not have to chain ``lint --strict``, a coverage assertion, and a
``--fail-on`` policy by hand. Every individual check is reported (pass or fail)
so a red gate always says *why* it is red.

The checks are:

* ``lint``      - the structural/quality lint report has no ``error`` findings.
                  This already subsumes dependency cycles, duplicate ids,
                  missing dependencies, and broken formal statuses.
* ``coverage``  - only evaluated when ``min_coverage`` is given. Fails when the
                  proved coverage percentage is below the threshold, or is
                  undefined (no formal targets yet) - an unknown coverage cannot
                  be shown to clear the bar.
* ``fail-on``   - only evaluated when ``fail_on`` statuses are given. Fails when
                  any node's formal status is in the selected set.
* ``min_grade`` - only evaluated when ``min_grade`` is given. Fails when the
                  project scorecard grade is below the requested letter grade,
                  or is undefined (no gradeable components).

The gate is pure: it never talks to Isabelle or the network. Feed it a project
that already had any stored check report applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report._markdown import md_cell as _md_cell
from isabelle_blueprint.report.lint import build_lint_report
from isabelle_blueprint.report.metrics import build_status_metrics
from isabelle_blueprint.report.scorecard import build_scorecard, grade_threshold


@dataclass(frozen=True)
class GateCheck:
    """The outcome of one named gate check."""

    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class GateReport:
    """The aggregate result of running the gate over a project."""

    project: str
    checks: list[GateCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failed(self) -> list[GateCheck]:
        return [check for check in self.checks if not check.ok]

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "failed": [check.name for check in self.failed],
        }


def build_gate_report(
    project: BlueprintProject,
    *,
    min_coverage: int | None = None,
    fail_on: set[str] | None = None,
    min_grade: str | None = None,
) -> GateReport:
    """Evaluate every requested gate check against ``project``."""
    checks: list[GateCheck] = []

    # Status metrics feed both the coverage and min_grade checks; compute them
    # once (when either is requested) and share the single object.
    metrics = (
        build_status_metrics(project)
        if (min_coverage is not None or min_grade is not None)
        else None
    )

    lint = build_lint_report(project)
    checks.append(
        GateCheck(
            name="lint",
            ok=lint.ok,
            detail=(
                "no lint errors"
                if lint.ok
                else f"{lint.error_count} lint error(s) "
                f"({lint.warning_count} warning(s))"
            ),
        )
    )

    if min_coverage is not None:
        assert metrics is not None  # computed above when min_coverage is set
        coverage = metrics.coverage_percent
        if coverage is None:
            checks.append(
                GateCheck(
                    name="coverage",
                    ok=False,
                    detail=f"coverage is undefined (no formal targets); need >= {min_coverage}%",
                )
            )
        else:
            checks.append(
                GateCheck(
                    name="coverage",
                    ok=coverage >= min_coverage,
                    detail=f"coverage {coverage}% (threshold {min_coverage}%)",
                )
            )

    if fail_on:
        offenders = sorted(
            node.id for node in project.nodes if node.status.formal.value in fail_on
        )
        selected = ", ".join(sorted(fail_on))
        if offenders:
            checks.append(
                GateCheck(
                    name="fail-on",
                    ok=False,
                    detail=f"{len(offenders)} node(s) match [{selected}]: "
                    + ", ".join(offenders),
                )
            )
        else:
            checks.append(
                GateCheck(
                    name="fail-on",
                    ok=True,
                    detail=f"no node matches [{selected}]",
                )
            )

    if min_grade is not None:
        assert metrics is not None  # computed above when min_grade is set
        threshold = grade_threshold(min_grade)
        card = build_scorecard(project, metrics=metrics)
        if card.score is None:
            # Intentional divergence from ``scorecard --min-grade``: an
            # ungradeable project (no gradeable components) FAILS the gate,
            # because CI cannot show an unknown grade clears the bar.
            checks.append(
                GateCheck(
                    name="min_grade",
                    ok=False,
                    detail=f"grade is undefined (no gradeable components); need >= {min_grade}",
                )
            )
        else:
            ok = threshold is not None and card.score >= threshold
            checks.append(
                GateCheck(
                    name="min_grade",
                    ok=ok,
                    detail=f"grade {card.grade} ({card.score}/100); threshold {min_grade}",
                )
            )

    return GateReport(project=project.name, checks=checks)


def render_gate_report(report: GateReport) -> str:
    """Render ``report`` as concise human-readable text (trailing newline).

    The pass/fail verdicts are colourised through :mod:`console` (green for
    pass, red for fail) when colour is enabled, matching the other health
    commands. Colour is a no-op for direct calls and machine-readable output.
    """
    from isabelle_blueprint import console

    headline = console.success("PASS") if report.ok else console.error("FAIL")
    lines = [f"{report.project}: gate {headline}"]
    for check in report.checks:
        mark = console.success("ok") if check.ok else console.error("FAIL")
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    return "\n".join(lines) + "\n"


def render_gate_markdown(report: GateReport) -> str:
    """Render ``report`` as a Markdown document (trailing newline).

    A heading is followed by an overall PASS/FAIL verdict line and a table of
    every check (name, ok, detail). The output is plain Markdown with no ANSI
    colour, so it is safe to capture into a file or a CI summary.
    """
    verdict = "PASS" if report.ok else "FAIL"
    lines = [
        f"# Gate: {_md_cell(report.project)}",
        "",
        f"**Overall:** {verdict}",
        "",
        "| Check | OK | Detail |",
        "| --- | :---: | --- |",
    ]
    for check in report.checks:
        ok_mark = "yes" if check.ok else "no"
        lines.append(
            f"| {_md_cell(check.name)} | {ok_mark} | {_md_cell(check.detail)} |"
        )
    return "\n".join(lines) + "\n"
