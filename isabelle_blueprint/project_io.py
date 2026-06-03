"""Shared project loading helpers for CLI and MCP entry points."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.isabelle.checker import CheckResult, apply_check_report
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.parser import parse_blueprint, parse_blueprint_file


def load_project(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    """Load configured blueprint sources without applying generated artifacts."""

    config = load_config(project_dir)
    paths = config.blueprint_paths
    missing = [p for p in paths if not p.exists()]
    if missing:
        if len(paths) == 1:
            raise BlueprintError(
                f"blueprint not found at {missing[0]}; run `isabelle-blueprint init` first"
            )
        formatted = ", ".join(str(p) for p in missing)
        raise BlueprintError(f"configured blueprints are missing: {formatted}")
    if len(paths) == 1:
        project = parse_blueprint_file(paths[0], project_name=config.project_name)
    else:
        project = parse_blueprint(paths, project_name=config.project_name)
    return config, project


def apply_stored_check_report(project: BlueprintProject, config: BlueprintConfig) -> None:
    """Apply a previously stored check report if available.

    The generated check report is intentionally best-effort for read views: if it
    is absent or unreadable, callers still get the parsed blueprint state.
    """

    if not config.check_report_path.exists():
        return
    try:
        report_data = json.loads(config.check_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(report_data, dict):
        return
    facts = report_data.get("facts")
    if facts is not None and (
        not isinstance(facts, list) or any(not isinstance(item, dict) for item in facts)
    ):
        return
    try:
        result = CheckResult.from_dict(report_data)
        apply_check_report(project, result)
    except (BlueprintError, TypeError, ValueError):
        return


def load_project_with_check(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    """Load a project and fold in the latest stored check report."""

    config, project = load_project(project_dir)
    apply_stored_check_report(project, config)
    return config, project
