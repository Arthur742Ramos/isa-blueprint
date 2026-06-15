"""Tests for PIDE dump inspection."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.isabelle.dump import apply_dump_report, inspect_dump_dir
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


def _node(node_id: str, fact: str) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(),
    )


def _project() -> BlueprintProject:
    return BlueprintProject.from_nodes(
        "p",
        [
            _node("clean", "Demo.clean"),
            _node("tainted", "Demo.tainted"),
            _node("missing", "Demo.missing"),
        ],
    )


def test_inspect_dump_dir_marks_proved_and_tainted_facts(tmp_path: Path):
    theory_dir = tmp_path / "Demo.Demo" / "theory"
    theory_dir.mkdir(parents=True)
    theory_dir.joinpath("thms").write_text(
        "\x05\x06entity\x06name=Demo.clean\x06xname=clean\x05"
        "\x05\x06entity\x06name=Demo.tainted\x06xname=tainted\x05"
        "Pure.skip_proof",
        encoding="utf-8",
    )

    result = inspect_dump_dir(_project(), tmp_path)
    by_fact = {fact.fact: fact for fact in result.facts}
    assert by_fact["Demo.clean"].exists is True
    assert by_fact["Demo.clean"].proof_status == "proved"
    assert by_fact["Demo.tainted"].proof_status == "tainted"
    assert by_fact["Demo.tainted"].oracles == ["Pure.skip_proof"]
    assert by_fact["Demo.missing"].exists is False


def test_apply_dump_report_updates_project_status(tmp_path: Path):
    theory_dir = tmp_path / "Demo.Demo" / "theory"
    theory_dir.mkdir(parents=True)
    theory_dir.joinpath("thms").write_text(
        "\x05\x06entity\x06name=Demo.clean\x06xname=clean\x05",
        encoding="utf-8",
    )
    project = _project()
    result = inspect_dump_dir(project, tmp_path)
    apply_dump_report(project, result)
    by_id = project.by_id()
    assert by_id["clean"].status.formal == FormalStatus.PROVED
    assert by_id["missing"].status.formal == FormalStatus.NOT_FOUND


def test_apply_dump_report_preserves_status_when_report_failed(tmp_path: Path):
    project = _project()
    by_id = project.by_id()
    by_id["clean"].status.formal = FormalStatus.PROVED
    by_id["tainted"].status.formal = FormalStatus.FOUND
    by_id["missing"].status.formal = FormalStatus.NAMED

    result = inspect_dump_dir(project, tmp_path / "does-not-exist")
    apply_dump_report(project, result)

    assert by_id["clean"].status.formal == FormalStatus.PROVED
    assert by_id["tainted"].status.formal == FormalStatus.FOUND
    assert by_id["missing"].status.formal == FormalStatus.NAMED
    assert by_id["clean"].status.check_error == result.error


def test_inspect_dump_dir_availability_reflects_path_not_ran(tmp_path: Path, monkeypatch):
    """``isabelle_available`` tracks PATH resolution, not whether we ran Isabelle."""
    from isabelle_blueprint.isabelle import dump as dump_module

    monkeypatch.setattr(dump_module.shutil, "which", lambda _exe: "/opt/isabelle/bin/isabelle")
    available = inspect_dump_dir(_project(), tmp_path)
    assert available.ran is False  # offline inspection
    assert available.isabelle_available is True

    monkeypatch.setattr(dump_module.shutil, "which", lambda _exe: None)
    missing = inspect_dump_dir(_project(), tmp_path)
    assert missing.isabelle_available is False


def test_run_dump_timeout_is_graceful(tmp_path: Path, monkeypatch):
    """A dump that exceeds the timeout must not propagate and must leave ran=False."""
    import shutil
    import subprocess

    from isabelle_blueprint.isabelle import dump as dump_module

    monkeypatch.setattr(shutil, "which", lambda _x: "/fake/isabelle")

    def fake_run(cmd, *, cwd=None, timeout=None, encoding="utf-8"):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(dump_module, "run_capture", fake_run)
    project = _project()
    result = dump_module.run_dump(
        project,
        output_dir=tmp_path / "dump",
        session_name="Demo",
        timeout=5,
    )
    assert result.ran is False
    assert "timed out" in (result.error or "").lower()
    # Graceful degradation still attaches reference facts.
    assert result.facts


def _write_dump_project(tmp_path: Path, *, uses: str = "") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "dump-cli"\n', encoding="utf-8"
    )
    uses_line = f"uses: {uses}\n" if uses else ""
    (tmp_path / "blueprint.md").write_text(
        f"# dump-cli\n\n::: lemma {{#a}}\ntitle: A\nisabelle: Demo.a\nstatus: stub\n"
        f"{uses_line}\nStatement.\n:::\n",
        encoding="utf-8",
    )


def test_cli_dump_json_emits_the_report(tmp_path: Path, capsys) -> None:
    _write_dump_project(tmp_path)

    rc = cli_main(["dump", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # The JSON mirrors the on-disk dump report (DumpResult.to_dict).
    assert {"ran", "facts", "isabelle_available"} <= set(data)
    assert data["ran"] is False  # no Isabelle available in CI
    disk = json.loads((tmp_path / "build" / "dump_report.json").read_text(encoding="utf-8"))
    assert data == disk


def test_cli_dump_json_reports_validation_error(tmp_path: Path, capsys) -> None:
    # A dangling dependency makes validation fail before any dump runs.
    _write_dump_project(tmp_path, uses="ghost")

    rc = cli_main(["dump", str(tmp_path), "--json"])

    assert rc == 2
    data = json.loads(capsys.readouterr().out)
    assert data["ran"] is False
    assert data["ok"] is False
    assert any("ghost" in issue for issue in data["issues"])


def test_cli_dump_plain_output_unchanged(tmp_path: Path, capsys) -> None:
    _write_dump_project(tmp_path)

    rc = cli_main(["dump", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "dump report ->" in out
    assert "{" not in out  # not JSON

