from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.status_overview import build_status_overview, render_status_overview


def _node(
    node_id: str,
    formal: FormalStatus,
    *,
    fact: str | None = None,
    uses: list[str] | None = None,
    kind: NodeKind = NodeKind.LEMMA,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        uses=uses or [],
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(formal=formal),
    )


def test_status_overview_reports_next_ready_task() -> None:
    project = BlueprintProject.from_nodes(
        "status-test",
        [
            _node("a", FormalStatus.PROVED, fact="Demo.a"),
            _node("b", FormalStatus.NAMED, fact="Demo.b", uses=["a"]),
            _node("c", FormalStatus.NAMED, fact="Demo.c", uses=["b"]),
        ],
    )

    overview = build_status_overview(project, generate_tasks(project))

    assert overview.health == "ready"
    assert overview.metrics.coverage_percent == 33
    assert overview.ready_task_count == 1
    assert overview.next_task is not None
    assert overview.next_task.node_id == "b"
    assert overview.to_dict()["next_task"]["target_fact"] == "Demo.b"  # type: ignore[index]
    assert "top_ready_tasks" not in overview.to_dict()


def test_status_overview_can_include_top_ready_tasks() -> None:
    project = BlueprintProject.from_nodes(
        "status-test",
        [
            _node("base", FormalStatus.PROVED, fact="Demo.base"),
            _node(
                "main",
                FormalStatus.NAMED,
                fact="Demo.main",
                uses=["base"],
                kind=NodeKind.THEOREM,
            ),
            _node("helper", FormalStatus.NAMED, fact="Demo.helper", uses=["base"]),
            _node(
                "later",
                FormalStatus.NAMED,
                fact="Demo.later",
                uses=["main"],
                kind=NodeKind.THEOREM,
            ),
        ],
    )

    overview = build_status_overview(project, generate_tasks(project), top_task_count=2)

    assert overview.next_task is not None
    assert overview.top_ready_tasks is not None
    assert [task.node_id for task in overview.top_ready_tasks] == ["main", "helper"]
    data = overview.to_dict()
    assert data["next_task"] == data["top_ready_tasks"][0]  # type: ignore[index]


def test_status_overview_preserves_unknown_coverage() -> None:
    project = BlueprintProject.from_nodes(
        "unstarted",
        [_node("a", FormalStatus.MISSING)],
    )

    overview = build_status_overview(project, generate_tasks(project))

    assert overview.health == "unstarted"
    assert overview.metrics.coverage_percent is None
    assert overview.to_dict()["metrics"]["coverage_percent"] is None  # type: ignore[index]
    assert "Coverage: no formal targets" in render_status_overview(overview)


def test_cli_status_json_output(tmp_path: Path, capsys) -> None:
    _write_status_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "CLI status"
    assert data["health"] == "ready"
    assert data["ready_task_count"] == 1
    assert data["next_task"]["node_id"] == "b"
    assert "top_ready_tasks" not in data


def test_cli_status_human_output(tmp_path: Path, capsys) -> None:
    _write_status_project(tmp_path)

    rc = cli_main(["status", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "CLI status: ready" in out
    assert "Coverage:" in out
    assert "Next task: task-b" in out
    assert "Top ready tasks:" not in out


def test_cli_status_top_tasks_json_output(tmp_path: Path, capsys) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--json", "--top-tasks", "2"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ready_task_count"] == 2
    assert [task["node_id"] for task in data["top_ready_tasks"]] == ["main", "helper"]
    assert data["next_task"] == data["top_ready_tasks"][0]


def test_cli_status_top_tasks_human_output(tmp_path: Path, capsys) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--top-tasks", "2"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Next task: task-main" in out
    assert "Top ready tasks:" in out
    assert "  1. task-main" in out
    assert "  2. task-helper" in out


def _write_status_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "CLI status"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# CLI status

::: lemma {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
uses:
  - a
status:
  formal: named

B.
:::
""",
        encoding="utf-8",
    )


def _write_multi_status_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Multi status"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# Multi status

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


def test_cli_status_filters_top_tasks_by_kind(tmp_path: Path, capsys) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(
        ["status", str(tmp_path), "--json", "--top-tasks", "5", "--kind", "theorem"]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 1
    assert data["filters"]["kind"] == ["theorem"]
    assert data["filters"]["priority"] == []
    assert data["next_task"]["node_id"] == "main"
    assert [task["node_id"] for task in data["top_ready_tasks"]] == ["main"]


def test_cli_status_filters_by_priority_and_difficulty(tmp_path: Path, capsys) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(
        [
            "status",
            str(tmp_path),
            "--json",
            "--top-tasks",
            "5",
            "--priority",
            "high",
            "--difficulty",
            "medium",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ready_task_count"] == 2
    assert data["filters"]["priority"] == ["high"]
    assert data["filters"]["difficulty"] == ["medium"]
    assert data["filtered_ready_task_count"] >= 1
    for task in data["top_ready_tasks"]:
        assert task["priority"] == "high"
        assert task["difficulty"] == "medium"


def test_cli_status_filter_no_match_reports_excluded(
    tmp_path: Path, capsys
) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(
        ["status", str(tmp_path), "--json", "--top-tasks", "5", "--difficulty", "low"]
    )

    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 0
    assert data["filters"]["difficulty"] == ["low"]
    assert data["next_task"] is None
    assert data["top_ready_tasks"] == []
    assert data["health"] == "ready"
    assert "No ready tasks match the requested filters" in captured.err
    assert "difficulty=low" in captured.err
    assert "2 ready tasks were excluded" in captured.err


def test_cli_status_human_output_shows_filter_banner(
    tmp_path: Path, capsys
) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(
        ["status", str(tmp_path), "--top-tasks", "5", "--kind", "theorem"]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Filters: kind=theorem" in out
    assert "Ready tasks: 2 total, 1 match filters" in out
    assert "Next task matching filters: task-main" in out
    assert "Top ready tasks matching filters:" in out
    assert "  1. task-main" in out


def test_cli_status_filters_by_exclude_node(tmp_path: Path, capsys) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(
        [
            "status",
            str(tmp_path),
            "--json",
            "--top-tasks",
            "5",
            "--exclude-node",
            "main",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ready_task_count"] == 2
    assert data["filtered_ready_task_count"] == 1
    assert data["filters"]["exclude_node"] == ["main"]
    assert data["next_task"]["node_id"] == "helper"


def test_cli_status_without_filters_omits_filter_fields(
    tmp_path: Path, capsys
) -> None:
    _write_multi_status_project(tmp_path)

    rc = cli_main(["status", str(tmp_path), "--json", "--top-tasks", "2"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "filters" not in data
    assert "filtered_ready_task_count" not in data

