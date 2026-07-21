# Ecosystem capability parity

IsabelleBlueprint has one canonical CLI and three narrower integration surfaces:
the MCP server, the VS Code extension, and the GitHub Action. Parity is
intentional rather than universal. A command belongs on another surface only
when that surface can preserve its trust boundary and user experience.

[`capability-parity.toml`](capability-parity.toml) is the machine-checked
inventory. It maps canonical CLI commands to MCP tool names, contributed VS
Code command IDs, and Action steps. It also classifies commands that remain
CLI-only. Tests compare the inventory with the CLI parser, MCP registrations,
extension manifest and registrations, and `action.yml`; adding or removing a
capability requires an explicit inventory update.

## Surface policy

- **MCP** favors deterministic structured data and library calls. Read-only
  tools never invoke the CLI. Mutating tools remain behind `--allow-writes`.
  `deps_audit` exposes only the pure comparison phase of `reconcile`; callers
  supply observed Isabelle fact dependencies, and the tool neither invokes
  Isabelle nor writes generated theories. Likewise, `agent_run_plan` and
  `preview_rename_node` expose planning/preview subsets.
- **VS Code** exposes common project workflows and analyses through the
  configured CLI executable. Commands show stdout and stderr in the
  `IsabelleBlueprint` output channel. Read-only analyses do not replace or
  clear diagnostics derived from the loaded project report.
- **GitHub Action** exposes only the fixed CI pipeline stages controlled by
  Action inputs. It is not a generic CLI proxy.

This inventory is additive documentation, not a promise that every command
will appear on every surface. The frozen v1 CLI, JSON, and Action output
contracts remain unchanged.
