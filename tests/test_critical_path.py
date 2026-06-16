from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.critical_path import (
    build_critical_path,
    render_critical_path_mermaid,
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


def _project(*nodes: BlueprintNode, name: str = "cp") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def test_linear_chain_depth_and_path() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
        _node("c", uses=["b"]),
    )

    overview = build_critical_path(project)

    assert overview.remaining_count == 3
    assert overview.goal_count == 1
    assert overview.longest is not None
    assert overview.longest.goal_id == "c"
    assert overview.longest.depth == 3
    assert overview.longest.path == ["a", "b", "c"]


def test_branching_picks_the_longest_chain() -> None:
    project = _project(
        _node("base"),
        _node("mid", uses=["base"]),
        _node("deep", uses=["mid"]),
        _node("shallow", uses=["base"]),
        _node("goal", uses=["deep", "shallow"]),
    )

    overview = build_critical_path(project)

    assert overview.longest is not None
    assert overview.longest.path == ["base", "mid", "deep", "goal"]
    assert overview.longest.depth == 4


def test_complete_dependency_resets_the_chain() -> None:
    project = _project(
        _node("a", formal=FormalStatus.PROVED),
        _node("b", uses=["a"]),
        _node("c", uses=["b"]),
    )

    overview = build_critical_path(project)

    assert overview.remaining_count == 2
    assert overview.longest is not None
    # ``a`` is proved, so the remaining chain starts at ``b``.
    assert overview.longest.path == ["b", "c"]
    assert overview.longest.depth == 2


def test_multiple_goals_are_reported_and_sorted() -> None:
    project = _project(
        _node("base"),
        _node("goal-deep", uses=["base"]),
        _node("goal-flat"),
    )

    overview = build_critical_path(project)

    assert overview.goal_count == 2
    ids = [goal.goal_id for goal in overview.goals]
    # Deepest goal first, then lexicographic.
    assert ids == ["goal-deep", "goal-flat"]
    assert overview.longest is not None
    assert overview.longest.goal_id == "goal-deep"


def test_bottlenecks_ranked_by_leverage() -> None:
    project = _project(
        _node("base"),
        _node("b", uses=["base"]),
        _node("c", uses=["base"]),
        _node("d", uses=["b"]),
    )

    overview = build_critical_path(project)

    leverage = {b.node_id: b.leverage for b in overview.bottlenecks}
    # base unblocks b, c, d; b unblocks d.
    assert leverage["base"] == 3
    assert leverage["b"] == 1
    assert overview.bottlenecks[0].node_id == "base"
    # Leaves with no dependents are not bottlenecks.
    assert "d" not in leverage


def test_proved_node_is_not_a_bottleneck() -> None:
    project = _project(
        _node("base", formal=FormalStatus.PROVED),
        _node("b", uses=["base"]),
    )

    overview = build_critical_path(project)

    assert overview.remaining_count == 1
    assert overview.bottlenecks == []
    assert overview.longest is not None
    assert overview.longest.path == ["b"]


def test_cycle_nodes_excluded_and_surfaced() -> None:
    project = _project(
        _node("x", uses=["y"]),
        _node("y", uses=["x"]),
        _node("z"),
    )

    overview = build_critical_path(project)

    assert overview.cycles
    cycle_members = {node_id for cycle in overview.cycles for node_id in cycle}
    assert cycle_members == {"x", "y"}
    # The acyclic remainder is still analysed.
    goal_ids = {goal.goal_id for goal in overview.goals}
    assert goal_ids == {"z"}


def test_missing_dependency_is_reported() -> None:
    project = _project(_node("a", uses=["ghost"]))

    overview = build_critical_path(project)

    assert len(overview.missing_dependencies) == 1
    assert overview.missing_dependencies[0].node_id == "a"
    assert overview.missing_dependencies[0].missing == ["ghost"]


def test_complete_depending_on_incomplete_is_inconsistent() -> None:
    project = _project(
        _node("a"),
        _node("b", uses=["a"], formal=FormalStatus.PROVED),
    )

    overview = build_critical_path(project)

    assert len(overview.inconsistent) == 1
    assert overview.inconsistent[0].node_id == "b"
    assert overview.inconsistent[0].incomplete_dependencies == ["a"]


def test_empty_and_complete_projects() -> None:
    empty = build_critical_path(_project())
    assert empty.remaining_count == 0
    assert empty.longest is None
    assert empty.goals == []

    done = build_critical_path(_project(_node("a", formal=FormalStatus.PROVED)))
    assert done.remaining_count == 0
    assert done.longest is None


def _write_project(tmp_path: Path, body: str, *, name: str = "cp-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# cp-test

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


def test_cli_text_output(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "critical path" in out.lower()
    assert "`a` -> `b`" in out


def test_cli_json_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "cp-test"
    assert data["schema_version"] == 1
    assert data["remaining_count"] == 2
    assert data["longest"]["path"] == ["a", "b"]
    assert {key for key in data} >= {
        "goals",
        "bottlenecks",
        "cycles",
        "missing_dependencies",
        "inconsistent",
    }


def test_cli_top_limits_bottlenecks(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--json", "--top", "1"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["bottlenecks"]) <= 1


def test_cli_goal_focus(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--goal", "b"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Goal `b`" in out
    assert "`a` -> `b`" in out
    assert out.endswith("\n")


def test_cli_write_artifacts(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--write"])

    assert rc == 0
    out = capsys.readouterr().out
    json_path = tmp_path / "build" / "critical-path.json"
    md_path = tmp_path / "build" / "critical-path.md"
    assert json_path.exists()
    assert md_path.exists()
    # The text report is still printed, and the write locations are announced.
    assert "critical path" in out.lower()
    assert "critical-path json ->" in out
    assert "critical-path md ->" in out

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["project"] == "cp-test"
    assert data["schema_version"] == 1
    assert data["longest"]["path"] == ["a", "b"]

    md = md_path.read_text(encoding="utf-8")
    assert "critical path" in md.lower()
    assert "`a` -> `b`" in md


def test_cli_write_json_payload_matches_stdout(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--json", "--write"])

    assert rc == 0
    captured = capsys.readouterr()
    # With --json the JSON goes to stdout; the write notices go to stderr.
    stdout_payload = json.loads(captured.out)
    assert "critical-path json ->" in captured.err

    file_payload = json.loads(
        (tmp_path / "build" / "critical-path.json").read_text(encoding="utf-8")
    )
    assert file_payload == stdout_payload


def test_cli_write_goal_focus_is_plain_markdown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(
        ["critical-path", str(tmp_path), "--goal", "b", "--write", "--color", "always"]
    )

    assert rc == 0
    out = capsys.readouterr().out
    # The printed report is goal-focused...
    assert "Goal `b`" in out
    assert "`a` -> `b`" in out

    md = (tmp_path / "build" / "critical-path.md").read_text(encoding="utf-8")
    # ...and the written artifact matches that goal-focused output, not the
    # project-wide one (no "## Bottlenecks" section is emitted for a single goal).
    assert "Goal `b`" in md
    assert "`a` -> `b`" in md
    assert "## Bottlenecks" not in md
    # The persisted Markdown is plain: it never contains ANSI escape codes even
    # though colour was forced on for the terminal.
    assert "\033[" not in md


def test_cli_markdown_stdout_is_plain(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(
        ["critical-path", str(tmp_path), "--goal", "b", "--markdown", "--color", "always"]
    )

    assert rc == 0
    out = capsys.readouterr().out
    # The goal chain is rendered to stdout as Markdown...
    assert "Goal `b`" in out
    assert "`a` -> `b`" in out
    # ...and it is plain: no ANSI escape sequences even with colour forced on.
    assert "\033[" not in out


def test_cli_markdown_rejects_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    with pytest.raises(SystemExit):
        cli_main(["critical-path", str(tmp_path), "--markdown", "--json"])


def test_cli_fail_on_cycle(tmp_path: Path, capsys) -> None:
    body = """# cyc

::: lemma {#x}
title: X
isabelle: Demo.x
status: stub
uses: y

X.

Sketch.
:::

::: lemma {#y}
title: Y
isabelle: Demo.y
status: stub
uses: x

Y.

Sketch.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["critical-path", str(tmp_path), "--fail-on-cycle"])

    assert rc == 2
    captured = capsys.readouterr()
    assert "Cycles" in captured.out
    # Strict failure messages go to stderr so the rendered report stays parseable on stdout.
    assert "critical-path:" in captured.err
    assert "critical-path:" not in captured.out


def test_cli_mermaid_output(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--mermaid"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("flowchart")
    # The goal-chain node ids appear as Mermaid nodes and an edge along the chain.
    assert 'n_a["a"]' in out
    assert 'n_b["b"]' in out
    assert "n_a --> n_b" in out
    # The leverage node (a unblocks b) is highlighted as a bottleneck.
    assert "style n_a" in out


def test_cli_mermaid_honours_goal(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--mermaid", "--goal", "b"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("flowchart")
    assert "n_a --> n_b" in out


def test_cli_mermaid_rejects_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    with pytest.raises(SystemExit):
        cli_main(["critical-path", str(tmp_path), "--mermaid", "--json"])


def test_cli_mermaid_rejects_markdown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    with pytest.raises(SystemExit):
        cli_main(["critical-path", str(tmp_path), "--mermaid", "--markdown"])


def test_cli_csv_output(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--csv"])

    assert rc == 0
    out = capsys.readouterr().out
    # No carriage returns: csv writer uses lineterminator='\n'.
    assert "\r" not in out
    lines = out.splitlines()
    assert lines[0] == "node_id,kind,leverage,on_critical_path"
    # ``a`` is the bottleneck (it unblocks ``b``) and lies on the critical chain.
    assert "a,definition,1,true" in lines
    # ``b`` is a leaf goal with no dependents, so it is not a bottleneck row.
    assert not any(row.startswith("b,") for row in lines[1:])


def test_cli_csv_honours_top(tmp_path: Path, capsys) -> None:
    body = _BODY + """
::: lemma {#c}
title: C
isabelle: Demo.c
status: stub
uses: a

Depends on a.

Sketch.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["critical-path", str(tmp_path), "--csv", "--top", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    # Header + exactly one bottleneck row when top trims the ranking.
    lines = out.splitlines()
    assert lines[0] == "node_id,kind,leverage,on_critical_path"
    assert len(lines) == 2
    assert lines[1].startswith("a,")


def test_cli_csv_rejects_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    with pytest.raises(SystemExit):
        cli_main(["critical-path", str(tmp_path), "--csv", "--json"])


def test_cli_csv_honours_goal(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["critical-path", str(tmp_path), "--csv", "--goal", "b"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "\r" not in out
    # ``a`` is on goal ``b``'s critical chain (a -> b).
    assert "a,definition,1,true" in out.splitlines()


def test_mermaid_invalid_goal_carries_distinct_message() -> None:
    # An unknown/invalid goal must render a message distinct from the
    # all-complete and cycle-tangled cases, mirroring the text renderer.
    project = _project(
        _node("a"),
        _node("b", uses=["a"]),
    )
    overview = build_critical_path(project)

    mermaid = render_critical_path_mermaid(overview, goal="does-not-exist")

    assert mermaid.startswith("flowchart")
    assert "is not a remaining goal" in mermaid
    assert "no remaining critical path" not in mermaid


def test_mermaid_all_complete_message() -> None:
    project = _project(_node("a", formal=FormalStatus.PROVED))
    overview = build_critical_path(project)

    mermaid = render_critical_path_mermaid(overview)

    assert "All formal targets are complete" in mermaid
    assert "is not a remaining goal" not in mermaid


def test_mermaid_cycle_tangled_message() -> None:
    project = _project(
        _node("a", uses=["b"]),
        _node("b", uses=["a"]),
    )
    overview = build_critical_path(project)

    mermaid = render_critical_path_mermaid(overview)

    assert "tangled in cycles" in mermaid
    assert "is not a remaining goal" not in mermaid

