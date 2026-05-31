"""Tests for the Markdown blueprint parser."""
from __future__ import annotations

import textwrap

import pytest

from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus
from isabelle_blueprint.parser.markdown import parse_blueprint_text


def _parse(text: str):
    return parse_blueprint_text(textwrap.dedent(text), source="t.md", project_name="t")


def test_minimal_node_with_kind_and_id_in_opener():
    project = _parse(
        """
        ::: lemma {#lem-one}
        title: One
        :::

        Body.
        :::
        """
    )
    assert len(project.nodes) == 1
    node = project.nodes[0]
    assert node.id == "lem-one"
    assert node.kind.value == "lemma"
    assert node.title == "One"
    assert "Body." in node.statement


def test_pandoc_brace_attribute_syntax():
    """`::: {.theorem #id}` is equivalent to `::: theorem {#id}`."""
    project = _parse(
        """
        ::: {.theorem #thm-x}
        title: X
        :::

        Body.
        :::
        """
    )
    assert len(project.nodes) == 1
    assert project.nodes[0].kind.value == "theorem"
    assert project.nodes[0].id == "thm-x"


def test_id_via_metadata_fallback():
    project = _parse(
        """
        ::: definition
        id: def-from-meta
        title: From meta
        :::

        Body.
        :::
        """
    )
    assert project.nodes[0].id == "def-from-meta"


def test_missing_id_raises():
    with pytest.raises(ParseError, match="missing an id"):
        _parse(
            """
            ::: lemma
            title: No id here
            :::

            Body.
            :::
            """
        )


def test_unknown_kind_falls_back_to_other():
    project = _parse(
        """
        ::: notation {#notation-x}
        title: Notation
        :::

        Body.
        :::
        """
    )
    assert project.nodes[0].kind.value == "other"


def test_uses_accepts_list_and_string():
    project = _parse(
        """
        ::: lemma {#a}
        uses:
          - dep1
          - dep2
        :::
        Body.
        :::

        ::: lemma {#b}
        uses: dep1, dep2
        :::
        Body.
        :::
        """
    )
    assert project.nodes[0].uses == ["dep1", "dep2"]
    assert project.nodes[1].uses == ["dep1", "dep2"]


def test_status_mapping_split_axes():
    project = _parse(
        """
        ::: theorem {#thm}
        status:
          blueprint: reviewed
          formal: found
          agent: ready
        :::
        Body.
        :::
        """
    )
    s = project.nodes[0].status
    assert s.blueprint == BlueprintStatus.REVIEWED
    assert s.formal == FormalStatus.FOUND
    assert s.agent == AgentStatus.READY


def test_isabelle_shorthand_derives_theory():
    project = _parse(
        """
        ::: lemma {#l}
        isabelle: Theory.fact_name
        :::
        Body.
        :::
        """
    )
    ref = project.nodes[0].isabelle
    assert ref.fact == "Theory.fact_name"
    assert ref.theory == "Theory"


def test_isabelle_mapping_explicit():
    project = _parse(
        """
        ::: lemma {#l}
        isabelle:
          fact: foo
          theory: Bar
          session: Baz
        :::
        Body.
        :::
        """
    )
    ref = project.nodes[0].isabelle
    assert ref.fact == "foo"
    assert ref.theory == "Bar"
    assert ref.session == "Baz"


def test_body_split_on_proof_heading():
    project = _parse(
        """
        ::: lemma {#l}
        title: t
        :::
        Statement line 1.

        Statement line 2.

        ## Proof
        Step 1.

        Step 2.
        :::
        """
    )
    node = project.nodes[0]
    assert "Statement line 1." in node.statement
    assert "Step 1." in node.informal_proof
    assert "## Proof" not in node.statement
    assert "## Proof" not in node.informal_proof


def test_proof_heading_inside_code_fence_is_ignored():
    project = _parse(
        """
        ::: lemma {#l}
        title: t
        :::
        Statement.

        ```
        ## Proof
        not a real heading
        ```

        ## Proof
        Real proof.
        :::
        """
    )
    node = project.nodes[0]
    assert "not a real heading" in node.statement
    assert "Real proof." in node.informal_proof


def test_triple_colon_inside_code_fence_does_not_close_block():
    project = _parse(
        """
        ::: lemma {#l}
        title: t
        :::
        Statement.

        ```
        :::
        ```

        more text
        :::
        """
    )
    assert len(project.nodes) == 1
    assert "more text" in project.nodes[0].statement


def test_invalid_yaml_raises_parse_error():
    with pytest.raises(ParseError, match="invalid YAML"):
        _parse(
            """
            ::: lemma {#l}
            title: "unterminated
            :::
            Body.
            :::
            """
        )


def test_unterminated_block_raises():
    with pytest.raises(ParseError, match="unterminated"):
        _parse(
            """
            ::: lemma {#l}
            title: t
            :::
            Body without closing fence.
            """
        )


def test_multiple_nodes_in_one_document():
    project = _parse(
        """
        ::: definition {#d1}
        :::
        First.
        :::

        Some prose outside any block - ignored.

        ::: lemma {#l1}
        uses: [d1]
        :::
        Second.
        :::
        """
    )
    assert [n.id for n in project.nodes] == ["d1", "l1"]
    assert project.nodes[1].uses == ["d1"]


def test_parse_blueprint_file(tmp_blueprint):
    from isabelle_blueprint.parser.markdown import parse_blueprint_file

    project = parse_blueprint_file(tmp_blueprint)
    assert {n.id for n in project.nodes} == {"def-even", "lem-sum-even"}
