"""Pinned hosted-Isabelle integration; explicitly opt in, never build locally by default."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.check_context import session_fingerprint

pytestmark = pytest.mark.skipif(
    os.environ.get("ISABELLE_BLUEPRINT_KERNEL_TESTS") != "1",
    reason="requires explicitly enabled hosted Isabelle kernel fixtures",
)


@pytest.fixture
def kernel_project(tmp_path):
    executable = shutil.which("isabelle")
    assert executable is not None, "kernel fixture requested but Isabelle is missing"
    version = run_capture([executable, "version"], timeout=30)
    assert version.returncode == 0 and version.stdout.strip() == "Isabelle2025-2"
    root = tmp_path / "session"
    shutil.copytree(Path(__file__).parent / "fixtures" / "kernel", root)
    return executable, root


def test_native_fingerprint_tracks_theory_ml_root_and_settings(kernel_project, monkeypatch):
    executable, root = kernel_project

    def fingerprint():
        value = session_fingerprint(
            executable, sessions=["Blueprint_Kernel_Fixture"], directories=[root], timeout=30
        )
        assert value is not None, "native source probe failed on the pinned supported release"
        return value

    original = fingerprint()
    assert fingerprint() == original
    for name, change in [
        ("Kernel_Fixture.thy", "\n(* changed source *)\n"),
        ("fixture_aux.ML", "\nval blueprint_extra_value = 2;\n"),
        ("ROOT", '\n  description "changed session metadata"\n'),
    ]:
        path = root / name
        text = path.read_text(encoding="utf-8")
        changed = (
            text.replace("  theories", change + "  theories") if name == "ROOT" else text + change
        )
        path.write_text(changed, encoding="utf-8")
        assert fingerprint() != original, name
        path.write_text(text, encoding="utf-8")
        assert fingerprint() == original
    monkeypatch.setenv("ISABELLE_BUILD_OPTIONS", "threads=1")
    assert fingerprint() != original
