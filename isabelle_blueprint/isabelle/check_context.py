"""Read native Isabelle source/configuration digests for incremental checks.

This query reads session dependencies; it does not build a session or run proofs.
Unsupported Scala APIs, missing inputs and failed probes disable Python cache
reuse. Isabelle's own build cache remains available on the normal check path.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from isabelle_blueprint.isabelle._run import run_capture

_PREFIX = "ISABELLE_BLUEPRINT_CONTEXT\t"


def session_fingerprint(
    executable: str,
    *,
    sessions: list[str],
    directories: list[Path],
    timeout: float | None = None,
) -> str | None:
    """Hash native source digests, ROOT metadata, settings and executable identity.

    Include every imported session, so an externally rebuilt dependency cannot
    hide a source change behind an up-to-date heap. Session digests cover theory
    sources and auxiliary files (including ML), plus parsed ROOT configuration.
    Fail closed if Isabelle cannot supply the complete evidence.
    """
    names = ", ".join(json.dumps(name) for name in sorted(set(sessions)))
    dirs = ", ".join(f"Path.explode({json.dumps(str(p.resolve()))})" for p in directories)
    script = f"""
import isabelle._
val options = Options.init()
val structure = Sessions.load_structure(options, dirs = List({dirs}))
val selected = structure.selection(Sessions.Selection(sessions = List({names})))
val deps = Sessions.deps(selected, inlined_files = true).check_errors
val sources = selected.imports_topological_order.sorted.map(name =>
  name + "\\n" + deps.sources_shasum(name).toString)
val settings = List("ISABELLE_HOME", "ISABELLE_IDENTIFIER", "ML_HOME", "ML_PLATFORM",
  "ML_OPTIONS", "ISABELLE_BUILD_OPTIONS").map(name =>
    name + "=" + Isabelle_System.getenv(name))
println("{_PREFIX}" + SHA1.digest((sources ::: settings).mkString("\\n")))
"""
    try:
        executable_path = Path(executable).resolve()
        executable_digest = hashlib.sha256(executable_path.read_bytes()).hexdigest()
        proc = run_capture(
            [executable, "scala", "-e", script],
            timeout=min(timeout, 30.0) if timeout is not None else 30.0,
            max_output_bytes=1_000_000,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    markers = [
        line[len(_PREFIX) :] for line in proc.stdout.splitlines() if line.startswith(_PREFIX)
    ]
    if len(markers) != 1 or re.fullmatch(r"[0-9a-f]{40}", markers[0]) is None:
        return None
    payload = f"{executable_path}\n{executable_digest}\n{markers[0]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
