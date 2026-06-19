"""Two-dimensional cross-tabulation of node counts.

Every existing roll-up (:mod:`~isabelle_blueprint.report.kinds`,
:mod:`~isabelle_blueprint.report.tags`, ``fact-coverage``) collapses a *single*
dimension. ``matrix`` answers the cross-dimensional planning question instead -
*which kinds are stuck in which formal states?*, *which blueprint stubs are
already proved?* - by tallying nodes across two of the four categorical axes a
node carries:

* ``formal``    - :class:`~isabelle_blueprint.model.status.FormalStatus`.
* ``blueprint`` - :class:`~isabelle_blueprint.model.status.BlueprintStatus`.
* ``agent``     - :class:`~isabelle_blueprint.model.status.AgentStatus`.
* ``kind``      - :class:`~isabelle_blueprint.model.node.NodeKind`.

Each node contributes to exactly one ``(row, col)`` cell, so the cell counts sum
to the project node total; row and column totals are the marginals. Only labels
actually present on some node produce a row or column (empty axis values are
omitted, mirroring ``kinds``), and present labels are ordered by their enum
declaration order so the output is stable and reads in a natural progression
(e.g. ``missing -> named -> ... -> proved`` for the formal axis). No Isabelle
invocation is required.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from isabelle_blueprint.model.node import BlueprintNode, NodeKind
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus
from isabelle_blueprint.report._markdown import md_cell as _escape_cell

MATRIX_SCHEMA_VERSION = 1

#: Selectable axes, mapped to their node accessor and the enum that fixes the
#: canonical label order. Keys are the values accepted by ``--rows``/``--cols``.
_AXES: dict[str, tuple[Callable[[BlueprintNode], str], type[StrEnum]]] = {
    "formal": (lambda n: n.status.formal.value, FormalStatus),
    "blueprint": (lambda n: n.status.blueprint.value, BlueprintStatus),
    "agent": (lambda n: n.status.agent.value, AgentStatus),
    "kind": (lambda n: n.kind.value, NodeKind),
}

#: Axis names in the order they are offered on the command line.
AXIS_NAMES: tuple[str, ...] = tuple(_AXES)


@dataclass(frozen=True)
class MatrixCell:
    """Node count for one ``(row label, column label)`` combination."""

    row: str
    col: str
    count: int

    def to_dict(self) -> dict[str, object]:
        return {"row": self.row, "col": self.col, "count": self.count}


@dataclass(frozen=True)
class MatrixReport:
    """A dense ``rows x cols`` cross-tabulation across a project."""

    project: str
    rows_dimension: str
    cols_dimension: str
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    cells: tuple[MatrixCell, ...]
    row_totals: dict[str, int]
    col_totals: dict[str, int]
    total: int
    schema_version: int = MATRIX_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "rows_dimension": self.rows_dimension,
            "cols_dimension": self.cols_dimension,
            "row_labels": list(self.row_labels),
            "col_labels": list(self.col_labels),
            "cells": [cell.to_dict() for cell in self.cells],
            "row_totals": dict(self.row_totals),
            "col_totals": dict(self.col_totals),
            "total": self.total,
        }


def _present_labels(values: set[str], enum_cls: type[StrEnum]) -> tuple[str, ...]:
    """Order the labels that occur, by their enum declaration order."""

    return tuple(member.value for member in enum_cls if member.value in values)


def build_matrix_report(
    project: BlueprintProject, rows_dimension: str, cols_dimension: str
) -> MatrixReport:
    """Cross-tabulate ``project`` nodes by two axes.

    ``rows_dimension`` and ``cols_dimension`` must each be one of
    :data:`AXIS_NAMES` and must differ; a same-axis request raises
    :class:`ValueError` (the CLI surfaces it as a clean ``BlueprintError``).
    Only labels present on some node become rows/columns, but every
    intersection of a present row and column produces a cell (including zero
    cells) so the grid stays rectangular.
    """

    for name in (rows_dimension, cols_dimension):
        if name not in _AXES:
            raise ValueError(
                f"unknown matrix dimension {name!r}; choose one of: "
                f"{', '.join(AXIS_NAMES)}"
            )
    if rows_dimension == cols_dimension:
        raise ValueError(
            f"matrix rows and cols must differ; both are {rows_dimension!r}"
        )

    row_of, row_enum = _AXES[rows_dimension]
    col_of, col_enum = _AXES[cols_dimension]

    counts: Counter[tuple[str, str]] = Counter()
    row_values: set[str] = set()
    col_values: set[str] = set()
    for node in project.nodes:
        row, col = row_of(node), col_of(node)
        counts[(row, col)] += 1
        row_values.add(row)
        col_values.add(col)

    row_labels = _present_labels(row_values, row_enum)
    col_labels = _present_labels(col_values, col_enum)

    cells = tuple(
        MatrixCell(row=row, col=col, count=counts.get((row, col), 0))
        for row in row_labels
        for col in col_labels
    )
    row_totals = {
        row: sum(counts.get((row, col), 0) for col in col_labels) for row in row_labels
    }
    col_totals = {
        col: sum(counts.get((row, col), 0) for row in row_labels) for col in col_labels
    }

    return MatrixReport(
        project=project.name,
        rows_dimension=rows_dimension,
        cols_dimension=cols_dimension,
        row_labels=row_labels,
        col_labels=col_labels,
        cells=cells,
        row_totals=row_totals,
        col_totals=col_totals,
        total=len(project.nodes),
    )


def _cell_lookup(report: MatrixReport) -> dict[tuple[str, str], int]:
    return {(cell.row, cell.col): cell.count for cell in report.cells}


def render_matrix_report(report: MatrixReport) -> str:
    """Render the cross-tabulation as a compact Markdown table.

    The first header cell names the row axis; columns are the present column
    labels followed by a ``Total`` marginal, and a trailing ``Total`` row holds
    the column marginals and the grand total.
    """

    title = f"{report.project} matrix: {report.rows_dimension} x {report.cols_dimension}"
    lines = [
        f"# {title}",
        "",
        f"{report.total} node(s) across {len(report.row_labels)} "
        f"{report.rows_dimension} x {len(report.col_labels)} "
        f"{report.cols_dimension} value(s).",
        "",
    ]
    if not report.row_labels or not report.col_labels:
        lines.append("_(no nodes)_")
        return "\n".join(lines) + "\n"

    header = f"| {_escape_cell(report.rows_dimension)} | " + " | ".join(
        [*(_escape_cell(col) for col in report.col_labels), "Total"]
    ) + " |"
    sep = "| " + " | ".join(["---"] * (len(report.col_labels) + 2)) + " |"
    lines.extend([header, sep])

    lookup = _cell_lookup(report)
    for row in report.row_labels:
        counts = [str(lookup[(row, col)]) for col in report.col_labels]
        counts.append(str(report.row_totals[row]))
        lines.append(f"| {_escape_cell(row)} | " + " | ".join(counts) + " |")

    totals = [str(report.col_totals[col]) for col in report.col_labels]
    totals.append(str(report.total))
    lines.append("| Total | " + " | ".join(totals) + " |")
    return "\n".join(lines) + "\n"


def render_matrix_csv(report: MatrixReport) -> str:
    """Render the cross-tabulation as CSV.

    The header is the row-axis name, the present column labels, then ``total``;
    each body row is a row label, its per-column counts, and its row total; a
    final ``total`` row carries the column marginals and the grand total.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([report.rows_dimension, *report.col_labels, "total"])

    lookup = _cell_lookup(report)
    for row in report.row_labels:
        counts = [lookup[(row, col)] for col in report.col_labels]
        writer.writerow([row, *counts, report.row_totals[row]])

    totals = [report.col_totals[col] for col in report.col_labels]
    writer.writerow(["total", *totals, report.total])
    return buffer.getvalue()
