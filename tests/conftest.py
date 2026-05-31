"""Pytest fixtures shared across the IsabelleBlueprint test suite."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.parser.markdown import parse_blueprint_text


@pytest.fixture
def sample_blueprint_text() -> str:
    return textwrap.dedent(
        """\
        # Demo blueprint

        ::: definition {#def-even}
        title: Even numbers
        isabelle: Arith_Demo.even_def
        status:
          blueprint: written
        :::

        An integer ``n`` is even when ``n mod 2 = 0``.
        :::

        ::: lemma {#lem-sum-even}
        title: Sum of evens is even
        isabelle: Arith_Demo.sum_even
        uses:
          - def-even
        status:
          blueprint: written
        :::

        If ``a`` and ``b`` are even, so is ``a + b``.

        ## Proof
        Substitute the definition and rearrange.
        :::
        """
    )


@pytest.fixture
def sample_project(sample_blueprint_text: str) -> BlueprintProject:
    return parse_blueprint_text(sample_blueprint_text, source="demo.md", project_name="demo")


@pytest.fixture
def two_node_chain() -> BlueprintProject:
    a = BlueprintNode(
        id="a",
        kind=NodeKind.DEFINITION,
        title="A",
        isabelle=IsabelleRef(fact="Demo.a"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.MISSING),
    )
    b = BlueprintNode(
        id="b",
        kind=NodeKind.LEMMA,
        title="B",
        uses=["a"],
        isabelle=IsabelleRef(fact="Demo.b"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.MISSING),
    )
    return BlueprintProject.from_nodes("chain", [a, b], sources=["demo.md"])


@pytest.fixture
def tmp_blueprint(tmp_path: Path, sample_blueprint_text: str) -> Path:
    p = tmp_path / "blueprint.md"
    p.write_text(sample_blueprint_text, encoding="utf-8")
    return p
