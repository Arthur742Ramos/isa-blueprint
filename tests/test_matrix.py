from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus
from isabelle_blueprint.report.matrix import (
    MATRIX_SCHEMA_VERSION,
    build_matrix_report,
    render_matrix_csv,
    render_matrix_report,
)


def _node(
    node_id: str,
    *,
    kind: NodeKind = NodeKind.LEMMA,
    formal: FormalStatus = FormalStatus.MISSING,
    blueprint: BlueprintStatus = BlueprintStatus.STUB,
    agent: AgentStatus = AgentStatus.BLOCKED,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal, blueprint=blueprint, agent=agent),
    )


def _project(*nodes: BlueprintNode, name: str = "mx") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _cell(report, row: str, col: str) -> int:
    return next(c.count for c in report.cells if c.row == row and c.col == col)


def test_default_axes_cell_counts() -> None:
    project = _project(
        _node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.NAMED),
        _node("c", kind=NodeKind.LEMMA, formal=FormalStatus.NAMED),
        _node("d", kind=NodeKind.DEFINITION, formal=FormalStatus.MISSING),
    )

    report = build_matrix_report(project, "formal", "kind")

    assert report.rows_dimension == "formal"
    assert report.cols_dimension == "kind"
    assert _cell(report, "named", "lemma") == 2
    assert _cell(report, "proved", "theorem") == 1
    assert _cell(report, "missing", "definition") == 1
    # Rectangular grid: a present-row/present-col intersection with no node is 0.
    assert _cell(report, "proved", "lemma") == 0


def test_totals_are_consistent() -> None:
    project = _project(
        _node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.NAMED),
        _node("c", kind=NodeKind.LEMMA, formal=FormalStatus.MISSING),
    )

    report = build_matrix_report(project, "formal", "kind")

    assert report.total == 3
    assert sum(c.count for c in report.cells) == report.total
    assert sum(report.row_totals.values()) == report.total
    assert sum(report.col_totals.values()) == report.total
    assert report.row_totals["named"] == 1
    assert report.col_totals["lemma"] == 2


def test_absent_labels_are_omitted() -> None:
    # Every node is a missing lemma, so only one row and one column appear even
    # though the formal/kind enums declare many more values.
    project = _project(
        _node("a", kind=NodeKind.LEMMA, formal=FormalStatus.MISSING),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.MISSING),
    )

    report = build_matrix_report(project, "formal", "kind")

    assert report.row_labels == ("missing",)
    assert report.col_labels == ("lemma",)
    assert len(report.cells) == 1


def test_labels_follow_enum_order() -> None:
    project = _project(
        _node("a", formal=FormalStatus.PROVED),
        _node("b", formal=FormalStatus.MISSING),
        _node("c", formal=FormalStatus.NAMED),
    )

    report = build_matrix_report(project, "formal", "kind")

    # FormalStatus declares missing, named, ..., proved in that order.
    assert report.row_labels == ("missing", "named", "proved")


def test_blueprint_and_agent_axes() -> None:
    project = _project(
        _node("a", blueprint=BlueprintStatus.WRITTEN, agent=AgentStatus.READY),
        _node("b", blueprint=BlueprintStatus.STUB, agent=AgentStatus.READY),
    )

    report = build_matrix_report(project, "blueprint", "agent")

    assert _cell(report, "written", "ready") == 1
    assert _cell(report, "stub", "ready") == 1
    assert report.col_labels == ("ready",)


def test_same_axis_raises() -> None:
    project = _project(_node("a"))

    try:
        build_matrix_report(project, "formal", "formal")
    except ValueError as exc:
        assert "differ" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected ValueError for identical axes")


def test_to_dict_shape() -> None:
    project = _project(_node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED))

    data = build_matrix_report(project, "formal", "kind").to_dict()

    assert data["schema_version"] == MATRIX_SCHEMA_VERSION
    assert data["project"] == "mx"
    assert data["rows_dimension"] == "formal"
    assert data["cols_dimension"] == "kind"
    assert data["total"] == 1
    assert {"row", "col", "count"} <= set(data["cells"][0])


def test_render_table_has_header_rows_and_total() -> None:
    project = _project(
        _node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.NAMED),
    )

    text = render_matrix_report(build_matrix_report(project, "formal", "kind"))

    assert "matrix: formal x kind" in text
    assert "| formal | lemma | theorem | Total |" in text
    # One body row per present row label, plus the trailing Total row.
    assert "| named |" in text
    assert "| proved |" in text
    assert "| Total |" in text


def test_render_empty_project() -> None:
    text = render_matrix_report(build_matrix_report(_project(), "formal", "kind"))
    assert "no nodes" in text


def test_render_csv_round_trips() -> None:
    project = _project(
        _node("a", kind=NodeKind.THEOREM, formal=FormalStatus.PROVED),
        _node("b", kind=NodeKind.LEMMA, formal=FormalStatus.NAMED),
    )

    report = build_matrix_report(project, "formal", "kind")
    rows = list(csv.reader(io.StringIO(render_matrix_csv(report))))

    assert rows[0] == ["formal", "lemma", "theorem", "total"]
    assert rows[-1][0] == "total"
    # Last data column on the total row is the grand total.
    assert rows[-1][-1] == str(report.total)


def test_markdown_escapes_pipe_in_label() -> None:
    # A node kind/status cannot contain a pipe, but the escaping helper must
    # still neutralise one if a label ever did, so the table cannot break.
    from isabelle_blueprint.report.matrix import _escape_cell

    assert _escape_cell("a|b") == r"a\|b"


def test_markdown_flattens_newline_in_label() -> None:
    # Previously matrix only escaped "|", so a newline in a label would split
    # the row and corrupt the table. The shared md_cell helper flattens all
    # newline forms to spaces; assert the rendered row stays on a single line.
    from isabelle_blueprint.report.matrix import MatrixCell, MatrixReport, render_matrix_report

    report = MatrixReport(
        project="mx",
        rows_dimension="formal",
        cols_dimension="kind",
        row_labels=("line1\r\nline2\nline3\rline4",),
        col_labels=("lemma",),
        cells=(MatrixCell(row="line1\r\nline2\nline3\rline4", col="lemma", count=1),),
        row_totals={"line1\r\nline2\nline3\rline4": 1},
        col_totals={"lemma": 1},
        total=1,
    )

    rendered = render_matrix_report(report)

    assert "line1 line2 line3 line4" in rendered
    # The data row must be a single physical line: find it and confirm no raw
    # newline leaked into the cell.
    data_rows = [ln for ln in rendered.splitlines() if ln.startswith("| line1")]
    assert data_rows == ["| line1 line2 line3 line4 | 1 | 1 |"]


_BODY = """# matrix-test

::: theorem {#big}
title: Big
isabelle: Demo.big
status:
  formal: proved
:::
A theorem.
:::

::: lemma {#helper}
title: Helper
isabelle: Demo.helper
uses: big
status:
  formal: named
:::
A lemma.
:::

::: lemma {#other}
title: Other
isabelle: Demo.other
status: stub
:::
Another lemma.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "matrix-test"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BODY, encoding="utf-8")


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["matrix", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "matrix-test matrix: formal x kind" in out
    assert "| named |" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["matrix", str(tmp_path), "--rows", "kind", "--cols", "formal", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rows_dimension"] == "kind"
    assert data["cols_dimension"] == "formal"
    assert data["total"] == 3
    assert data["schema_version"] == MATRIX_SCHEMA_VERSION


def test_cli_csv(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["matrix", str(tmp_path), "--csv"])

    assert rc == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0][0] == "formal"
    assert rows[-1][0] == "total"


def test_cli_same_axis_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["matrix", str(tmp_path), "--rows", "formal", "--cols", "formal"])

    assert rc == 1
    assert "differ" in capsys.readouterr().err


def test_cli_json_csv_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)

    import pytest

    with pytest.raises(SystemExit):
        cli_main(["matrix", str(tmp_path), "--json", "--csv"])


def test_cli_json_conforms_to_schema(tmp_path: Path, capsys) -> None:
    import pytest

    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator

    from isabelle_blueprint.schemas import read_schema

    _write_project(tmp_path)

    rc = cli_main(["matrix", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    Draft202012Validator(json.loads(read_schema("matrix"))).validate(data)
