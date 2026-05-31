"""Tests for Lean Blueprint-style LaTeX parsing."""
from __future__ import annotations

import textwrap

import pytest

from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.parser import parse_blueprint_file
from isabelle_blueprint.parser.latex import parse_latex_text, render_markdown_blueprint


def _parse(text: str):
    return parse_latex_text(textwrap.dedent(text), source="blueprint.tex", project_name="tex")


def test_parse_latex_theorem_with_lean_blueprint_metadata():
    project = _parse(
        r"""
        \begin{theorem}[Sum of evens]
        \label{thm:sum-even}
        \lean{Arith_Demo.sum_even}
        \uses{def:even, lem:add-comm}
        \leanok

        If two integers are even, their sum is even.

        \begin{proof}
        Expand both divisibility witnesses and combine them.
        \end{proof}
        \end{theorem}
        """
    )

    node = project.nodes[0]
    assert node.id == "thm:sum-even"
    assert node.kind.value == "theorem"
    assert node.title == "Sum of evens"
    assert node.isabelle.fact == "Arith_Demo.sum_even"
    assert node.isabelle.theory == "Arith_Demo"
    assert node.uses == ["def:even", "lem:add-comm"]
    assert node.status.formal == FormalStatus.FOUND
    assert "two integers" in node.statement
    assert "Expand both" in node.informal_proof


def test_parse_latex_accepts_isabelle_metadata_and_tags():
    project = _parse(
        r"""
        \begin{lemma}
        \label{lem-basic}
        \isabelle{Demo.basic}
        \tags{algebra, smoke}
        Body.
        \end{lemma}
        """
    )

    node = project.nodes[0]
    assert node.title == "Lem basic"
    assert node.tags == ["algebra", "smoke"]
    assert node.status.formal == FormalStatus.NAMED


def test_latex_node_without_label_is_rejected():
    with pytest.raises(ParseError, match="missing a \\\\label"):
        _parse(
            r"""
            \begin{lemma}
            Body.
            \end{lemma}
            """
        )


def test_parse_blueprint_file_dispatches_by_tex_suffix(tmp_path):
    path = tmp_path / "blueprint.tex"
    path.write_text(
        textwrap.dedent(
            r"""
            \begin{definition}
            \label{def:x}
            Statement.
            \end{definition}
            """
        ),
        encoding="utf-8",
    )
    project = parse_blueprint_file(path)
    assert [node.id for node in project.nodes] == ["def:x"]


def test_latex_project_can_render_back_to_markdown_interchange():
    project = _parse(
        r"""
        \begin{corollary}[C]
        \label{cor:c}
        \isabelle{Demo.c}
        Text.
        \end{corollary}
        """
    )
    markdown = render_markdown_blueprint(project)
    assert "::: corollary {#cor:c}" in markdown
    assert "isabelle: Demo.c" in markdown
    assert "Text." in markdown
