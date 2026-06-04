from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import AnyUrl

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.mcp_server import _roadmap_filters, build_server

_BLUEPRINT = """# MCP test

::: definition {#base}
title: Base
isabelle: Demo.base
status:
  formal: proved

BASE.
:::

::: theorem {#main}
title: Main
isabelle: Demo.main
uses:
  - base
status:
  formal: named

MAIN.
:::
"""


def test_mcp_server_lists_read_tools_and_gates_write_tools(tmp_path: Path) -> None:
    _write_project(tmp_path)

    read_only = build_server(tmp_path)
    read_only_names = {tool.name for tool in asyncio.run(read_only.list_tools())}
    assert {"status", "roadmap", "list_tasks", "next_task", "agent_context"} <= read_only_names
    assert {"critical_path", "impact", "stats"} <= read_only_names
    assert {"history", "compat", "suggest_facts"} <= read_only_names
    assert "record_attempt" not in read_only_names
    assert "assign_node" not in read_only_names

    writable = build_server(tmp_path, allow_writes=True)
    writable_names = {tool.name for tool in asyncio.run(writable.list_tools())}
    assert "record_attempt" in writable_names
    assert "assign_node" in writable_names


def test_mcp_status_and_next_task_payloads(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    status = _direct_tool_result(server, "status", {"top_tasks": 1})
    assert status["health"] == "ready"
    assert status["ready_task_count"] == 1
    assert status["next_task"]["id"] == "task-main"

    next_task = _direct_tool_result(server, "next_task", {})
    assert next_task["task"]["node_id"] == "main"
    assert "Acceptance criteria" in next_task["prompt"]


def test_mcp_analysis_tools_expose_cli_payloads(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    critical = _direct_tool_result(server, "critical_path", {"top": 1})
    assert critical["project"] == "mcp-test"
    assert len(critical["bottlenecks"]) <= 1

    overview = _direct_tool_result(server, "impact", {"top": 1})
    assert overview["node_count"] == 2
    assert len(overview["rankings"]) == 1
    assert overview["rankings"][0]["node_id"] == "base"

    report = _direct_tool_result(server, "impact", {"node": "base"})
    assert report["node_id"] == "base"
    assert report["direct_dependents"] == ["main"]
    assert any(node["node_id"] == "main" for node in report["blast_radius"])

    stats = _direct_tool_result(server, "stats", {})
    assert stats["project"] == "mcp-test"
    assert stats["total_attempts"] == 0


def test_mcp_history_tool_reports_trend_deltas(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    empty = _direct_tool_result(server, "history", {})
    assert empty["entry_count"] == 0
    assert empty["entries"] == []
    assert empty["latest"] is None
    assert empty["trends_path"].endswith("trends.json")

    trends_path = tmp_path / "build" / "trends.json"
    trends_path.parent.mkdir(parents=True, exist_ok=True)
    trends_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "timestamp": "2026-06-01T00:00:00Z",
                        "coverage_percent": 40,
                        "proved_count": 2,
                    },
                    {
                        "timestamp": "2026-06-02T00:00:00Z",
                        "coverage_percent": 60,
                        "proved_count": 5,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = _direct_tool_result(server, "history", {})
    assert summary["entry_count"] == 2
    assert summary["latest"]["coverage_percent"] == 60
    coverage_delta = next(d for d in summary["deltas"] if d["metric"] == "coverage_percent")
    assert coverage_delta["before"] == 40
    assert coverage_delta["after"] == 60
    assert coverage_delta["delta"] == 20

    limited = _direct_tool_result(server, "history", {"limit": 1})
    assert len(limited["entries"]) == 1
    assert limited["entries"][0]["coverage_percent"] == 60


def test_mcp_history_rejects_non_positive_limit(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError), match="limit must be at least 1"):
        _direct_tool_result(server, "history", {"limit": 0})


def test_mcp_compat_tool_is_read_only(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    report = _direct_tool_result(server, "compat", {"isabelle": "definitely-not-isabelle"})
    assert isinstance(report["ok"], bool)
    assert report["isabelle_available"] is False
    assert isinstance(report["issues"], list)
    assert any(issue["code"] == "isabelle-missing" for issue in report["issues"])
    # The MCP tool must not write the compat report file (CLI-only side effect).
    assert not (tmp_path / "build" / "compat_report.json").exists()


def test_mcp_suggest_facts_tool_returns_suggestions(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "suggest_facts", {})
    suggestions = payload["suggestions"]
    assert isinstance(suggestions, list)
    assert payload["count"] == len(suggestions)
    known_ids = {"base", "main"}
    for suggestion in suggestions:
        assert suggestion["node_id"] in known_ids
        assert isinstance(suggestion["suggestions"], list)


def test_mcp_history_and_fact_suggestion_resources(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    history_contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://history"))))
    history = json.loads(history_contents[0].content)
    assert history["entry_count"] == 0

    facts_contents = list(
        asyncio.run(server.read_resource(AnyUrl("blueprint://fact-suggestions")))
    )
    facts = json.loads(facts_contents[0].content)
    assert facts["count"] == len(facts["suggestions"])


def test_mcp_impact_unknown_node_lists_known_ids(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError)) as excinfo:
        _direct_tool_result(server, "impact", {"node": "nope"})
    message = str(excinfo.value)
    assert "unknown node 'nope'" in message
    assert "base" in message and "main" in message


def test_mcp_resources_are_project_scoped_json(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://nodes/main"))))
    node = json.loads(contents[0].content)

    assert node["id"] == "main"
    assert node["uses"] == ["base"]


def test_mcp_record_attempt_writes_memory_when_enabled(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path, allow_writes=True)

    result = _direct_tool_result(
        server,
        "record_attempt",
        {
            "node_id": "main",
            "outcome": "failed",
            "summary": "simp did not close the goal",
            "next_step": "try induction",
        },
    )

    assert result["node_id"] == "main"
    assert result["attempt"]["outcome"] == "failed"
    memory = json.loads((tmp_path / ".isabelle-blueprint" / "agent-memory.json").read_text())
    assert memory["nodes"]["main"]["attempts"][0]["summary"] == "simp did not close the goal"


def test_mcp_lists_and_selects_projects_from_repo_root(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha-project")
    _write_project(tmp_path / "beta", name="beta-project")
    server = build_server(tmp_path, allow_writes=True)

    projects = _direct_tool_result(server, "list_projects", {})
    assert projects["default_project"] is None
    assert [project["id"] for project in projects["projects"]] == ["alpha", "beta"]

    with pytest.raises(ToolError, match="project is required"):
        _direct_tool_result(server, "status", {})

    alpha_status = _direct_tool_result(server, "status", {"project": "alpha", "top_tasks": 1})
    assert alpha_status["health"] == "ready"
    assert alpha_status["next_task"]["node_id"] == "main"

    beta_status = _direct_tool_result(server, "status", {"project": "beta-project"})
    assert beta_status["ready_task_count"] == 1

    beta_attempt = _direct_tool_result(
        server,
        "record_attempt",
        {
            "project": "beta",
            "node_id": "main",
            "outcome": "failed",
            "summary": "needs a different induction",
        },
    )
    assert beta_attempt["memory_file"] == str(
        tmp_path / "beta" / ".isabelle-blueprint" / "agent-memory.json"
    )
    assert not (tmp_path / "alpha" / ".isabelle-blueprint" / "agent-memory.json").exists()


def test_mcp_project_scoped_resources_work_for_repo_root(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha-project")
    _write_project(tmp_path / "beta", name="beta-project")
    server = build_server(tmp_path)

    contents = list(
        asyncio.run(server.read_resource(AnyUrl("blueprint://projects/alpha/nodes/main")))
    )
    node = json.loads(contents[0].content)

    assert node["id"] == "main"
    assert node["uses"] == ["base"]


def test_mcp_launch_dir_project_remains_default_with_child_projects(tmp_path: Path) -> None:
    _write_project(tmp_path, name="root-project")
    _write_project(tmp_path / "child", name="child-project")
    server = build_server(tmp_path)

    projects = _direct_tool_result(server, "list_projects", {})
    assert projects["default_project"] == "root"

    status = _direct_tool_result(server, "status", {"top_tasks": 1})
    assert status["health"] == "ready"
    assert status["next_task"]["node_id"] == "main"

    contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://nodes/main"))))
    node = json.loads(contents[0].content)
    assert node["id"] == "main"


def test_mcp_rejects_project_selectors_outside_catalog(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha-project")
    server = build_server(tmp_path)

    with pytest.raises(ToolError, match="unknown project"):
        _direct_tool_result(server, "status", {"project": "../alpha"})


def test_mcp_roadmap_filters_validate_kind() -> None:
    with pytest.raises(BlueprintError, match="unknown roadmap kind"):
        _roadmap_filters(kind=["not-a-kind"])


def test_mcp_stdio_client_can_list_tools_and_call_status(tmp_path: Path) -> None:
    _write_project(tmp_path)

    async def run_client() -> tuple[set[str], dict[str, object]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "isabelle_blueprint.mcp_server",
                "--project-dir",
                str(tmp_path),
            ],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("status", arguments={"top_tasks": 1})
                return {tool.name for tool in tools.tools}, result.structuredContent

    tool_names, status = asyncio.run(run_client())

    assert "next_task" in tool_names
    assert status["health"] == "ready"
    assert status["next_task"]["node_id"] == "main"


def _write_project(tmp_path: Path, *, name: str = "mcp-test") -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _direct_tool_result(server, name: str, arguments: dict[str, object]) -> dict[str, object]:
    _content, structured = asyncio.run(server.call_tool(name, arguments))
    return structured


_THY_A = (
    "theory A\nimports Main\nbegin\n"
    'definition foo :: "nat" where "foo = 0"\n'
    'lemma base: "foo = 0" by (simp add: foo_def)\n'
    "end\n"
)
_THY_B = (
    "theory B\nimports A\nbegin\n"
    'lemma uses_base: "foo = 0" using base sorry\n'
    "end\n"
)


def _write_demo_session(directory: Path, *, session: str = "Demo") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ROOT").write_text(
        f"session {session} = HOL +\n  theories\n    A\n    B\n", encoding="utf-8"
    )
    (directory / "A.thy").write_text(_THY_A, encoding="utf-8")
    (directory / "B.thy").write_text(_THY_B, encoding="utf-8")
    return directory


def test_mcp_theory_index_tool_registered_and_payload(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _write_demo_session(tmp_path)
    server = build_server(tmp_path)

    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "theory_index" in tool_names

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    assert payload["has_import_cycle"] is False
    assert any(marker["token"] == "sorry" for marker in payload["sorries"])
    assert "B.uses_base" in payload["unreferenced"]
    assert payload["session"] is None
    assert payload["warnings"] == []
    assert all(isinstance(path, str) for path in payload["theory_files"])
    assert len(payload["source_roots"]) == 1


def test_mcp_theory_index_works_with_broken_blueprint(tmp_path: Path) -> None:
    # Source-only analysis must not parse the blueprint, so it still works when
    # blueprint.md is malformed (where status/next_task would fail).
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "broken"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text("::: definition {#oops}\n", encoding="utf-8")
    _write_demo_session(tmp_path)
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError)):
        _direct_tool_result(server, "status", {})

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}


def test_mcp_theory_index_errors_without_sources(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError), match="no .thy files"):
        _direct_tool_result(server, "theory_index", {})


def test_mcp_theory_index_honours_isabelle_dirs_and_session(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "dirs"\n\n[isabelle]\ndirs = ["src"]\nsession = "Demo"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_demo_session(tmp_path / "src")
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    assert payload["session"] == "Demo"
    assert payload["source_roots"][0].endswith("src")


def test_mcp_theory_index_is_best_effort_across_roots(tmp_path: Path) -> None:
    # One configured root lacks the selected session; it must be recorded as a
    # warning instead of aborting the whole index when another root resolves.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "multi"\n\n[isabelle]\ndirs = ["a", "b"]\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_demo_session(tmp_path / "a")
    _write_demo_session(tmp_path / "b", session="Other")
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "theory_index", {"session": "Demo"})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    assert payload["session"] == "Demo"
    assert len(payload["source_roots"]) == 1
    assert any("Demo" in warning for warning in payload["warnings"])


def test_mcp_theory_index_surfaces_ambiguous_session_error(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "ambig"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    (tmp_path / "ROOT").write_text(
        "session One = HOL +\n  theories\n    A\n\n"
        "session Two = HOL +\n  theories\n    B\n",
        encoding="utf-8",
    )
    (tmp_path / "A.thy").write_text(_THY_A, encoding="utf-8")
    (tmp_path / "B.thy").write_text(_THY_B, encoding="utf-8")
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError), match="multiple sessions"):
        _direct_tool_result(server, "theory_index", {})


def test_mcp_theory_index_resources_are_json(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha")
    _write_demo_session(tmp_path / "alpha")
    server = build_server(tmp_path)

    default_contents = list(
        asyncio.run(server.read_resource(AnyUrl("blueprint://theory-index")))
    )
    default_index = json.loads(default_contents[0].content)
    assert {t["name"] for t in default_index["theories"]} == {"A", "B"}

    scoped_contents = list(
        asyncio.run(
            server.read_resource(AnyUrl("blueprint://projects/alpha/theory-index"))
        )
    )
    scoped_index = json.loads(scoped_contents[0].content)
    assert {t["name"] for t in scoped_index["theories"]} == {"A", "B"}
