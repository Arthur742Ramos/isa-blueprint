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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.config import DEFAULT_BLUEPRINT_NAME, DEFAULT_CONFIG_NAME
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.project_io import load_project_with_check
from isabelle_blueprint.report.metrics import build_status_metrics
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
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
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
        error=None,
    )


def _aggregate(projects: list[PortfolioProject]) -> PortfolioTotals:
    loaded = [p for p in projects if p.error is None]

    def total(attr: str) -> int:
        return sum(getattr(p, attr) or 0 for p in loaded)

    targets = total("formal_target_count")
    proved = total("proved_count")
    # Truncate (not round) so portfolio-wide 100% means every formal target is
    # proved, matching the per-project metric in metrics.py; clamp a non-zero
    # sub-1% ratio up to 1 so real progress is never shown as a misleading 0%.
    if targets:
        coverage: int | None = proved * 100 // targets
        if coverage == 0 and proved > 0:
            coverage = 1
    else:
        coverage = None
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


def portfolio_payload(report: PortfolioReport) -> dict[str, Any]:
    """Render ``report`` as a JSON-friendly dict."""
    return {
        "schema_version": report.schema_version,
        "root": report.root,
        "totals": report.totals.to_dict(),
        "projects": [p.to_dict() for p in report.projects],
    }


def _coverage_text(coverage: int | None) -> str:
    return "n/a" if coverage is None else f"{coverage}%"


def render_portfolio_report(report: PortfolioReport) -> str:
    """Render ``report`` as concise human-readable text (trailing newline)."""
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
    return "\n".join(lines) + "\n"
