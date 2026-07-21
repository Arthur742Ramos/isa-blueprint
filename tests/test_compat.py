"""Tests for Isabelle/AFP compatibility checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.config import load_config
from isabelle_blueprint.isabelle.compat import check_compatibility


def test_load_config_reads_version_and_afp_pins(tmp_path: Path):
    afp = tmp_path / "afp"
    afp.mkdir()
    (tmp_path / "isabelle-blueprint.toml").write_text(
        """
        [project]
        name = "Pinned"

        [isabelle]
        session = "Pinned_Session"
        version = "Isabelle2025-2"
        dirs = ["sessions"]

        [afp]
        root = "afp"
        entry = "Some_Entry"
        required = true
        """,
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    assert config.isabelle_version == "Isabelle2025-2"
    assert config.afp_root == afp.resolve()
    assert config.afp_entry == "Some_Entry"
    assert config.afp_required is True
    assert config.isabelle_dirs == [(tmp_path / "sessions").resolve()]


def test_compatibility_report_ok_for_matching_version_and_session(tmp_path: Path, monkeypatch):
    (tmp_path / "ROOT").write_text('session "Demo" = "HOL" +\n', encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text(
        """
        [isabelle]
        session = "Demo"
        version = "Isabelle2025-2"
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr("shutil.which", lambda _exe: "/fake/isabelle")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["isabelle", "version"], 0, stdout="Isabelle2025-2\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = check_compatibility(load_config(tmp_path))
    assert report.ok
    assert report.actual_isabelle_version == "Isabelle2025-2"
    assert report.discovered_sessions == ["Demo"]


def test_compatibility_report_follows_roots_indirection(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (tmp_path / "ROOTS").write_text("sessions\n", encoding="utf-8")
    (sessions / "ROOT").write_text('session "Demo" = "HOL" +\n', encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text(
        """
        [isabelle]
        session = "Demo"
        version = "Isabelle2025-2"
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr("shutil.which", lambda _exe: "/fake/isabelle")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["isabelle", "version"], 0, stdout="Isabelle2025-2\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = check_compatibility(load_config(tmp_path))
    assert report.ok
    assert report.discovered_sessions == ["Demo"]


def test_compatibility_report_errors_on_version_and_session_mismatch(tmp_path: Path, monkeypatch):
    (tmp_path / "ROOT").write_text('session "Other" = "HOL" +\n', encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text(
        """
        [isabelle]
        session = "Demo"
        version = "Isabelle2025-2"
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr("shutil.which", lambda _exe: "/fake/isabelle")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["isabelle", "version"], 0, stdout="Isabelle2024\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = check_compatibility(load_config(tmp_path))
    codes = {issue.code for issue in report.issues}
    assert not report.ok
    assert "isabelle-version-mismatch" in codes
    assert "session-not-found" in codes


def test_compatibility_report_checks_afp_entry(tmp_path: Path, monkeypatch):
    (tmp_path / "ROOT").write_text('session "Demo" = "HOL" +\n', encoding="utf-8")
    afp_root = tmp_path / "afp"
    (afp_root / "thys").mkdir(parents=True)
    (tmp_path / "isabelle-blueprint.toml").write_text(
        """
        [isabelle]
        session = "Demo"

        [afp]
        root = "afp"
        entry = "Missing_Entry"
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _exe: None)
    report = check_compatibility(load_config(tmp_path))
    codes = {issue.code for issue in report.issues}
    assert "afp-entry-not-found" in codes


def _write_min_config(tmp_path: Path, *, name: str = "compat-cli") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n', encoding="utf-8"
    )


def test_cli_compat_json_emits_the_report(tmp_path: Path, capsys) -> None:
    _write_min_config(tmp_path)

    rc = cli_main(["compat", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # The JSON mirrors the on-disk compat report (CompatibilityReport.to_dict).
    assert {"ok", "isabelle_available", "issues", "project_root"} <= set(data)
    assert isinstance(data["issues"], list)


def test_cli_compat_json_matches_disk_report(tmp_path: Path, capsys) -> None:
    _write_min_config(tmp_path)

    rc = cli_main(["compat", str(tmp_path), "--json"])

    assert rc == 0
    stdout = json.loads(capsys.readouterr().out)
    disk = json.loads((tmp_path / "build" / "compat_report.json").read_text(encoding="utf-8"))
    assert stdout == disk


def test_cli_compat_plain_output_unchanged(tmp_path: Path, capsys) -> None:
    _write_min_config(tmp_path)

    rc = cli_main(["compat", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "compat report ->" in out
    assert "{" not in out  # not JSON
