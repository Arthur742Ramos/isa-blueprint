from __future__ import annotations

from isabelle_blueprint.explain import explain_project, render_explanations
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str, formal: FormalStatus, *, uses=None, error=None):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal, check_error=error),
    )


def test_explain_not_found_suggests_spelling():
    project = BlueprintProject.from_nodes("p", [_node("a", FormalStatus.NOT_FOUND)])

    explanation = explain_project(project)[0]

    assert explanation.severity == "error"
    assert "not found" in explanation.summary.lower()
    assert explanation.next_steps


def test_explain_missing_dependency():
    project = BlueprintProject.from_nodes("p", [_node("a", FormalStatus.NAMED, uses=["missing"])])

    explanation = explain_project(project)[0]

    assert any("undefined dependencies" in reason for reason in explanation.reasons)


def test_explain_unknown_node():
    project = BlueprintProject.from_nodes("p", [])

    explanation = explain_project(project, node_id="nope")[0]

    assert explanation.node_id == "nope"
    assert explanation.severity == "error"


def test_render_explanations_is_human_readable():
    project = BlueprintProject.from_nodes("p", [_node("a", FormalStatus.TAINTED, error="uses sorry")])

    text = render_explanations(explain_project(project))

    assert "a:" in text
    assert "uses sorry" in text
