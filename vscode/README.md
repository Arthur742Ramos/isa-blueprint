# IsabelleBlueprint VS Code Extension

This extension surfaces the generated IsabelleBlueprint status file in VS Code.
Run `isabelle-blueprint check` or `isabelle-blueprint report` first so
`build/project.json` exists, then use the proof-cockpit **Blueprint Nodes**
explorer view.

Features:

- Explorer tree grouped into ready, problem, stale/named, blocked, and complete
  proof work.
- Inline diagnostics on source lines for missing, stale, broken, or tainted nodes.
- Refresh command and file watcher for `build/project.json`.
- A status bar cockpit showing coverage, ready/problem counts, stale-report state,
  and a shortcut to the generated dashboard.
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

**Run Lint** and **Run Gate** use the same shell-free `execFile` path as the
other CLI commands. Their stdout/stderr and gate failure details appear in the
`IsabelleBlueprint` output channel. Both analyses are read-only, so they leave
the current editor diagnostics in place; run **Check** or **Report** to
regenerate `build/project.json` and refresh diagnostics from new project state.
