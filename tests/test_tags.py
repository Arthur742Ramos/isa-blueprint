from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.tags import (
    TAGS_SCHEMA_VERSION,
    build_tag_report,
    render_tag_report,
)


def _node(
    node_id: str,
    *,
    tags: list[str] | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
        tags=list(tags or []),
    )


def _project(*nodes: BlueprintNode, name: str = "tg") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _stat(report, tag: str):
    return next(stat for stat in report.tags if stat.tag == tag)


def test_multi_tag_nodes_counted_under_each_tag() -> None:
    project = _project(
        _node("a", tags=["core", "alg"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.MISSING),
        _node("c"),
    )

    report = build_tag_report(project)

    assert report.total_nodes == 3
    assert report.untagged_count == 1
    assert _stat(report, "core").node_count == 2
    assert _stat(report, "alg").node_count == 1


def test_per_tag_target_and_coverage_counts() -> None:
    project = _project(
        _node("a", tags=["core"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.FOUND),
        _node("c", tags=["core"], formal=FormalStatus.BROKEN),
        _node("d", tags=["core"], formal=FormalStatus.MISSING),
    )

    core = _stat(build_tag_report(project), "core")

    assert core.node_count == 4
    assert core.formal_target_count == 3  # missing is not a target
    assert core.proved_count == 1
    assert core.found_count == 1
    assert core.problem_count == 1  # broken
    assert core.coverage_percent == 33  # 1 * 100 // 3, truncated


def test_coverage_none_without_targets() -> None:
    project = _project(_node("a", tags=["doc"], formal=FormalStatus.MISSING))

    assert _stat(build_tag_report(project), "doc").coverage_percent is None


def test_tags_sorted_by_usage_then_alpha() -> None:
    project = _project(
        _node("a", tags=["beta"]),
        _node("b", tags=["beta"]),
        _node("c", tags=["alpha"]),
        _node("d", tags=["gamma"]),
    )

    report = build_tag_report(project)
    ordered = [stat.tag for stat in report.tags]

    # 'beta' has 2 nodes, so it leads; the two single-node tags tie and sort
    # alphabetically.
    assert ordered == ["beta", "alpha", "gamma"]


def test_duplicate_tag_on_one_node_not_double_counted() -> None:
    project = _project(_node("a", tags=["core", "core"]))

    report = build_tag_report(project)

    assert _stat(report, "core").node_count == 1
    assert len(report.tags) == 1


def test_to_dict_shape() -> None:
    project = _project(_node("a", tags=["core"], formal=FormalStatus.PROVED))

    data = build_tag_report(project).to_dict()

    assert data["schema_version"] == TAGS_SCHEMA_VERSION
    assert data["project"] == "tg"
    assert data["total_nodes"] == 1
    assert data["tag_count"] == 1
    assert data["tags"][0]["tag"] == "core"


def test_render_table_and_empty() -> None:
    text = render_tag_report(build_tag_report(_project(_node("a", tags=["core"]))))
    assert "| Tag |" in text
    assert "core" in text

    empty = render_tag_report(build_tag_report(_project(_node("a"))))
    assert "no tagged nodes" in empty


def _write_project(tmp_path: Path, body: str, *, name: str = "tag-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# tag-test

::: definition {#a}
title: A
isabelle: Demo.a
status: stub
tags: core, alg

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a
tags: core

Depends on a.

Sketch.
:::

::: lemma {#c}
title: C
isabelle: Demo.c
status: stub

Untagged.

Sketch.
:::
"""


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "tag-test tags" in out
    assert "core" in out
    assert "1 untagged" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "tag-test"
    assert data["schema_version"] == TAGS_SCHEMA_VERSION
    assert data["total_nodes"] == 3
    assert data["untagged_count"] == 1
    tags = {stat["tag"]: stat for stat in data["tags"]}
    assert tags["core"]["node_count"] == 2
    assert tags["alg"]["node_count"] == 1
