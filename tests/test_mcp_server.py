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
    assert {"critical_path", "impact", "stats", "path"} <= read_only_names
    assert {"history", "compat", "suggest_facts", "staleness", "burndown"} <= read_only_names
    assert "portfolio" in read_only_names
    assert "agent_run_plan" in read_only_names
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

    path = _direct_tool_result(server, "path", {"source": "main", "target": "base"})
    assert path["connected"] is True
    assert path["shortest_path"] == ["main", "base"]
    assert path["distance"] == 1

    stats = _direct_tool_result(server, "stats", {})
    assert stats["project"] == "mcp-test"
    assert stats["total_attempts"] == 0


def test_mcp_agent_run_plan_is_read_only(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    plan = _direct_tool_result(
        server, "agent_run_plan", {"command": "solver --in {prompt_file} --node {node_id}"}
    )
    assert plan["task"]["node_id"] == "main"
    assert plan["command_argv_preview"][0] == "solver"
    assert plan["command_argv_preview"][-1] == "main"
    assert any(part.endswith(".md") for part in plan["command_argv_preview"])
    assert plan["command_error"] is None
    assert plan["cli_argv"][:2] == ["isabelle-blueprint", "agent-run"]
    assert plan["outcome_mapping"]["spawn_error"] == "blocked"
    assert "CLI-only" in plan["execution_note"]
    # The planning tool must never execute or write the prompt file.
    assert not (tmp_path / "build" / "agent-run").exists()

    malformed = _direct_tool_result(server, "agent_run_plan", {"command": "solver {bogus}"})
    assert "unknown command placeholder" in malformed["command_error"]
    assert malformed["command_argv_preview"] is None

    without_command = _direct_tool_result(server, "agent_run_plan", {})
    assert without_command["command_argv_preview"] is None
    assert without_command["cli_argv"][-2:] == ["--command", "<solver> {prompt_file}"]

    # A command that omits {prompt_file} is permitted by the planner, but the
    # suggested cli_argv must stay runnable by mirroring --allow-missing-prompt.
    missing_prompt = _direct_tool_result(
        server, "agent_run_plan", {"command": "solver --quiet"}
    )
    assert missing_prompt["command_error"] is None
    assert missing_prompt["command_argv_preview"] == ["solver", "--quiet"]
    assert "--allow-missing-prompt" in missing_prompt["cli_argv"]
    assert "--allow-missing-prompt" not in plan["cli_argv"]


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


def test_mcp_preview_rename_node_dry_run(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    result = _direct_tool_result(
        server, "preview_rename_node", {"old_id": "base", "new_id": "renamed_base"}
    )

    assert result["dry_run"] is True


def test_mcp_preview_rename_node_malformed_config_raises_blueprint_error(tmp_path: Path) -> None:
    # preview_rename_node loads only the config; a malformed TOML must surface as
    # a BlueprintError (the user-facing type) rather than leaking a raw
    # ValueError/OSError from load_config.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "oops\n', encoding="utf-8"  # unterminated string
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError)) as excinfo:
        _direct_tool_result(
            server, "preview_rename_node", {"old_id": "base", "new_id": "x"}
        )
    assert "could not load configuration" in str(excinfo.value)


@pytest.mark.parametrize("tool_name", ["compat", "history", "burndown", "theory_index"])
def test_mcp_config_only_tools_wrap_malformed_config(tmp_path: Path, tool_name: str) -> None:
    # compat/history/burndown/theory_index read only the config (history/burndown
    # work even when the blueprint can't parse). A malformed isabelle-blueprint.toml
    # must still surface as a BlueprintError, not a leaked ValueError/OSError.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "oops\n', encoding="utf-8"  # unterminated string
    )
    server = build_server(tmp_path)

    with pytest.raises((BlueprintError, ToolError)) as excinfo:
        _direct_tool_result(server, tool_name, {})
    assert "could not load configuration" in str(excinfo.value)


_STALE_BLUEPRINT = """# Stale MCP test

::: definition {#base}
title: Base
isabelle: Demo.base
status: broken

BASE.
:::

::: theorem {#main}
title: Main
isabelle: Demo.main
uses:
  - base
status: proved

MAIN.
:::
"""


def test_mcp_staleness_tool_and_resource(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "stale-mcp"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_STALE_BLUEPRINT, encoding="utf-8")
    server = build_server(tmp_path)

    result = _direct_tool_result(server, "staleness", {"top": 5})
    assert result["project"] == "stale-mcp"
    assert result["stale_count"] == 1
    stale = result["stale_nodes"][0]
    assert stale["node_id"] == "main"
    assert stale["severity"] == "problem"

    contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://staleness"))))
    payload = json.loads(contents[0].content)
    assert payload["stale_nodes"][0]["node_id"] == "main"


def test_mcp_burndown_tool_and_resource(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    empty = _direct_tool_result(server, "burndown", {})
    assert empty["status"] == "no_history"
    assert empty["trends_path"].endswith("trends.json")

    trends_path = tmp_path / "build" / "trends.json"
    trends_path.parent.mkdir(parents=True, exist_ok=True)
    trends_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "timestamp": f"2026-06-0{day}T00:00:00Z",
                        "proved_count": proved,
                        "formal_target_count": 10,
                    }
                    for day, proved in ((1, 0), (2, 2), (3, 4), (4, 6), (5, 8))
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _direct_tool_result(server, "burndown", {"limit": 2})
    assert result["status"] == "on_track"
    assert result["eta_date"] == "2026-06-06"
    assert result["forecast"]["net_burndown_per_day"] == 2.0
    assert len(result["points"]) == 2

    contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://burndown"))))
    payload = json.loads(contents[0].content)
    assert payload["status"] == "on_track"
    assert payload["eta_date"] == "2026-06-06"


def test_mcp_portfolio_tool_and_resource(tmp_path: Path) -> None:
    # Root is the default mcp-test project (1/2 proved); add a second project
    # under the launch root so the roll-up spans more than one project.
    _write_project(tmp_path)
    sub = tmp_path / "extra"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "extra"\n', encoding="utf-8"
    )
    (sub / "blueprint.md").write_text(
        "# extra\n\n"
        "::: lemma {#solo}\n"
        "title: Solo\n"
        "isabelle: Demo.solo\n"
        "status:\n  formal: proved\n\n"
        "SOLO.\n"
        ":::\n",
        encoding="utf-8",
    )
    server = build_server(tmp_path)

    result = _direct_tool_result(server, "portfolio", {})
    assert result["schema_version"] == 1
    assert result["totals"]["project_count"] == 2
    assert result["totals"]["proved_count"] == 2
    assert result["totals"]["formal_target_count"] == 3
    ids = {project["id"] for project in result["projects"]}
    assert ids == {".", "extra"}

    contents = list(asyncio.run(server.read_resource(AnyUrl("blueprint://portfolio"))))
    payload = json.loads(contents[0].content)
    assert payload["totals"]["project_count"] == 2
    assert {project["id"] for project in payload["projects"]} == {".", "extra"}


def test_portfolio_discovery_matches_mcp_catalog(tmp_path: Path) -> None:
    # The portfolio module re-implements project discovery; guard against it
    # drifting from the MCP catalog's discovery on a mixed directory tree.
    from isabelle_blueprint.mcp_server import _discover_project_roots
    from isabelle_blueprint.report.portfolio import discover_project_roots

    _write_project(tmp_path)  # root is a project
    _write_project(tmp_path / "alpha")
    _write_project(tmp_path / "alpha" / "nested")  # nested: must be pruned
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_project(tmp_path / "build" / "ghost")  # inside skip dir: ignored

    assert discover_project_roots(tmp_path) == _discover_project_roots(tmp_path)


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


def test_mcp_record_attempt_rejects_bad_outcome_and_unknown_node(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path, allow_writes=True)

    with pytest.raises((BlueprintError, ToolError), match="unknown memory outcome"):
        _direct_tool_result(
            server,
            "record_attempt",
            {"node_id": "main", "outcome": "bogus", "summary": "x"},
        )

    with pytest.raises((BlueprintError, ToolError), match="unknown node id"):
        _direct_tool_result(
            server,
            "record_attempt",
            {"node_id": "ghost", "outcome": "failed", "summary": "x"},
        )


def test_mcp_assign_node_sets_and_clears_when_enabled(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path, allow_writes=True)

    set_result = _direct_tool_result(
        server, "assign_node", {"node_id": "main", "owner": "alice", "note": "lead"}
    )
    assert set_result["changed"] is True
    assert set_result["assignment"]["owner"] == "alice"
    assert set_result["assignment"]["note"] == "lead"
    store = json.loads((tmp_path / ".isabelle-blueprint" / "assignments.json").read_text())
    assert store["nodes"]["main"]["owner"] == "alice"

    clear_result = _direct_tool_result(
        server, "assign_node", {"node_id": "main", "clear": True}
    )
    assert clear_result["changed"] is True
    assert clear_result["assignment"] is None


def test_mcp_assign_node_rejects_blank_and_whitespace_owner(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path, allow_writes=True)

    # Empty owner and whitespace-only owner are both rejected -- the latter
    # previously slipped through (truthy) and persisted a junk blank-owner record.
    with pytest.raises((BlueprintError, ToolError), match="owner is required"):
        _direct_tool_result(server, "assign_node", {"node_id": "main"})
    with pytest.raises((BlueprintError, ToolError), match="owner is required"):
        _direct_tool_result(server, "assign_node", {"node_id": "main", "owner": "   "})
    assert not (tmp_path / ".isabelle-blueprint" / "assignments.json").exists()


def test_mcp_assign_node_strips_owner_whitespace(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path, allow_writes=True)

    result = _direct_tool_result(
        server, "assign_node", {"node_id": "main", "owner": "  bob  "}
    )
    assert result["assignment"]["owner"] == "bob"


def test_mcp_list_assignments_is_read_only_and_mirrors_store(tmp_path: Path) -> None:
    _write_project(tmp_path)

    # Available on a default (read-only) server -- no --allow-writes needed.
    read_only = build_server(tmp_path)
    assert "list_assignments" in {t.name for t in asyncio.run(read_only.list_tools())}

    empty = _direct_tool_result(read_only, "list_assignments", {})
    assert empty["assignments"] == []

    # Seed an assignment via the write tool, then read it back read-only.
    writable = build_server(tmp_path, allow_writes=True)
    _direct_tool_result(
        writable, "assign_node", {"node_id": "main", "owner": "alice", "note": "lead"}
    )
    listed = _direct_tool_result(read_only, "list_assignments", {})
    owners = {item["node_id"]: item["owner"] for item in listed["assignments"]}
    assert owners["main"] == "alice"


def test_mcp_assignments_resource_registered(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)
    uris = {str(r.uri) for r in asyncio.run(server.list_resources())}
    assert "blueprint://assignments" in uris


def test_mcp_prove_task_prompt_is_registered_and_renders(tmp_path: Path) -> None:
    _write_project(tmp_path)
    server = build_server(tmp_path)

    # prove_task is the only @server.prompt; assert it is discoverable...
    prompt_names = {p.name for p in asyncio.run(server.list_prompts())}
    assert "prove_task" in prompt_names

    # ...and that it renders the ready task's prompt body.
    result = asyncio.run(server.get_prompt("prove_task", {}))
    text = result.messages[0].content.text
    assert "Acceptance criteria" in text


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


def test_mcp_theory_index_warns_on_missing_root(tmp_path: Path) -> None:
    # A configured root that is absent on disk must be surfaced as a warning
    # (not silently dropped) when another root still resolves theories.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "missing"\n\n[isabelle]\ndirs = ["a", "gone"]\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_demo_session(tmp_path / "a")
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    assert len(payload["source_roots"]) == 1
    assert any("does not exist" in warning for warning in payload["warnings"])


def test_mcp_theory_index_warns_on_empty_root(tmp_path: Path) -> None:
    # A configured root that exists but resolves no theory files must be recorded
    # rather than silently contributing nothing to the index.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "empty"\n\n[isabelle]\ndirs = ["a", "blank"]\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_demo_session(tmp_path / "a")
    (tmp_path / "blank").mkdir()
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    assert len(payload["source_roots"]) == 1
    assert any("resolved no theory files" in warning for warning in payload["warnings"])


def test_mcp_theory_index_translates_cli_session_hint(tmp_path: Path) -> None:
    # The ambiguous-session ValueError carries CLI guidance ("pass --session NAME").
    # When it is collected as a per-root warning it must be rephrased for MCP
    # callers, who pass a `session` argument instead of a command-line flag.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "hint"\n\n[isabelle]\ndirs = ["a", "ambig"]\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")
    _write_demo_session(tmp_path / "a")
    ambiguous = tmp_path / "ambig"
    ambiguous.mkdir()
    (ambiguous / "ROOT").write_text(
        "session One = HOL +\n  theories\n    A\n\n"
        "session Two = HOL +\n  theories\n    B\n",
        encoding="utf-8",
    )
    server = build_server(tmp_path)

    payload = _direct_tool_result(server, "theory_index", {})
    assert {t["name"] for t in payload["theories"]} == {"A", "B"}
    hints = [w for w in payload["warnings"] if "multiple sessions" in w]
    assert hints
    assert all("--session" not in warning for warning in hints)
    assert any("`session`" in warning for warning in hints)


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
