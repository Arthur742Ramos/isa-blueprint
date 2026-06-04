"""Inspect Isabelle PIDE dump output for blueprint facts.

``isabelle dump`` writes cumulative theory content in a compact YXML-ish text
format. We only need a narrow slice here: entity names in theory fact/thm files
and oracle markers that identify skipped proofs or other trusted-code
dependencies.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

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
    result = DumpResult(
        ran=False, isabelle_available=isabelle_available, inspected_dir=str(output_dir)
    )
    if not isabelle_available:
        result.error = f"Isabelle executable {isabelle_executable!r} not found on PATH"
        return _with_reference_facts(result, project)
    if session_name is None:
        result.error = "No Isabelle session configured; cannot run PIDE dump"
        return _with_reference_facts(result, project)

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [resolved_isabelle or isabelle_executable, "dump", "-A", aspects, "-O", str(output_dir)]
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
    inspected = inspect_dump_dir(project, output_dir, ran=True)
    inspected.invoked_command = result.invoked_command
    inspected.isabelle_available = result.isabelle_available
    inspected.return_code = result.return_code
    inspected.duration_seconds = result.duration_seconds
    inspected.stdout = result.stdout
    inspected.stderr = result.stderr
    return inspected


def inspect_dump_dir(project: BlueprintProject, dump_dir: Path, *, ran: bool = False) -> DumpResult:
    """Inspect an existing ``isabelle dump`` output directory."""
    dump_dir = dump_dir.resolve()
    result = DumpResult(ran=ran, inspected_dir=str(dump_dir), isabelle_available=ran)
    if not dump_dir.exists():
        result.error = f"dump directory does not exist: {dump_dir}"
        return _with_reference_facts(result, project)

    fact_index = _read_fact_index(dump_dir)
    for node in project.nodes:
        fact = node.isabelle.fact
        if not fact:
            result.facts.append(DumpFact(node.id, "", node.isabelle.theory, exists=False))
            continue
        entry = fact_index.get(fact)
        if entry is None:
            result.facts.append(
                DumpFact(
                    node.id,
                    fact,
                    node.isabelle.theory,
                    exists=False,
                    proof_status="not_found",
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
                proof_status="tainted" if oracles else "proved",
                oracles=oracles,
                source=entry["source"],
            )
        )
    return result


def apply_dump_report(project: BlueprintProject, result: DumpResult) -> None:
    """Update node formal statuses from a PIDE dump report."""
    if result.error:
        for node in project.nodes:
            if node.isabelle.fact:
                node.status.last_checked = result.timestamp
                node.status.check_error = result.error
        project.recompute_agent_status()
        return

    by_fact = {fact.fact: fact for fact in result.facts if fact.fact}
    for node in project.nodes:
        fact = node.isabelle.fact
        if not fact:
            node.status.formal = FormalStatus.MISSING
            continue
        node.status.last_checked = result.timestamp
        record = by_fact.get(fact)
        if record is None:
            node.status.formal = FormalStatus.NAMED
            node.status.check_error = result.error
        elif not record.exists:
            node.status.formal = FormalStatus.NOT_FOUND
            node.status.check_error = "fact not present in PIDE dump"
        elif record.oracles:
            node.status.formal = FormalStatus.TAINTED
            node.status.check_error = "fact depends on " + ", ".join(record.oracles)
        else:
            node.status.formal = FormalStatus.PROVED
            node.status.check_error = None
    project.recompute_agent_status()


def _with_reference_facts(result: DumpResult, project: BlueprintProject) -> DumpResult:
    result.facts = [
        DumpFact(node.id, node.isabelle.fact or "", node.isabelle.theory, exists=False)
        for node in project.nodes
        if node.isabelle.fact
    ]
    return result


def _read_fact_index(dump_dir: Path) -> dict[str, _FactEntry]:
    index: dict[str, _FactEntry] = {}
    for path in dump_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name not in {"thms", "fact"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
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
        match.group("value")
        for match in _ATTR_RE.finditer(record)
        if match.group("key") == "name"
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
    "run_dump",
    "write_dump_report",
]
