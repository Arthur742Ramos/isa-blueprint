from __future__ import annotations

import re
from pathlib import Path

import pytest

from isabelle_blueprint.cli import _build_parser
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.templates import TEMPLATES


def test_top_level_help_highlights_common_workflows() -> None:
    help_text = _build_parser().format_help()

    assert "common workflows:" in help_text
    assert "isabelle-blueprint init my-formalization --template agent-ready" in help_text
    assert "isabelle-blueprint init --list-templates" in help_text


def test_init_list_templates_prints_descriptions_without_writing(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(tmp_path)

    rc = cli_main(["init", "--list-templates"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Available templates:" in out
    for name, template in TEMPLATES.items():
        assert name in out
        assert template.description in out
    assert not (tmp_path / "blueprint.md").exists()
    assert not (tmp_path / "isabelle-blueprint.toml").exists()


def test_init_agent_ready_template_writes_task_workflow(tmp_path: Path) -> None:
    rc = cli_main(["init", str(tmp_path), "--template", "agent-ready"])

    assert rc == 0
    assert "Agent-ready blueprint" in (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    workflow = (tmp_path / ".github" / "workflows" / "blueprint.yml").read_text(encoding="utf-8")
    assert "isabelle-blueprint gate ." in workflow
    assert "isabelle-blueprint tasks . --github-issues" in workflow


@pytest.mark.parametrize("template_name", sorted(TEMPLATES))
def test_init_templates_write_pinned_least_privilege_ci(tmp_path: Path, template_name: str) -> None:
    project_dir = tmp_path / template_name
    assert cli_main(["init", str(project_dir), "--template", template_name]) == 0

    workflow = (project_dir / ".github" / "workflows" / "blueprint.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "isabelle-blueprint gate ." in workflow
    for line in workflow.splitlines():
        if "uses:" in line:
            ref = line.split("uses:", 1)[1].split("#", 1)[0].strip()
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), ref


def test_init_on_existing_file_reports_clean_error(tmp_path: Path, capsys) -> None:
    # Pointing init at a path that exists as a regular file used to leak a raw
    # FileExistsError traceback (mkdir); it should be a clean BlueprintError.
    target = tmp_path / "README.md"
    target.write_text("not a directory", encoding="utf-8")

    rc = cli_main(["init", str(target)])

    assert rc == 1
    assert "is not a directory" in capsys.readouterr().err


def test_init_afp_template_writes_required_afp_config(tmp_path: Path) -> None:
    rc = cli_main(["init", str(tmp_path), "--template", "afp"])

    assert rc == 0
    config = (tmp_path / "isabelle-blueprint.toml").read_text(encoding="utf-8")
    assert "required = true" in config
    assert 'entry = "My_AFP_Entry"' in config


def test_init_templates_can_write_latex_blueprints(tmp_path: Path) -> None:
    for name in TEMPLATES:
        project_dir = tmp_path / name
        rc = cli_main(["init", str(project_dir), "--template", name, "--format", "latex"])

        assert rc == 0
        assert not (project_dir / "blueprint.md").exists()
        blueprint = (project_dir / "blueprint.tex").read_text(encoding="utf-8")
        config = (project_dir / "isabelle-blueprint.toml").read_text(encoding="utf-8")
        assert r"\begin{document}" in blueprint
        assert r"\label{" in blueprint
        assert 'blueprint = "blueprint.tex"' in config
        assert cli_main(["report", str(project_dir)]) == 0
