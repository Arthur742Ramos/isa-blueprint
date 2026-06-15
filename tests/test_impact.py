from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.impact import (
    UnknownNodeError,
    build_impact_overview,
    build_impact_report,
    render_impact_dot,
    render_impact_mermaid,
)


def _node(
    node_id: str,
    *,
    uses: list[str] | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
    kind: NodeKind = NodeKind.LEMMA,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
    )


def _project(*nodes: BlueprintNode, name: str = "imp") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def test_linear_chain_blast_radius_and_distance() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
        _node("c", uses=["b"]),
    )

    report = build_impact_report(project, "a")

    assert report.blast_radius_count == 2
    assert report.direct_dependents == ["b"]
    assert [(item.node_id, item.distance) for item in report.blast_radius] == [
        ("b", 1),
        ("c", 2),
    ]
    assert report.affected_goals == ["c"]


def test_leaf_node_has_empty_blast_radius() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
    )

    report = build_impact_report(project, "b")

    assert report.blast_radius_count == 0
    assert report.direct_dependents == []
    assert report.affected_goals == []
    assert report.complete_affected == []


def test_blast_radius_counts_all_statuses_unlike_leverage() -> None:
    # A proved foundational lemma still has a large blast radius even though
    # critical-path leverage (incomplete-only) would be 0.
    project = _project(
        _node("base", formal=FormalStatus.PROVED),
        _node("mid", uses=["base"], formal=FormalStatus.PROVED),
        _node("top", uses=["mid"], formal=FormalStatus.PROVED),
    )

    report = build_impact_report(project, "base")

    assert report.blast_radius_count == 2
    assert report.complete_affected == ["mid", "top"]
    assert report.affected_goals == ["top"]


def test_shortest_distance_with_branching() -> None:
    # goal depends on base both directly and via mid; distance is the shortest hop.
    project = _project(
        _node("base"),
        _node("mid", uses=["base"]),
        _node("goal", uses=["base", "mid"]),
    )

    report = build_impact_report(project, "base")

    distances = {item.node_id: item.distance for item in report.blast_radius}
    assert distances == {"mid": 1, "goal": 1}
    assert report.affected_goals == ["goal"]


def test_diamond_blast_radius() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
        _node("c", uses=["a"]),
        _node("d", uses=["b", "c"]),
    )

    report = build_impact_report(project, "a")

    distances = {item.node_id: item.distance for item in report.blast_radius}
    assert distances == {"b": 1, "c": 1, "d": 2}
    assert report.direct_dependents == ["b", "c"]
    assert report.affected_goals == ["d"]


def test_cycle_is_handled_finitely() -> None:
    project = _project(
        _node("x", uses=["y"]),
        _node("y", uses=["x"]),
        _node("z", uses=["x"]),
    )

    report = build_impact_report(project, "y")

    assert report.in_cycle is True
    # Traversal terminates; x and z (via x) are reachable dependents of y.
    ids = {item.node_id for item in report.blast_radius}
    assert ids == {"x", "z"}


def test_unknown_node_raises() -> None:
    project = _project(_node("a"))

    with pytest.raises(UnknownNodeError):
        build_impact_report(project, "nope")


def test_overview_ranks_by_blast_radius() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
        _node("c", uses=["b"]),
    )

    overview = build_impact_overview(project)

    assert overview.node_count == 3
    ranked = [(r.node_id, r.blast_radius_count) for r in overview.rankings]
    assert ranked == [("a", 2), ("b", 1), ("c", 0)]


def test_overview_empty_project() -> None:
    overview = build_impact_overview(_project())

    assert overview.node_count == 0
    assert overview.rankings == []


def _write_project(tmp_path: Path, body: str, *, name: str = "imp-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# imp-test

::: definition {#a}
title: A
isabelle: Demo.a
status: stub

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

Depends on a.

Sketch.
:::
"""


def test_cli_single_node_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "impact" in out.lower()
    assert "Blast radius" in out
    assert "`b`" in out


def test_cli_single_node_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["node_id"] == "a"
    assert data["blast_radius_count"] == 1
    assert data["direct_dependents"] == ["b"]
    assert data["affected_goals"] == ["b"]


def test_cli_overview_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "imp-test"
    assert data["schema_version"] == 1
    assert data["node_count"] == 2
    assert data["rankings"][0]["node_id"] == "a"


def test_cli_top_limits_rankings(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--json", "--top", "1"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["rankings"]) == 1


def test_cli_unknown_node_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "missing"])

    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown node" in err


def test_cli_dot_format_emits_subgraph(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--format", "dot"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "digraph" in out
    # The focus node and its downstream dependent appear, with the dependency edge.
    assert '"a"' in out
    assert '"b"' in out
    assert '"b" -> "a"' in out


def test_cli_dot_format_requires_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--format", "dot"])

    assert rc != 0
    err = capsys.readouterr().err
    assert "--format dot requires --node" in err


def test_cli_mermaid_format_emits_flowchart(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--format", "mermaid"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "flowchart" in out
    # The focus node id and its downstream dependent both appear as Mermaid nodes,
    # with the dependency edge and the focus-node highlight style.
    assert "n_a" in out
    assert "n_b" in out
    assert "n_b --> n_a" in out
    assert "style n_a fill:#fde047" in out


def test_cli_mermaid_format_requires_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--format", "mermaid"])

    assert rc != 0
    err = capsys.readouterr().err
    assert "--format mermaid requires --node" in err


def test_mermaid_label_escapes_newline_and_quote() -> None:
    # A node whose label text contains a double-quote, backslash and newline must
    # be escaped per the project Mermaid convention so the flowchart stays valid.
    evil = 'a"x\\y\nz'
    project = _project(
        _node(evil),
        _node("b", uses=[evil]),
    )

    mermaid = render_impact_mermaid(project, evil)

    assert "flowchart" in mermaid
    assert "&quot;" in mermaid
    # The focus node's label line must carry the escaped <br/> form and contain no
    # raw newline inside the label token itself.
    label_line = next(
        line for line in mermaid.splitlines() if line.lstrip().startswith("n_a")
    )
    assert "<br/>" in label_line
    assert "\n" not in label_line


def test_cli_format_json_matches_json_flag(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--format", "json"])
    assert rc == 0
    format_out = capsys.readouterr().out

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--json"])
    assert rc == 0
    json_out = capsys.readouterr().out

    # `--format json` must be exactly equivalent to the legacy `--json` alias.
    assert format_out == json_out
    assert json.loads(format_out)["node_id"] == "a"


def test_cli_json_conflicts_with_format_dot(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["impact", str(tmp_path), "--node", "a", "--json", "--format", "dot"])

    assert rc != 0
    err = capsys.readouterr().err
    assert "--json conflicts with --format dot" in err


def test_dot_escapes_node_id_with_quote_and_backslash() -> None:
    # A node id containing a double-quote, backslash and newline must be escaped
    # in both the node declarations and the edge statements so the emitted DOT
    # stays valid and cannot be used for DOT injection.
    evil = 'a"x\\y\nz'
    project = _project(
        _node(evil),
        _node("b", uses=[evil]),
    )

    dot = render_impact_dot(project, evil)

    escaped = 'a\\"x\\\\y\\nz'
    # The raw, unescaped id must never appear inside a quoted token.
    assert '"a"x' not in dot
    assert "\\y\nz" not in dot
    # The escaped id appears in the node declaration and on the edge.
    assert f'"{escaped}" [label=' in dot
    assert f'"b" -> "{escaped}";' in dot
    # Every quoted token must contain balanced, escaped quotes only; verify the
    # declaration line and edge line are present and well-formed.
    assert f'digraph "impact_{escaped}"' in dot


