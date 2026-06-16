"""Cross-project portfolio roll-up.

Discovers every IsabelleBlueprint project under a root directory and aggregates
their status into a single dashboard: per-project coverage / health plus
portfolio-wide totals. Useful for monorepos or umbrella repositories that hold
several formalization projects side by side, where ``status`` (one project) does
not give the whole picture.

Discovery mirrors the MCP server's project catalog: a directory is a project
root when it contains an ``isabelle-blueprint.toml`` or ``blueprint.md`` marker,
nested projects are not descended into, and noisy build/vendor directories are
skipped. Loading each project is best-effort - a project that fails to parse is
recorded with its error rather than aborting the whole roll-up.
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.config import DEFAULT_BLUEPRINT_NAME, DEFAULT_CONFIG_NAME
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.project_io import load_project_with_check
from isabelle_blueprint.report.metrics import (
    PROBLEM_FORMAL_STATUSES,
    build_status_metrics,
    coverage_percent,
)
from isabelle_blueprint.report.status_overview import build_status_overview

PORTFOLIO_SCHEMA_VERSION = 1

_SKIP_DIRS = {
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "site",
    "venv",
}


@dataclass(frozen=True)
class ProblemNode:
    """A single node that is actively wrong (broken/not_found/tainted/failed_check)."""

    id: str
    formal_status: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "formal_status": self.formal_status}


@dataclass(frozen=True)
class PortfolioProject:
    """One project's contribution to the portfolio roll-up."""

    id: str
    name: str
    path: str
    health: str | None = None
    node_count: int | None = None
    formal_target_count: int | None = None
    proved_count: int | None = None
    found_count: int | None = None
    problem_count: int | None = None
    stale_count: int | None = None
    has_cycles: bool | None = None
    coverage_percent: int | None = None
    ready_task_count: int | None = None
    problem_nodes: tuple[ProblemNode, ...] = ()
    error: str | None = None

    def to_dict(self, *, details: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "health": self.health,
            "node_count": self.node_count,
            "formal_target_count": self.formal_target_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "stale_count": self.stale_count,
            "has_cycles": self.has_cycles,
            "coverage_percent": self.coverage_percent,
            "ready_task_count": self.ready_task_count,
            "error": self.error,
        }
        if details:
            payload["problem_nodes"] = [node.to_dict() for node in self.problem_nodes]
        return payload


@dataclass(frozen=True)
class PortfolioTotals:
    """Portfolio-wide aggregates across the loadable projects."""

    project_count: int
    loaded_count: int
    error_count: int
    node_count: int
    formal_target_count: int
    proved_count: int
    found_count: int
    problem_count: int
    stale_count: int
    coverage_percent: int | None
    projects_with_problems: int
    projects_with_cycles: int
    projects_complete: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_count": self.project_count,
            "loaded_count": self.loaded_count,
            "error_count": self.error_count,
            "node_count": self.node_count,
            "formal_target_count": self.formal_target_count,
            "proved_count": self.proved_count,
            "found_count": self.found_count,
            "problem_count": self.problem_count,
            "stale_count": self.stale_count,
            "coverage_percent": self.coverage_percent,
            "projects_with_problems": self.projects_with_problems,
            "projects_with_cycles": self.projects_with_cycles,
            "projects_complete": self.projects_complete,
        }


@dataclass(frozen=True)
class PortfolioReport:
    """A full portfolio roll-up for a directory tree."""

    schema_version: int
    root: str
    totals: PortfolioTotals
    projects: list[PortfolioProject] = field(default_factory=list)


def _has_marker(path: Path) -> bool:
    return (path / DEFAULT_CONFIG_NAME).is_file() or (path / DEFAULT_BLUEPRINT_NAME).is_file()


def _should_descend(path: Path) -> bool:
    name = path.name
    if path.is_symlink():
        return False
    if name.startswith("."):
        return False
    return name not in _SKIP_DIRS


def _relative_path(root: Path, project_root: Path) -> str:
    if project_root == root:
        return "."
    return project_root.relative_to(root).as_posix()


def discover_project_roots(root: Path) -> list[Path]:
    """Return the project roots under ``root``, sorted by relative path.

    A nested project (one inside another project's tree) is treated as its own
    root but its subtree is not descended into further, matching the MCP
    catalog's behaviour.
    """
    root = root.resolve()
    roots: list[Path] = []
    if _has_marker(root):
        roots.append(root)

    for current_raw, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_raw)
        dirnames[:] = sorted(
            dirname for dirname in dirnames if _should_descend(current / dirname)
        )
        if current == root:
            continue
        if DEFAULT_CONFIG_NAME in filenames or DEFAULT_BLUEPRINT_NAME in filenames:
            roots.append(current.resolve())
            dirnames[:] = []

    unique = list(dict.fromkeys(roots))
    return sorted(unique, key=lambda path: _relative_path(root, path))


def _collect_problem_nodes(project: BlueprintProject) -> tuple[ProblemNode, ...]:
    """Return the ids/statuses of nodes that are actively wrong, in source order.

    "Actively wrong" mirrors ``problem_count``: a node whose formal status is one
    of ``broken``/``not_found``/``tainted``/``failed_check``. ``stale`` is
    excluded (dependencies changed, the proof itself did not fail).
    """
    return tuple(
        ProblemNode(id=node.id, formal_status=node.status.formal.value)
        for node in project.nodes
        if node.status.formal.value in PROBLEM_FORMAL_STATUSES
    )


def _build_project(project_root: Path, relative: str) -> PortfolioProject:
    try:
        _config, project = load_project_with_check(project_root)
    except (BlueprintError, OSError, ValueError) as exc:
        # Best-effort: a single unparseable project (bad blueprint, malformed
        # TOML, unreadable file) becomes an error entry rather than aborting
        # the whole roll-up. ``ValueError`` also covers ``tomllib`` decode and
        # unicode-decode failures, which subclass it.
        return PortfolioProject(id=relative, name=relative, path=relative, error=str(exc))

    metrics = build_status_metrics(project)
    ready_tasks = generate_tasks(project)
    overview = build_status_overview(project, ready_tasks)
    return PortfolioProject(
        id=relative,
        name=project.name,
        path=relative,
        health=overview.health,
        node_count=metrics.node_count,
        formal_target_count=metrics.formal_target_count,
        proved_count=metrics.proved_count,
        found_count=metrics.found_count,
        problem_count=metrics.problem_count,
        stale_count=metrics.stale_count,
        has_cycles=metrics.has_cycles,
        coverage_percent=metrics.coverage_percent,
        ready_task_count=overview.ready_task_count,
        problem_nodes=_collect_problem_nodes(project),
        error=None,
    )


def _aggregate(projects: list[PortfolioProject]) -> PortfolioTotals:
    loaded = [p for p in projects if p.error is None]

    def total(attr: str) -> int:
        return sum(getattr(p, attr) or 0 for p in loaded)

    targets = total("formal_target_count")
    proved = total("proved_count")
    coverage = coverage_percent(proved, targets)
    return PortfolioTotals(
        project_count=len(projects),
        loaded_count=len(loaded),
        error_count=len(projects) - len(loaded),
        node_count=total("node_count"),
        formal_target_count=targets,
        proved_count=proved,
        found_count=total("found_count"),
        problem_count=total("problem_count"),
        stale_count=total("stale_count"),
        coverage_percent=coverage,
        projects_with_problems=sum(1 for p in loaded if (p.problem_count or 0) > 0),
        projects_with_cycles=sum(1 for p in loaded if p.has_cycles),
        projects_complete=sum(1 for p in loaded if p.health == "complete"),
    )


def build_portfolio(root: Path) -> PortfolioReport:
    """Discover and roll up every blueprint project under ``root``."""
    root = root.resolve()
    projects = [
        _build_project(project_root, _relative_path(root, project_root))
        for project_root in discover_project_roots(root)
    ]
    return PortfolioReport(
        schema_version=PORTFOLIO_SCHEMA_VERSION,
        root=str(root),
        totals=_aggregate(projects),
        projects=projects,
    )


PORTFOLIO_SORT_KEYS = ("name", "coverage", "nodes", "problems")


def sort_portfolio_report(report: PortfolioReport, sort_by: str) -> PortfolioReport:
    """Return ``report`` with its projects reordered by ``sort_by``.

    ``name`` sorts ascending (case-insensitive); ``coverage``, ``nodes`` and
    ``problems`` sort descending (highest first). Projects whose chosen metric is
    None (load error or undefined, e.g. no formal targets) sort last. The original
    report-discovery order is the tie-breaker, so the sort is stable. Totals are
    unaffected. An unknown ``sort_by`` raises ``ValueError``.
    """
    projects = list(report.projects)
    if sort_by == "name":
        projects.sort(key=lambda p: p.name.casefold())
    else:
        attrs = {
            "coverage": "coverage_percent",
            "nodes": "node_count",
            "problems": "problem_count",
        }
        if sort_by not in attrs:
            raise ValueError(f"unknown sort key: {sort_by!r}")
        attr = attrs[sort_by]

        def metric_key(project: PortfolioProject) -> tuple[bool, int]:
            value = getattr(project, attr)
            return (value is None, -(value or 0))

        projects.sort(key=metric_key)
    return PortfolioReport(
        schema_version=report.schema_version,
        root=report.root,
        totals=report.totals,
        projects=projects,
    )


def coverage_gate_failures(report: PortfolioReport, min_coverage: int) -> list[str]:
    """Return the ids of projects whose proved-coverage is below ``min_coverage``.

    Projects with undefined coverage (no formal targets, or a load error) have
    no measurable coverage and are therefore never counted as failures. Results
    follow the report's project order.
    """
    return [
        project.id
        for project in report.projects
        if project.coverage_percent is not None
        and project.coverage_percent < min_coverage
    ]


def portfolio_payload(report: PortfolioReport, *, details: bool = False) -> dict[str, Any]:
    """Render ``report`` as a JSON-friendly dict.

    When ``details`` is set, each project gains an additive ``problem_nodes``
    array (``{id, formal_status}`` per actively-wrong node); the rest of the
    payload is unchanged.
    """
    return {
        "schema_version": report.schema_version,
        "root": report.root,
        "totals": report.totals.to_dict(),
        "projects": [p.to_dict(details=details) for p in report.projects],
    }


def _coverage_text(coverage: int | None) -> str:
    return "n/a" if coverage is None else f"{coverage}%"


def render_portfolio_report(report: PortfolioReport, *, details: bool = False) -> str:
    """Render ``report`` as concise human-readable text (trailing newline).

    When ``details`` is set, a short per-project ``Problem details:`` block is
    appended beneath the project table, naming each project's actively-wrong
    node ids (and flagging dependency cycles). Without it the output is
    unchanged.
    """
    totals = report.totals
    if totals.project_count == 0:
        return (
            f"Portfolio: no IsabelleBlueprint projects found under {report.root}.\n"
        )

    lines = [
        f"Portfolio: {totals.project_count} project(s) under {report.root}"
    ]
    lines.append(
        f"  Coverage: {_coverage_text(totals.coverage_percent)} "
        f"({totals.proved_count}/{totals.formal_target_count} proved across "
        f"{totals.node_count} nodes)"
    )
    lines.append(
        f"  Problems: {totals.problem_count} in "
        f"{totals.projects_with_problems} project(s); "
        f"cycles in {totals.projects_with_cycles}; "
        f"stale {totals.stale_count}; "
        f"complete {totals.projects_complete}/{totals.loaded_count}"
    )
    if totals.error_count:
        lines.append(f"  Failed to load: {totals.error_count} project(s)")

    lines.append("  Projects:")
    for project in report.projects:
        if project.error is not None:
            lines.append(f"    {project.path}  ERROR: {project.error}")
            continue
        lines.append(
            f"    {project.path}  [{project.health}] "
            f"coverage={_coverage_text(project.coverage_percent)} "
            f"proved={project.proved_count}/{project.formal_target_count} "
            f"problems={project.problem_count} ready={project.ready_task_count}"
        )
    if details:
        lines.extend(_problem_detail_lines(report))
    return "\n".join(lines) + "\n"


def _problem_detail_lines(report: PortfolioReport) -> list[str]:
    """Per-project problem-node breakdown for ``--details`` text output."""
    detail: list[str] = []
    flagged = [
        project
        for project in report.projects
        if project.error is None and (project.problem_nodes or project.has_cycles)
    ]
    detail.append("  Problem details:")
    if not flagged:
        detail.append("    (none)")
        return detail
    for project in flagged:
        parts: list[str] = []
        if project.problem_nodes:
            parts.append(
                ", ".join(
                    f"{node.id} ({node.formal_status})" for node in project.problem_nodes
                )
            )
        if project.has_cycles:
            parts.append("has cycles")
        detail.append(f"    {project.path}: " + "; ".join(parts))
    return detail


_CSV_COLUMNS = (
    "name",
    "path",
    "node_count",
    "coverage_percent",
    "proved_count",
    "problem_count",
    "has_cycles",
    "health",
)


def _md_cell(text: str) -> str:
    """Escape a value for safe inclusion in a Markdown table cell.

    A literal ``|`` would otherwise start a new column and a newline would
    terminate the row, so both are neutralised.
    """

    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


_MARKDOWN_HEADERS = (
    "Project",
    "Nodes",
    "Coverage",
    "Proved",
    "Problems",
    "Cycles",
    "Health",
)


def _problem_nodes_cell(project: PortfolioProject) -> str:
    """Semicolon-joined ``id (status)`` list of a project's problem nodes."""
    return "; ".join(
        f"{node.id} ({node.formal_status})" for node in project.problem_nodes
    )


def render_portfolio_markdown(report: PortfolioReport, *, details: bool = False) -> str:
    """Render ``report`` as a Markdown document (trailing newline).

    A level-2 heading, a one-line totals summary, and a table with one row per
    project: name, node count, coverage, proved, problems, a cycles flag, and
    health/status. Errored projects use ``error`` as their status and leave
    numeric cells blank. User-controlled text (project names) is escaped so a
    stray ``|`` or newline cannot break the table.

    When ``details`` is set, an extra trailing ``Problem nodes`` column lists
    each project's actively-wrong node ids; without it the table is unchanged.
    """
    totals = report.totals
    lines = ["## Portfolio"]
    if totals.project_count == 0:
        lines.append("")
        lines.append(
            f"No IsabelleBlueprint projects found under `{report.root}`."
        )
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append(
        f"**Totals:** {totals.project_count} project(s); coverage "
        f"{_coverage_text(totals.coverage_percent)} "
        f"({totals.proved_count}/{totals.formal_target_count} proved across "
        f"{totals.node_count} nodes); problems {totals.problem_count} in "
        f"{totals.projects_with_problems} project(s); cycles in "
        f"{totals.projects_with_cycles}; complete "
        f"{totals.projects_complete}/{totals.loaded_count}"
        + (f"; failed to load {totals.error_count}" if totals.error_count else "")
    )
    lines.append("")
    headers = _MARKDOWN_HEADERS + (("Problem nodes",) if details else ())
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for project in report.projects:
        if project.error is not None:
            cells = [_md_cell(project.name), "", "", "", "", "", "error"]
        else:
            cells = [
                _md_cell(project.name),
                "" if project.node_count is None else str(project.node_count),
                _coverage_text(project.coverage_percent),
                "" if project.proved_count is None else str(project.proved_count),
                "" if project.problem_count is None else str(project.problem_count),
                "" if project.has_cycles is None else ("yes" if project.has_cycles else "no"),
                project.health or "",
            ]
        if details:
            cells.append(_md_cell(_problem_nodes_cell(project)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_portfolio_csv(report: PortfolioReport, *, details: bool = False) -> str:
    """Render ``report`` as CSV: a header row plus one row per project.

    Columns: project name, relative path, node count, coverage percent, proved
    count, problem count, a cycles flag, and health/status. Errored projects use
    ``error`` as their status and leave numeric cells blank. Uses ``\\r\\n`` line
    terminators per the :mod:`csv` module default.

    When ``details`` is set, an extra trailing ``problem_nodes`` column carries a
    semicolon-joined ``id (status)`` list of each project's actively-wrong nodes;
    without it the columns are unchanged.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = _CSV_COLUMNS + (("problem_nodes",) if details else ())
    writer.writerow(columns)
    for project in report.projects:
        status = "error" if project.error is not None else (project.health or "")
        row = [
            project.name,
            project.path,
            "" if project.node_count is None else project.node_count,
            "" if project.coverage_percent is None else project.coverage_percent,
            "" if project.proved_count is None else project.proved_count,
            "" if project.problem_count is None else project.problem_count,
            "" if project.has_cycles is None else project.has_cycles,
            status,
        ]
        if details:
            row.append(_problem_nodes_cell(project))
        writer.writerow(row)
    return buffer.getvalue()
