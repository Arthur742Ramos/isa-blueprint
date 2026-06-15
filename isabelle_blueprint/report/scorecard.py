"""Composite project quality scorecard: one graded 0-100 health number.

``scorecard`` answers "how healthy is this project, at a glance, and where is
it weakest?". It distils the existing per-axis analyses into a single weighted
score (0-100) plus a letter grade (``A+`` ... ``F``) and a breakdown of the
component scores that fed it, so a project lead can track one number over time
and still see which dimension is dragging it down.

This is deliberately distinct from the categorical ``status`` health *label*
(``ready``/``stale``/``problem``/...): that label classifies the project's
current state, whereas the scorecard grades its overall quality on a continuous
scale. Every component is computed without invoking Isabelle, so the scorecard
works anywhere the blueprint parses.

Components (each a 0.0-1.0 ratio, or ``None`` when undefined and therefore
excluded from the weighted average):

* **coverage** - proved share of formal targets (mirrors the coverage metric).
* **integrity** - problem-free share of formal targets (broken/tainted/not_found
  /failed_check count against it).
* **structure** - share of nodes free of dependency cycles and missing
  dependencies.
* **freshness** - non-stale share of formal targets.
* **documentation** - graded write-up completeness across every node
  (``stub`` = 0, ``written`` = 0.6, ``reviewed`` = 1.0).
* **readiness** - share of *incomplete* nodes that are actionable now (all of
  their dependencies are already found/proved).

The overall score is the weight-normalised average of the components that are
defined, scaled to 0-100. When no component is defined (an empty project) the
score is ``None`` and the grade is ``n/a``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics

SCORECARD_SCHEMA_VERSION = 1

# Statuses that count as "complete" formal work for readiness purposes. Kept
# local (rather than importing roadmap.COMPLETE_FORMAL_STATUSES) so this module
# stays free of cross-report coupling; the set mirrors that definition.
_COMPLETE_FORMAL = frozenset({FormalStatus.FOUND.value, FormalStatus.PROVED.value})

# Graded credit for each informal write-up state.
_DOC_CREDIT: dict[str, float] = {
    BlueprintStatus.STUB.value: 0.0,
    BlueprintStatus.WRITTEN.value: 0.6,
    BlueprintStatus.REVIEWED.value: 1.0,
}

# Component weights. Their relative magnitudes are what matter: components that
# are ``None`` for a given project drop out and the rest are renormalised.
_WEIGHTS: dict[str, float] = {
    "coverage": 0.30,
    "integrity": 0.25,
    "structure": 0.15,
    "freshness": 0.10,
    "documentation": 0.10,
    "readiness": 0.10,
}

_COMPONENT_LABELS: dict[str, str] = {
    "coverage": "Coverage",
    "integrity": "Integrity",
    "structure": "Structure",
    "freshness": "Freshness",
    "documentation": "Documentation",
    "readiness": "Readiness",
}

# Letter-grade cutoffs (inclusive lower bound), highest first.
_GRADE_BANDS: tuple[tuple[int, str], ...] = (
    (97, "A+"),
    (93, "A"),
    (90, "A-"),
    (87, "B+"),
    (83, "B"),
    (80, "B-"),
    (77, "C+"),
    (73, "C"),
    (70, "C-"),
    (67, "D+"),
    (63, "D"),
    (60, "D-"),
    (0, "F"),
)


@dataclass(frozen=True)
class ScoreComponent:
    """One graded dimension that feeds the overall score."""

    name: str
    label: str
    score: float | None
    weight: float
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "score": None if self.score is None else round(self.score, 4),
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Scorecard:
    """A project's composite quality score plus its component breakdown."""

    project: str
    score: int | None
    grade: str
    components: tuple[ScoreComponent, ...]
    schema_version: int = SCORECARD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "score": self.score,
            "grade": self.grade,
            "components": [component.to_dict() for component in self.components],
        }


def grade_for(score: int | None) -> str:
    """Return the letter grade for a 0-100 ``score`` (``n/a`` when ``None``)."""

    if score is None:
        return "n/a"
    for threshold, letter in _GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


# Every recognised letter grade, best grade first (excludes the ``n/a`` sentinel
# used for an ungradeable project). Useful as a CLI ``choices`` list.
ALL_GRADES: tuple[str, ...] = tuple(letter for _threshold, letter in _GRADE_BANDS)


def grade_threshold(grade: str) -> int | None:
    """Return the inclusive minimum score a project needs to earn ``grade``.

    For example ``grade_threshold("B")`` is ``83``. Returns ``None`` when
    ``grade`` is not one of :data:`ALL_GRADES`, so callers can validate input.
    """

    for threshold, letter in _GRADE_BANDS:
        if letter == grade:
            return threshold
    return None


def build_scorecard(
    project: BlueprintProject, *, metrics: StatusMetrics | None = None
) -> Scorecard:
    """Compute the composite :class:`Scorecard` for ``project``.

    ``metrics`` lets a caller pass an already-computed
    :class:`~isabelle_blueprint.report.metrics.StatusMetrics` to avoid a
    redundant recomputation; when ``None`` (the default) it is computed here, so
    every existing caller is unaffected.
    """

    if metrics is None:
        metrics = build_status_metrics(project)
    node_count = metrics.node_count
    targets = metrics.formal_target_count

    coverage = _ratio(metrics.proved_count, targets)
    integrity = _ratio(targets - metrics.problem_count, targets)
    freshness = _ratio(targets - metrics.stale_count, targets)

    affected = _structurally_affected(project)
    structure = _ratio(node_count - affected, node_count)

    documentation = _documentation_score(project)
    readiness, actionable, incomplete = _readiness_score(project)

    components = (
        ScoreComponent(
            name="coverage",
            label=_COMPONENT_LABELS["coverage"],
            score=coverage,
            weight=_WEIGHTS["coverage"],
            detail=(
                f"{metrics.proved_count}/{targets} formal target(s) proved"
                if targets
                else "no formal targets yet"
            ),
        ),
        ScoreComponent(
            name="integrity",
            label=_COMPONENT_LABELS["integrity"],
            score=integrity,
            weight=_WEIGHTS["integrity"],
            detail=(
                f"{metrics.problem_count} problem status(es) among {targets} target(s)"
                if targets
                else "no formal targets yet"
            ),
        ),
        ScoreComponent(
            name="structure",
            label=_COMPONENT_LABELS["structure"],
            score=structure,
            weight=_WEIGHTS["structure"],
            detail=(
                f"{affected}/{node_count} node(s) in a cycle or missing a dependency"
                if node_count
                else "no nodes"
            ),
        ),
        ScoreComponent(
            name="freshness",
            label=_COMPONENT_LABELS["freshness"],
            score=freshness,
            weight=_WEIGHTS["freshness"],
            detail=(
                f"{metrics.stale_count} stale of {targets} target(s)"
                if targets
                else "no formal targets yet"
            ),
        ),
        ScoreComponent(
            name="documentation",
            label=_COMPONENT_LABELS["documentation"],
            score=documentation,
            weight=_WEIGHTS["documentation"],
            detail=(
                f"write-up credit across {node_count} node(s)"
                if node_count
                else "no nodes"
            ),
        ),
        ScoreComponent(
            name="readiness",
            label=_COMPONENT_LABELS["readiness"],
            score=readiness,
            weight=_WEIGHTS["readiness"],
            detail=(
                f"{actionable}/{incomplete} incomplete node(s) unblocked"
                if incomplete
                else "no incomplete nodes"
            ),
        ),
    )

    score = _weighted_score(components)
    return Scorecard(
        project=project.name,
        score=score,
        grade=grade_for(score),
        components=components,
    )


def render_scorecard(card: Scorecard) -> str:
    """Render the scorecard as compact Markdown for the terminal or a file."""

    from isabelle_blueprint import console

    headline = "n/a" if card.score is None else f"{card.score}/100"
    overall = _paint_score(f"{headline} ({card.grade})", card.score, console)
    lines = [
        f"# {card.project} scorecard",
        "",
        f"Overall: {overall}",
        "",
        "| Component | Score | Weight |",
        "| --- | --- | --- |",
    ]
    for component in card.components:
        score_text = "n/a" if component.score is None else f"{round(component.score * 100)}%"
        weight_text = f"{round(component.weight * 100)}%"
        lines.append(f"| {component.label} | {score_text} | {weight_text} |")
    lines.append("")
    for component in card.components:
        score_text = "n/a" if component.score is None else f"{round(component.score * 100)}%"
        lines.append(f"- {component.label} ({score_text}): {component.detail}")
    return "\n".join(lines) + "\n"


def write_scorecard_markdown(card: Scorecard, path: Path) -> Path:
    """Write :func:`render_scorecard` Markdown for ``card`` to ``path``.

    The parent directory is created if needed. Returns the path written.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_scorecard(card), encoding="utf-8")
    return path


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return ``numerator / denominator`` clamped to ``[0, 1]``; ``None`` if undefined."""

    if denominator <= 0:
        return None
    value = numerator / denominator
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _structurally_affected(project: BlueprintProject) -> int:
    """Count nodes tangled in a cycle or referencing a missing dependency."""

    validation = project.validate()
    affected: set[str] = {node_id for cycle in validation.cycles for node_id in cycle}
    affected.update(node_id for node_id, _missing in validation.missing_dependencies)
    return len(affected)


def _documentation_score(project: BlueprintProject) -> float | None:
    if not project.nodes:
        return None
    total = sum(_DOC_CREDIT.get(node.status.blueprint.value, 0.0) for node in project.nodes)
    return total / len(project.nodes)


def _readiness_score(project: BlueprintProject) -> tuple[float | None, int, int]:
    """Return (readiness, actionable_count, incomplete_count).

    An *incomplete* node is one whose formal status is not yet found/proved. It
    is *actionable* when every dependency it ``uses`` exists and is already
    found/proved - exactly the precondition for it to become agent-ready.
    """

    by_id = project.by_id()
    incomplete = [
        node for node in project.nodes if node.status.formal.value not in _COMPLETE_FORMAL
    ]
    if not incomplete:
        return None, 0, 0
    actionable = 0
    for node in incomplete:
        deps_ok = all(
            (dep := by_id.get(dep_id)) is not None
            and dep.status.formal.value in _COMPLETE_FORMAL
            for dep_id in node.uses
        )
        if deps_ok:
            actionable += 1
    return actionable / len(incomplete), actionable, len(incomplete)


def _weighted_score(components: tuple[ScoreComponent, ...]) -> int | None:
    weighted = 0.0
    total_weight = 0.0
    for component in components:
        if component.score is None:
            continue
        weighted += component.score * component.weight
        total_weight += component.weight
    if total_weight == 0.0:
        return None
    return round(weighted / total_weight * 100)


def _paint_score(text: str, score: int | None, console) -> str:  # type: ignore[no-untyped-def]
    if score is None:
        return console.dim(text)
    if score >= 80:
        return console.success(text)
    if score >= 60:
        return console.warning(text)
    return console.error(text)
