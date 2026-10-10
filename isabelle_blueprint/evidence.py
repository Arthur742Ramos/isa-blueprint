"""Read-only canonical evidence snapshots shared by CLI, MCP and editor clients."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import load_project, restore_evidence
from isabelle_blueprint.report.metrics import build_status_metrics


def read_evidence_snapshot(project_dir: Path) -> dict:
    """Observe current provenance once, without writing reports or building proofs.

    Canonical planning metrics preserve their established meaning. Authored
    formal claims are retained explicitly, separately from native evidence.
    """
    config, project = load_project(project_dir)
    claims = {node.id: node.status.formal.value for node in project.nodes}
    evidence = restore_evidence(project, config)
    nodes = {}
    for node in sorted(project.nodes, key=lambda item: item.id):
        state = evidence["state"]
        if not node.isabelle.fact:
            state = "no_target"
        elif state in {"current", "node_changed"}:
            state = (
                "node_changed"
                if (
                    node.status.formal == FormalStatus.STALE
                    or (
                        node.status.check_error and "node inputs changed" in node.status.check_error
                    )
                )
                else ("incomplete" if node.status.formal == FormalStatus.NAMED else "current")
            )
        nodes[node.id] = {
            "authored_formal_claim": claims[node.id],
            "state": state,
            "origin": "authored" if state == "absent" else evidence["origin"],
            "checked_at": (
                None if state in {"absent", "malformed", "incomplete"} else node.status.last_checked
            ),
            "reason": node.status.check_error
            or (None if state in {"current", "no_target"} else evidence["reason"]),
        }
    return {
        "schema_version": 1,
        "observed_at": datetime.now(UTC).isoformat(),
        "project_root": str(config.project_root),
        "project": project.to_dict(),
        "metrics": build_status_metrics(project).to_dict(),
        "ready_task_ids": sorted(task.node_id for task in generate_tasks(project)),
        "evidence": evidence,
        "node_evidence": nodes,
        "inputs": {
            "config_path": str(config.project_root / "isabelle-blueprint.toml"),
            "blueprint_paths": [str(path) for path in config.blueprint_paths],
            "check_report_path": str(config.check_report_path),
            "dump_report_path": str(config.dump_report_path),
            "isabelle_dirs": [str(path) for path in config.isabelle_dirs],
        },
    }
