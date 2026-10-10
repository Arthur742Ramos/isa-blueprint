"""Inspect Isabelle PIDE dump output for blueprint facts.

``isabelle dump`` writes cumulative theory content in a compact YXML-ish text
format. We only need a narrow slice here: entity names in theory fact/thm files
and oracle markers that identify skipped proofs or other trusted-code
dependencies. These observations cannot establish current proof trust: generated
dumps delegate proof classification to the native checker.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from isabelle_blueprint.isabelle import check_cache, check_context, checker
from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


class _FactEntry(TypedDict):
    """Aggregated PIDE-dump metadata for a single fact name."""

    oracles: set[str]
    source: str


@dataclass
class DumpFact:
    node_id: str
    fact: str
    theory: str | None
    exists: bool
    proof_status: str | None = None
    oracles: list[str] = field(default_factory=list)
    source: str | None = None
    session: str | None = None
    observed_in_dump: bool | None = None


@dataclass
class DumpResult:
    ran: bool
    inspected_dir: str | None = None
    invoked_command: list[str] = field(default_factory=list)
    isabelle_available: bool = False
    return_code: int | None = None
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    facts: list[DumpFact] = field(default_factory=list)
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    verification: dict | None = None
    proof_metadata_complete: bool = False
    evidence_reason: str | None = None
    previous_checked: dict[str, str | None] = field(default_factory=dict)
    previous_statuses: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.return_code in {None, 0}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["facts"] = [asdict(f) for f in self.facts]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> DumpResult:
        from dataclasses import fields as dc_fields

        known = {f.name for f in dc_fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "facts"}
        fact_known = {f.name for f in dc_fields(DumpFact)}
        facts = [
            DumpFact(**{k: v for k, v in raw.items() if k in fact_known})
            for raw in data.get("facts", [])
        ]
        result = cls(**kwargs)
        result.facts = facts
        return result


def parse_dump_report(data: object) -> DumpResult | None:
    """Reject malformed or conflicting observations before restoring evidence."""
    if not isinstance(data, dict) or not isinstance(data.get("facts", []), list):
        return None
    if any(not isinstance(fact, dict) for fact in data.get("facts", [])):
        return None
    try:
        result = DumpResult.from_dict(data)
    except (TypeError, ValueError):
        return None
    if any(
        type(value) is not bool
        for value in (result.ran, result.isabelle_available, result.proof_metadata_complete)
    ) or (result.ran and type(result.return_code) is not int):
        return None
    if not isinstance(result.timestamp, str) or any(
        value is not None and not isinstance(value, str)
        for value in (result.error, result.evidence_reason)
    ):
        return None
    for history in (result.previous_checked, result.previous_statuses):
        if not isinstance(history, dict) or any(
            not isinstance(key, str) or (value is not None and not isinstance(value, str))
            for key, value in history.items()
        ):
            return None
    if result.verification is not None and checker.parse_check_report(result.verification) is None:
        return None
    seen: dict[tuple[str, str, str | None, str | None], DumpFact] = {}
    for fact in result.facts:
        if (
            not isinstance(fact.node_id, str)
            or not isinstance(fact.fact, str)
            or type(fact.exists) is not bool
            or any(
                value is not None and not isinstance(value, str)
                for value in (fact.theory, fact.session, fact.proof_status, fact.source)
            )
            or fact.proof_status not in {None, "proved", "tainted"}
            or (fact.observed_in_dump is not None and type(fact.observed_in_dump) is not bool)
            or not isinstance(fact.oracles, list)
            or any(not isinstance(oracle, str) for oracle in fact.oracles)
        ):
            return None
        key = (fact.node_id, fact.fact, fact.theory, fact.session)
        if key in seen and seen[key] != fact:
            return None
        seen[key] = fact
    return result


_ENTITY_RE = re.compile(r"(?:^|[\x05\x06])entity\x06(?P<attrs>[^\x05]+)")
_ATTR_RE = re.compile(r"(?P<key>[A-Za-z_][\w-]*)=(?P<value>[^\x06]+)")
_SKIP_PROOF_NAMES = {"Pure.skip_proof", "skip_proof"}


def write_dump_report(result: DumpResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path


def run_dump(
    project: BlueprintProject,
    *,
    output_dir: Path,
    session_name: str | None,
    isabelle_executable: str = "isabelle",
    project_root: Path | None = None,
    extra_dirs: list[Path] | None = None,
    aspects: str = "theory",
    timeout: float | None = None,
) -> DumpResult:
    """Run ``isabelle dump`` and inspect the generated dump directory."""
    resolved_isabelle = shutil.which(isabelle_executable)
    isabelle_available = resolved_isabelle is not None
    result = _new_result(
        project, ran=False, isabelle_available=isabelle_available, inspected_dir=str(output_dir)
    )
    if not isabelle_available:
        result.error = f"Isabelle executable {isabelle_executable!r} not found on PATH"
        return _with_reference_facts(result, project)
    if session_name is None:
        result.error = "No Isabelle session configured; cannot run PIDE dump"
        return _with_reference_facts(result, project)

    initial_context = check_context.project_fingerprint(
        project,
        session_name=session_name,
        isabelle_executable=isabelle_executable,
        project_root=project_root,
        extra_dirs=extra_dirs,
        timeout=timeout,
    )
    # Never inspect a previous run or delete an imported/user-owned dump tree.
    fresh_dir = output_dir / ("run-" + uuid.uuid4().hex)
    try:
        fresh_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        result.error = f"cannot create fresh dump directory: {exc}"
        return _with_reference_facts(result, project)
    result.inspected_dir = str(fresh_dir)
    cmd = [resolved_isabelle or isabelle_executable, "dump", "-A", aspects, "-O", str(fresh_dir)]
    if project_root is not None:
        cmd.extend(["-D", str(project_root)])
    for d in extra_dirs or []:
        cmd.extend(["-d", str(d)])
    cmd.append(session_name)
    result.invoked_command = cmd

    start = time.monotonic()
    try:
        proc = run_capture(
            cmd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result.error = (
            f"isabelle dump timed out after {timeout:.0f}s; "
            "increase [isabelle].timeout in isabelle-blueprint.toml or pass --timeout"
        )
        return _with_reference_facts(result, project)
    except OSError as exc:
        result.error = f"failed to invoke {isabelle_executable!r}: {exc}"
        result.isabelle_available = False
        return _with_reference_facts(result, project)
    finally:
        result.duration_seconds = time.monotonic() - start

    result.ran = True
    result.return_code = proc.returncode
    result.stdout = proc.stdout
    result.stderr = proc.stderr
    if proc.returncode != 0:
        result.error = f"isabelle dump returned {proc.returncode}"
        return _with_reference_facts(result, project)
    inspected = inspect_dump_dir(
        project, fresh_dir, ran=True, isabelle_executable=isabelle_executable
    )
    inspected.invoked_command = result.invoked_command
    inspected.isabelle_available = result.isabelle_available
    inspected.return_code = result.return_code
    inspected.duration_seconds = result.duration_seconds
    inspected.stdout = result.stdout
    inspected.stderr = result.stderr
    inspected.timestamp = result.timestamp
    if not any(fact.observed_in_dump for fact in inspected.facts):
        inspected.evidence_reason = (
            "fresh dump contains no matching theorem observations; run check"
        )
        return inspected
    verified = checker.run_check(
        project,
        build_dir=fresh_dir / "_verification",
        session_name=session_name,
        isabelle_executable=isabelle_executable,
        project_root=project_root,
        extra_dirs=extra_dirs,
        timeout=timeout,
        proof_status=True,
    )
    if initial_context is None or verified.source_fingerprint != initial_context:
        verified.source_context_changed = True
        verified.source_fingerprint = None
        verified.node_fingerprints = {}
        verified.proof_checked = False
        verified.error = "dump source context changed or is unverifiable; rerun check"
        for checked in verified.facts:
            checked.exists = False
            checked.proof_status = None
            checked.oracles = []
            checked.error = verified.error
    inspected.verification = verified.to_dict()
    inspected.evidence_reason = verified.error
    inspected.proof_metadata_complete = bool(
        verified.ran
        and verified.return_code == 0
        and verified.source_fingerprint
        and verified.proof_checked
        and all(fact.proof_status in {"proved", "tainted"} for fact in verified.facts)
    )
    by_reference = {(fact.node_id, fact.fact, fact.theory): fact for fact in verified.facts}
    for fact in inspected.facts:
        record = by_reference.get((fact.node_id, fact.fact, fact.theory))
        if record is not None:
            fact.exists = record.exists
            fact.proof_status = record.proof_status
            fact.oracles = list(record.oracles)
    return inspected


def inspect_dump_dir(
    project: BlueprintProject,
    dump_dir: Path,
    *,
    ran: bool = False,
    isabelle_executable: str = "isabelle",
) -> DumpResult:
    """Inspect an existing ``isabelle dump`` output directory.

    ``isabelle_available`` reflects whether the Isabelle binary is resolvable on
    PATH and is independent of ``ran``: inspecting an existing dump directory
    offline should not be reported as "Isabelle unavailable" merely because this
    call did not launch an Isabelle process.
    """
    dump_dir = dump_dir.resolve()
    result = _new_result(
        project,
        ran=ran,
        inspected_dir=str(dump_dir),
        isabelle_available=shutil.which(isabelle_executable) is not None,
    )
    if not dump_dir.exists():
        result.error = f"dump directory does not exist: {dump_dir}"
        return _with_reference_facts(result, project)
    if not dump_dir.is_dir():
        result.error = f"dump path is not a directory: {dump_dir}"
        return _with_reference_facts(result, project)

    try:
        fact_index = _read_fact_index(dump_dir)
    except (OSError, UnicodeError) as exc:
        result.error = f"cannot read dump observations: {exc}"
        return _with_reference_facts(result, project)
    result.evidence_reason = (
        "dump observations have no current native proof evidence; run isabelle-blueprint check"
    )
    for node in project.nodes:
        fact = node.isabelle.fact
        if not fact:
            result.facts.append(
                DumpFact(
                    node.id,
                    "",
                    node.isabelle.theory,
                    exists=False,
                    session=node.isabelle.session,
                    observed_in_dump=False,
                )
            )
            continue
        entry = fact_index.get(fact)
        if entry is None:
            result.facts.append(
                DumpFact(
                    node.id,
                    fact,
                    node.isabelle.theory,
                    exists=False,
                    session=node.isabelle.session,
                    observed_in_dump=False,
                )
            )
            continue
        oracles = sorted(entry["oracles"])
        result.facts.append(
            DumpFact(
                node.id,
                fact,
                node.isabelle.theory,
                exists=True,
                proof_status="tainted" if oracles else None,
                oracles=oracles,
                source=entry["source"],
                session=node.isabelle.session,
                observed_in_dump=True,
            )
        )
    return result


def apply_dump_report(project: BlueprintProject, result: DumpResult) -> None:
    """Apply only native verification as current evidence; retain raw observations."""
    verified = checker.parse_check_report(result.verification)
    if result.ran and result.return_code == 0 and not result.error and verified is not None:
        checker.apply_check_report(project, verified)
        by_reference = {(fact.node_id, fact.fact, fact.theory): fact for fact in verified.facts}
        for node in project.nodes:
            if not node.isabelle.fact:
                continue
            matched = (node.id, node.isabelle.fact, node.isabelle.theory) in by_reference
            current = verified.source_fingerprint and (
                verified.node_fingerprints.get(node.id)
                == check_cache.compute_node_hash(node, context=verified.source_fingerprint)
            )
            if (
                verified.ran
                and not verified.source_context_changed
                and (not current or not matched)
            ):
                node.status.formal = FormalStatus.STALE if matched else FormalStatus.NAMED
                node.status.last_checked = None
                node.status.check_error = (
                    "dump verification inputs are unverifiable or changed; run check"
                )
            elif not verified.ran:
                node.status.last_checked = result.previous_checked.get(node.id)
        project.recompute_agent_status()
        return

    observations = {
        (fact.node_id, fact.fact, fact.theory, fact.session): fact
        for fact in result.facts
        if fact.fact
    }
    for node in project.nodes:
        fact = node.isabelle.fact
        previous_time = node.status.last_checked
        node.status.check_error = None
        if not fact:
            node.status.formal = FormalStatus.MISSING
            node.status.last_checked = None
            continue
        record = observations.get((node.id, fact, node.isabelle.theory, node.isabelle.session))
        historical = record is not None and (
            record.exists
            or result.previous_statuses.get(node.id) in {"proved", "found", "tainted", "stale"}
            or previous_time is not None
        )
        node.status.formal = FormalStatus.STALE if historical else FormalStatus.NAMED
        node.status.last_checked = (
            result.previous_checked.get(node.id, previous_time) if record is not None else None
        )
        node.status.check_error = (
            result.error
            or result.evidence_reason
            or ("dump has no current native proof evidence; run isabelle-blueprint check")
        )
    project.recompute_agent_status()


def _new_result(project: BlueprintProject, **kwargs) -> DumpResult:
    return DumpResult(
        **kwargs,
        previous_checked={node.id: node.status.last_checked for node in project.nodes},
        previous_statuses={node.id: node.status.formal.value for node in project.nodes},
    )


def _with_reference_facts(result: DumpResult, project: BlueprintProject) -> DumpResult:
    result.facts = [
        DumpFact(
            node.id,
            node.isabelle.fact or "",
            node.isabelle.theory,
            exists=False,
            session=node.isabelle.session,
            observed_in_dump=False,
        )
        for node in project.nodes
        if node.isabelle.fact
    ]
    return result


def _read_fact_index(dump_dir: Path) -> dict[str, _FactEntry]:
    index: dict[str, _FactEntry] = {}
    for path in sorted(dump_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name not in {"thms", "fact"}:
            continue
        text = path.read_text(encoding="utf-8")
        for attrs, record in _entity_records(text):
            name = attrs.get("name")
            if not name:
                continue
            entry = index.setdefault(name, {"oracles": set(), "source": str(path)})
            entry["oracles"].update(_oracles_in_record(record))
    return index


def _entity_records(text: str) -> list[tuple[dict[str, str], str]]:
    matches = list(_ENTITY_RE.finditer(text))
    records: list[tuple[dict[str, str], str]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        attrs = {m.group("key"): m.group("value") for m in _ATTR_RE.finditer(match.group("attrs"))}
        records.append((attrs, text[match.start() : end]))
    return records


def _oracles_in_record(record: str) -> set[str]:
    names = {
        match.group("value") for match in _ATTR_RE.finditer(record) if match.group("key") == "name"
    }
    taint = {name for name in names if name in _SKIP_PROOF_NAMES or name.endswith(".skip_proof")}
    if "Pure.skip_proof" in record:
        taint.add("Pure.skip_proof")
    elif "skip_proof" in record:
        taint.add("skip_proof")
    if "oracle" in record.lower() and not taint:
        taint.add("oracle")
    return taint


__all__ = [
    "DumpFact",
    "DumpResult",
    "apply_dump_report",
    "inspect_dump_dir",
    "parse_dump_report",
    "run_dump",
    "write_dump_report",
]
