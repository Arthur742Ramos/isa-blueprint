"""Incremental check cache.

Stores a JSON map of ``node_id -> {"hash": "...", "fact_check": {...}}`` so that
subsequent ``isabelle-blueprint check --incremental`` runs can skip re-verifying
nodes whose blueprint inputs *and* checker context have not changed.

The cache is intentionally conservative:

* Only fact records that were proved on a successful build are persisted.
* The hash mixes per-node inputs (id, fact, theory, session, deps) with global
  checker context (schema version, isabelle executable, session name, extra
  build dirs, proof-status flag) so any change that *could* invalidate the
  proof invalidates the cache entry.
* Bumping :data:`CACHE_SCHEMA_VERSION` invalidates the entire cache.

This module deliberately avoids importing :mod:`isabelle_blueprint.isabelle.checker`
(which would form a cycle) — it operates on plain dictionaries that mirror the
:class:`~isabelle_blueprint.isabelle.checker.FactCheck` shape and lets the
checker handle the conversion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from isabelle_blueprint.model.node import BlueprintNode

CACHE_SCHEMA_VERSION = 1

# Marker stored at the top of the on-disk cache so future format changes can be
# detected and the entire cache discarded automatically.
_SCHEMA_KEY = "schema"
_ENTRIES_KEY = "entries"


def compute_context_fingerprint(
    *,
    session_name: str | None,
    isabelle_executable: str,
    extra_dirs: Iterable[Path] | None,
    project_root: Path | None,
    proof_status: bool,
) -> str:
    """Stable identifier for the global checker context.

    Any change here invalidates *all* cache entries for the current run. We
    deliberately use the *configured* ``isabelle_executable`` string rather
    than the resolved absolute path so that a user moving their Isabelle
    install (but keeping ``isabelle`` on PATH) doesn't pointlessly invalidate
    everything. If the executable changes name, the cache invalidates.
    """
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "session_name": session_name,
        "isabelle_executable": isabelle_executable,
        "extra_dirs": sorted(str(d) for d in (extra_dirs or [])),
        "project_root": str(project_root) if project_root is not None else None,
        "proof_status": bool(proof_status),
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def compute_node_hash(node: BlueprintNode, *, context: str) -> str:
    """Per-node hash mixing node identity, fact references, deps, and context.

    The ``context`` argument must be the value returned by
    :func:`compute_context_fingerprint` for the current run.
    """
    kind_value = getattr(node.kind, "value", str(node.kind))
    payload = {
        "context": context,
        "id": node.id,
        "kind": kind_value,
        "fact": node.isabelle.fact,
        "theory": node.isabelle.theory,
        "session": node.isabelle.session,
        "uses": sorted(list(node.uses or [])),
    }
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    """Load the cache; return ``{}`` if the file is missing, corrupt, or stale.

    A bumped :data:`CACHE_SCHEMA_VERSION` (or any other unrecognised payload
    shape) discards everything — incremental mode is just an optimisation, so
    a fresh start is always a safe fallback.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get(_SCHEMA_KEY) != CACHE_SCHEMA_VERSION:
        return {}
    entries = data.get(_ENTRIES_KEY)
    if not isinstance(entries, dict):
        return {}
    # Defensively filter out anything that isn't shaped like an entry.
    return {
        nid: entry
        for nid, entry in entries.items()
        if isinstance(entry, dict) and "hash" in entry and isinstance(entry.get("fact_check"), dict)
    }


def save_cache(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    """Write the cache atomically(ish).

    We write to a temp sibling first then rename so a crash mid-write doesn't
    leave a partially-flushed cache that would later be discarded by
    :func:`load_cache`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {_SCHEMA_KEY: CACHE_SCHEMA_VERSION, _ENTRIES_KEY: entries}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def reusable_entry(entry: dict[str, Any], *, proof_status_required: bool) -> dict[str, Any] | None:
    """Return the cached ``fact_check`` dict if it's safe to reuse, else None.

    A cached fact is reusable when:

    * ``exists`` is true (we proved it existed),
    * no oracles were involved (oracle-tainted proofs are never reused),
    * if the current run requested proof-status verification, the cached
      ``proof_status`` is exactly ``"proved"``. Cached ``found`` or
      ``tainted`` values are not safe to reuse — they might be green by
      luck on this run but the user explicitly asked us to verify the
      proof status, so re-verify them.
    """
    fc_raw = entry.get("fact_check")
    if not isinstance(fc_raw, dict):
        return None
    if not fc_raw.get("exists"):
        return None
    oracles = fc_raw.get("oracles") or []
    if oracles:
        return None
    if proof_status_required and fc_raw.get("proof_status") != "proved":
        return None
    return fc_raw


def record_entry(fact_check_dict: dict[str, Any], *, node_hash: str) -> dict[str, Any]:
    """Wrap a fact-check dict in the on-disk cache-entry shape."""
    return {"hash": node_hash, "fact_check": fact_check_dict}


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "compute_context_fingerprint",
    "compute_node_hash",
    "load_cache",
    "save_cache",
    "reusable_entry",
    "record_entry",
]
