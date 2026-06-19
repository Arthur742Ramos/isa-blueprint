"""Tests for the Markdown blueprint parser."""
from __future__ import annotations

import textwrap

import pytest

from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus
from isabelle_blueprint.parser.markdown import parse_blueprint_text
from isabelle_blueprint.scaffold import render_node_stub


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


def test_invalid_explicit_status_raises_parse_error():
    with pytest.raises(ParseError, match="invalid formal status 'typo'"):
        _parse(
            """
            ::: theorem {#thm}
            status:
              formal: typo
            :::
            Body.
            :::
            """
        )


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


# --- Lighter authoring grammar -------------------------------------------------


def test_single_close_no_metadata():
    """A node may omit metadata entirely and use one closing ``:::``."""
    project = _parse(
        """
        ::: lemma {#add-comm}
        The sum is commutative.
        :::
        """
    )
    assert len(project.nodes) == 1
    node = project.nodes[0]
    assert node.id == "add-comm"
    assert "commutative" in node.statement


def test_title_humanized_from_id_when_omitted():
    """When no ``title:`` is given, derive a readable one from the id."""
    project = _parse(
        """
        ::: lemma {#add-comm}
        Body.
        :::
        """
    )
    assert project.nodes[0].title == "Add comm"


def test_explicit_title_wins_over_humanized():
    project = _parse(
        """
        ::: lemma {#add-comm}
        title: Commutativity of addition

        Body.
        :::
        """
    )
    assert project.nodes[0].title == "Commutativity of addition"


def test_inline_metadata_then_blank_line():
    """Inline ``key: value`` metadata is closed by a blank line, not ``:::``."""
    project = _parse(
        """
        ::: lemma {#l-blank}
        title: Blank separated
        uses: [d1]

        The body starts here.
        :::
        """
    )
    node = project.nodes[0]
    assert node.title == "Blank separated"
    assert node.uses == ["d1"]
    assert "body starts here" in node.statement


def test_frontmatter_metadata():
    """``---`` fenced YAML frontmatter is accepted as metadata."""
    project = _parse(
        """
        ::: theorem {#thm-fm}
        ---
        title: Frontmatter theorem
        uses: [lem-a, lem-b]
        ---
        Statement body.
        :::
        """
    )
    node = project.nodes[0]
    assert node.title == "Frontmatter theorem"
    assert node.uses == ["lem-a", "lem-b"]
    assert "Statement body" in node.statement


def test_body_first_line_bullet_list():
    """A body beginning with a bullet list is not mistaken for metadata."""
    project = _parse(
        """
        ::: remark {#r-list}

        - first point
        - second point
        :::
        """
    )
    node = project.nodes[0]
    assert "first point" in node.statement
    assert "second point" in node.statement


def test_body_starting_with_code_fence():
    project = _parse(
        """
        ::: lemma {#l-fence}

        ```isabelle
        lemma foo: "x = x" by simp
        ```
        :::
        """
    )
    node = project.nodes[0]
    assert "lemma foo" in node.statement


def test_status_defaults_to_written_with_body():
    """A node with a real body but no explicit status is 'written', not 'stub'."""
    project = _parse(
        """
        ::: lemma {#l-written}
        Some real content.
        :::
        """
    )
    assert project.nodes[0].status.blueprint == BlueprintStatus.WRITTEN


def test_explicit_status_overrides_written_default():
    project = _parse(
        """
        ::: lemma {#l-stub}
        status:
          blueprint: stub
        :::
        Some content.
        :::
        """
    )
    assert project.nodes[0].status.blueprint == BlueprintStatus.STUB




def test_render_node_stub_round_trips_through_parser():
    """A generated stub must parse back into an equivalent node."""
    text = render_node_stub("theorem", "thm:pythagoras", uses=["add-zero-right"])
    project = _parse(text)
    assert len(project.nodes) == 1
    node = project.nodes[0]
    assert node.id == "thm:pythagoras"
    assert node.kind.value == "theorem"
    assert node.title == "Pythagoras"
    assert node.isabelle is not None and node.isabelle.fact == "pythagoras"
    assert node.uses == ["add-zero-right"]
    assert node.status.blueprint == BlueprintStatus.STUB


def test_render_node_stub_without_fact_omits_isabelle():
    text = render_node_stub("definition", "set-union", fact="")
    project = _parse(text)
    node = project.nodes[0]
    assert node.title == "Set union"
    assert node.isabelle is None or node.isabelle.fact is None


def test_parse_blueprint_file_strips_leading_utf8_bom(tmp_path):
    """A leading UTF-8 BOM must not defeat the first anchored ^::: directive."""
    from isabelle_blueprint.parser.markdown import parse_blueprint_file

    text = textwrap.dedent(
        """
        ::: lemma {#lem-one}
        title: One
        :::

        Body.
        :::
        """
    ).lstrip("\n")
    path = tmp_path / "bom.md"
    # Prefixing the string with U+FEFF and encoding as utf-8 writes the BOM bytes.
    path.write_text("\ufeff" + text, encoding="utf-8")

    project = parse_blueprint_file(path)
    assert len(project.nodes) == 1
    assert project.nodes[0].id == "lem-one"
