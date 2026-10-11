# IsabelleBlueprint VS Code Extension

This extension reads the canonical `isabelle-blueprint snapshot --json` view in
trusted workspaces. Open a configured blueprint project and use the **Blueprint
Nodes** explorer view. Coverage, ready tasks, node statuses and evidence reasons
come from the same read-only service used by the CLI and MCP.

Run `isabelle-blueprint check` to establish native proof evidence.
An `absent` evidence state displays authored claims explicitly; it does not
certify them. If the CLI lacks snapshot support, is unavailable, or the workspace
is untrusted, an existing `build/project.json` supplies historical navigation
only. Historical views have zero proved/ready counts and retain the error reason.

Features:

- Explorer tree grouped into ready, problem, stale/named, blocked, and complete
  proof work.
- Inline diagnostics on source lines for missing, stale, broken, or tainted nodes.
- Refresh command and watchers for configured blueprint/check/dump paths,
  Isabelle theories, ML files, `ROOT`, `ROOTS`, configuration and assignments.
- A status bar cockpit showing coverage, ready/problem counts, stale-report state,
  and a shortcut to the generated dashboard. Project and node tooltips explain
  evidence origin and the actual source, provenance or CLI failure.
- One-click navigation from the tree to the node source.
- **Go to Blueprint Node** and **Open Dashboard** commands, including a guarded
  dashboard render when the configured site is missing.
- Hover summaries and CodeLens affordances in Markdown/LaTeX blueprints for
  opening the matching proof dossier or explaining a node.
- Commands to run `isabelle-blueprint report`, `check`, `lint`, `gate`, `tasks`,
  `roadmap`, and `agent-context` from the active workspace.
- Proof-analytics commands that surface read-only insight in the output panel:
  **Audit Staleness** (`staleness`), **Forecast Burndown** (`burndown`), and
  **Show Critical Path** (`critical-path`).
- Owner annotations in the tree: when `.isabelle-blueprint/assignments.json`
  assigns an owner to a node, the row shows `@owner` and the tooltip lists the
  full owner; the tree refreshes automatically when assignments change.
- Command to open the CLI-selected next ready task prompt without generating
  prompt files first.
- Task prompt preview from generated `build/prompts/task-<node>.md` files, with
  live CLI fallback for ready nodes when prompt files have not been generated.
- Node explanation and memory-recording commands from the tree, plus quick fixes
  for status diagnostics.
- Markdown and LaTeX authoring assistance: snippets, dependency/fact
  completions, go-to-definition for node ids, and quick fixes for missing
  dependencies.

Configuration:

```json
{
  "isabelleBlueprint.projectJson": "build/project.json",
  "isabelleBlueprint.cliPath": "isabelle-blueprint",
  "isabelleBlueprint.sitePath": "site/index.html"
}
```

Source changes immediately clear proof and ready claims while evidence is
pending. Unsaved relevant documents stay pending until saved. Requests coalesce
per workspace root, with one snapshot process at a time; obsolete responses are
discarded. Refresh, focus, configuration and trust changes revalidate evidence.
External settings or installations that have no file watcher are rechecked on
focus or manual refresh. No refresh starts a proof build.

**Run Lint** and **Run Gate** use the same shell-free `execFile` path as the
other CLI commands. Their stdout/stderr and gate failure details appear in the
`IsabelleBlueprint` output channel. Both analyses are read-only, so they leave
the current editor diagnostics in place; run **Check** or **Report** to
refresh canonical evidence after an explicit check or source correction.

For contributors, Node 22 is used in CI. `npm ci && npm test` compiles and runs
behavior tests for decoding, invalidation, source paths and refresh scheduling.
With the Python CLI and MCP extra installed, `npm run test:host` launches an
isolated VS Code 1.90.2 development host and exercises actual editor events and
CLI/MCP parity. On Linux use `xvfb-run -a npm run test:host`.
`ISABELLE_BLUEPRINT_EDITOR_KERNEL_TESTS=1` additionally builds an isolated native
fixture, changes a theory in the editor, checks stale evidence across all three
surfaces, and explicitly rechecks to restore current proof evidence. The pinned
Isabelle CI job runs this mode; ordinary local tests do not build Isabelle.
