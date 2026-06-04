# MCP server

`isabelle-blueprint-mcp` serves one IsabelleBlueprint project over the
[Model Context Protocol](https://modelcontextprotocol.io/), so AI agents can
inspect formalization status, choose ready proof tasks, retrieve proof prompts,
and record handoff memory without guessing CLI commands or parsing generated
files.

## Install

MCP support is an optional dependency group so the core CLI and GitHub Action
stay lightweight. Install the package with the `mcp` extra before launching
`isabelle-blueprint-mcp`; a plain `pip install isabelle-blueprint` does not
include the MCP runtime dependency:

```bash
pip install "isabelle-blueprint[mcp]"
```

The package installs a second console script for MCP clients:

```bash
isabelle-blueprint-mcp --project-dir .
```

The default transport is `stdio`, which is what most desktop and local-agent MCP
clients expect.

## Client configuration

Point your MCP client at the project root containing `isabelle-blueprint.toml`:

```json
{
  "mcpServers": {
    "isabelle-blueprint": {
      "command": "isabelle-blueprint-mcp",
      "args": ["--project-dir", "/path/to/formalization"]
    }
  }
}
```

Use `--allow-writes` only for agents you trust to update local handoff stores:

```json
{
  "mcpServers": {
    "isabelle-blueprint": {
      "command": "isabelle-blueprint-mcp",
      "args": [
        "--project-dir",
        "/path/to/formalization",
        "--allow-writes"
      ]
    }
  }
}
```

For a remote or long-lived local process, use streamable HTTP:

```bash
isabelle-blueprint-mcp \
  --project-dir /path/to/formalization \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp
```

## Tools

Read tools are always registered:

| Tool | Purpose |
| --- | --- |
| `version` | Package version, schema names, project directory, and write-mode status. |
| `status` | Same project health shape as `isabelle-blueprint status --json`; supports ready-task filters and `top_tasks`. |
| `roadmap` | Staged proof-work roadmap; supports `status`, `stage`, and `kind` filters. |
| `list_tasks` | Ready proof tasks using the same ordering and filters as the CLI. |
| `next_task` | Selected ready task plus the rendered Markdown proof prompt. |
| `agent_context` | Compact handoff bundle matching `agent-context --json`. |
| `explain_node` | Status/blocker explanations for one node or all nodes. |
| `lint` | Structural and quality findings without invoking Isabelle. |
| `graph` | Dependency graph as `json`, `dot`, or `mermaid` without writing files. |
| `schema` | List packaged JSON Schemas or return one schema by name. |
| `doctor` | Local setup diagnostics. |
| `preview_rename_node` | Dry-run node rename preview; never writes files. |

When `--allow-writes` is supplied, two low-risk write tools are also registered:

| Tool | Purpose |
| --- | --- |
| `record_attempt` | Append proof-attempt memory for a known node in `.isabelle-blueprint/agent-memory.json`. |
| `assign_node` | Set or clear per-node ownership in `.isabelle-blueprint/assignments.json`. |

Write tools are launch-gated rather than tool-parameter gated: without
`--allow-writes`, they do not appear in `tools/list`. The server serializes write
tool calls inside one process to avoid overlapping load/modify/write operations.

## Resources

| URI | Content |
| --- | --- |
| `blueprint://project` | Parsed `project.json`-style graph with stored check results applied. |
| `blueprint://nodes/{node_id}` | One node using the stable node JSON shape. |
| `blueprint://tasks` | Ready-task catalog and suggested next task. |
| `blueprint://roadmap` | Unfiltered roadmap payload. |
| `blueprint://agent-context` | Default agent-context payload. |
| `blueprint://schemas/{name}` | Packaged JSON Schema text. |

All project-reading surfaces load the blueprint and then apply the latest stored
`check_report.json`, matching the CLI behavior for `status`, `roadmap`, `tasks`,
`next`, and `agent-context`.

## Prompt

`prove_task` returns the rendered proof prompt for the suggested ready task, or
for a selected node/task id when the optional `node` argument is supplied. It
uses the same task selection and diagnostics as `next_task`.

## Typical agent loop

1. Call `status` to classify the project and inspect the next task.
2. Call `next_task` or the `prove_task` prompt to get the proof handoff.
3. Edit Isabelle theory files outside the MCP server.
4. Run `isabelle-blueprint check` from the agent environment or ask a human/CI to
   run it.
5. If `--allow-writes` is enabled, call `record_attempt` with the outcome and next
   step so future prompts include the attempt memory.
