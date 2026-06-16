from __future__ import annotations

from pathlib import Path

from isabelle_blueprint import doctor as doctor_module
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.config import BlueprintConfig
from isabelle_blueprint.doctor import (
    _check_afp,
    _check_graphviz,
    _check_isabelle,
    run_doctor,
)

_BLUEPRINT = """# Demo

::: lemma {#demo}
title: Demo
isabelle: Demo.demo
status: stub

Statement.
:::
"""


def test_doctor_reports_project_without_errors(tmp_path: Path) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")

    # Inject a definitely-absent executable so the check is hermetic and fast
    # (no PATH probe for a real `isabelle` that may or may not be installed).
    report = run_doctor(tmp_path, isabelle_executable="__isabelle_absent__")

    assert not report.has_errors
    assert any(check.name == "blueprints" and check.status == "ok" for check in report.checks)


def test_doctor_strict_fails_when_blueprint_missing(tmp_path: Path) -> None:
    rc = cli_main(["doctor", str(tmp_path), "--isabelle", "__isabelle_absent__", "--strict"])

    assert rc == 7


def test_doctor_json_output(tmp_path: Path, capsys) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")

    rc = cli_main(["doctor", str(tmp_path), "--isabelle", "__isabelle_absent__", "--json"])

    assert rc == 0
    out = capsys.readouterr().out
    assert '"checks"' in out
    assert '"project_dir"' in out
    # Without --require the additive requirements array is absent.
    assert '"requirements"' not in out


def test_doctor_require_present_tool_exits_zero(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    # Make Graphviz `dot` deterministically present, Isabelle absent.
    monkeypatch.setattr(
        doctor_module.shutil,
        "which",
        lambda exe: "/usr/bin/dot" if exe == "dot" else None,
    )

    rc = cli_main([
        "doctor",
        str(tmp_path),
        "--isabelle",
        "__isabelle_absent__",
        "--require",
        "graphviz",
    ])

    assert rc == 0


def test_doctor_require_absent_tool_exits_five(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    # Force every tool off PATH so the isabelle check is deterministically not ok
    # (no dependency on whether a real `isabelle` happens to be installed).
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _exe: None)
    rc = cli_main([
        "doctor",
        str(tmp_path),
        "--isabelle",
        "__isabelle_absent__",
        "--require",
        "isabelle",
    ])

    assert rc == 5
    out = capsys.readouterr().out
    assert "required tool unavailable: isabelle" in out


def test_doctor_require_json_reports_requirements(tmp_path: Path, capsys, monkeypatch) -> None:
    import json

    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    monkeypatch.setattr(
        doctor_module.shutil,
        "which",
        lambda exe: "/usr/bin/dot" if exe == "dot" else None,
    )

    rc = cli_main([
        "doctor",
        str(tmp_path),
        "--isabelle",
        "__isabelle_absent__",
        "--require",
        "graphviz",
        "--require",
        "isabelle",
        "--json",
    ])

    assert rc == 5
    payload = json.loads(capsys.readouterr().out)
    reqs = {entry["tool"]: entry for entry in payload["requirements"]}
    assert reqs["graphviz"] == {"tool": "graphviz", "available": True, "required": True}
    assert reqs["isabelle"] == {"tool": "isabelle", "available": False, "required": True}


def test_doctor_require_rejects_unknown_tool(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["doctor", str(tmp_path), "--require", "rustc"])
    # argparse rejects invalid choices with exit code 2 at parse time.
    assert excinfo.value.code == 2


def _config(tmp_path: Path, **kwargs) -> BlueprintConfig:
    defaults = dict(
        project_root=tmp_path,
        blueprint_path=tmp_path / "blueprint.md",
        build_dir=tmp_path / "build",
        site_dir=tmp_path / "site",
    )
    defaults.update(kwargs)
    return BlueprintConfig(**defaults)


def test_doctor_config_load_error_short_circuits(tmp_path: Path) -> None:
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    (tmp_path / "isabelle-blueprint.toml").write_text("this is = not = valid", encoding="utf-8")

    report = run_doctor(tmp_path, isabelle_executable="__isabelle_absent__")

    config_checks = [c for c in report.checks if c.name == "config"]
    assert config_checks and config_checks[0].status == "error"
    assert report.has_errors


def test_check_graphviz_found(monkeypatch) -> None:
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _exe: "/usr/bin/dot")
    check = _check_graphviz()
    assert check.status == "ok"
    assert "dot" in check.message


def test_check_isabelle_runs_version(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _exe: "/opt/isabelle")

    class _Proc:
        returncode = 0
        stdout = "Isabelle2024: April 2024"
        stderr = ""

    monkeypatch.setattr(doctor_module.subprocess, "run", lambda *a, **k: _Proc())
    check = _check_isabelle(_config(tmp_path), isabelle_executable=None)
    assert check.status == "ok"
    assert "Isabelle2024" in check.message


def test_check_isabelle_version_mismatch_warns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _exe: "/opt/isabelle")

    class _Proc:
        returncode = 0
        stdout = "Isabelle2024"
        stderr = ""

    monkeypatch.setattr(doctor_module.subprocess, "run", lambda *a, **k: _Proc())
    check = _check_isabelle(
        _config(tmp_path, isabelle_version="Isabelle2025"), isabelle_executable=None
    )
    assert check.status == "warning"
    assert "Expected" in check.message


def test_check_afp_not_required(tmp_path: Path) -> None:
    [check] = _check_afp(_config(tmp_path))
    assert check.status == "ok"
    assert "not required" in check.message


def test_check_afp_required_but_unconfigured(tmp_path: Path) -> None:
    [check] = _check_afp(_config(tmp_path, afp_required=True))
    assert check.status == "error"


def test_check_afp_root_missing(tmp_path: Path) -> None:
    [check] = _check_afp(_config(tmp_path, afp_root=tmp_path / "no-afp", afp_required=True))
    assert check.status == "error"
    assert "does not exist" in check.message


def test_check_afp_entry_missing(tmp_path: Path) -> None:
    afp = tmp_path / "afp"
    afp.mkdir()
    [check] = _check_afp(_config(tmp_path, afp_root=afp, afp_entry="Missing_Entry"))
    assert check.status == "warning"
    assert "entry not found" in check.message.lower()


def test_check_afp_ok(tmp_path: Path) -> None:
    afp = tmp_path / "afp"
    (afp / "thys" / "Good_Entry").mkdir(parents=True)
    [check] = _check_afp(_config(tmp_path, afp_root=afp, afp_entry="Good_Entry"))
    assert check.status == "ok"

