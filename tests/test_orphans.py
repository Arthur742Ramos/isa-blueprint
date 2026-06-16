"""Tests for the ``orphans`` unreachable-node analysis."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.orphans import (
    ORPHANS_SCHEMA_VERSION,
    build_orphan_report,
    render_orphan_report,
    render_orphans_csv,
    render_orphans_markdown,
)


def _node(
    node_id: str,
    *,
    uses: list[str] | None = None,
    kind: NodeKind = NodeKind.LEMMA,
    formal: FormalStatus = FormalStatus.MISSING,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
        uses=list(uses or []),
    )


def _project(*nodes: BlueprintNode, name: str = "orph") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _ids(report) -> list[str]:
    return [orphan.id for orphan in report.orphans]


# ---- unit-level behaviour --------------------------------------------------


def test_node_disconnected_from_goals_is_orphan() -> None:
    # top -> mid -> base is the goal chain. `alone` is a root that builds toward
    # nothing, so it is dead weight unreachable from any real goal.
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("mid", uses=["base"]),
        _node("top", uses=["mid"], kind=NodeKind.THEOREM),
        _node("alone", kind=NodeKind.DEFINITION),
    )

    report = build_orphan_report(project)

    assert _ids(report) == ["alone"]
    assert report.orphan_count == 1
    # base/mid/top are all justified by the goal `top`.
    assert "base" not in _ids(report)
    assert "top" not in _ids(report)


def test_fully_isolated_node_flagged_as_subset() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("alone", kind=NodeKind.REMARK),
    )

    report = build_orphan_report(project)
    by_id = {orphan.id: orphan for orphan in report.orphans}

    assert "alone" in by_id
    assert by_id["alone"].isolated is True
    assert report.isolated_count == 1


def test_disconnected_subgraph_with_internal_edges_is_orphan() -> None:
    # `ca`/`cb` form a self-contained cycle: each has both a dependency and a
    # dependent, so neither is a zero-degree isolated node, yet the whole
    # subgraph is unreachable from the goal `top` (no member is a root). This is
    # what distinguishes orphans from lint's isolated-node rule.
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("ca", uses=["cb"]),
        _node("cb", uses=["ca"]),
    )

    report = build_orphan_report(project)
    by_id = {orphan.id: orphan for orphan in report.orphans}

    assert set(by_id) == {"ca", "cb"}
    # Each has a real edge, so neither is "isolated".
    assert by_id["ca"].isolated is False
    assert by_id["cb"].isolated is False


def test_fully_connected_project_reports_none() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("mid", uses=["base"]),
        _node("top", uses=["mid"], kind=NodeKind.THEOREM),
    )

    report = build_orphan_report(project)

    assert report.orphan_count == 0
    assert report.orphans == ()


def test_report_carries_kind_and_formal_status() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("ca", uses=["cb"], kind=NodeKind.COROLLARY, formal=FormalStatus.PROVED),
        _node("cb", uses=["ca"]),
    )

    report = build_orphan_report(project)
    ca = next(o for o in report.orphans if o.id == "ca")

    assert ca.kind == "corollary"
    assert ca.formal_status == "proved"


def test_to_dict_shape() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("alone"),
    )

    payload = build_orphan_report(project).to_dict()

    assert payload["schema_version"] == ORPHANS_SCHEMA_VERSION
    assert payload["project"] == "orph"
    assert payload["orphan_count"] == 1
    assert payload["orphans"][0] == {
        "id": "alone",
        "kind": "lemma",
        "formal_status": "missing",
        "isolated": True,
    }


def test_render_escapes_pipe_in_id() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("a|b"),
    )

    rendered = render_orphan_report(build_orphan_report(project))

    assert r"a\|b" in rendered
    assert "orphan node(s)" in rendered


def test_render_clean_project() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
    )

    rendered = render_orphan_report(build_orphan_report(project))

    assert "No orphan nodes" in rendered
    # Clean output is a single concise line: no Markdown heading.
    assert "# " not in rendered
    assert rendered.count("\n") == 1


# ---- end-to-end CLI --------------------------------------------------------

_BLUEPRINT_WITH_ORPHAN = """# demo

::: definition {#base}
title: Base
isabelle: Demo.base
status: stub
:::
Base.
:::

::: theorem {#top}
title: Top
isabelle: Demo.top
uses:
  - base
status: stub
:::
Top.
:::

::: lemma {#ca}
title: Cycle A
isabelle: Demo.ca
uses:
  - cb
status: stub
:::
Cycle A.
:::

::: lemma {#cb}
title: Cycle B
isabelle: Demo.cb
uses:
  - ca
status: stub
:::
Cycle B.
:::
"""

_BLUEPRINT_CLEAN = """# demo

::: definition {#base}
title: Base
isabelle: Demo.base
status: stub
:::
Base.
:::

::: theorem {#top}
title: Top
isabelle: Demo.top
uses:
  - base
status: stub
:::
Top.
:::
"""


def _write(tmp_path: Path, blueprint: str) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(blueprint, encoding="utf-8")


def test_cli_reports_orphan_in_text(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "ca" in out
    assert "cb" in out
    assert "orphan node(s)" in out


def test_cli_json_shape(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "demo"
    assert data["orphan_count"] == 2
    ids = {o["id"] for o in data["orphans"]}
    assert ids == {"ca", "cb"}
    assert set(data["orphans"][0]) == {"id", "kind", "formal_status", "isolated"}


def test_cli_fail_on_orphan_exits_5(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path), "--fail-on-orphan"])

    assert rc == 5
    err = capsys.readouterr().err
    assert "fail-on-orphan policy triggered" in err


def test_cli_clean_project_exits_0_and_reports_none(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_CLEAN)

    rc = cli_main(["orphans", str(tmp_path), "--fail-on-orphan"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "No orphan nodes" in out


# ---- markdown / csv render helpers -----------------------------------------


def test_render_markdown_table_has_orphan_row() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("a|b"),
    )

    rendered = render_orphans_markdown(build_orphan_report(project))

    assert "| Node | Kind | Formal status | Isolated |" in rendered
    assert "| --- | --- | --- | --- |" in rendered
    # Pipe in the id is escaped so it cannot break the table.
    assert r"a\|b" in rendered
    assert "yes" in rendered


def test_render_markdown_clean_has_no_table() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
    )

    rendered = render_orphans_markdown(build_orphan_report(project))

    assert "_(no orphan nodes)_" in rendered
    assert "| Node |" not in rendered


def test_render_csv_no_carriage_return() -> None:
    project = _project(
        _node("base", kind=NodeKind.DEFINITION),
        _node("top", uses=["base"], kind=NodeKind.THEOREM),
        _node("alone"),
    )

    rendered = render_orphans_csv(build_orphan_report(project))

    assert "\r" not in rendered
    assert rendered.splitlines()[0] == "id,kind,formal_status,isolated"
    assert "alone,lemma,missing,true" in rendered


# ---- end-to-end CLI: markdown / csv ----------------------------------------


def test_cli_markdown_table_with_orphan_row(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "| Node | Kind | Formal status | Isolated |" in out
    assert "| ca |" in out
    assert "| cb |" in out


def test_cli_csv_header_and_orphan_row_no_cr(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path), "--csv"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "\r" not in out
    assert out.splitlines()[0] == "id,kind,formal_status,isolated"
    ids = {line.split(",")[0] for line in out.splitlines()[1:]}
    assert {"ca", "cb"} <= ids


def test_cli_csv_with_fail_on_orphan_exits_5(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    rc = cli_main(["orphans", str(tmp_path), "--csv", "--fail-on-orphan"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "\r" not in captured.out
    assert captured.out.splitlines()[0] == "id,kind,formal_status,isolated"
    assert "fail-on-orphan policy triggered" in captured.err


def test_cli_markdown_clean_project_exits_0(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _BLUEPRINT_CLEAN)

    rc = cli_main(["orphans", str(tmp_path), "--markdown", "--fail-on-orphan"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "_(no orphan nodes)_" in out


def test_cli_markdown_and_json_rejected(tmp_path: Path) -> None:
    _write(tmp_path, _BLUEPRINT_WITH_ORPHAN)

    with pytest.raises(SystemExit) as exc:
        cli_main(["orphans", str(tmp_path), "--markdown", "--json"])

    assert exc.value.code == 2

