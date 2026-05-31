"""Tests for the incremental check cache (v0.6)."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from isabelle_blueprint.isabelle import check_cache, checker as checker_module
from isabelle_blueprint.isabelle._run import RunResult
from isabelle_blueprint.isabelle.checker import FactCheck, run_check
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject


# ---------------------------------------------------------------------------
# helpers (mirror tests/test_checker.py style)
# ---------------------------------------------------------------------------


def _node(node_id: str, fact: str | None, *, uses=None, session: str | None = None):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=fact, session=session) if fact else IsabelleRef(),
        status=NodeStatus(),
    )


def _proj(*nodes):
    return BlueprintProject.from_nodes("p", list(nodes))


def _ctx(**overrides):
    base = dict(
        session_name="My_Session",
        isabelle_executable="isabelle",
        extra_dirs=None,
        project_root=None,
        proof_status=True,
    )
    base.update(overrides)
    return check_cache.compute_context_fingerprint(**base)


# ---------------------------------------------------------------------------
# Pure-function tests: hashes and context fingerprints
# ---------------------------------------------------------------------------


def test_compute_context_fingerprint_is_deterministic():
    a = _ctx()
    b = _ctx()
    assert a == b


@pytest.mark.parametrize(
    "field, value",
    [
        ("session_name", "Other_Session"),
        ("isabelle_executable", "isabelle-2024"),
        ("proof_status", False),
    ],
)
def test_compute_context_fingerprint_sensitive_to_each_field(field, value):
    base = _ctx()
    changed = _ctx(**{field: value})
    assert base != changed


def test_compute_context_fingerprint_sensitive_to_extra_dirs(tmp_path: Path):
    base = _ctx(extra_dirs=None)
    with_dir = _ctx(extra_dirs=[tmp_path / "afp"])
    assert base != with_dir


def test_compute_context_fingerprint_extra_dirs_order_independent(tmp_path: Path):
    a = _ctx(extra_dirs=[tmp_path / "x", tmp_path / "y"])
    b = _ctx(extra_dirs=[tmp_path / "y", tmp_path / "x"])
    assert a == b


def test_compute_node_hash_is_deterministic():
    n = _node("a", "Demo.foo", uses=["b", "c"])
    ctx = _ctx()
    assert check_cache.compute_node_hash(n, context=ctx) == check_cache.compute_node_hash(n, context=ctx)


@pytest.mark.parametrize(
    "build",
    [
        lambda: _node("a", "Demo.bar"),  # fact changed
        lambda: _node("a", "Demo.foo", uses=["different"]),  # deps changed
        lambda: _node("a", "Demo.foo", session="Other"),  # session changed
        lambda: _node("a", "Other.foo"),  # theory changed (via fact)
        lambda: _node("renamed", "Demo.foo"),  # id changed
    ],
)
def test_compute_node_hash_sensitive_to_node_fields(build):
    baseline = check_cache.compute_node_hash(_node("a", "Demo.foo"), context=_ctx())
    changed = check_cache.compute_node_hash(build(), context=_ctx())
    assert baseline != changed


def test_compute_node_hash_sensitive_to_context():
    n = _node("a", "Demo.foo")
    h1 = check_cache.compute_node_hash(n, context=_ctx())
    h2 = check_cache.compute_node_hash(n, context=_ctx(session_name="Other"))
    assert h1 != h2


def test_compute_node_hash_uses_order_independent():
    n1 = _node("a", "Demo.foo", uses=["b", "c"])
    n2 = _node("a", "Demo.foo", uses=["c", "b"])
    ctx = _ctx()
    assert check_cache.compute_node_hash(n1, context=ctx) == check_cache.compute_node_hash(n2, context=ctx)


# ---------------------------------------------------------------------------
# Pure-function tests: load_cache / save_cache
# ---------------------------------------------------------------------------


def test_load_cache_missing_file_returns_empty(tmp_path: Path):
    assert check_cache.load_cache(tmp_path / "missing.json") == {}


def test_save_then_load_round_trip(tmp_path: Path):
    path = tmp_path / "cache.json"
    entries = {
        "a": check_cache.record_entry(
            {"node_id": "a", "fact": "Demo.a", "theory": "Demo", "exists": True,
             "error": None, "proof_status": "proved", "oracles": []},
            node_hash="abc",
        ),
    }
    check_cache.save_cache(path, entries)
    loaded = check_cache.load_cache(path)
    assert loaded == entries


def test_load_cache_with_bumped_schema_returns_empty(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"schema": 999999, "entries": {"a": {"hash": "x"}}}), encoding="utf-8")
    assert check_cache.load_cache(path) == {}


def test_load_cache_corrupt_file_returns_empty(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("this is not json {{{", encoding="utf-8")
    assert check_cache.load_cache(path) == {}


def test_load_cache_filters_malformed_entries(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps(
            {
                "schema": check_cache.CACHE_SCHEMA_VERSION,
                "entries": {
                    "good": {"hash": "h", "fact_check": {"node_id": "good", "fact": "F", "exists": True}},
                    "no_hash": {"fact_check": {"node_id": "x"}},
                    "no_fact_check": {"hash": "h"},
                    "not_a_dict": "garbage",
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = check_cache.load_cache(path)
    assert set(loaded.keys()) == {"good"}


def test_save_cache_is_atomic_via_temp_file(tmp_path: Path):
    path = tmp_path / "cache.json"
    check_cache.save_cache(path, {"a": {"hash": "h", "fact_check": {"node_id": "a", "fact": "F", "exists": True}}})
    # No leftover .tmp file after a successful save.
    assert not (path.with_suffix(path.suffix + ".tmp")).exists()
    assert path.exists()


# ---------------------------------------------------------------------------
# reusable_entry
# ---------------------------------------------------------------------------


def _entry(**fc_overrides):
    fc = {
        "node_id": "a",
        "fact": "Demo.a",
        "theory": "Demo",
        "exists": True,
        "error": None,
        "proof_status": "proved",
        "oracles": [],
    }
    fc.update(fc_overrides)
    return {"hash": "h", "fact_check": fc}


def test_reusable_entry_returns_dict_when_clean():
    assert check_cache.reusable_entry(_entry(), proof_status_required=True) is not None


def test_reusable_entry_skips_when_not_exists():
    assert check_cache.reusable_entry(_entry(exists=False), proof_status_required=True) is None


def test_reusable_entry_skips_when_oracles_present():
    assert check_cache.reusable_entry(_entry(oracles=["Pure.skip_proof"]), proof_status_required=True) is None


def test_reusable_entry_skips_when_proof_status_not_proved_and_required():
    assert check_cache.reusable_entry(_entry(proof_status="found"), proof_status_required=True) is None
    assert check_cache.reusable_entry(_entry(proof_status=None), proof_status_required=True) is None


def test_reusable_entry_does_not_require_proof_status_when_not_requested():
    # When proof_status was not requested, a "found" record is still reusable
    # (we only ever verified existence).
    assert check_cache.reusable_entry(_entry(proof_status="found"), proof_status_required=False) is not None


def test_reusable_entry_missing_fact_check_returns_none():
    assert check_cache.reusable_entry({"hash": "h"}, proof_status_required=True) is None


# ---------------------------------------------------------------------------
# End-to-end integration with run_check (fake isabelle binary)
# ---------------------------------------------------------------------------


def _fake_proof_status_run(*expected_node_ids: str):
    """Build a fake run_capture that emits an ISABELLE_BLUEPRINT_FACT line per id."""
    expected = list(expected_node_ids)
    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd=None, timeout=None, env=None):
        calls.append(list(cmd))
        lines = [
            f"ISABELLE_BLUEPRINT_FACT\t{nid}\tDemo.{nid}\tproved\t-"
            for nid in expected
        ]
        return RunResult(args=list(cmd), returncode=0, stdout="\n".join(lines) + "\n", stderr="")

    return fake_run, calls


def _fake_isabelle(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")


def test_run_check_incremental_populates_cache_on_first_run(tmp_path: Path, monkeypatch):
    project = _proj(_node("a", "Demo.a"), _node("b", "Demo.b"))
    _fake_isabelle(monkeypatch)
    fake_run, calls = _fake_proof_status_run("a", "b")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)

    cache_path = tmp_path / "check-cache.json"
    result = run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    assert result.ran is True
    assert result.return_code == 0
    assert len(calls) == 1  # isabelle build was invoked
    assert cache_path.exists()

    cache = check_cache.load_cache(cache_path)
    assert set(cache.keys()) == {"a", "b"}
    for nid in ("a", "b"):
        fc = cache[nid]["fact_check"]
        assert fc["exists"] is True
        assert fc["proof_status"] == "proved"


def test_run_check_incremental_second_pass_short_circuits(tmp_path: Path, monkeypatch):
    """Second run with no changes must not invoke isabelle."""
    project = _proj(_node("a", "Demo.a"), _node("b", "Demo.b"))
    _fake_isabelle(monkeypatch)
    fake_run, calls = _fake_proof_status_run("a", "b")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)
    cache_path = tmp_path / "check-cache.json"

    # First run populates the cache.
    run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    assert len(calls) == 1

    # Second run on the same project: cache should short-circuit, fake_run must
    # not be invoked again.
    def must_not_run(*args, **kwargs):
        raise AssertionError("run_capture should not be called when cache covers everything")

    monkeypatch.setattr(checker_module, "run_capture", must_not_run)
    result2 = run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    assert result2.ran is True
    assert result2.return_code == 0
    assert result2.proof_checked is True
    assert {fc.node_id for fc in result2.facts} == {"a", "b"}
    assert all(fc.proof_status == "proved" for fc in result2.facts)


def test_run_check_incremental_only_re_checks_changed_nodes(tmp_path: Path, monkeypatch):
    """If a node's inputs change, only that node is rebuilt; others stay cached."""
    _fake_isabelle(monkeypatch)
    cache_path = tmp_path / "check-cache.json"
    build_dir = tmp_path / "build"

    # First run: project has 'a' and 'b' both proved.
    project_v1 = _proj(_node("a", "Demo.a"), _node("b", "Demo.b"))
    fake_run_v1, calls_v1 = _fake_proof_status_run("a", "b")
    monkeypatch.setattr(checker_module, "run_capture", fake_run_v1)
    run_check(
        project_v1,
        build_dir=build_dir,
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    assert len(calls_v1) == 1

    # Second run: 'b' has a new fact reference. Only 'b' should be in the
    # wrapper theory; the generated cmd should still go through; fake_run
    # should be called exactly once.
    project_v2 = _proj(_node("a", "Demo.a"), _node("b", "Demo.b_changed"))
    calls_v2: list[list[str]] = []

    def fake_run_v2(cmd, *, cwd=None, timeout=None, env=None):
        calls_v2.append(list(cmd))
        return RunResult(
            args=list(cmd),
            returncode=0,
            stdout="ISABELLE_BLUEPRINT_FACT\tb\tDemo.b_changed\tproved\t-\n",
            stderr="",
        )

    monkeypatch.setattr(checker_module, "run_capture", fake_run_v2)
    result = run_check(
        project_v2,
        build_dir=build_dir,
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    assert len(calls_v2) == 1, "build should still run for the changed node"
    assert result.ran is True

    # Wrapper theory should reference only the changed fact, not the cached one.
    theory_text = (build_dir / "Blueprint_Check.thy").read_text(encoding="utf-8")
    assert "Demo.b_changed" in theory_text
    assert "Demo.a" not in theory_text

    # Result still surfaces both nodes (a from cache, b freshly proved).
    by_node = {fc.node_id: fc for fc in result.facts}
    assert by_node["a"].proof_status == "proved"
    assert by_node["a"].fact == "Demo.a"
    assert by_node["b"].proof_status == "proved"
    assert by_node["b"].fact == "Demo.b_changed"

    # Cache now reflects the new fact for 'b'.
    cache = check_cache.load_cache(cache_path)
    assert cache["b"]["fact_check"]["fact"] == "Demo.b_changed"


def test_run_check_incremental_invalidates_when_context_changes(tmp_path: Path, monkeypatch):
    """Changing the session name (context) must invalidate cache entries."""
    project = _proj(_node("a", "Demo.a"))
    _fake_isabelle(monkeypatch)
    cache_path = tmp_path / "check-cache.json"
    build_dir = tmp_path / "build"

    fake_run, calls = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)

    run_check(
        project,
        build_dir=build_dir,
        session_name="Session_One",
        incremental=True,
        cache_path=cache_path,
    )
    assert len(calls) == 1

    # Same node, different session -> cache entry no longer matches.
    fake_run2, calls2 = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run2)
    run_check(
        project,
        build_dir=build_dir,
        session_name="Session_Two",
        incremental=True,
        cache_path=cache_path,
    )
    assert len(calls2) == 1, "context change must trigger a re-build"


def test_run_check_jobs_flag_inserts_minus_j_into_command(tmp_path: Path, monkeypatch):
    project = _proj(_node("a", "Demo.a"))
    _fake_isabelle(monkeypatch)
    fake_run, calls = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)

    run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        jobs=4,
    )
    assert calls, "fake run_capture should have been invoked"
    cmd = calls[0]
    assert "-j" in cmd
    j_idx = cmd.index("-j")
    assert cmd[j_idx + 1] == "4"
    # -j must precede the wrapper session (the final positional argument).
    assert j_idx < cmd.index("Blueprint_Check_Wrapper")


def test_run_check_jobs_omitted_when_not_set(tmp_path: Path, monkeypatch):
    project = _proj(_node("a", "Demo.a"))
    _fake_isabelle(monkeypatch)
    fake_run, calls = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)

    run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
    )
    assert "-j" not in calls[0]


def test_run_check_non_incremental_writes_no_cache(tmp_path: Path, monkeypatch):
    project = _proj(_node("a", "Demo.a"))
    _fake_isabelle(monkeypatch)
    fake_run, _ = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)

    cache_path = tmp_path / "check-cache.json"
    run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        incremental=False,
        cache_path=cache_path,
    )
    assert not cache_path.exists()


def test_run_check_incremental_oracle_tainted_not_cached(tmp_path: Path, monkeypatch):
    """A tainted (oracle-based) proof must not be persisted to the cache."""
    project = _proj(_node("a", "Demo.a"))
    _fake_isabelle(monkeypatch)

    def fake_run(cmd, *, cwd=None, timeout=None, env=None):
        return RunResult(
            args=list(cmd),
            returncode=0,
            stdout="ISABELLE_BLUEPRINT_FACT\ta\tDemo.a\ttainted\tPure.skip_proof\n",
            stderr="",
        )

    monkeypatch.setattr(checker_module, "run_capture", fake_run)
    cache_path = tmp_path / "check-cache.json"
    result = run_check(
        project,
        build_dir=tmp_path / "build",
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    # The fact was reported, but tainted -> not in cache.
    assert result.ran is True
    cache = check_cache.load_cache(cache_path)
    assert "a" not in cache


def test_run_check_incremental_skips_when_isabelle_missing_but_still_reports_cached_hits(
    tmp_path: Path, monkeypatch
):
    """Cache hits should still surface even when isabelle disappears later."""
    project = _proj(_node("a", "Demo.a"))
    cache_path = tmp_path / "check-cache.json"
    build_dir = tmp_path / "build"

    # Pre-populate the cache via a successful first run.
    _fake_isabelle(monkeypatch)
    fake_run, _ = _fake_proof_status_run("a")
    monkeypatch.setattr(checker_module, "run_capture", fake_run)
    run_check(
        project,
        build_dir=build_dir,
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )

    # Second run: isabelle vanished from PATH. We can short-circuit entirely
    # because the cache covers every node.
    monkeypatch.setattr(shutil, "which", lambda _x: None)
    result = run_check(
        project,
        build_dir=build_dir,
        session_name="My_Session",
        incremental=True,
        cache_path=cache_path,
    )
    # We DO have a cache hit, so the run "succeeded" without needing isabelle.
    assert result.ran is True
    assert {fc.node_id for fc in result.facts} == {"a"}
    assert result.facts[0].proof_status == "proved"
