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


def test_cli_agent_context_filters_embedded_ready_tasks(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(
        ["agent-context", str(tmp_path), "--json", "--kind", "theorem"]
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 1
    assert data["filters"]["kind"] == ["theorem"]
    assert data["filters"]["priority"] == []
    assert data["suggested_next_task"] == "task-main"
    assert [task["id"] for task in data["ready_tasks"]] == ["task-main"]
    assert data["ready_tasks_truncated"] is False


def test_cli_agent_context_filter_no_match_reports_excluded(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(
        ["agent-context", str(tmp_path), "--json", "--difficulty", "low"]
    )

    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 0
    assert data["filters"]["difficulty"] == ["low"]
    assert data["ready_tasks"] == []
    assert data["suggested_next_task"] == "task-main"
    assert "No ready tasks match the requested filters" in captured.err
    assert "difficulty=low" in captured.err


def test_cli_agent_context_filter_argv_propagates_into_commands(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(
        [
            "agent-context",
            str(tmp_path),
            "--json",
            "--kind",
            "theorem",
            "--exclude-node",
            "later",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    commands = {cmd["intent"]: cmd["argv"] for cmd in data["commands"]}

    for intent in ("refresh_context", "write_context", "next_task_prompt"):
        argv = commands[intent]
        assert "--kind" in argv
        assert "theorem" in argv
        assert "--exclude-node" in argv
        assert "later" in argv

    for intent in ("inspect_roadmap", "prepare_attempt", "record_attempt"):
        argv = commands[intent]
        assert "--kind" not in argv
        assert "--exclude-node" not in argv


def test_cli_agent_context_filter_markdown_render(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(["agent-context", str(tmp_path), "--kind", "theorem"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Filters: `kind=theorem`" in out
    assert "Filtered ready tasks: `1`" in out
    assert "## Ready tasks matching filters" in out
    assert "`task-main`" in out
    assert "`task-helper`" not in out
    assert "--kind theorem" in out


def test_cli_agent_context_write_keeps_canonical_tasks_under_filters(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(
        ["agent-context", str(tmp_path), "--write", "--kind", "theorem"]
    )

    assert rc == 0

    tasks_path = tmp_path / "build" / "tasks.json"
    assert tasks_path.exists()
    tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
    task_ids = {task["id"] for task in tasks_data["tasks"]}
    assert task_ids == {"task-main", "task-helper"}
    assert "filters" not in tasks_data
    assert "filtered_task_count" not in tasks_data

    roadmap_path = tmp_path / "build" / "roadmap.json"
    assert roadmap_path.exists()
    roadmap_data = json.loads(roadmap_path.read_text(encoding="utf-8"))
    roadmap_task_ids = {
        item["task_id"]
        for stage in roadmap_data["stages"]
        for item in stage["items"]
    }
    assert "task-main" in roadmap_task_ids
    assert "task-helper" in roadmap_task_ids

    context_path = tmp_path / "build" / "agent-context.json"
    context_data = json.loads(context_path.read_text(encoding="utf-8"))
    assert context_data["ready_task_count"] == 2
    assert context_data["filtered_ready_task_count"] == 1
    assert context_data["filters"]["kind"] == ["theorem"]
    assert [task["id"] for task in context_data["ready_tasks"]] == ["task-main"]

    assert (tmp_path / "build" / "prompts" / "task-main.md").exists()
    assert (tmp_path / "build" / "prompts" / "task-helper.md").exists()


def test_cli_agent_context_without_filters_omits_filter_fields(
    tmp_path: Path, capsys
) -> None:
    _write_agent_context_project(tmp_path)

    rc = cli_main(["agent-context", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "filters" not in data
    assert "filtered_ready_task_count" not in data
    for cmd in data["commands"]:
        for token in (
            "--kind",
            "--priority",
            "--difficulty",
            "--memory-state",
            "--last-outcome",
            "--exclude-node",
        ):
            assert token not in cmd["argv"]


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
