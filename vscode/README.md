# IsabelleBlueprint VS Code Extension

This extension surfaces the generated IsabelleBlueprint status file in VS Code.
Run `isabelle-blueprint check` or `isabelle-blueprint report` first so
`build/project.json` exists, then use the **Blueprint Nodes** explorer view.

Features:

- Explorer tree for every blueprint node.
- Inline diagnostics on source lines for missing, stale, broken, or tainted nodes.
- Refresh command and file watcher for `build/project.json`.
- One-click navigation from the tree to the node source.
- Commands to run `isabelle-blueprint report`, `check`, and `tasks` from the
  active workspace.
- Task prompt preview from the generated `build/prompts/task-<node>.md` files.

Configuration:

```json
{
  "isabelleBlueprint.projectJson": "build/project.json",
  "isabelleBlueprint.cliPath": "isabelle-blueprint"
}
```
