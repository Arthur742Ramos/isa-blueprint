"""Shared project loading helpers for CLI and MCP entry points."""

from __future__ import annotations

import json
import re
from pathlib import Path

from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.isabelle import check_cache, check_context
from isabelle_blueprint.isabelle.checker import CheckResult, FactCheck, apply_check_report
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


def apply_stored_check_report(project: BlueprintProject, config: BlueprintConfig) -> None:
    """Apply a previously stored check report if available.

    The generated check report is intentionally best-effort for read views: if it
    is absent or unreadable, callers still get the parsed blueprint state.
    """

    if not config.check_report_path.exists():
        return
    try:
        report_data = json.loads(config.check_report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
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
        if not _well_formed_check_report(result):
            return
        reason = None
        if result.source_context_changed:
            reason = result.error or "source context changed during check; rerun check"
        elif not result.source_fingerprint:
            reason = "stored report has no source provenance; rerun check"
        elif (
            check_context.project_fingerprint(
                project,
                session_name=config.isabelle_session,
                isabelle_executable=config.isabelle_executable,
                extra_dirs=config.isabelle_dirs,
                project_root=config.project_root,
                timeout=config.isabelle_timeout,
            )
            != result.source_fingerprint
        ):
            reason = "stored report source context changed or is unverifiable; rerun check"
        stored_timestamp = report_data.get("timestamp")
        if not isinstance(stored_timestamp, str):
            stored_timestamp = None
            reason = reason or "stored report timestamp is unavailable; rerun check"
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
            if reason is not None or not node_current:
                stale_nodes.append(
                    (node, matched, reason or "stored report node inputs changed; rerun check")
                )
        apply_check_report(project, result)
        for node, matched, message in stale_nodes:
            node.status.formal = FormalStatus.STALE if matched else FormalStatus.NAMED
            node.status.last_checked = stored_timestamp if matched else None
            node.status.check_error = message
        project.recompute_agent_status()
    except (BlueprintError, TypeError, ValueError):
        return


def _well_formed_check_report(result: CheckResult) -> bool:
    """Reject malformed persisted evidence before it can promote any status."""
    if any(
        type(value) is not bool
        for value in (
            result.ran,
            result.isabelle_available,
            result.proof_checked,
            result.source_context_changed,
        )
    ):
        return False
    if not isinstance(result.timestamp, str) or (
        result.error is not None and not isinstance(result.error, str)
    ):
        return False
    if result.ran and type(result.return_code) is not int:
        return False
    if result.source_fingerprint is not None and not _is_fingerprint(result.source_fingerprint):
        return False
    if not isinstance(result.node_fingerprints, dict) or any(
        not isinstance(key, str) or not _is_fingerprint(value)
        for key, value in result.node_fingerprints.items()
    ):
        return False
    seen: dict[tuple[str, str, str | None], FactCheck] = {}
    for fact in result.facts:
        if (
            not isinstance(fact.node_id, str)
            or not fact.node_id
            or not isinstance(fact.fact, str)
            or not fact.fact
            or (fact.theory is not None and not isinstance(fact.theory, str))
            or type(fact.exists) is not bool
            or (fact.error is not None and not isinstance(fact.error, str))
            or (fact.exists and fact.error is not None)
            or (not fact.exists and fact.proof_status is not None)
            or (fact.proof_status is not None and not isinstance(fact.proof_status, str))
            or fact.proof_status not in {None, "proved", "tainted"}
            or not isinstance(fact.oracles, list)
            or any(not isinstance(oracle, str) for oracle in fact.oracles)
        ):
            return False
        key = (fact.node_id, fact.fact, fact.theory)
        if key in seen and seen[key] != fact:
            return False
        seen[key] = fact
    return True


def _is_fingerprint(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_project_with_check(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    """Load a project and fold in the latest stored check report."""

    config, project = load_project(project_dir)
    apply_stored_check_report(project, config)
    return config, project
