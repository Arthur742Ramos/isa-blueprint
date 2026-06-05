# MCP server

`isabelle-blueprint-mcp` serves one IsabelleBlueprint project, or a repository
containing multiple IsabelleBlueprint projects, over the
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

Point your MCP client at either a project root containing `isabelle-blueprint.toml`
or a repository root containing multiple project subdirectories:

```json
{
  "mcpServers": {
    "isabelle-blueprint": {
      "command": "isabelle-blueprint-mcp",
      "args": ["--project-dir", "/path/to/repo-or-formalization"]
    }
  }
}
```

When the launch directory contains more than one IsabelleBlueprint project and is
not itself a project, call `list_projects` first and pass a returned project
`id`, relative path, absolute path, or unique project name as the optional
`project` argument to project-specific tools:

```json
{
  "project": "examples-group-theory",
  "top_tasks": 3
}
```

If the launch directory is itself a project, it remains the default for legacy
clients even when child directories also contain projects. A single discovered
child project is also selected by default. This is separate from
`[project].blueprints`, which combines multiple blueprint files inside one
IsabelleBlueprint project.

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
| `version` | Package version, schema names, launch/default project directories, and write-mode status. |
| `list_projects` | Discovered project catalog with ids, names, paths, and the default project if one is unambiguous. |
| `status` | Same project health shape as `isabelle-blueprint status --json`; supports ready-task filters and `top_tasks`. |
| `roadmap` | Staged proof-work roadmap; supports `status`, `stage`, and `kind` filters. |
| `list_tasks` | Ready proof tasks using the same ordering and filters as the CLI. |
| `next_task` | Selected ready task plus the rendered Markdown proof prompt. |
| `agent_run_plan` | Plans an `agent-run` invocation for the next ready task: returns the selected task, the resolved `command_argv_preview` (placeholders substituted), the `prompt_path`, the exact `cli_argv` to run locally, and the outcome mapping. **Never executes the command or writes the prompt** — it is a read-only planner. Supply `command` to preview substitution; an invalid template is reported in `command_error` rather than raising. |
| `agent_context` | Compact handoff bundle matching `agent-context --json`. |
| `explain_node` | Status/blocker explanations for one node or all nodes. |
| `lint` | Structural and quality findings without invoking Isabelle. |
| `critical_path` | Longest-pole proof-dependency analysis; supports `top` to limit bottlenecks. |
| `impact` | Downstream blast-radius ranking, or one node's impact report when `node` is set (`top` limits rankings; ignored with `node`). |
| `staleness` | Trust audit of `found`/`proved` nodes: flags ones resting on broken/missing (`problem`), unproven (`incomplete`), `stale`, or newer-checked (`outdated`) dependencies, plus cycle members; supports `top` and `max_causes`. |
| `stats` | Agent-memory analytics: attempts, outcomes, and success rates. |
| `history` | Coverage trend history summary from `trends.json`; supports `limit`. Reads only the trend store, so it works even when the blueprint fails to parse. |
| `burndown` | Velocity / ETA-to-full-coverage forecast from `trends.json`; forecasts from the slope of *remaining* work (so a growing target shows up) and reports proved/target/net-burndown velocities. Supports `window` and `limit`; reads only the trend store. |
| `compat` | Isabelle/AFP version-pin and session-visibility check; supports `isabelle`. Read-only (never writes the compat report file). |
| `portfolio` | Workspace-wide roll-up across every discovered project: per-project coverage / health / ready-task counts plus portfolio totals. Takes no `project` argument (it spans the whole launch root); unparseable projects are reported as error entries without failing the roll-up. |
| `suggest_facts` | Fuzzy fact-name suggestions for unresolved formal targets. |
| `theory_index` | Source-only index of Isabelle `.thy` files (cross-theory reference graph, import deps, `sorry`/`oops` markers, unreferenced entries); supports `session`. Never parses the blueprint, so it works in CI, on partial checkouts, and when the blueprint fails to load. Resolves sources from `[isabelle].dirs`/`session` (or a `ROOT`/`.thy` files at the project root) best-effort across roots, echoing `source_roots`/`theory_files` and any per-root `warnings`. |
| `graph` | Dependency graph as `json`, `dot`, or `mermaid` without writing files. |
| `schema` | List packaged JSON Schemas or return one schema by name. |
| `doctor` | Local setup diagnostics. |
| `preview_rename_node` | Dry-run node rename preview; never writes files. |
| `list_assignments` | List recorded per-node ownership (owner/note/updated_at); read-only counterpart to `assign_node`. |

When `--allow-writes` is supplied, two low-risk write tools are also registered:

| Tool | Purpose |
| --- | --- |
| `record_attempt` | Append proof-attempt memory for a known node in `.isabelle-blueprint/agent-memory.json`. |
| `assign_node` | Set or clear per-node ownership in `.isabelle-blueprint/assignments.json`. |

Write tools are launch-gated rather than tool-parameter gated: without
`--allow-writes`, they do not appear in `tools/list`. The server serializes write
tool calls inside one process to avoid overlapping load/modify/write operations.

Running a solver is deliberately **not** an MCP tool. Spawning arbitrary local
processes is a different trust boundary from the server's read/append-JSON
surface, so `agent_run_plan` only *plans* the invocation and hands back the exact
`cli_argv`; actually executing it is left to `isabelle-blueprint agent-run` on the
operator's machine, where the timeout, output cap, and shell-free argv handling
apply.

## Resources

| URI | Content |
| --- | --- |
| `blueprint://projects` | Discovered project catalog. |
| `blueprint://project` | Parsed `project.json`-style graph for the default project, with stored check results applied. |
| `blueprint://nodes/{node_id}` | One node using the stable node JSON shape. |
| `blueprint://tasks` | Ready-task catalog and suggested next task. |
| `blueprint://roadmap` | Unfiltered roadmap payload. |
| `blueprint://agent-context` | Default agent-context payload. |
| `blueprint://history` | Coverage trend history summary for the default project. |
| `blueprint://fact-suggestions` | Fuzzy fact-name suggestions for the default project. |
| `blueprint://theory-index` | Source-only `.thy` index for the default project. |
| `blueprint://staleness` | Trusted-node staleness audit for the default project. |
| `blueprint://assignments` | Recorded per-node ownership for the default project. |
| `blueprint://burndown` | Velocity / ETA-to-full-coverage forecast for the default project. |
| `blueprint://portfolio` | Workspace-wide roll-up across every discovered project (no project-scoped variant). |
| `blueprint://projects/{project}/project` | Parsed project graph for a selected project id. |
| `blueprint://projects/{project}/nodes/{node_id}` | One selected-project node. |
| `blueprint://projects/{project}/tasks` | Selected-project ready-task catalog. |
| `blueprint://projects/{project}/roadmap` | Selected-project roadmap payload. |
| `blueprint://projects/{project}/agent-context` | Selected-project agent-context payload. |
| `blueprint://projects/{project}/history` | Selected-project coverage trend history summary. |
| `blueprint://projects/{project}/fact-suggestions` | Selected-project fuzzy fact-name suggestions. |
| `blueprint://projects/{project}/theory-index` | Selected-project source-only `.thy` index. |
| `blueprint://projects/{project}/staleness` | Selected-project trusted-node staleness audit. |
| `blueprint://projects/{project}/assignments` | Selected-project recorded per-node ownership. |
| `blueprint://projects/{project}/burndown` | Selected-project velocity / ETA forecast. |
| `blueprint://schemas/{name}` | Packaged JSON Schema text. |

Most project-reading surfaces load the blueprint and then apply the latest stored
`check_report.json`, matching the CLI behavior for `status`, `roadmap`, `tasks`,
`next`, and `agent-context`. The source-only surfaces (`history`, `burndown`,
`theory-index`) intentionally skip blueprint parsing so they keep working on
partial checkouts and when the blueprint fails to load.

## Prompt

`prove_task` returns the rendered proof prompt for the suggested ready task, or
for a selected node/task id when the optional `node` argument is supplied. In
multi-project servers, pass the optional `project` argument just like `next_task`.
It uses the same task selection and diagnostics as `next_task`.

## Typical agent loop

1. Call `status` to classify the project and inspect the next task.
2. Call `next_task` or the `prove_task` prompt to get the proof handoff.
3. Edit Isabelle theory files outside the MCP server.
4. Run `isabelle-blueprint check` from the agent environment or ask a human/CI to
   run it.
5. If `--allow-writes` is enabled, call `record_attempt` with the outcome and next
   step so future prompts include the attempt memory.
