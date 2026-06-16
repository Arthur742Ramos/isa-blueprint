from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.kinds import (
    KINDS_SCHEMA_VERSION,
    build_kind_report,
    render_kind_report,
)


def _node(
    node_id: str,
    *,
    kind: NodeKind = NodeKind.LEMMA,
    formal: FormalStatus = FormalStatus.MISSING,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
    )


def _project(*nodes: BlueprintNode, name: str = "kd") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _stat(report, kind: str):
    return next(stat for stat in report.kinds if stat.kind == kind)


def test_nodes_grouped_by_kind() -> None:
    project = _project(
        _node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.MISSING),
        _node("c", kind=NodeKind.LEMMA, formal=FormalStatus.FOUND),
    )

    report = build_kind_report(project)

    assert report.total_nodes == 3
    assert _stat(report, "theorem").node_count == 1
    assert _stat(report, "lemma").node_count == 2
    # Per-kind node counts sum to the project total.
    assert sum(s.node_count for s in report.kinds) == report.total_nodes


def test_per_kind_target_and_coverage_counts() -> None:
    project = _project(
        _node("a", kind=NodeKind.LEMMA, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.FOUND),
        _node("c", kind=NodeKind.LEMMA, formal=FormalStatus.BROKEN),
        _node("d", kind=NodeKind.LEMMA, formal=FormalStatus.MISSING),
    )

    lemma = _stat(build_kind_report(project), "lemma")

    assert lemma.node_count == 4
    assert lemma.formal_target_count == 3  # missing is not a target
    assert lemma.proved_count == 1
    assert lemma.found_count == 1
    assert lemma.problem_count == 1  # broken
    assert lemma.coverage_percent == 33  # 1 * 100 // 3, truncated


def test_coverage_none_without_targets() -> None:
    project = _project(_node("a", kind=NodeKind.NOTE, formal=FormalStatus.MISSING))

    assert _stat(build_kind_report(project), "note").coverage_percent is None


def test_kinds_sorted_by_count_then_alpha() -> None:
    project = _project(
        _node("a", kind=NodeKind.LEMMA),
        _node("b", kind=NodeKind.LEMMA),
        _node("c", kind=NodeKind.THEOREM),
        _node("d", kind=NodeKind.DEFINITION),
    )

    ordered = [stat.kind for stat in build_kind_report(project).kinds]

    # lemma has 2 nodes, so it leads; the two single-node kinds tie and sort
    # alphabetically.
    assert ordered == ["lemma", "definition", "theorem"]


def test_to_dict_shape() -> None:
    project = _project(_node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED))

    data = build_kind_report(project).to_dict()

    assert data["schema_version"] == KINDS_SCHEMA_VERSION
    assert data["project"] == "kd"
    assert data["total_nodes"] == 1
    assert data["kind_count"] == 1
    assert data["kinds"][0]["kind"] == "theorem"


def test_render_table_and_empty() -> None:
    text = render_kind_report(build_kind_report(_project(_node("a", kind=NodeKind.LEMMA))))
    assert "| Kind |" in text
    assert "lemma" in text

    empty = render_kind_report(build_kind_report(_project()))
    assert "no nodes" in empty


def _write_project(tmp_path: Path, body: str, *, name: str = "kind-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# kind-test

::: theorem {#big}
title: Big
isabelle: Demo.big
status:
  formal: proved

A theorem.

Sketch.
:::

::: lemma {#helper}
title: Helper
isabelle: Demo.helper
status:
  formal: found
uses: big

A lemma.

Sketch.
:::

::: lemma {#other}
title: Other
isabelle: Demo.other
status: stub

Another lemma.

Sketch.
:::
"""


def test_cli_text_reports_both_kinds(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["kinds", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "kind-test kinds" in out
    assert "theorem" in out
    assert "lemma" in out
    # lemma carries two nodes; the row must be present.
    assert "| lemma | 2 |" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["kinds", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "kind-test"
    assert data["schema_version"] == KINDS_SCHEMA_VERSION
    assert data["total_nodes"] == 3
    kinds = {stat["kind"]: stat for stat in data["kinds"]}
    assert kinds["theorem"]["node_count"] == 1
    assert kinds["theorem"]["proved_count"] == 1
    assert kinds["theorem"]["coverage_percent"] == 100
    assert kinds["lemma"]["node_count"] == 2
    assert kinds["lemma"]["found_count"] == 1


def test_cli_json_conforms_to_schema(tmp_path: Path, capsys) -> None:
    import pytest

    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator

    from isabelle_blueprint.schemas import read_schema

    _write_project(tmp_path, _BODY)

    rc = cli_main(["kinds", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    Draft202012Validator(json.loads(read_schema("kinds"))).validate(data)
