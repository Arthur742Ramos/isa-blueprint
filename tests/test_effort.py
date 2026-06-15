"""Tests for the optional per-node ``effort`` weight and effort-weighted report."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.parser.latex import (
    parse_latex_text,
    render_latex_blueprint,
    render_markdown_blueprint,
)
from isabelle_blueprint.parser.markdown import parse_blueprint_text
from isabelle_blueprint.report.effort import build_effort_report, render_effort_report


def _md(effort_line: str) -> str:
    return textwrap.dedent(
        f"""\
        # demo

        ::: lemma {{#a}}
        title: A
        isabelle: Demo.a
        {effort_line}
        status: proved

        A statement.
        :::
        """
    )


# ---------------------------------------------------------------------------
# Markdown parsing + round-trip
# ---------------------------------------------------------------------------


def test_markdown_effort_parsed_as_int():
    project = parse_blueprint_text(_md("effort: 3"))
    assert project.nodes[0].effort == 3


def test_markdown_effort_quoted_string_coerced():
    project = parse_blueprint_text(_md('effort: "5"'))
    assert project.nodes[0].effort == 5


def test_markdown_effort_absent_is_none():
    project = parse_blueprint_text(_md("title: A"))
    assert project.nodes[0].effort is None


def test_markdown_effort_round_trips_through_writer():
    project = parse_blueprint_text(_md("effort: 7"))
    rendered = render_markdown_blueprint(project)
    assert "effort: 7" in rendered
    reparsed = parse_blueprint_text(rendered)
    assert reparsed.nodes[0].effort == 7


@pytest.mark.parametrize("value", ["0", "-2", "abc", "true", "1.5"])
def test_markdown_invalid_effort_raises(value):
    with pytest.raises(ParseError):
        parse_blueprint_text(_md(f"effort: {value}"))


# ---------------------------------------------------------------------------
# LaTeX parsing + round-trip
# ---------------------------------------------------------------------------


def _tex(effort_line: str) -> str:
    return textwrap.dedent(
        f"""\
        \\begin{{lemma}}[A]
        \\label{{a}}
        \\isabelle{{Demo.a}}
        {effort_line}

        A statement.
        \\end{{lemma}}
        """
    )


def test_latex_effort_parsed_and_stripped_from_statement():
    project = parse_latex_text(_tex("\\effort{4}"), source="b.tex", project_name="t")
    node = project.nodes[0]
    assert node.effort == 4
    assert "effort" not in node.statement


def test_latex_effort_round_trips_through_writer():
    project = parse_latex_text(_tex("\\effort{6}"), source="b.tex", project_name="t")
    rendered = render_latex_blueprint(project)
    assert "\\effort{6}" in rendered
    reparsed = parse_latex_text(rendered, source="b.tex", project_name="t")
    assert reparsed.nodes[0].effort == 6


@pytest.mark.parametrize("value", ["", "0", "abc", "-1"])
def test_latex_invalid_effort_raises(value):
    with pytest.raises(ParseError):
        parse_latex_text(_tex(f"\\effort{{{value}}}"), source="b.tex", project_name="t")


# ---------------------------------------------------------------------------
# to_dict shape
# ---------------------------------------------------------------------------


def test_to_dict_includes_effort_key():
    node = BlueprintNode(id="a", kind=NodeKind.LEMMA, title="A")
    assert node.to_dict()["effort"] is None
    node_with = BlueprintNode(id="b", kind=NodeKind.LEMMA, title="B", effort=2)
    assert node_with.to_dict()["effort"] == 2


# ---------------------------------------------------------------------------
# Effort-weighted report
# ---------------------------------------------------------------------------


def _node(node_id: str, *, effort=None, formal=FormalStatus.MISSING) -> BlueprintNode:
    ref = IsabelleRef(fact=f"Demo.{node_id}") if formal != FormalStatus.MISSING else IsabelleRef()
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=ref,
        status=NodeStatus(formal=formal),
        effort=effort,
    )


def test_effort_report_weights_by_effort():
    # proved effort 5, found-but-not-proved effort 3 -> coverage 5/8 = 62%.
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", effort=5, formal=FormalStatus.PROVED),
            _node("b", effort=3, formal=FormalStatus.FOUND),
        ],
    )
    report = build_effort_report(project)
    assert report.proved_effort == 5
    assert report.found_effort == 3
    assert report.formal_target_effort == 8
    assert report.remaining_effort == 3
    assert report.coverage_percent == 62


def test_effort_report_defaults_missing_effort_to_one():
    # One proved node with explicit effort 4, one proved node without effort (weight 1).
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", effort=4, formal=FormalStatus.PROVED),
            _node("b", formal=FormalStatus.PROVED),
        ],
    )
    report = build_effort_report(project)
    assert report.explicit_effort_count == 1
    assert report.total_effort == 5
    assert report.formal_target_effort == 5
    assert report.coverage_percent == 100


def test_effort_report_coverage_none_without_targets():
    project = BlueprintProject.from_nodes("p", [_node("a", effort=2)])
    report = build_effort_report(project)
    assert report.coverage_percent is None
    assert "n/a" in render_effort_report(report)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "effort-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # effort-test

            ::: lemma {#a}
            title: A
            isabelle: Demo.a
            effort: 4
            status: proved

            A statement.
            :::
            """
        ),
        encoding="utf-8",
    )


def test_cli_effort_text(tmp_path, capsys):
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Effort-weighted progress" in out
    assert "Total effort: 4" in out


def test_cli_effort_json(tmp_path, capsys):
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["proved_effort"] == 4
    assert payload["coverage_percent"] == 100
    assert payload["default_effort"] == 1
    assert "by_tag" not in payload


# ---------------------------------------------------------------------------
# --by-tag grouping
# ---------------------------------------------------------------------------


def _tagged(node_id, *, effort, formal, tags):
    node = _node(node_id, effort=effort, formal=formal)
    node.tags = list(tags)
    return node


def test_by_tag_groups_and_multi_tag_counts_under_each():
    project = BlueprintProject.from_nodes(
        "p",
        [
            _tagged("a", effort=4, formal=FormalStatus.PROVED, tags=["algebra", "core"]),
            _tagged("b", effort=2, formal=FormalStatus.FOUND, tags=["algebra"]),
            _tagged("c", effort=3, formal=FormalStatus.MISSING, tags=[]),
        ],
    )
    report = build_effort_report(project)
    by_tag = {t.tag: t for t in report.by_tag}
    assert set(by_tag) == {"algebra", "core", "(untagged)"}
    # a (4) + b (2) under algebra; only a is proved.
    assert by_tag["algebra"].total_effort == 6
    assert by_tag["algebra"].proved_effort == 4
    assert by_tag["algebra"].remaining_effort == 2
    assert by_tag["algebra"].percent == 66
    # a also counts under core.
    assert by_tag["core"].total_effort == 4
    assert by_tag["core"].proved_effort == 4
    assert by_tag["core"].percent == 100
    # untagged bucket holds c.
    assert by_tag["(untagged)"].total_effort == 3
    assert by_tag["(untagged)"].percent == 0
    # untagged bucket sorts last.
    assert report.by_tag[-1].tag == "(untagged)"


def test_to_dict_includes_by_tag_only_when_requested():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=1, formal=FormalStatus.PROVED, tags=["x"])]
    )
    report = build_effort_report(project)
    assert "by_tag" not in report.to_dict()
    payload = report.to_dict(include_by_tag=True)
    assert payload["by_tag"][0]["tag"] == "x"
    assert payload["by_tag"][0]["proved_effort"] == 1


def test_render_by_tag_table_present_only_when_requested():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=2, formal=FormalStatus.PROVED, tags=["algebra"])]
    )
    report = build_effort_report(project)
    assert "Effort by tag" not in render_effort_report(report)
    rendered = render_effort_report(report, by_tag=True)
    assert "## Effort by tag" in rendered
    assert "| algebra |" in rendered


def _write_tagged_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "effort-tag-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # effort-tag-test

            ::: lemma {#a}
            title: A
            isabelle: Demo.a
            effort: 4
            status: proved
            tags: algebra, core

            A statement.
            :::

            ::: lemma {#b}
            title: B
            effort: 2

            B statement.
            :::
            """
        ),
        encoding="utf-8",
    )


def test_cli_effort_by_tag_text(tmp_path, capsys):
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--by-tag"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Effort-weighted progress" in out
    assert "## Effort by tag" in out
    assert "| algebra |" in out
    assert "(untagged)" in out


def test_cli_effort_by_tag_json(tmp_path, capsys):
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--by-tag", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "by_tag" in payload
    tags = {t["tag"]: t for t in payload["by_tag"]}
    assert tags["algebra"]["total_effort"] == 4
    assert tags["algebra"]["proved_effort"] == 4
    assert tags["(untagged)"]["total_effort"] == 2
    assert tags["(untagged)"]["proved_effort"] == 0


def test_cli_effort_json_without_by_tag_omits_key(tmp_path, capsys):
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "by_tag" not in payload
