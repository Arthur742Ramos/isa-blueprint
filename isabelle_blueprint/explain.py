"""Human-readable explanations for blueprint status problems."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from isabelle_blueprint.isabelle.suggestions import FactSuggestion, suggestions_by_node
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject, ValidationReport
from isabelle_blueprint.model.status import FormalStatus


@dataclass
class NodeExplanation:
    node_id: str
    title: str
    formal_status: str
    severity: str
    summary: str
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def explain_project(
    project: BlueprintProject,
    *,
    node_id: str | None = None,
    fact_suggestions: list[FactSuggestion] | None = None,
) -> list[NodeExplanation]:
    """Explain why selected nodes are in their current status."""

    validation = project.validate()
    suggestion_index = suggestions_by_node(fact_suggestions or [])
    nodes = project.nodes if node_id is None else [n for n in project.nodes if n.id == node_id]
    if node_id is not None and not nodes:
        return [
            NodeExplanation(
                node_id=node_id,
                title=node_id,
                formal_status="unknown",
                severity="error",
                summary=f"Node {node_id!r} is not in this project.",
                next_steps=["Check the node id or regenerate build/project.json."],
            )
        ]
    return [_explain_node(project, node, validation, suggestion_index) for node in nodes]


def render_explanations(explanations: list[NodeExplanation]) -> str:
    lines: list[str] = []
    for explanation in explanations:
        lines.append(
            f"{explanation.node_id}: {explanation.summary} "
            f"[{explanation.severity}, formal={explanation.formal_status}]"
        )
        for reason in explanation.reasons:
            lines.append(f"  reason: {reason}")
        for suggestion in explanation.suggestions:
            lines.append(f"  suggestion: {suggestion}")
        for step in explanation.next_steps:
            lines.append(f"  next: {step}")
    return "\n".join(lines) + ("\n" if lines else "")


def _explain_node(
    project: BlueprintProject,
    node: BlueprintNode,
    validation: ValidationReport,
    suggestion_index: dict[str, FactSuggestion],
) -> NodeExplanation:
    missing_deps = [missing for owner, missing in validation.missing_dependencies if owner == node.id]
    cycles = [cycle for cycle in validation.cycles if node.id in cycle]
    reasons: list[str] = []
    suggestions: list[str] = []
    next_steps: list[str] = []

    if missing_deps:
        reasons.append("This node references undefined dependencies: " + ", ".join(missing_deps))
        for missing in missing_deps:
            hints = validation.suggestions.get(missing)
            if hints:
                suggestions.append(f"For dependency {missing!r}, did you mean {', '.join(hints)}?")
        next_steps.append("Fix the `uses` list or create the missing dependency nodes.")

    if cycles:
        rendered = [" -> ".join(cycle) for cycle in cycles]
        reasons.append("This node is part of a dependency cycle: " + "; ".join(rendered))
        next_steps.append("Break the cycle by extracting an earlier lemma or removing a reversed dependency.")

    status = node.status.formal
    if status == FormalStatus.MISSING:
        reasons.append("No Isabelle fact is assigned to this blueprint node.")
        next_steps.append("Add an `isabelle:` fact name, or leave it blueprint-only if no formal target is intended.")
        summary = "No formal target is assigned."
        severity = "info"
    elif status == FormalStatus.NAMED:
        reasons.append(f"Fact `{node.isabelle.fact}` is named but has not been checked yet.")
        next_steps.append("Run `isabelle-blueprint check` or `isabelle-blueprint dump`.")
        summary = "Formal target is named but unchecked."
        severity = "warning"
    elif status == FormalStatus.NOT_FOUND:
        reasons.append(f"Checker could not resolve `{node.isabelle.fact}` in the configured Isabelle context.")
        if node.id in suggestion_index:
            for fact in suggestion_index[node.id].suggestions:
                suggestions.append(f"Nearby Isabelle fact: `{fact}`")
        next_steps.append("Check the theory/session prefix, AFP dirs, and spelling of the fact name.")
        summary = "Named Isabelle fact was not found."
        severity = "error"
    elif status == FormalStatus.FOUND:
        reasons.append(f"Fact `{node.isabelle.fact}` exists, but proof trust has not been established.")
        next_steps.append("Run `dump` or a proof-status-aware `check` to detect sorry/oracle dependencies.")
        summary = "Fact exists, proof trust still needs confirmation."
        severity = "ok"
    elif status == FormalStatus.PROVED:
        reasons.append(f"Fact `{node.isabelle.fact}` exists and no sorry/oracle dependency was detected.")
        summary = "Fact is proved."
        severity = "ok"
    elif status == FormalStatus.TAINTED:
        reasons.append("The proof appears to depend on `sorry`, skipped proof, or another oracle.")
        if node.status.check_error:
            reasons.append(node.status.check_error)
        next_steps.append("Inspect theorem dependencies and replace the tainted proof path with a completed proof.")
        summary = "Fact is tainted by an oracle or skipped proof."
        severity = "error"
    elif status == FormalStatus.STALE:
        reasons.append("The blueprint inputs or dependencies changed after the last successful check.")
        next_steps.append("Rerun `isabelle-blueprint check --incremental` to refresh stale facts.")
        summary = "Cached proof status is stale."
        severity = "warning"
    elif status in {FormalStatus.BROKEN, FormalStatus.FAILED_CHECK}:
        if node.status.check_error:
            reasons.append(node.status.check_error)
        else:
            reasons.append("The Isabelle check failed before a more precise per-fact status was available.")
        next_steps.append("Open the check report and fix the first Isabelle build error.")
        summary = "Checker failed for this node."
        severity = "error"
    else:
        summary = "Status is not recognized by this version."
        severity = "warning"

    return NodeExplanation(
        node_id=node.id,
        title=node.title,
        formal_status=status.value,
        severity=severity,
        summary=summary,
        reasons=reasons,
        suggestions=suggestions,
        next_steps=next_steps,
    )
