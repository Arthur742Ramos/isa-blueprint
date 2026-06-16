"""SARIF 2.1.0 rendering for lint findings.

SARIF (Static Analysis Results Interchange Format) lets ``isabelle-blueprint
lint`` surface findings in GitHub code scanning and other SARIF-aware tools.

The conversion is intentionally dependency-free: it builds plain dictionaries
matching the SARIF 2.1.0 object model.  When a finding's node carries source
information (``source_file`` / ``source_line``) the result gets a physical
``location`` so code scanning can annotate the exact blueprint line; otherwise
it falls back to a ``logicalLocation`` keyed by the node id.
"""
from __future__ import annotations

import hashlib
import json

from isabelle_blueprint import __version__
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.lint import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    LintReport,
)

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Arthur742Ramos/isa-blueprint"

# SARIF result levels: error/warning/note (note is SARIF's "informational").
_LEVEL_BY_SEVERITY = {
    SEVERITY_ERROR: "error",
    SEVERITY_WARNING: "warning",
    SEVERITY_INFO: "note",
}

# Stable, human-readable descriptions per lint code for the SARIF rule table.
_RULE_DESCRIPTIONS = {
    "duplicate-id": "A node id is declared more than once.",
    "missing-dependency": "A node depends on an undefined node id.",
    "cycle": "The dependency graph contains a cycle.",
    "self-dependency": "A node lists its own id as a dependency.",
    "broken-formal-status": "A node's formal status indicates active breakage.",
    "stale-formal-status": "A node's proof is stale and should be re-checked.",
    "empty-statement": "A node has no statement text.",
    "missing-informal-proof": "A proof-bearing node has no informal proof sketch.",
    "no-isabelle-fact": "A node has no Isabelle fact assigned yet.",
    "isolated-node": "A node has no dependencies and nothing depends on it.",
    "duplicate-title": "Two or more nodes share an identical title.",
    "duplicate-fact": "Two or more nodes reference the same Isabelle fact.",
    "singleton-tag": "A tag is used by exactly one node.",
    "tag-case-collision": "Tags differ only by case, fragmenting the tag rollup.",
    "missing-effort": "An unproved top-level goal has no effort estimate.",
}


def build_sarif(report: LintReport, project: BlueprintProject | None = None) -> dict[str, object]:
    """Return a SARIF 2.1.0 log document for ``report``.

    ``project`` is optional but, when provided, lets findings reference the
    blueprint source file and line of the offending node.
    """

    source_index = _source_index(project)

    rules = [_rule(code) for code in sorted({f.code for f in report.findings})]
    results = [_result(finding, source_index) for finding in report.findings]

    return {
        "version": SARIF_VERSION,
        "$schema": SARIF_SCHEMA,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "isabelle-blueprint",
                        "informationUri": INFORMATION_URI,
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def render_sarif(report: LintReport, project: BlueprintProject | None = None) -> str:
    """Render ``report`` as a SARIF JSON string (trailing newline)."""

    return json.dumps(build_sarif(report, project), indent=2) + "\n"


def _source_index(project: BlueprintProject | None) -> dict[str, tuple[str | None, int | None]]:
    if project is None:
        return {}
    return {node.id: (node.source_file, node.source_line) for node in project.nodes}


def _rule(code: str) -> dict[str, object]:
    return {
        "id": code,
        "name": code,
        "shortDescription": {"text": _RULE_DESCRIPTIONS.get(code, code)},
    }


def _result(
    finding,
    source_index: dict[str, tuple[str | None, int | None]],
) -> dict[str, object]:
    result: dict[str, object] = {
        "ruleId": finding.code,
        "level": _LEVEL_BY_SEVERITY.get(finding.severity, "note"),
        "message": {"text": finding.message},
        "partialFingerprints": {"isabelleBlueprint/v1": _fingerprint(finding)},
    }
    location = _location(finding, source_index)
    if location is not None:
        result["locations"] = [location]
    return result


def _location(
    finding,
    source_index: dict[str, tuple[str | None, int | None]],
) -> dict[str, object] | None:
    if finding.node_id is None:
        return None
    location: dict[str, object] = {
        "logicalLocations": [
            {"name": finding.node_id, "fullyQualifiedName": finding.node_id, "kind": "member"}
        ]
    }
    source_file, source_line = source_index.get(finding.node_id, (None, None))
    if source_file:
        physical: dict[str, object] = {"artifactLocation": {"uri": _uri(source_file)}}
        if source_line and source_line > 0:
            physical["region"] = {"startLine": source_line}
        location["physicalLocation"] = physical
    return location


def _uri(source_file: str) -> str:
    return source_file.replace("\\", "/")


def _fingerprint(finding) -> str:
    payload = f"{finding.code}\n{finding.node_id or ''}\n{finding.message}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
