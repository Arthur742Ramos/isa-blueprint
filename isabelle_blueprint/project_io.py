"""Shared project loading helpers for CLI and MCP entry points."""

from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.isabelle import check_cache, check_context
from isabelle_blueprint.isabelle.checker import CheckResult, apply_check_report, parse_check_report
from isabelle_blueprint.isabelle.dump import (
    apply_dump_report,
    parse_dump_report,
    restore_dump_history,
    verification_succeeded,
)
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.parser import parse_blueprint, parse_blueprint_file


def load_config_checked(project_dir: Path) -> BlueprintConfig:
    """Load the project config, surfacing malformed-config errors cleanly.

    ``load_config`` raises ValueError (incl. tomllib.TOMLDecodeError and float()
    conversion errors) and OSError on a malformed or unreadable
    isabelle-blueprint.toml. Callers that present errors to a user (the CLI's
    main() handler, the MCP tools) want a BlueprintError one-liner rather than a
    leaked internal exception type, so wrap those here. ``load_config`` itself
    keeps raising ValueError, which doctor.py and the multi-blueprint tests rely
    on catching.
    """

    try:
        return load_config(project_dir)
    except (ValueError, OSError) as exc:
        raise BlueprintError(f"could not load configuration in {project_dir}: {exc}") from exc


def load_project(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    """Load configured blueprint sources without applying generated artifacts."""

    config = load_config_checked(project_dir)
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


def latest_evidence(config: BlueprintConfig) -> tuple[str, Path, object, str | None] | None:
    """Select the latest completed report write; check wins equal write times.

    A malformed latest artifact still supersedes older evidence. Reads never
    resurrect a successful older attempt after a failed or incomplete dump.
    """
    candidates = []
    for origin, path in (("dump", config.dump_report_path), ("check", config.check_report_path)):
        try:
            candidates.append((path.stat().st_mtime_ns, origin == "check", origin, path))
        except OSError:
            continue
    if not candidates:
        return None
    _, _, origin, path = max(candidates)
    error = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        data = None
        error = str(exc)
    return origin, path, data, error


def apply_stored_check_report(project: BlueprintProject, config: BlueprintConfig) -> None:
    """Restore the latest check or dump through the same canonical read path."""
    restore_evidence(project, config)


def restore_evidence(project: BlueprintProject, config: BlueprintConfig) -> dict:
    """Restore evidence once and return the reason used by canonical read views."""
    selected = latest_evidence(config)
    metadata = {
        "origin": "authored",
        "state": "absent",
        "reason": "No saved native evidence; statuses are blueprint claims.",
        "report_path": None,
        "attempted_at": None,
        "checked_at": None,
    }
    if selected is None:
        return metadata
    origin, path, data, read_error = selected
    metadata.update(origin=origin, report_path=str(path))
    if isinstance(data, dict) and isinstance(data.get("timestamp"), str):
        metadata["attempted_at"] = data["timestamp"]
    if origin == "dump":
        dumped = parse_dump_report(data)
        if dumped is None:
            _invalidate_report(project)
            metadata.update(
                state="malformed", reason=read_error or "Invalid dump evidence fields; rerun check."
            )
            return metadata
        verified = parse_check_report(dumped.verification)
        if dumped.ran and dumped.return_code == 0 and not dumped.error and verified is not None:
            metadata.update(_restore_check(project, config, verified, dumped.verification or {}))
            if not verification_succeeded(verified):
                restore_dump_history(project, dumped)
                metadata["checked_at"] = max(
                    (
                        node.status.last_checked
                        for node in project.nodes
                        if node.status.last_checked
                    ),
                    default=None,
                )
                if metadata["state"] == "current":
                    metadata.update(
                        state="incomplete",
                        reason=verified.error or "Dump verification did not complete; rerun check.",
                    )
        else:
            apply_dump_report(project, dumped)
            metadata.update(
                state="incomplete" if dumped.ran or dumped.error else "offline",
                reason=dumped.error
                or dumped.evidence_reason
                or "Raw dump has no native proof evidence; run check.",
            )
            metadata["checked_at"] = max(
                (node.status.last_checked for node in project.nodes if node.status.last_checked),
                default=None,
            )
        return metadata
    result = parse_check_report(data)
    if result is None:
        _invalidate_report(project)
        metadata.update(
            state="malformed", reason=read_error or "Invalid check evidence fields; rerun check."
        )
        return metadata
    metadata.update(_restore_check(project, config, result, data if isinstance(data, dict) else {}))
    return metadata


def _invalidate_report(project: BlueprintProject) -> None:
    for node in project.nodes:
        if node.isabelle.fact:
            node.status.formal = FormalStatus.NAMED
            node.status.last_checked = None
            node.status.check_error = (
                "latest evidence report is malformed or unreadable; rerun check"
            )
    project.recompute_agent_status()


def _restore_check(
    project: BlueprintProject, config: BlueprintConfig, result: CheckResult, data: dict
) -> dict:
    reason = None
    state = "current"
    if result.source_context_changed:
        reason = result.error or "source context changed during check; rerun check"
        state = "source_changed"
    elif not result.source_fingerprint:
        reason = result.error or "stored report has no source provenance; rerun check"
        state = "incomplete" if not result.ran and result.error else "legacy"
    else:
        current = check_context.project_fingerprint(
            project,
            session_name=config.isabelle_session,
            isabelle_executable=config.isabelle_executable,
            extra_dirs=config.isabelle_dirs,
            project_root=config.project_root,
            timeout=config.isabelle_timeout,
        )
        if current is None:
            state = "probe_unavailable"
            reason = (
                "stored report source context changed or is unverifiable; native provenance probe "
                "unavailable; check Isabelle/session configuration and rerun check"
            )
        elif current != result.source_fingerprint:
            state = "source_changed"
            reason = (
                "stored report source context changed or is unverifiable; "
                "sources changed; rerun check"
            )
    stored_timestamp = data.get("timestamp")
    if not isinstance(stored_timestamp, str):
        stored_timestamp = None
        reason = reason or "stored report timestamp is unavailable; rerun check"
        if state == "current":
            state = "legacy"
    by_reference = {(fc.node_id, fc.fact, fc.theory): fc for fc in result.facts}
    stale_nodes = []
    for node in project.nodes:
        if not node.isabelle.fact:
            continue
        matched = (node.id, node.isabelle.fact, node.isabelle.theory) in by_reference
        node_current = bool(result.source_fingerprint) and (
            result.node_fingerprints.get(node.id)
            == check_cache.compute_node_hash(node, context=result.source_fingerprint or "")
        )
        if reason is not None or not node_current or not matched:
            stale_nodes.append(
                (node, matched, reason or "stored report node inputs changed; rerun check")
            )
    apply_check_report(project, result)
    for node, matched, message in stale_nodes:
        node.status.formal = FormalStatus.STALE if matched else FormalStatus.NAMED
        node.status.last_checked = stored_timestamp if matched else None
        node.status.check_error = message
    project.recompute_agent_status()
    if state == "current" and stale_nodes:
        state = "node_changed"
        reason = "stored report node inputs changed; rerun check"
    if state == "current" and (not result.ran or result.error):
        state = "incomplete"
        reason = result.error or "Latest check did not run; rerun check"
    return {
        "state": state,
        "reason": reason,
        "checked_at": stored_timestamp if result.ran else None,
    }


def load_project_with_check(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    """Load a project and fold in the latest stored proof evidence."""

    config, project = load_project(project_dir)
    apply_stored_check_report(project, config)
    return config, project
