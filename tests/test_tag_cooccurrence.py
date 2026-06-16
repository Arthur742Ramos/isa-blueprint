from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.tag_cooccurrence import (
    TAG_COOCCURRENCE_SCHEMA_VERSION,
    build_tag_cooccurrence_report,
    render_tag_cooccurrence_report,
)


def _node(node_id: str, *, tags: list[str] | None = None) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(),
        tags=list(tags or []),
    )


def _project(*nodes: BlueprintNode, name: str = "co") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _pair(report, a: str, b: str):
    key = tuple(sorted((a, b)))
    return next(p for p in report.pairs if p.tags == key)


def test_pair_shared_by_two_nodes_counts_two() -> None:
    project = _project(
        _node("a", tags=["core", "alg"]),
        _node("b", tags=["core", "alg"]),
        _node("c", tags=["core"]),
    )

    report = build_tag_cooccurrence_report(project)

    pair = _pair(report, "core", "alg")
    assert pair.shared_count == 2
    assert pair.node_ids == ("a", "b")
    assert pair.tags == ("alg", "core")


def test_nodes_with_fewer_than_two_tags_contribute_no_pairs() -> None:
    project = _project(
        _node("a", tags=["core"]),
        _node("b", tags=[]),
        _node("c"),
    )

    report = build_tag_cooccurrence_report(project)

    assert report.pairs == ()


def test_repeated_tag_within_node_not_double_counted() -> None:
    project = _project(_node("a", tags=["core", "core", "alg"]))

    report = build_tag_cooccurrence_report(project)

    assert _pair(report, "core", "alg").shared_count == 1


def test_pairs_sorted_by_descending_shared_count_then_pair() -> None:
    project = _project(
        _node("a", tags=["x", "y"]),
        _node("b", tags=["x", "y"]),
        _node("c", tags=["p", "q"]),
    )

    report = build_tag_cooccurrence_report(project)

    assert [p.tags for p in report.pairs] == [("x", "y"), ("p", "q")]


def test_min_shared_filters_low_count_pairs() -> None:
    project = _project(
        _node("a", tags=["x", "y"]),
        _node("b", tags=["x", "y"]),
        _node("c", tags=["p", "q"]),
    )

    report = build_tag_cooccurrence_report(project, min_shared=2)

    assert [p.tags for p in report.pairs] == [("x", "y")]


def test_min_shared_below_one_is_clamped() -> None:
    project = _project(_node("a", tags=["x", "y"]))

    report = build_tag_cooccurrence_report(project, min_shared=0)

    assert report.min_shared == 1
    assert _pair(report, "x", "y").shared_count == 1


def test_report_to_dict_shape() -> None:
    project = _project(_node("a", tags=["x", "y"]))

    payload = build_tag_cooccurrence_report(project).to_dict()

    assert payload["schema_version"] == TAG_COOCCURRENCE_SCHEMA_VERSION
    assert payload["project"] == "co"
    assert payload["min_shared"] == 1
    assert payload["pair_count"] == 1
    assert payload["pairs"] == [
        {"tags": ["x", "y"], "shared_count": 1, "node_ids": ["a"]}
    ]


def test_render_lists_pairs_and_empty_message() -> None:
    populated = render_tag_cooccurrence_report(
        build_tag_cooccurrence_report(_project(_node("a", tags=["x", "y"])))
    )
    assert "| Tag A | Tag B | Shared nodes |" in populated
    assert "| x | y | 1 |" in populated

    empty = render_tag_cooccurrence_report(
        build_tag_cooccurrence_report(_project(_node("a", tags=["solo"])))
    )
    assert "_(no co-occurring tags)_" in empty


# --- E2E CLI tests -----------------------------------------------------------

_BLUEPRINT = """# co

::: lemma {#a}
title: A
isabelle: Demo.a
tags: core, alg
status: stub
:::
A.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
tags: core, alg
status: stub
:::
B.
:::

::: lemma {#c}
title: C
isabelle: Demo.c
tags: core
status: stub
:::
C.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "co"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def test_cli_text_reports_cooccurring_pair(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["tag-cooccurrence", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "| alg | core | 2 |" in out


def test_cli_json_payload_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["tag-cooccurrence", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "co"
    assert data["min_shared"] == 1
    assert data["pairs"] == [
        {"tags": ["alg", "core"], "shared_count": 2, "node_ids": ["a", "b"]}
    ]


def test_cli_min_filters_low_count_pairs(tmp_path: Path, capsys) -> None:
    # Add a node introducing a count-1 pair that --min 2 should drop.
    blueprint = _BLUEPRINT + """
::: lemma {#d}
title: D
isabelle: Demo.d
tags: extra, solo
status: stub
:::
D.
:::
"""
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "co"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(blueprint, encoding="utf-8")

    rc = cli_main(["tag-cooccurrence", str(tmp_path), "--json", "--min", "2"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["min_shared"] == 2
    assert [p["tags"] for p in data["pairs"]] == [["alg", "core"]]
