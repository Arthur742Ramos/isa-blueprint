from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.path import (
    DIRECTION_DEPENDED_ON_BY,
    DIRECTION_DEPENDS_ON,
    DIRECTION_SELF,
    PATH_SCHEMA_VERSION,
    UnknownNodeError,
    build_path_report,
    render_path_report,
)


def _node(node_id: str, *, uses: list[str] | None = None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(),
    )


def _project(*nodes: BlueprintNode, name: str = "pt") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _chain() -> BlueprintProject:
    # c -> b -> a  (c uses b, b uses a)
    return _project(_node("a"), _node("b", uses=["a"]), _node("c", uses=["b"]))


def test_forward_depends_on_path() -> None:
    report = build_path_report(_chain(), "c", "a")

    assert report.found is True
    assert report.direction == DIRECTION_DEPENDS_ON
    assert report.path == ["c", "b", "a"]
    assert report.length == 2
    assert report.source_title == "C"
    assert report.target_title == "A"


def test_backward_depended_on_by_path() -> None:
    # There is no a -> ... -> c chain, so the search flips direction.
    report = build_path_report(_chain(), "a", "c")

    assert report.found is True
    assert report.direction == DIRECTION_DEPENDED_ON_BY
    assert report.path == ["c", "b", "a"]
    assert report.length == 2


def test_self_path() -> None:
    report = build_path_report(_chain(), "a", "a")

    assert report.found is True
    assert report.direction == DIRECTION_SELF
    assert report.path == ["a"]
    assert report.length == 0


def test_disconnected_nodes_report_not_found() -> None:
    report = build_path_report(_project(_node("x"), _node("y")), "x", "y")

    assert report.found is False
    assert report.direction is None
    assert report.path == []
    assert report.length == 0


def test_unknown_endpoints_raise() -> None:
    project = _chain()

    with pytest.raises(UnknownNodeError) as excinfo:
        build_path_report(project, "ghost", "a")
    assert excinfo.value.args[0] == "ghost"

    with pytest.raises(UnknownNodeError) as excinfo:
        build_path_report(project, "a", "ghost")
    assert excinfo.value.args[0] == "ghost"


def test_shortest_path_tie_break_is_deterministic() -> None:
    # goal depends on base via two equal-length routes; sorted neighbour order
    # makes the lexicographically smaller mid win.
    project = _project(
        _node("base"),
        _node("m1", uses=["base"]),
        _node("m2", uses=["base"]),
        _node("goal", uses=["m1", "m2"]),
    )

    report = build_path_report(project, "goal", "base")

    assert report.path == ["goal", "m1", "base"]
    assert report.length == 2


def test_render_text_variants() -> None:
    chain = _chain()
    assert "`c` depends on `a`" in render_path_report(build_path_report(chain, "c", "a"))
    # Backward direction renders target-depends-on-source phrasing.
    assert "`c` depends on `a`" in render_path_report(build_path_report(chain, "a", "c"))
    assert "not connected" in render_path_report(
        build_path_report(_project(_node("x"), _node("y")), "x", "y")
    )


def _write_project(tmp_path: Path, body: str, *, name: str = "path-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# path-test

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

Uses a.

Sketch.
:::

::: theorem {#c}
title: C
isabelle: Demo.c
status: stub
uses: b

Uses b.

Sketch.
:::
"""


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["path", "c", "a", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "dependency path" in out
    assert "`c` -> `b` -> `a`" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["path", "c", "a", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == PATH_SCHEMA_VERSION
    assert data["project"] == "path-test"
    assert data["found"] is True
    assert data["direction"] == DIRECTION_DEPENDS_ON
    assert data["path"] == ["c", "b", "a"]
    assert data["length"] == 2


def test_cli_unknown_node_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["path", "c", "missing", str(tmp_path)])

    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown node" in err
    assert "missing" in err


def _diamond() -> BlueprintProject:
    # goal depends on base via two equal-length routes (goal->m1->base and
    # goal->m2->base), so two shortest paths exist.
    return _project(
        _node("base"),
        _node("m1", uses=["base"]),
        _node("m2", uses=["base"]),
        _node("goal", uses=["m1", "m2"]),
    )


def test_all_enumerates_every_shortest_path() -> None:
    report = build_path_report(_diamond(), "goal", "base", all_paths=True)

    assert report.found is True
    assert report.direction == DIRECTION_DEPENDS_ON
    assert report.paths == [["goal", "m1", "base"], ["goal", "m2", "base"]]
    # Back-compat: single path stays the first (lexicographically smallest).
    assert report.path == ["goal", "m1", "base"]
    assert report.length == 2


def test_all_default_off_returns_single_path() -> None:
    report = build_path_report(_diamond(), "goal", "base")

    assert report.paths == [["goal", "m1", "base"]]
    assert report.path == ["goal", "m1", "base"]


def test_all_backward_direction_preserved() -> None:
    report = build_path_report(_diamond(), "base", "goal", all_paths=True)

    assert report.direction == DIRECTION_DEPENDED_ON_BY
    assert report.paths == [["goal", "m1", "base"], ["goal", "m2", "base"]]


def test_render_lists_each_path() -> None:
    text = render_path_report(build_path_report(_diamond(), "goal", "base", all_paths=True))
    assert "2 shortest path(s)" in text
    assert "Path 1: `goal` -> `m1` -> `base`" in text
    assert "Path 2: `goal` -> `m2` -> `base`" in text


_DIAMOND_BODY = """# path-test

::: definition {#base}
title: BASE
isabelle: Demo.base
status: stub

A base.

Sketch.
:::

::: lemma {#m1}
title: M1
isabelle: Demo.m1
status: stub
uses: base

Uses base.

Sketch.
:::

::: lemma {#m2}
title: M2
isabelle: Demo.m2
status: stub
uses: base

Uses base.

Sketch.
:::

::: theorem {#goal}
title: GOAL
isabelle: Demo.goal
status: stub
uses: m1, m2

Uses m1 and m2.

Sketch.
:::
"""


def test_cli_all_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _DIAMOND_BODY)

    rc = cli_main(["path", "goal", "base", str(tmp_path), "--all"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "2 shortest path(s)" in out
    assert "Path 1: `goal` -> `m1` -> `base`" in out
    assert "Path 2: `goal` -> `m2` -> `base`" in out


def test_cli_all_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _DIAMOND_BODY)

    rc = cli_main(["path", "goal", "base", str(tmp_path), "--all", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["found"] is True
    assert data["direction"] == DIRECTION_DEPENDS_ON
    assert data["paths"] == [["goal", "m1", "base"], ["goal", "m2", "base"]]
    # Existing single-path keys stay populated with the first path.
    assert data["path"] == ["goal", "m1", "base"]
    assert data["length"] == 2


def test_cli_json_without_all_has_single_element_paths(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _DIAMOND_BODY)

    rc = cli_main(["path", "goal", "base", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["path"] == ["goal", "m1", "base"]
    assert data["paths"] == [["goal", "m1", "base"]]
