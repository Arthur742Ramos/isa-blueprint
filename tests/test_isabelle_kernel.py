"""Pinned hosted-Isabelle integration; explicitly opt in, never build locally by default."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from isabelle_blueprint.config import BlueprintConfig
from isabelle_blueprint.isabelle import check_context, checker
from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.check_context import session_fingerprint
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import apply_stored_check_report

pytestmark = pytest.mark.skipif(
    os.environ.get("ISABELLE_BLUEPRINT_KERNEL_TESTS") != "1",
    reason="requires explicitly enabled hosted Isabelle kernel fixtures",
)


@pytest.fixture
def kernel_project(tmp_path, monkeypatch):
    executable = shutil.which("isabelle")
    assert executable is not None, "kernel fixture requested but Isabelle is missing"
    version = run_capture([executable, "version"], timeout=30)
    assert version.returncode == 0 and version.stdout.strip() == "Isabelle2025-2"
    user_home = tmp_path / "isabelle-user"
    monkeypatch.setenv("USER_HOME", str(user_home))
    home = run_capture([executable, "getenv", "-b", "ISABELLE_HOME_USER"], timeout=30)
    assert home.returncode == 0, home.stderr
    settings_home = Path(home.stdout.strip())
    assert settings_home.is_relative_to(user_home)
    settings = settings_home / "etc" / "settings"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('ISABELLE_BUILD_OPTIONS="threads=2"\n', encoding="utf-8")
    root = tmp_path / "session"
    shutil.copytree(Path(__file__).parent / "fixtures" / "kernel", root)
    return executable, root


def test_native_fingerprint_tracks_theory_ml_root_and_settings(kernel_project, monkeypatch):
    executable, root = kernel_project
    probes = []

    def capture(*args, **kwargs):
        result = run_capture(*args, **kwargs)
        probes.append(result)
        return result

    monkeypatch.setattr(check_context, "run_capture", capture)

    def fingerprint():
        value = session_fingerprint(
            executable, sessions=["Blueprint_Kernel_Fixture"], directories=[root], timeout=30
        )
        assert value is not None, [(p.returncode, p.stdout, p.stderr) for p in probes]
        return value

    original = fingerprint()
    assert fingerprint() == original
    for name, change in [
        ("Kernel_Fixture.thy", "\n(* changed source *)\n"),
        ("fixture_aux.ML", "\nval blueprint_extra_value = 2;\n"),
        ("ROOT", "\n  options [threads = 1]\n"),
    ]:
        path = root / name
        text = path.read_text(encoding="utf-8")
        changed = (
            text.replace("quick_and_dirty = true", "quick_and_dirty = true, threads = 1")
            if name == "ROOT"
            else text + change
        )
        path.write_text(changed, encoding="utf-8")
        assert fingerprint() != original, name
        path.write_text(text, encoding="utf-8")
        assert fingerprint() == original
    home = run_capture([executable, "getenv", "-b", "ISABELLE_HOME_USER"], timeout=30)
    assert home.returncode == 0, home.stderr
    (Path(home.stdout.strip()) / "etc" / "settings").write_text(
        'ISABELLE_BUILD_OPTIONS="threads=1"\n', encoding="utf-8"
    )
    assert fingerprint() != original


def _project(*facts):
    return BlueprintProject.from_nodes(
        "kernel",
        [
            BlueprintNode(
                id=fact,
                kind=NodeKind.LEMMA,
                title=fact,
                isabelle=IsabelleRef(fact=f"Kernel_Fixture.{fact}"),
            )
            for fact in facts
        ],
    )


def _check(project, kernel_project, tmp_path, **kwargs):
    executable, root = kernel_project
    result = checker.run_check(
        project,
        build_dir=tmp_path / "check",
        session_name="Blueprint_Kernel_Fixture",
        isabelle_executable=executable,
        project_root=root,
        timeout=300,
        jobs=1,
        **kwargs,
    )
    checker.apply_check_report(project, result)
    return result


def _config(kernel_project, tmp_path):
    executable, root = kernel_project
    return BlueprintConfig(
        project_root=root,
        blueprint_path=root / "blueprint.md",
        build_dir=tmp_path / "check",
        site_dir=tmp_path / "site",
        isabelle_session="Blueprint_Kernel_Fixture",
        isabelle_executable=executable,
        isabelle_timeout=300,
    )


def test_kernel_distinguishes_complete_proof_and_sorry(kernel_project, tmp_path):
    project = _project("clean", "admitted")
    result = _check(project, kernel_project, tmp_path)
    assert result.ran and result.return_code == 0, result.to_dict()
    assert result.proof_checked, result.to_dict()
    assert project.by_id()["clean"].status.formal == FormalStatus.PROVED
    assert project.by_id()["admitted"].status.formal == FormalStatus.TAINTED
    assert any(
        "skip_proof" in oracle for oracle in result.facts[0].oracles + result.facts[1].oracles
    )


def test_kernel_missing_fact_does_not_mark_other_facts_missing(kernel_project, tmp_path):
    project = _project("clean", "missing_fact")
    result = _check(project, kernel_project, tmp_path)
    assert result.ran and result.return_code != 0, result.to_dict()
    assert project.by_id()["missing_fact"].status.formal == FormalStatus.NOT_FOUND
    assert project.by_id()["clean"].status.formal == FormalStatus.NAMED
    assert not result.proof_checked


@pytest.mark.parametrize("mode", ["ml_error", "no_export"])
def test_kernel_export_failure_cannot_reuse_previous_proof(
    kernel_project, tmp_path, monkeypatch, mode
):
    project = _project("clean")
    initial = _check(project, kernel_project, tmp_path)
    assert initial.proof_checked and project.nodes[0].status.formal == FormalStatus.PROVED
    original = checker.generate_check_theory

    def broken_export(*args, **kwargs):
        text = original(*args, **kwargs)
        export = 'File.write (Path.explode "Blueprint_Proof_Status.tsv")'
        replacement = (
            '(fn _ => error "fixture extraction failure")' if mode == "ml_error" else "(fn _ => ())"
        )
        assert export in text
        return text.replace(export, replacement)

    monkeypatch.setattr(checker, "generate_check_theory", broken_export)
    result = _check(project, kernel_project, tmp_path)
    assert result.ran, result.to_dict()
    assert not result.proof_checked and result.facts[0].proof_status is None, result.to_dict()
    assert project.nodes[0].status.formal == (
        FormalStatus.NAMED if mode == "ml_error" else FormalStatus.FOUND
    ), result.to_dict()
    config = _config(kernel_project, tmp_path)
    checker.write_report(result, config.check_report_path)
    restored = _project("clean")
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == project.nodes[0].status.formal
    assert restored.nodes[0].status.formal != FormalStatus.PROVED


def test_kernel_incremental_cache_rechecks_externally_rebuilt_source(kernel_project, tmp_path):
    executable, root = kernel_project
    project = _project("clean")
    options = dict(incremental=True, cache_path=tmp_path / "cache.json")
    initial = _check(project, kernel_project, tmp_path, **options)
    assert initial.proof_checked and project.nodes[0].status.formal == FormalStatus.PROVED
    hit = _check(project, kernel_project, tmp_path, **options)
    assert hit.ran and hit.invoked_command == [], hit.to_dict()
    source = root / "Kernel_Fixture.thy"
    source.write_text(
        source.read_text(encoding="utf-8").replace("by simp", "sorry"), encoding="utf-8"
    )
    # Rebuild the user's heap independently, so build freshness alone is not
    # sufficient evidence for the Python cache to reuse the previous record.
    rebuilt = run_capture(
        [executable, "build", "-b", "-d", str(root), "Blueprint_Kernel_Fixture"], timeout=300
    )
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    changed = _check(project, kernel_project, tmp_path, **options)
    assert changed.invoked_command and changed.return_code == 0, changed.to_dict()
    assert project.nodes[0].status.formal == FormalStatus.TAINTED, changed.to_dict()


def test_kernel_saved_report_freshness_and_obsolete_diagnostics(
    kernel_project, tmp_path, monkeypatch
):
    from isabelle_blueprint import mcp_server

    _, root = kernel_project
    config = _config(kernel_project, tmp_path)
    project = _project("clean")
    initial = _check(project, kernel_project, tmp_path)
    assert initial.source_fingerprint is not None, initial.to_dict()
    checker.write_report(initial, config.check_report_path)
    restored = _project("clean")
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == FormalStatus.PROVED

    def load_snapshot(_directory):
        loaded = _project("clean")
        apply_stored_check_report(loaded, config)
        return config, loaded

    monkeypatch.setattr(mcp_server, "load_config_checked", lambda _directory: config)
    monkeypatch.setattr(mcp_server, "load_project_with_check", load_snapshot)
    cache = mcp_server._SnapshotCache()
    first = cache.get(root)
    assert first.project.nodes[0].status.formal == FormalStatus.PROVED
    source = root / "Kernel_Fixture.thy"
    original = source.read_text(encoding="utf-8")
    source.write_text(original.replace("lemma clean:", "lemma renamed:"), encoding="utf-8")
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == FormalStatus.STALE
    reloaded = cache.get(root)
    assert reloaded is not first
    assert reloaded.project.nodes[0].status.formal == FormalStatus.STALE
    failed = _check(_project("clean"), kernel_project, tmp_path)
    assert failed.return_code != 0, failed.to_dict()
    checker.write_report(failed, config.check_report_path)
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == FormalStatus.NOT_FOUND
    source.write_text(original, encoding="utf-8")
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == FormalStatus.STALE
    assert "Undefined fact" not in restored.nodes[0].status.check_error
    successful = _check(restored, kernel_project, tmp_path)
    checker.write_report(successful, config.check_report_path)
    apply_stored_check_report(restored, config)
    assert restored.nodes[0].status.formal == FormalStatus.PROVED
    assert restored.nodes[0].status.check_error is None
