"""Run the Isabelle checker.

This module is tolerant of a missing ``isabelle`` binary: it always produces a
``check_report.json`` describing what happened, even when no actual build was
attempted. That keeps the rest of the pipeline (graph colouring, web site, agent
task generation) functional in dev environments without Isabelle installed.
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

from isabelle_blueprint.errors import CheckerError
from isabelle_blueprint.isabelle import check_cache
from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.theory_gen import (
    generate_check_root,
    generate_check_theory,
    group_facts_by_theory,
)
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


class _ProofMarker(TypedDict):
    """Per-fact proof outcome parsed from the checker's status output."""

    status: str
    oracles: list[str]


@dataclass
class FactCheck:
    node_id: str
    fact: str
    theory: str | None
    exists: bool
    error: str | None = None
    proof_status: str | None = None
    oracles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.oracles is None:
            self.oracles = []

    @property
    def tainted(self) -> bool:
        return self.proof_status == "tainted" or bool(self.oracles)


@dataclass
class CheckResult:
    """Outcome of running the Isabelle checker."""

    ran: bool
    invoked_command: list[str] = field(default_factory=list)
    isabelle_available: bool = False
    return_code: int | None = None
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    facts: list[FactCheck] = field(default_factory=list)
    error: str | None = None
    generated_theory_path: str | None = None
    proof_checked: bool = False
    proof_status_path: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["facts"] = [asdict(f) for f in self.facts]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CheckResult:
        """Reconstruct a :class:`CheckResult` from a previously-serialised dict.

        Unknown fields in *data* are ignored; missing fields fall back to
        dataclass defaults. This makes the round-trip resilient as new fields
        are added.
        """
        from dataclasses import fields as dc_fields

        known = {f.name for f in dc_fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "facts"}
        facts_raw = data.get("facts") or []
        fact_known = {f.name for f in dc_fields(FactCheck)}
        facts = [
            FactCheck(**{k: v for k, v in fc.items() if k in fact_known})
            for fc in facts_raw
        ]
        result = cls(**kwargs)
        result.facts = facts
        return result


# ---------------------------------------------------------------------------
# Pattern to recognise unresolved @{thm ...} errors.
# Examples from Isabelle stderr:
#   *** Undefined fact: "Foo.bar"
#   *** Bad fact "Foo.bar"
# ---------------------------------------------------------------------------
_FACT_ERROR_PATTERNS = [
    re.compile(r'Undefined fact:\s*"?([^"\n]+)"?', re.IGNORECASE),
    re.compile(r'Bad fact\s*"?([^"\n]+)"?', re.IGNORECASE),
    re.compile(r'Unknown fact\s*"?([^"\n]+)"?', re.IGNORECASE),
]

_PROOF_STATUS_PREFIX = "ISABELLE_BLUEPRINT_FACT\t"


def write_report(result: CheckResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def apply_check_report(project: BlueprintProject, result: CheckResult) -> None:
    """Update each node's ``status.formal`` based on the check report.

    When the checker did not actually run (no Isabelle on PATH, no session
    configured, or invocation failed), every node with a declared fact name is
    set to :attr:`FormalStatus.NAMED` — the user claimed a fact name but we
    have not yet *confirmed* the fact exists in any session. Only an actual
    successful build flips a node to :attr:`FormalStatus.FOUND`, and only a
    failed build that explicitly named the fact flips a node to
    :attr:`FormalStatus.NOT_FOUND`.
    """
    by_fact = {fc.fact: fc for fc in result.facts}
    for node in project.nodes:
        fact = node.isabelle.fact
        if not fact:
            node.status.formal = FormalStatus.MISSING
            continue
        node.status.last_checked = result.timestamp
        if not result.ran:
            # We never actually invoked the build; treat all named facts as
            # claimed-but-unverified regardless of any default record content.
            node.status.formal = FormalStatus.NAMED
            node.status.check_error = result.error
            continue
        record = by_fact.get(fact)
        if record is None:
            node.status.formal = FormalStatus.NAMED
            node.status.check_error = result.error
            continue
        if record.exists:
            if record.tainted:
                node.status.formal = FormalStatus.TAINTED
                oracle_text = (
                    ", ".join(record.oracles) if record.oracles else "detected theorem oracle"
                )
                node.status.check_error = f"fact depends on {oracle_text}"
            elif result.proof_checked and record.proof_status == "proved":
                node.status.formal = FormalStatus.PROVED
                node.status.check_error = None
            else:
                node.status.formal = FormalStatus.FOUND
                node.status.check_error = None
        else:
            node.status.formal = FormalStatus.NOT_FOUND
            node.status.check_error = record.error
    project.recompute_agent_status()


def run_check(
    project: BlueprintProject,
    *,
    build_dir: Path,
    session_name: str | None = None,
    isabelle_executable: str = "isabelle",
    extra_dirs: list[Path] | None = None,
    project_root: Path | None = None,
    write_theory: bool = True,
    proof_status: bool = True,
    timeout: float | None = None,
    incremental: bool = False,
    cache_path: Path | None = None,
    jobs: int | None = None,
) -> CheckResult:
    """Generate the check theory and (optionally) run ``isabelle build``.

    If ``session_name`` is ``None`` or the Isabelle binary is unavailable, we
    skip the build step and return a report describing the situation without
    raising. Each fact's per-node status is set to ``NAMED`` in that case.

    When ``incremental`` is true and ``cache_path`` is provided, nodes whose
    inputs and context hash match a previously-proved cache entry are
    short-circuited: they are surfaced as already-proved ``FactCheck`` records
    without being included in the generated wrapper theory, and ``isabelle
    build`` is invoked on only the remaining subset. If every node is a cache
    hit, the build step is skipped entirely.

    ``jobs`` is forwarded as ``isabelle build -j N`` to control parallelism
    across upstream session builds. Values <= 0 are ignored.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    proof_status_path = build_dir / "Blueprint_Proof_Status.tsv"
    check_timestamp = datetime.now(UTC).isoformat()

    # === Incremental cache: partition nodes into cache_hits vs to_check ===
    use_cache = bool(incremental and cache_path is not None)
    cache_entries: dict[str, dict] = {}
    node_hashes: dict[str, str] = {}
    cached_hits: dict[str, FactCheck] = {}
    if use_cache and cache_path is not None:
        cache_entries = check_cache.load_cache(cache_path)
        context_fingerprint = check_cache.compute_context_fingerprint(
            session_name=session_name,
            isabelle_executable=isabelle_executable,
            extra_dirs=extra_dirs,
            project_root=project_root,
            proof_status=proof_status,
        )
        for node in project.nodes:
            if not node.isabelle.fact:
                continue
            h = check_cache.compute_node_hash(node, context=context_fingerprint)
            node_hashes[node.id] = h
            entry = cache_entries.get(node.id)
            if entry is None or entry.get("hash") != h:
                continue
            fc_dict = check_cache.reusable_entry(entry, proof_status_required=proof_status)
            if fc_dict is None:
                continue
            cached_hits[node.id] = FactCheck(
                node_id=fc_dict["node_id"],
                fact=fc_dict["fact"],
                theory=fc_dict.get("theory"),
                exists=True,
                error=None,
                proof_status=fc_dict.get("proof_status"),
                oracles=list(fc_dict.get("oracles") or []),
            )

    # Set of node ids that still need verification: all nodes with a fact ref,
    # minus the cache hits.
    facts_node_ids = {n.id for n in project.nodes if n.isabelle.fact}
    to_check_ids = facts_node_ids - cached_hits.keys()
    include_filter: set[str] | None = to_check_ids if use_cache else None

    theory_text = generate_check_theory(
        project,
        emit_proof_status=proof_status,
        default_import_session=session_name,
        proof_status_file=proof_status_path.name,
        generation_nonce=(
            check_timestamp if proof_status and not proof_status_path.exists() else None
        ),
        include_node_ids=include_filter,
    )
    theory_path = build_dir / "Blueprint_Check.thy"
    if write_theory:
        theory_path.write_text(theory_text, encoding="utf-8")

    grouped = group_facts_by_theory(project, include_node_ids=include_filter)
    references = [
        FactCheck(node_id=ref.node_id, fact=ref.fact, theory=ref.theory, exists=False)
        for theory_refs in grouped.values()
        for ref in theory_refs
    ]

    resolved_isabelle = shutil.which(isabelle_executable)
    isabelle_available = resolved_isabelle is not None
    result = CheckResult(
        ran=False,
        isabelle_available=isabelle_available,
        generated_theory_path=str(theory_path),
        proof_status_path=str(proof_status_path),
        facts=references,
    )

    # Fast path: every reference is a cache hit, so don't invoke isabelle.
    # Persist the cache (dropping entries for any nodes that have since been
    # deleted from the blueprint) and return immediately. We still mark
    # ``ran=True`` and ``proof_checked`` so that ``apply_check_report`` will
    # honour the cached proof statuses rather than knock everything down to
    # NAMED.
    if use_cache and cached_hits and not to_check_ids and cache_path is not None:
        result.ran = True
        result.return_code = 0
        result.proof_checked = bool(proof_status)
        result.facts = list(cached_hits.values())
        retained = {nid: cache_entries[nid] for nid in cached_hits if nid in cache_entries}
        try:
            check_cache.save_cache(cache_path, retained)
        except OSError:
            pass
        return result

    if not isabelle_available:
        result.error = (
            f"Isabelle executable {isabelle_executable!r} not found on PATH; "
            "skipped build. Fact-existence is assumed unverified."
        )
        _merge_cache_hits_into(result, cached_hits)
        return result

    if session_name is None:
        result.error = (
            "No Isabelle session configured (set [isabelle].session in "
            "isabelle-blueprint.toml); skipped build."
        )
        _merge_cache_hits_into(result, cached_hits)
        return result

    # Drop a small ROOT alongside the generated theory so ``isabelle build``
    # can resolve a wrapper session that inherits from the user's session and
    # adds the Blueprint_Check theory. Without this, ``-d .`` finds nothing
    # buildable (the user's ROOT lives in project_root, not build_dir), the
    # build trivially fails, and every fact is silently flipped to NOT_FOUND.
    wrapper_session = "Blueprint_Check_Wrapper"
    session_deps = sorted(
        {
            ref.session
            for theory_refs in grouped.values()
            for ref in theory_refs
            if ref.session and ref.session != session_name
        }
    )
    (build_dir / "ROOT").write_text(
        generate_check_root(session_name, wrapper_name=wrapper_session, session_deps=session_deps),
        encoding="utf-8",
    )

    cmd = [resolved_isabelle or isabelle_executable, "build", "-d", str(build_dir)]
    if project_root is not None:
        cmd.extend(["-d", str(project_root)])
    for d in extra_dirs or []:
        cmd.extend(["-d", str(d)])
    if jobs is not None and jobs > 0:
        cmd.extend(["-j", str(jobs)])
    cmd.append(wrapper_session)
    result.invoked_command = cmd

    start = time.monotonic()
    try:
        proc = run_capture(
            cmd,
            cwd=str(build_dir),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # The build did not finish within the configured budget. Treat this as
        # "verification did not complete" (ran stays False) so facts remain
        # NAMED/unverified rather than being flipped to NOT_FOUND.
        result.error = (
            f"isabelle build timed out after {timeout:.0f}s; "
            "increase [isabelle].timeout in isabelle-blueprint.toml or pass --timeout"
        )
        _merge_cache_hits_into(result, cached_hits)
        return result
    except OSError as exc:
        # Binary resolved on PATH but couldn't actually be launched (stale
        # shim, broken symlink, permission error, etc.). From the pipeline's
        # point of view that's the same as "not available".
        result.error = f"failed to invoke {isabelle_executable!r}: {exc}"
        result.isabelle_available = False
        _merge_cache_hits_into(result, cached_hits)
        return result
    finally:
        result.duration_seconds = time.monotonic() - start

    result.ran = True
    result.return_code = proc.returncode
    result.stdout = proc.stdout
    result.stderr = proc.stderr

    proof_status_text = ""
    if proof_status_path.exists():
        proof_status_text = proof_status_path.read_text(encoding="utf-8", errors="ignore")
    proof_markers = _extract_proof_status(
        proc.stdout + "\n" + proc.stderr + "\n" + proof_status_text
    )
    bad_facts = _extract_bad_facts(proc.stderr + "\n" + proc.stdout)
    if proc.returncode == 0:
        for fc in result.facts:
            fc.exists = True
            marker = proof_markers.get((fc.node_id, fc.fact))
            if marker is not None:
                fc.proof_status = marker["status"]
                fc.oracles = marker["oracles"]
        result.proof_checked = bool(proof_markers)
    else:
        for fc in result.facts:
            if fc.fact in bad_facts:
                fc.exists = False
                fc.error = bad_facts[fc.fact]
            else:
                # If the build failed but this particular fact wasn't named in
                # the error, we can't tell whether it existed. Mark unknown.
                fc.exists = False
                fc.error = "build failed; existence unknown"
        if not bad_facts:
            result.error = (
                f"isabelle build returned {proc.returncode} with no recognised fact errors"
            )

    # Splice cache hits back into result.facts so the report covers every node.
    # Cache hits carry proof_status="proved" by construction, so even if the
    # current build returned 0 facts (everything was cached or the wrapper was
    # empty), we still want proof_checked=True when proof status was requested.
    if cached_hits:
        _merge_cache_hits_into(result, cached_hits)
        if proof_status:
            result.proof_checked = True

    # Persist the updated cache: keep the cache hits as-is and refresh entries
    # for newly-verified facts. Skip anything that wasn't conclusively proved.
    if use_cache and cache_path is not None:
        new_cache: dict[str, dict] = {}
        for nid in cached_hits:
            if nid in cache_entries:
                new_cache[nid] = cache_entries[nid]
        for fc in result.facts:
            if fc.node_id in cached_hits:
                continue
            if not fc.exists or fc.error:
                continue
            if fc.tainted:
                continue
            if proof_status and fc.proof_status != "proved":
                continue
            cached_hash = node_hashes.get(fc.node_id)
            if not cached_hash:
                continue
            new_cache[fc.node_id] = check_cache.record_entry(asdict(fc), node_hash=cached_hash)
        try:
            check_cache.save_cache(cache_path, new_cache)
        except OSError:
            # Cache persistence is best-effort: a write failure must never
            # break a check run.
            pass

    return result


def _merge_cache_hits_into(result: CheckResult, cached_hits: dict[str, FactCheck]) -> None:
    """Append cache-hit fact checks to ``result.facts``, skipping duplicates."""
    if not cached_hits:
        return
    existing = {fc.node_id for fc in result.facts}
    for nid, fc in cached_hits.items():
        if nid not in existing:
            result.facts.append(fc)


def _extract_bad_facts(stderr_text: str) -> dict[str, str]:
    bad: dict[str, str] = {}
    for line in stderr_text.splitlines():
        for pattern in _FACT_ERROR_PATTERNS:
            m = pattern.search(line)
            if m:
                name = m.group(1).strip()
                bad[name] = line.strip()
                break
    return bad


def _extract_proof_status(output_text: str) -> dict[tuple[str, str], _ProofMarker]:
    statuses: dict[tuple[str, str], _ProofMarker] = {}
    for line in output_text.splitlines():
        if _PROOF_STATUS_PREFIX not in line:
            continue
        _, payload = line.split(_PROOF_STATUS_PREFIX, 1)
        parts = payload.split("\t")
        if len(parts) < 4:
            continue
        node_id, fact, status, oracle_text = parts[:4]
        oracles = [] if oracle_text in {"", "-"} else [o for o in oracle_text.split(",") if o]
        statuses[(node_id, fact)] = {"status": status, "oracles": oracles}
    return statuses


# Re-export for convenience.
__all__ = [
    "CheckResult",
    "FactCheck",
    "CheckerError",
    "apply_check_report",
    "_extract_proof_status",
    "run_check",
    "write_report",
]
