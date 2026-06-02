from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint import __version__
from isabelle_blueprint.cli import main as cli_main


def test_cli_agent_context_json_is_clean_and_project_relative(
    tmp_path: Path,
    capsys,
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(["agent-context", str(tmp_path), "--json", "--max-tasks", "1"])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert data["tool_version"] == __version__
    assert data["project"]["name"] == "Agent context"
    assert data["health"] == "ready"
    assert data["ready_task_count"] == 2
    assert data["ready_tasks_truncated"] is True
    assert data["suggested_next_task"] == "task-main"
    assert data["ready_tasks"][0]["prompt_path"] == "build/prompts/task-main.md"
    assert "\\" not in data["ready_tasks"][0]["prompt_path"]
    assert data["artifacts"]["tasks_json"] == "build/tasks.json"
    assert data["commands"][0]["intent"] == "refresh_context"
    assert [command["intent"] for command in data["commands"]] == [
        "refresh_context",
        "write_context",
        "next_task_prompt",
        "inspect_roadmap",
        "prepare_attempt",
        "record_attempt",
    ]


def test_cli_agent_context_write_outputs_bundle_and_task_prompts(
    tmp_path: Path,
    capsys,
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(["agent-context", str(tmp_path), "--write"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "agent-context json ->" in out
    assert (tmp_path / "build" / "agent-context.json").exists()
    assert (tmp_path / "build" / "agent-context.md").exists()
    assert (tmp_path / "build" / "project.json").exists()
    assert (tmp_path / "build" / "roadmap.json").exists()
    assert (tmp_path / "build" / "prompts" / "task-main.md").exists()
    data = json.loads((tmp_path / "build" / "agent-context.json").read_text(encoding="utf-8"))
    assert data["ready_tasks"][0]["id"] == "task-main"


def test_agent_context_schema_is_packaged(capsys) -> None:
    rc = cli_main(["schema"])

    assert rc == 0
    assert "agent-context" in capsys.readouterr().out


def _write_agent_context_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Agent context"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# Agent context

::: lemma {#base}
title: Base
isabelle: Demo.base
status:
  formal: proved

Base.
:::

::: theorem {#main}
title: Main
isabelle: Demo.main
uses:
  - base
status:
  formal: named

Main.
:::

::: lemma {#helper}
title: Helper
isabelle: Demo.helper
uses:
  - base
status:
  formal: named

Helper.
:::

::: theorem {#later}
title: Later
isabelle: Demo.later
uses:
  - main
status:
  formal: named

Later.
:::
""",
        encoding="utf-8",
    )
