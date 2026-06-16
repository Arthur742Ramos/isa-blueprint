"""Tests for the optional per-node ``effort`` weight and effort-weighted report."""
from __future__ import annotations

import csv
import io
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
from isabelle_blueprint.report.effort import (
    build_effort_gate,
    build_effort_report,
    render_effort_markdown,
    render_effort_report,
)


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
    report = build_effort_report(project, include_by_tag=True)
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


def test_by_tag_untagged_bucket_present_when_all_nodes_tagged():
    # Every node carries a tag, yet the untagged bucket must still appear (zeros)
    # so consumers can rely on a stable output shape and "untagged sorts last".
    project = BlueprintProject.from_nodes(
        "p",
        [
            _tagged("a", effort=2, formal=FormalStatus.PROVED, tags=["algebra"]),
            _tagged("b", effort=1, formal=FormalStatus.FOUND, tags=["core"]),
        ],
    )
    report = build_effort_report(project, include_by_tag=True)
    by_tag = {t.tag: t for t in report.by_tag}
    assert "(untagged)" in by_tag
    untagged = by_tag["(untagged)"]
    assert untagged.node_count == 0
    assert untagged.total_effort == 0
    assert untagged.proved_effort == 0
    assert untagged.remaining_effort == 0
    assert untagged.percent is None
    assert report.by_tag[-1].tag == "(untagged)"


def test_build_effort_report_by_tag_empty_by_default():
    # build_effort_report omits the per-tag breakdown unless explicitly requested.
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=1, formal=FormalStatus.PROVED, tags=["x"])]
    )
    assert build_effort_report(project).by_tag == ()
    assert build_effort_report(project, include_by_tag=True).by_tag != ()


def test_to_dict_includes_by_tag_only_when_requested():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=1, formal=FormalStatus.PROVED, tags=["x"])]
    )
    report = build_effort_report(project, include_by_tag=True)
    assert "by_tag" not in report.to_dict()
    payload = report.to_dict(include_by_tag=True)
    assert payload["by_tag"][0]["tag"] == "x"
    assert payload["by_tag"][0]["proved_effort"] == 1


def test_render_by_tag_table_present_only_when_requested():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=2, formal=FormalStatus.PROVED, tags=["algebra"])]
    )
    report = build_effort_report(project, include_by_tag=True)
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


# ---------------------------------------------------------------------------
# --fail-under CI gate
# ---------------------------------------------------------------------------


def _write_partial_project(tmp_path: Path) -> None:
    # proved effort 4, found-but-not-proved effort 2 -> coverage 4/6 = 66%.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "effort-partial"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # effort-partial

            ::: lemma {#a}
            title: A
            isabelle: Demo.a
            effort: 4
            status: proved

            A statement.
            :::

            ::: lemma {#b}
            title: B
            isabelle: Demo.b
            effort: 2
            status: found

            B statement.
            :::
            """
        ),
        encoding="utf-8",
    )


def test_cli_effort_fail_under_below_threshold_exits_5(tmp_path, capsys):
    # 66% effort-weighted coverage falls short of 90%.
    _write_partial_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--fail-under", "90"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "is below 90" in captured.err


def test_cli_effort_fail_under_met_exits_0(tmp_path, capsys):
    # The single-node project is fully proved -> 100% coverage.
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--fail-under", "75"])
    assert rc == 0
    assert capsys.readouterr().err == ""


def test_cli_effort_fail_under_json_gate_present(tmp_path, capsys):
    _write_partial_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--fail-under", "90", "--json"])
    assert rc == 5
    payload = json.loads(capsys.readouterr().out)
    gate = payload["gate"]
    assert gate["fail_under"] == 90
    assert gate["effort_percent"] == 66
    assert gate["meets"] is False


def test_cli_effort_fail_under_json_gate_met(tmp_path, capsys):
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--fail-under", "100", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate"]["meets"] is True
    assert payload["gate"]["effort_percent"] == 100


def test_cli_effort_without_fail_under_unchanged(tmp_path, capsys):
    # Absent the flag, no gate object appears and the exit code stays 0.
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "gate" not in payload


def test_cli_effort_fail_under_undefined_coverage_fails(tmp_path, capsys):
    # A project with no formal targets has undefined coverage, which never meets.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "effort-empty"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # effort-empty

            ::: lemma {#a}
            title: A
            effort: 2

            A statement.
            :::
            """
        ),
        encoding="utf-8",
    )
    rc = cli_main(["effort", str(tmp_path), "--fail-under", "1", "--json"])
    assert rc == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate"]["effort_percent"] is None
    assert payload["gate"]["meets"] is False


def test_cli_effort_fail_under_rejects_out_of_range(tmp_path):
    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["effort", str(tmp_path), "--fail-under", "150"])


def test_build_effort_gate_helper():
    project = BlueprintProject.from_nodes(
        "p",
        [
            _node("a", effort=5, formal=FormalStatus.PROVED),
            _node("b", effort=3, formal=FormalStatus.FOUND),
        ],
    )
    report = build_effort_report(project)  # 5/8 = 62%
    assert build_effort_gate(report, 60.0) == {
        "fail_under": 60.0,
        "effort_percent": 62,
        "meets": True,
    }
    assert build_effort_gate(report, 62)["meets"] is True
    assert build_effort_gate(report, 63)["meets"] is False


# ---------------------------------------------------------------------------
# --markdown output
# ---------------------------------------------------------------------------


def test_render_effort_markdown_summary_table():
    project = BlueprintProject.from_nodes(
        "p", [_node("a", effort=4, formal=FormalStatus.PROVED)]
    )
    report = build_effort_report(project)
    rendered = render_effort_markdown(report)
    assert "# Effort-weighted progress" in rendered
    assert "| Metric | Value |" in rendered
    assert "| Total effort | 4 |" in rendered
    assert "| Coverage percent | 100% |" in rendered
    # The per-tag table is absent unless requested.
    assert "## Effort by tag" not in rendered


def test_render_effort_markdown_by_tag_table():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=2, formal=FormalStatus.PROVED, tags=["algebra"])]
    )
    report = build_effort_report(project, include_by_tag=True)
    rendered = render_effort_markdown(report, by_tag=True)
    assert "## Effort by tag" in rendered
    assert "| algebra |" in rendered


def test_render_effort_markdown_escapes_tag_pipe():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=1, formal=FormalStatus.PROVED, tags=["a|b"])]
    )
    report = build_effort_report(project, include_by_tag=True)
    rendered = render_effort_markdown(report, by_tag=True)
    assert r"a\|b" in rendered


def test_render_effort_markdown_normalises_tag_newline():
    project = BlueprintProject.from_nodes(
        "p", [_tagged("a", effort=1, formal=FormalStatus.PROVED, tags=["a\nb"])]
    )
    report = build_effort_report(project, include_by_tag=True)
    rendered = render_effort_markdown(report, by_tag=True)
    tag_rows = [line for line in rendered.splitlines() if line.startswith("| a")]
    assert tag_rows == ["| a b | 1 | 1 | 1 | 0 | 100% |"]


def test_render_effort_markdown_coverage_na():
    project = BlueprintProject.from_nodes("p", [_node("a", effort=2)])
    report = build_effort_report(project)
    rendered = render_effort_markdown(report)
    assert "| Coverage percent | n/a |" in rendered


def test_cli_effort_markdown(tmp_path, capsys):
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--markdown"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Effort-weighted progress" in out
    assert "| Coverage percent | 100% |" in out
    assert "| Metric | Value |" in out


def test_cli_effort_markdown_by_tag(tmp_path, capsys):
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--markdown", "--by-tag"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Effort-weighted progress" in out
    assert "## Effort by tag" in out
    assert "| algebra |" in out


def test_cli_effort_markdown_and_json_mutually_exclusive(tmp_path):
    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["effort", str(tmp_path), "--markdown", "--json"])


def test_cli_effort_markdown_with_fail_under_gate_exits_5(tmp_path, capsys):
    # 66% effort-weighted coverage falls short of 90%; markdown still prints.
    _write_partial_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--markdown", "--fail-under", "90"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "# Effort-weighted progress" in captured.out
    assert "| Coverage percent | 66% |" in captured.out
    assert "is below 90" in captured.err


# ---------------------------------------------------------------------------
# --csv output
# ---------------------------------------------------------------------------


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_cli_effort_csv_summary(tmp_path, capsys):
    _write_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--csv"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\r" not in out
    rows = _parse_csv(out)
    assert rows[0] == [
        "total_effort",
        "formal_target_effort",
        "proved_effort",
        "found_effort",
        "remaining_effort",
        "coverage_percent",
    ]
    # Single proved node with effort 4 -> fully covered.
    assert rows[1] == ["4", "4", "4", "0", "0", "100"]
    assert len(rows) == 2


def test_cli_effort_csv_by_tag(tmp_path, capsys):
    _write_tagged_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--csv", "--by-tag"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\r" not in out
    rows = _parse_csv(out)
    assert rows[0] == [
        "tag",
        "total_effort",
        "proved_effort",
        "remaining_effort",
        "coverage_percent",
    ]
    by_tag = {r[0]: r for r in rows[1:]}
    assert by_tag["algebra"] == ["algebra", "4", "4", "0", "100"]
    assert by_tag["core"] == ["core", "4", "4", "0", "100"]
    # Untagged bucket holds node b (effort 2, not proved); 0% coverage.
    assert by_tag["(untagged)"] == ["(untagged)", "2", "0", "2", "0"]
    # Untagged bucket sorts last.
    assert rows[-1][0] == "(untagged)"


def test_cli_effort_csv_with_fail_under_gate_exits_5(tmp_path, capsys):
    # CSV still prints, and the unmet gate sets exit 5.
    _write_partial_project(tmp_path)
    rc = cli_main(["effort", str(tmp_path), "--csv", "--fail-under", "90"])
    assert rc == 5
    captured = capsys.readouterr()
    assert "\r" not in captured.out
    rows = _parse_csv(captured.out)
    assert rows[0][0] == "total_effort"
    # proved 4 / target 6 -> 66%.
    assert rows[1] == ["6", "6", "4", "2", "2", "66"]
    assert "is below 90" in captured.err


def test_cli_effort_csv_and_json_mutually_exclusive(tmp_path):
    _write_project(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["effort", str(tmp_path), "--csv", "--json"])


