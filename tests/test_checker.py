"""Tests for the Isabelle checker scaffolding."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.isabelle.checker import (
    CheckResult,
    FactCheck,
    apply_check_report,
    run_check,
    write_report,
)
from isabelle_blueprint.isabelle.theory_gen import (
    generate_check_theory,
    group_facts_by_theory,
)
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str, fact: str | None, *, uses=None):
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=fact) if fact else IsabelleRef(),
        status=NodeStatus(),
    )


def _proj(*nodes):
    return BlueprintProject.from_nodes("p", list(nodes))


# ---------------------------------------------------------------------------
# theory generation
# ---------------------------------------------------------------------------


def test_group_facts_skips_nodes_without_isabelle_ref():
    project = _proj(_node("a", None), _node("b", "Demo.b"))
    grouped = group_facts_by_theory(project)
    assert "Demo" in grouped
    assert all(r.node_id == "b" for r in grouped["Demo"])


def test_generate_check_theory_minimum_shape():
    project = _proj(_node("a", "Demo.foo"), _node("b", "Other.bar"))
    text = generate_check_theory(project, theory_name="Blueprint_Check")
    assert text.startswith("theory Blueprint_Check")
    assert text.rstrip().endswith("end")
    assert '"Demo"' in text
    assert '"Other"' in text
    # Both fact antiquotations are present
    assert "@{thm Demo.foo}" in text
    assert "@{thm Other.bar}" in text
    # Node id should appear in the trailing comment for traceability
    assert "(* a *)" in text
    assert "(* b *)" in text


def test_generate_check_theory_empty_project_uses_main():
    project = _proj()
    text = generate_check_theory(project)
    assert '"Main"' in text


# ---------------------------------------------------------------------------
# apply_check_report
# ---------------------------------------------------------------------------


def test_apply_check_report_skipped_run_marks_all_named():
    project = _proj(_node("a", "Demo.a"), _node("b", "Demo.b"), _node("c", None))
    result = CheckResult(
        ran=False,
        isabelle_available=False,
        error="isabelle not on PATH",
        facts=[FactCheck("a", "Demo.a", "Demo", exists=False),
               FactCheck("b", "Demo.b", "Demo", exists=False)],
    )
    apply_check_report(project, result)
    by_id = project.by_id()
    assert by_id["a"].status.formal == FormalStatus.NAMED
    assert by_id["b"].status.formal == FormalStatus.NAMED
    # Node without a fact stays MISSING.
    assert by_id["c"].status.formal == FormalStatus.MISSING
    assert by_id["a"].status.check_error == "isabelle not on PATH"


def test_apply_check_report_found_when_exists_true():
    project = _proj(_node("a", "Demo.a"))
    result = CheckResult(
        ran=True,
        return_code=0,
        isabelle_available=True,
        facts=[FactCheck("a", "Demo.a", "Demo", exists=True)],
    )
    apply_check_report(project, result)
    assert project.by_id()["a"].status.formal == FormalStatus.FOUND


def test_apply_check_report_not_found_when_explicitly_bad():
    project = _proj(_node("a", "Demo.a"))
    result = CheckResult(
        ran=True,
        return_code=1,
        isabelle_available=True,
        facts=[FactCheck("a", "Demo.a", "Demo", exists=False, error="Undefined fact: Demo.a")],
    )
    apply_check_report(project, result)
    node = project.by_id()["a"]
    assert node.status.formal == FormalStatus.NOT_FOUND
    assert node.status.check_error == "Undefined fact: Demo.a"


def test_apply_check_report_named_when_record_missing_after_run():
    """If the build ran but no FactCheck record exists for a node, fall back to NAMED."""
    project = _proj(_node("a", "Demo.a"))
    result = CheckResult(ran=True, return_code=0, isabelle_available=True, facts=[])
    apply_check_report(project, result)
    assert project.by_id()["a"].status.formal == FormalStatus.NAMED


# ---------------------------------------------------------------------------
# CheckResult round-trip
# ---------------------------------------------------------------------------


def test_check_result_to_dict_and_from_dict_round_trip():
    original = CheckResult(
        ran=True,
        invoked_command=["isabelle", "build"],
        isabelle_available=True,
        return_code=0,
        duration_seconds=1.5,
        stdout="ok",
        stderr="",
        facts=[FactCheck("a", "Demo.a", "Demo", exists=True)],
    )
    d = original.to_dict()
    restored = CheckResult.from_dict(d)
    assert restored.ran is True
    assert restored.return_code == 0
    assert restored.duration_seconds == 1.5
    assert len(restored.facts) == 1
    assert restored.facts[0].fact == "Demo.a"
    assert restored.facts[0].exists is True


def test_check_result_from_dict_tolerates_unknown_fields():
    """Adding new fields to a saved report shouldn't break replay."""
    d = {
        "ran": False,
        "isabelle_available": False,
        "facts": [
            {"node_id": "a", "fact": "Demo.a", "theory": "Demo", "exists": False,
             "secret_future_field": 42}
        ],
        "totally_unknown_top_key": "ignored",
    }
    restored = CheckResult.from_dict(d)
    assert restored.ran is False
    assert restored.facts[0].fact == "Demo.a"


# ---------------------------------------------------------------------------
# run_check (no Isabelle on PATH)
# ---------------------------------------------------------------------------


def test_run_check_writes_theory_and_returns_skipped_result(tmp_path: Path):
    project = _proj(_node("a", "Demo.a"))
    result = run_check(
        project,
        build_dir=tmp_path,
        session_name=None,
        # Definitely not on PATH:
        isabelle_executable="definitely-not-installed-isabelle-xyz",
    )
    assert result.ran is False
    assert result.isabelle_available is False
    assert result.error and "not found" in result.error
    # Theory file should still have been written for inspection.
    assert (tmp_path / "Blueprint_Check.thy").exists()


def test_run_check_no_session_skips_build(tmp_path: Path, monkeypatch):
    """Even with isabelle available, session=None should short-circuit."""
    # Pretend the binary is on PATH.
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")
    project = _proj(_node("a", "Demo.a"))
    result = run_check(project, build_dir=tmp_path, session_name=None)
    assert result.ran is False
    assert result.isabelle_available is True
    assert "session" in (result.error or "").lower()


def test_write_report_round_trip(tmp_path: Path):
    result = CheckResult(
        ran=False,
        isabelle_available=False,
        facts=[FactCheck("a", "Demo.a", "Demo", exists=False)],
    )
    path = tmp_path / "report.json"
    write_report(result, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ran"] is False
    assert data["facts"][0]["fact"] == "Demo.a"
    # And it must round-trip back through from_dict.
    restored = CheckResult.from_dict(data)
    assert restored.facts[0].fact == "Demo.a"
