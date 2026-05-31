"""Write a machine-readable summary of the project."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject


def write_project_report(project: BlueprintProject, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project.to_json(), encoding="utf-8")
    return path


def project_summary(project: BlueprintProject) -> dict:
    """Return a compact summary suitable for badge/status reporting."""
    totals: dict[str, int] = {}
    for node in project.nodes:
        totals[node.status.formal.value] = totals.get(node.status.formal.value, 0) + 1
    return {
        "name": project.name,
        "node_count": len(project.nodes),
        "formal_status_counts": totals,
    }


def write_summary_json(project: BlueprintProject, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project_summary(project), indent=2), encoding="utf-8")
    return path
