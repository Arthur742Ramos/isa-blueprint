"""Reconcile author-declared ``uses`` edges against Isabelle's real proof deps.

For every PROVED-eligible node (one carrying a resolvable Isabelle ``fact``),
this asks the kernel -- via :mod:`reconcile_theory` -- for the immediate named
theorems each proof actually depends on, maps those fact names back to blueprint
node ids, and diffs them against the author's declared ``uses`` list. The result
highlights:

* ``used_but_undeclared`` -- a node the proof really depends on but which the
  author did not list in ``uses`` (a STRONG signal of a missing edge), and
* ``declared_but_unused`` -- a declared dependency that does not appear among the
  proof's immediate deps. This is ADVISORY only: kernel deduplication and library
  aliasing can legitimately hide a genuinely-used edge, so it is never an error.

Like :mod:`isabelle_blueprint.isabelle.checker`, this module is tolerant of a
missing ``isabelle`` binary or unconfigured session: it always returns a
:class:`ReconcileResult` describing what happened and never raises.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.reconcile_theory import (
    DEPS_MARKER,
    generate_reconcile_theory,
)
from isabelle_blueprint.isabelle.theory_gen import (
    generate_check_root,
    group_facts_by_theory,
)
from isabelle_blueprint.model.project import BlueprintProject

_THEORY_NAME = "Blueprint_Deps"
_WRAPPER_SESSION = "Blueprint_Deps_Wrapper"
_RESULT_FILE = "Blueprint_Deps.tsv"


@dataclass
class ReconcileResult:
    """Outcome of running the dependency-extraction build."""

    ran: bool
    isabelle_available: bool = False
    return_code: int | None = None
    duration_seconds: float = 0.0
    error: str | None = None
    # node id -> list of dependency *fact names* (already filtered to the
    # blueprint's own fact set by the generated ML).
    deps: dict[str, list[str]] = field(default_factory=dict)
    generated_theory_path: str | None = None
    deps_path: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NodeReconcile:
    """Per-node reconciliation between declared ``uses`` and real proof deps."""

    node_id: str
    fact: str
    actual_dep_node_ids: list[str]
    declared_dep_node_ids: list[str]
    used_but_undeclared: list[str]
    declared_but_unused: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def parse_deps_tsv(text: str) -> dict[str, list[str]]:
    """Parse the deps TSV written by the generated wrapper.

    Each meaningful line is ``ISABELLE_BLUEPRINT_DEPS<TAB>node<TAB>fact<TAB>a,b``;
    the trailing column is a comma-joined list of dependency fact names (possibly
    empty). Lines without the marker, or with too few columns, are ignored. The
    last occurrence for a given node wins.
    """
    out: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        if DEPS_MARKER not in line:
            continue
        _, payload = line.split(DEPS_MARKER, 1)
        payload = payload.lstrip("\t")
        parts = payload.split("\t")
        if len(parts) < 3:
            # node + fact present but no deps column: treat as empty deps.
            if len(parts) == 2:
                out[parts[0]] = []
            continue
        node_id = parts[0]
        dep_text = parts[2]
        deps = [d for d in dep_text.split(",") if d] if dep_text not in {"", "-"} else []
        out[node_id] = deps
    return out


def reconcile_diff(project: BlueprintProject, deps: dict[str, list[str]]) -> list[NodeReconcile]:
    """Diff each node's declared ``uses`` against its real proof-dep node ids.

    *deps* maps a node id to the dependency fact names reported by the kernel.
    Those fact names are mapped back to node ids via the project's
    ``fact -> node id`` index; deps that do not correspond to a blueprint node
    (or that point back at the node itself) are dropped.
    """
    fact_to_node: dict[str, str] = {}
    for n in project.nodes:
        if n.isabelle.fact:
            fact_to_node.setdefault(n.isabelle.fact, n.id)
    by_id = project.by_id()

    results: list[NodeReconcile] = []
    for node_id in sorted(deps):
        node = by_id.get(node_id)
        if node is None or not node.isabelle.fact:
            continue
        actual: set[str] = set()
        for dep_fact in deps[node_id]:
            dep_node = fact_to_node.get(dep_fact)
            if dep_node is not None and dep_node != node_id:
                actual.add(dep_node)
        declared = {d for d in node.uses if d != node_id}
        results.append(
            NodeReconcile(
                node_id=node_id,
                fact=node.isabelle.fact,
                actual_dep_node_ids=sorted(actual),
                declared_dep_node_ids=sorted(declared),
                used_but_undeclared=sorted(actual - declared),
                declared_but_unused=sorted(declared - actual),
            )
        )
    return results


def reconcile_payload(project: BlueprintProject, result: ReconcileResult) -> dict:
    """Package the result + diff into a schema-style dict for ``--json``."""
    diffs = reconcile_diff(project, result.deps)
    nodes_with_undeclared = sum(1 for d in diffs if d.used_but_undeclared)
    nodes_with_unused = sum(1 for d in diffs if d.declared_but_unused)
    total_undeclared = sum(len(d.used_but_undeclared) for d in diffs)
    total_unused = sum(len(d.declared_but_unused) for d in diffs)
    return {
        "schema": "reconcile",
        "ran": result.ran,
        "isabelle_available": result.isabelle_available,
        "return_code": result.return_code,
        "error": result.error,
        "timestamp": result.timestamp,
        "nodes": [d.to_dict() for d in diffs],
        "summary": {
            "nodes_analyzed": len(diffs),
            "nodes_with_undeclared": nodes_with_undeclared,
            "nodes_with_unused": nodes_with_unused,
            "total_undeclared_edges": total_undeclared,
            "total_unused_edges": total_unused,
        },
    }


def run_reconcile(
    project: BlueprintProject,
    *,
    build_dir: Path,
    session_name: str | None = None,
    isabelle_executable: str = "isabelle",
    extra_dirs: list[Path] | None = None,
    project_root: Path | None = None,
    timeout: float | None = None,
    jobs: int | None = None,
) -> ReconcileResult:
    """Build the deps-extraction wrapper theory and read back the deps TSV.

    Mirrors :func:`isabelle_blueprint.isabelle.checker.run_check`: a missing
    ``isabelle`` binary, an unconfigured session, a timeout, or an OS-level
    launch failure all short-circuit to ``ran=False`` with an explanatory
    ``error`` rather than raising.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    deps_path = build_dir / _RESULT_FILE
    # A stale file from a prior run would be misread as the current outcome.
    try:
        deps_path.unlink()
    except FileNotFoundError:
        pass

    theory_text = generate_reconcile_theory(
        project,
        deps_file=deps_path.name,
        theory_name=_THEORY_NAME,
        default_import_session=session_name,
        nonce=f"{datetime.now(UTC).isoformat()}-{uuid.uuid4().hex}",
    )

    resolved_isabelle = shutil.which(isabelle_executable)
    isabelle_available = resolved_isabelle is not None
    result = ReconcileResult(
        ran=False,
        isabelle_available=isabelle_available,
        deps_path=str(deps_path),
    )

    if theory_text is None:
        result.error = (
            "no PROVED-eligible nodes (none carry a resolvable Isabelle fact); "
            "nothing to reconcile"
        )
        return result

    theory_path = build_dir / f"{_THEORY_NAME}.thy"
    theory_path.write_text(theory_text, encoding="utf-8")
    result.generated_theory_path = str(theory_path)

    if not isabelle_available:
        result.error = (
            f"Isabelle executable {isabelle_executable!r} not found on PATH; "
            "skipped reconcile build."
        )
        return result

    if session_name is None:
        result.error = (
            "No Isabelle session configured (set [isabelle].session in "
            "isabelle-blueprint.toml); skipped reconcile build."
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

    start = time.monotonic()
    try:
        proc = run_capture(cmd, cwd=str(build_dir), timeout=timeout)
    except subprocess.TimeoutExpired:
        result.error = (
            f"isabelle build timed out after {timeout:.0f}s; "
            "increase [isabelle].timeout in isabelle-blueprint.toml or pass --timeout"
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

    if deps_path.exists():
        result.deps = parse_deps_tsv(deps_path.read_text(encoding="utf-8", errors="ignore"))
        if proc.returncode != 0 and not result.deps:
            result.error = (
                f"isabelle build returned {proc.returncode} (reconcile run failed)"
            )
    else:
        result.error = (
            f"isabelle build returned {proc.returncode} without writing a deps file"
        )

    return result


__all__ = [
    "NodeReconcile",
    "ReconcileResult",
    "parse_deps_tsv",
    "reconcile_diff",
    "reconcile_payload",
    "run_reconcile",
]
