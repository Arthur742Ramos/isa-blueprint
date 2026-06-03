from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
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


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "mcp-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def _direct_tool_result(server, name: str, arguments: dict[str, object]) -> dict[str, object]:
    _content, structured = asyncio.run(server.call_tool(name, arguments))
    return structured
