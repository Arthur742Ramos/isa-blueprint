from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.cli import main as cli_main


def test_init_agent_ready_template_writes_task_workflow(tmp_path: Path) -> None:
    rc = cli_main(["init", str(tmp_path), "--template", "agent-ready"])

    assert rc == 0
    assert "Agent-ready blueprint" in (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    workflow = (tmp_path / ".github" / "workflows" / "blueprint.yml").read_text(encoding="utf-8")
    assert "isabelle-blueprint tasks . --github-issues" in workflow


def test_init_afp_template_writes_required_afp_config(tmp_path: Path) -> None:
    rc = cli_main(["init", str(tmp_path), "--template", "afp"])

    assert rc == 0
    config = (tmp_path / "isabelle-blueprint.toml").read_text(encoding="utf-8")
    assert "required = true" in config
    assert 'entry = "My_AFP_Entry"' in config

