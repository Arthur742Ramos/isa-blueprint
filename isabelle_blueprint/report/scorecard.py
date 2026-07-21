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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import COMPLETE_FORMAL_STATUSES, BlueprintStatus
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics

SCORECARD_SCHEMA_VERSION = 1


class _ScoreConsole(Protocol):
    def dim(self, text: str) -> str: ...

    def success(self, text: str) -> str: ...

    def warning(self, text: str) -> str: ...

    def error(self, text: str) -> str: ...


# Statuses that count as "complete" formal work for readiness purposes, as
# their string values (this module compares against ``status.formal.value``).
# Derived from the shared model.status definition so every report agrees on
# what "complete" means.
_COMPLETE_FORMAL = frozenset(status.value for status in COMPLETE_FORMAL_STATUSES)

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

# Every recognised component name, in their canonical reporting order. Useful as
# a CLI ``choices``/validation list for per-component gates.
SCORE_COMPONENTS: tuple[str, ...] = tuple(_COMPONENT_LABELS)

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


@dataclass(frozen=True)
class ScorecardDelta:
    """The change in a scorecard's overall score and components vs a baseline.

    ``baseline_score`` is the previous overall score (``None`` if the baseline
    was ungradeable). ``score_change`` is ``current - baseline`` overall score
    (``None`` when either side is ungradeable). ``component_changes`` maps each
    component name to its percentage-point change (``current% - baseline%``),
    omitting any component undefined on either side.
    """

    baseline_score: int | None
    score_change: int | None
    component_changes: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_score": self.baseline_score,
            "score_change": self.score_change,
            "component_changes": dict(self.component_changes),
        }


def load_scorecard_baseline(path: Path) -> Scorecard:
    """Load a previously-saved scorecard JSON payload as a :class:`Scorecard`.

    ``path`` may point directly at a JSON file (as produced by
    ``scorecard --json``) or at a directory containing ``scorecard.json``.
    Raises :class:`BlueprintError` with a clear message when the file is
    missing, unreadable, not valid JSON, or not a recognised scorecard payload.
    """

    payload_path = path / "scorecard.json" if path.is_dir() else path
    try:
        raw = payload_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BlueprintError(f"scorecard baseline not found at {payload_path}") from exc
    except OSError as exc:
        raise BlueprintError(
            f"scorecard baseline could not be read: {payload_path}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BlueprintError(f"scorecard baseline is not valid JSON: {payload_path}") from exc
    if not isinstance(data, dict):
        raise BlueprintError(f"scorecard baseline must be a JSON object: {payload_path}")
    schema_version = data.get("schema_version")
    if schema_version != SCORECARD_SCHEMA_VERSION:
        raise BlueprintError(
            f"unsupported scorecard baseline schema_version {schema_version!r}; "
            f"expected {SCORECARD_SCHEMA_VERSION}: {payload_path}"
        )
    score = data.get("score")
    if not (score is None or isinstance(score, int)):
        raise BlueprintError(f"scorecard baseline has an invalid 'score': {payload_path}")
    project = data.get("project")
    if not isinstance(project, str):
        raise BlueprintError(f"scorecard baseline 'project' must be a string: {payload_path}")
    grade = data.get("grade")
    if not isinstance(grade, str):
        raise BlueprintError(f"scorecard baseline 'grade' must be a string: {payload_path}")
    raw_components = data.get("components")
    if not isinstance(raw_components, list):
        raise BlueprintError(f"scorecard baseline is missing its 'components': {payload_path}")
    components: list[ScoreComponent] = []
    for entry in raw_components:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise BlueprintError(f"scorecard baseline has a malformed component: {payload_path}")
        name = entry["name"]
        label = entry.get("label")
        detail = entry.get("detail")
        if not isinstance(label, str) or not isinstance(detail, str):
            raise BlueprintError(
                f"scorecard baseline component '{name}' is missing a string "
                f"'label'/'detail': {payload_path}"
            )
        if "score" not in entry:
            raise BlueprintError(
                f"scorecard baseline component '{name}' is missing its 'score': {payload_path}"
            )
        comp_score = entry["score"]
        if not (comp_score is None or isinstance(comp_score, (int, float))):
            raise BlueprintError(
                f"scorecard baseline component '{name}' has an invalid score: {payload_path}"
            )
        if comp_score is not None and not (0.0 <= float(comp_score) <= 1.0):
            raise BlueprintError(
                f"scorecard baseline component '{name}' score is out of range "
                f"[0, 1]: {payload_path}"
            )
        weight = entry.get("weight")
        if not isinstance(weight, (int, float)) or float(weight) < 0.0:
            raise BlueprintError(
                f"scorecard baseline component '{name}' has an invalid weight: {payload_path}"
            )
        components.append(
            ScoreComponent(
                name=name,
                label=label,
                score=None if comp_score is None else float(comp_score),
                weight=float(weight),
                detail=detail,
            )
        )
    return Scorecard(
        project=project,
        score=score,
        grade=grade,
        components=tuple(components),
        schema_version=SCORECARD_SCHEMA_VERSION,
    )


def build_scorecard_delta(current: Scorecard, baseline: Scorecard) -> ScorecardDelta:
    """Compute the :class:`ScorecardDelta` of ``current`` against ``baseline``."""

    if current.score is None or baseline.score is None:
        score_change: int | None = None
    else:
        score_change = current.score - baseline.score

    baseline_by_name = {c.name: c.score for c in baseline.components}
    component_changes: dict[str, int] = {}
    for component in current.components:
        if component.score is None:
            continue
        prev = baseline_by_name.get(component.name)
        if prev is None:
            continue
        component_changes[component.name] = round(component.score * 100) - round(prev * 100)
    return ScorecardDelta(
        baseline_score=baseline.score,
        score_change=score_change,
        component_changes=component_changes,
    )


def render_score_delta(score_change: int | None) -> str:
    """Format an overall ``score_change`` as a signed ``since baseline`` suffix."""

    if score_change is None:
        return "[n/a since baseline]"
    return f"[{score_change:+d} since baseline]"


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
            detail=(f"write-up credit across {node_count} node(s)" if node_count else "no nodes"),
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


def render_scorecard(card: Scorecard, *, delta: ScorecardDelta | None = None) -> str:
    """Render the scorecard as compact Markdown for the terminal or a file.

    When ``delta`` is provided (from a ``--since`` baseline) the overall line
    gains a signed ``[+N since baseline]`` suffix and each changed component row
    shows its percentage-point change; ``delta=None`` (the default) leaves the
    output byte-for-byte identical to the historical rendering.
    """

    from isabelle_blueprint import console

    headline = "n/a" if card.score is None else f"{card.score}/100"
    overall = _paint_score(f"{headline} ({card.grade})", card.score, console)
    if delta is not None:
        overall = f"{overall} {render_score_delta(delta.score_change)}"
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
        if delta is not None and component.name in delta.component_changes:
            score_text = f"{score_text} ({delta.component_changes[component.name]:+d})"
        weight_text = f"{round(component.weight * 100)}%"
        lines.append(f"| {component.label} | {score_text} | {weight_text} |")
    lines.append("")
    for component in card.components:
        score_text = "n/a" if component.score is None else f"{round(component.score * 100)}%"
        lines.append(f"- {component.label} ({score_text}): {component.detail}")
    return "\n".join(lines) + "\n"


def write_scorecard_markdown(
    card: Scorecard, path: Path, *, delta: ScorecardDelta | None = None
) -> Path:
    """Write :func:`render_scorecard` Markdown for ``card`` to ``path``.

    The parent directory is created if needed. Returns the path written.
    Colour is disabled while rendering so the persisted ``.md`` never contains
    ANSI escape codes even when stdout is an interactive TTY; the CLI's stdout
    colour behaviour is left unchanged. ``delta`` is forwarded to
    :func:`render_scorecard` so a ``--since`` run records the trend too.
    """

    from isabelle_blueprint import console

    path.parent.mkdir(parents=True, exist_ok=True)
    was_enabled = console.is_enabled()
    console.set_enabled(False)
    try:
        markdown = render_scorecard(card, delta=delta)
    finally:
        console.set_enabled(was_enabled)
    path.write_text(markdown, encoding="utf-8")
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
            (dep := by_id.get(dep_id)) is not None and dep.status.formal.value in _COMPLETE_FORMAL
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


def _paint_score(text: str, score: int | None, console: _ScoreConsole) -> str:
    if score is None:
        return console.dim(text)
    if score >= 80:
        return console.success(text)
    if score >= 60:
        return console.warning(text)
    return console.error(text)
