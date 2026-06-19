"""Run Isabelle's Sledgehammer against a single blueprint node.

This mirrors :mod:`isabelle_blueprint.isabelle.checker`: it is tolerant of a
missing ``isabelle`` binary and never raises -- every failure mode is folded
into a :class:`SledgehammerResult` describing what happened.

The node's proof obligation comes from one of two sources:

* an explicit ``goal`` proposition on the node (parsed with ``Syntax.read_prop``
  in the generated wrapper), or
* the node's named Isabelle ``fact``, whose statement is re-proved from scratch.

Because batch ``isabelle build`` suppresses sledgehammer/``writeln`` stdout, the
generated theory writes a one-line TSV result to a file which we read back here
-- exactly the pattern the proof-status checker uses.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.theory_gen import (
    generate_check_root,
    generate_sledgehammer_theory,
    group_facts_by_theory,
)
from isabelle_blueprint.model.project import BlueprintProject

_DEFAULT_ML_TIMEOUT = 30.0
# Headroom for session startup / proof reconstruction on top of the sledgehammer
# budget before the build subprocess itself is force-killed.
_BUILD_TIMEOUT_MARGIN = 120.0

_THEORY_NAME = "Blueprint_Sledgehammer"
_WRAPPER_SESSION = "Blueprint_Sledgehammer_Wrapper"
_RESULT_FILE = "Blueprint_Sledgehammer.tsv"

# 'Try this: by simp (0.0 ms)' -> 'by simp'. The trailing timing annotation is
# optional so we tolerate a proof line that has been stripped of it.
_TRY_THIS_RE = re.compile(r"^Try this:\s*(.*?)\s*(?:\(\d[\d.]*\s*m?s\))?\s*$")
_TIMING_TAIL_RE = re.compile(r"\s*\(\d[\d.]*\s*m?s\)\s*$")


@dataclass
class SledgehammerResult:
    """Outcome of running Sledgehammer against one node."""

    ran: bool
    isabelle_available: bool = False
    return_code: int | None = None
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    node_id: str | None = None
    found: bool = False
    proof_line: str | None = None
    prover: str | None = None
    outcome_tag: str | None = None
    error: str | None = None
    generated_theory_path: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


def extract_proof(raw: str | None) -> str | None:
    """Clean a raw sledgehammer proof string into a bare Isar one-liner.

    ``'Try this: by simp (0.0 ms)'`` becomes ``'by simp'``. Empty/blank input
    returns ``None``. A missing ``Try this:`` prefix and/or missing timing
    annotation are both tolerated.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    m = _TRY_THIS_RE.match(text)
    if m:
        proof = m.group(1).strip()
        return proof or None
    text = _TIMING_TAIL_RE.sub("", text).strip()
    return text or None


def parse_sledgehammer_tsv(text: str) -> tuple[bool, str | None, str | None]:
    """Parse the result TSV written by the generated wrapper.

    Returns ``(found, outcome_tag, proof_line)``. The expected single line is
    ``"<SOME|NONE>\\t<outcome_tag>\\t<raw proof>"``; missing trailing columns are
    tolerated. ``found`` is ``True`` only when the first column is ``SOME``.
    """
    line = ""
    for candidate in (text or "").splitlines():
        if candidate.strip():
            line = candidate
            break
    if not line:
        return False, None, None
    parts = line.split("\t")
    found = parts[0].strip().upper() == "SOME"
    outcome_tag = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    proof_line = extract_proof(parts[2]) if len(parts) > 2 else None
    return found, outcome_tag, proof_line


def run_sledgehammer(
    project: BlueprintProject,
    *,
    node_id: str,
    build_dir: Path,
    session_name: str | None = None,
    isabelle_executable: str = "isabelle",
    extra_dirs: list[Path] | None = None,
    project_root: Path | None = None,
    timeout: float | None = None,
    jobs: int | None = None,
) -> SledgehammerResult:
    """Generate a one-node wrapper theory and run ``isabelle build`` on it.

    ``timeout`` is the Sledgehammer time budget (in seconds) embedded in the
    generated ML; the build subprocess is given that budget plus a fixed margin
    before it is force-killed. As with the checker, a missing ``isabelle`` binary
    or unconfigured session short-circuits to ``ran=False`` with an explanatory
    ``error`` rather than raising.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    result_path = build_dir / _RESULT_FILE
    # Stale result from a prior run would be misread as the current outcome.
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass

    ml_timeout = _DEFAULT_ML_TIMEOUT if timeout is None else float(timeout)
    theory_text = generate_sledgehammer_theory(
        project,
        node_id=node_id,
        result_file=result_path.name,
        timeout=ml_timeout,
        theory_name=_THEORY_NAME,
        default_import_session=session_name,
        nonce=f"{datetime.now(UTC).isoformat()}-{uuid.uuid4().hex}",
    )

    resolved_isabelle = shutil.which(isabelle_executable)
    isabelle_available = resolved_isabelle is not None
    result = SledgehammerResult(
        ran=False,
        isabelle_available=isabelle_available,
        node_id=node_id,
    )

    if theory_text is None:
        result.error = (
            f"node {node_id!r} has neither a 'goal' proposition nor a resolvable "
            "Isabelle fact to re-prove; nothing to attempt"
        )
        return result

    theory_path = build_dir / f"{_THEORY_NAME}.thy"
    theory_path.write_text(theory_text, encoding="utf-8")
    result.generated_theory_path = str(theory_path)

    if not isabelle_available:
        result.error = (
            f"Isabelle executable {isabelle_executable!r} not found on PATH; "
            "skipped sledgehammer run."
        )
        return result

    if session_name is None:
        result.error = (
            "No Isabelle session configured (set [isabelle].session in "
            "isabelle-blueprint.toml); skipped sledgehammer run."
        )
        return result

    grouped = group_facts_by_theory(project)
    session_deps = sorted(
        {
            ref.session
            for theory_refs in grouped.values()
            for ref in theory_refs
            if ref.session and ref.session != session_name
        }
    )
    (build_dir / "ROOT").write_text(
        generate_check_root(
            session_name,
            wrapper_name=_WRAPPER_SESSION,
            theory_name=_THEORY_NAME,
            session_deps=session_deps,
        ),
        encoding="utf-8",
    )

    cmd = [resolved_isabelle or isabelle_executable, "build", "-d", str(build_dir)]
    if project_root is not None:
        cmd.extend(["-d", str(project_root)])
    for d in extra_dirs or []:
        cmd.extend(["-d", str(d)])
    if jobs is not None and jobs > 0:
        cmd.extend(["-j", str(jobs)])
    cmd.append(_WRAPPER_SESSION)

    build_timeout = None if timeout is None else float(timeout) + _BUILD_TIMEOUT_MARGIN
    start = time.monotonic()
    try:
        proc = run_capture(cmd, cwd=str(build_dir), timeout=build_timeout)
    except subprocess.TimeoutExpired:
        result.error = (
            f"isabelle build timed out after {build_timeout:.0f}s; "
            "increase --sledgehammer-timeout"
        )
        return result
    except OSError as exc:
        result.error = f"failed to invoke {isabelle_executable!r}: {exc}"
        result.isabelle_available = False
        return result
    finally:
        result.duration_seconds = time.monotonic() - start

    result.ran = True
    result.return_code = proc.returncode
    result.stdout = proc.stdout
    result.stderr = proc.stderr

    if result_path.exists():
        tsv = result_path.read_text(encoding="utf-8", errors="ignore")
        found, outcome_tag, proof_line = parse_sledgehammer_tsv(tsv)
        result.found = found
        result.outcome_tag = outcome_tag
        result.proof_line = proof_line
        # A non-zero exit with no proof signals a build/runtime failure (e.g. a
        # malformed goal that does not typecheck) rather than a clean miss, so
        # surface it as an error the caller can treat as a blocker.
        if not found and proc.returncode != 0:
            result.error = (
                f"isabelle build returned {proc.returncode} (sledgehammer run failed)"
            )
    else:
        result.found = False
        result.error = (
            f"isabelle build returned {proc.returncode} without writing a "
            "sledgehammer result file"
        )

    return result


__all__ = [
    "SledgehammerResult",
    "extract_proof",
    "parse_sledgehammer_tsv",
    "run_sledgehammer",
]
