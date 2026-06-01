# IsabelleBlueprint VS Code Extension

This extension surfaces the generated IsabelleBlueprint status file in VS Code.
Run `isabelle-blueprint check` or `isabelle-blueprint report` first so
`build/project.json` exists, then use the **Blueprint Nodes** explorer view.

Features:

- Explorer tree for every blueprint node.
- Inline diagnostics on source lines for missing, stale, broken, or tainted nodes.
- Refresh command and file watcher for `build/project.json`.
- One-click navigation from the tree to the node source.
- Commands to run `isabelle-blueprint report`, `check`, `tasks`, `roadmap`, and
  `agent-context` from the active workspace.
- Command to open the CLI-selected next ready task prompt without generating
  prompt files first.
- Task prompt preview from generated `build/prompts/task-<node>.md` files, with
  live CLI fallback for ready nodes when prompt files have not been generated.
- Markdown and LaTeX authoring assistance: snippets, dependency/fact
  completions, go-to-definition for node ids, and quick fixes for missing
  dependencies.

Configuration:

```json
{
  "isabelleBlueprint.projectJson": "build/project.json",
  "isabelleBlueprint.cliPath": "isabelle-blueprint"
}
```
