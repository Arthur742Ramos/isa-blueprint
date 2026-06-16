from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.levels import (
    LEVELS_SCHEMA_VERSION,
    build_levels_report,
    render_levels_report,
)
from isabelle_blueprint.schemas import available_schemas, read_schema

pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)


def _node(node_id: str, *, uses: list[str] | None = None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(),
    )


def _project(*nodes: BlueprintNode, name: str = "lv") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _chain() -> BlueprintProject:
    # c -> b -> a  (c uses b, b uses a); three topological levels.
    return _project(_node("a"), _node("b", uses=["a"]), _node("c", uses=["b"]))


def test_levels_layering_basic() -> None:
    report = build_levels_report(_chain())

    assert report.level_count == 3
    assert report.levels[0].node_ids == ("a",)
    assert report.levels[0].index == 0
    assert report.levels[1].node_ids == ("b",)
    assert report.levels[2].node_ids == ("c",)
    assert report.max_width == 1
    assert report.cyclic_nodes == ()


def test_leaf_in_level_zero() -> None:
    # Two leaves at level 0, one dependent at level 1; widest level = 2.
    report = build_levels_report(
        _project(_node("x"), _node("y"), _node("z", uses=["x", "y"]))
    )

    assert report.level_count == 2
    assert set(report.levels[0].node_ids) == {"x", "y"}
    assert report.levels[0].count == 2
    assert report.max_width == 2
    assert report.levels[1].node_ids == ("z",)


def test_cycle_reported_separately() -> None:
    # p <-> q form a cycle; r is a clean leaf.
    report = build_levels_report(
        _project(_node("p", uses=["q"]), _node("q", uses=["p"]), _node("r"))
    )

    assert set(report.cyclic_nodes) == {"p", "q"}
    # The leaf is still placed; cycle nodes never appear in a level.
    placed = {nid for level in report.levels for nid in level.node_ids}
    assert "r" in placed
    assert placed.isdisjoint(report.cyclic_nodes)


def test_to_dict_shape() -> None:
    data = build_levels_report(_chain()).to_dict()

    assert data["schema_version"] == LEVELS_SCHEMA_VERSION
    assert data["project"] == "lv"
    assert data["level_count"] == 3
    assert data["max_width"] == 1
    assert data["levels"][0] == {"index": 0, "node_ids": ["a"], "count": 1}
    assert data["cyclic_nodes"] == []


def test_render_text_mentions_levels_and_summary() -> None:
    text = render_levels_report(build_levels_report(_chain()))

    assert "Level 0" in text
    assert "`a`" in text
    assert "3 level(s)" in text


_BODY = """# levels-test

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


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "levels-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BODY, encoding="utf-8")


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["levels", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "3 level(s)" in out
    assert "Level 0" in out


def test_cli_json_conforms_to_schema(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["levels", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["level_count"] == 3
    # The leaf `a` is at level 0.
    assert data["levels"][0]["node_ids"] == ["a"]
    Draft202012Validator(json.loads(read_schema("levels"))).validate(data)


def test_levels_schema_registered_and_metavalid() -> None:
    assert "levels" in available_schemas()
    Draft202012Validator.check_schema(json.loads(read_schema("levels")))


def test_schema_command_prints_levels(capsys) -> None:
    assert cli_main(["schema", "levels"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"]
    Draft202012Validator.check_schema(payload)
