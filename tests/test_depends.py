from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.depends import (
    DEPENDS_SCHEMA_VERSION,
    UnknownNodeError,
    build_depends_report,
    render_depends_report,
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


def _project(*nodes: BlueprintNode, name: str = "dep") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _chain() -> BlueprintProject:
    # c -> b -> a  (c uses b, b uses a)
    return _project(_node("a"), _node("b", uses=["a"]), _node("c", uses=["b"]))


def test_direct_dependencies_and_dependents() -> None:
    # b depends on a, and is depended on by c (one hop each way).
    report = build_depends_report(_chain(), "b")

    assert report.project == "dep"
    assert report.node == "b"
    assert [n.id for n in report.depends_on] == ["a"]
    assert [n.id for n in report.depended_on_by] == ["c"]
    dep = report.depends_on[0]
    assert dep.kind == "lemma"
    assert dep.formal_status == "missing"


def test_leaf_has_empty_depends_on() -> None:
    # a uses nothing, so depends_on is empty but b depends on it.
    report = build_depends_report(_chain(), "a")

    assert report.depends_on == []
    assert [n.id for n in report.depended_on_by] == ["b"]


def test_unknown_node_raises() -> None:
    with pytest.raises(UnknownNodeError) as excinfo:
        build_depends_report(_chain(), "ghost")
    assert excinfo.value.args[0] == "ghost"


def test_missing_dependency_edges_are_omitted() -> None:
    # `x` lists a `uses` entry that is not a real node; it must not appear.
    report = build_depends_report(_project(_node("x", uses=["ghost"])), "x")
    assert report.depends_on == []
    assert report.depended_on_by == []


def test_render_text_lists_both_sections() -> None:
    text = render_depends_report(build_depends_report(_chain(), "b"))
    assert "Depends on:" in text
    assert "Depended on by:" in text
    assert "`a`" in text
    assert "`c`" in text


def test_render_text_empty_sections() -> None:
    text = render_depends_report(build_depends_report(_project(_node("solo")), "solo"))
    assert "Depends on:\n- (none)" in text
    assert "Depended on by:\n- (none)" in text


def _write_project(tmp_path: Path, body: str, *, name: str = "dep-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# dep-test

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

    rc = cli_main(["depends", "b", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Depends on:" in out
    assert "Depended on by:" in out
    assert "`a`" in out
    assert "`c`" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["depends", "b", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == DEPENDS_SCHEMA_VERSION
    assert data["project"] == "dep-test"
    assert data["node"] == "b"
    assert data["depends_on"] == [{"id": "a", "kind": "definition", "formal_status": "missing"}]
    assert data["depended_on_by"] == [{"id": "c", "kind": "theorem", "formal_status": "missing"}]


def test_cli_json_leaf_empty(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["depends", "a", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["depends_on"] == []
    assert [n["id"] for n in data["depended_on_by"]] == ["b"]


def test_cli_unknown_node_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["depends", "ghost", str(tmp_path)])

    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown node 'ghost'" in err
    assert "known node ids:" in err
    # The known ids are listed so the user can recover.
    assert "a" in err and "b" in err and "c" in err
