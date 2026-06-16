# CLI contract

This document is the **frozen public surface** of the `isabelle-blueprint`
command-line tool as of v1.10.0. Subcommand names, flag names, default values,
and exit-code semantics listed here will not change without a major version
bump. New flags and subcommands may be added in backward-compatible releases
provided the existing ones keep behaving the same way.

Help text in `--help` is authoritative for prose; this document is
authoritative for the contract.

---

## Top-level invocation

```text
isabelle-blueprint [--version] <subcommand> [...]
python -m isabelle_blueprint [--version] <subcommand> [...]
```

Both entry points behave identically. The console script is registered as
`isabelle-blueprint`. `--version` prints `isabelle-blueprint <version>` and
exits 0.

A subcommand is **required**; calling `isabelle-blueprint` with no subcommand
prints help on stderr and exits 2.

Most subcommands accept an optional positional `project_dir` (default: current
working directory). When supplied it must point at a directory containing a
valid `isabelle-blueprint.toml`.

### Global options

`--color {auto,always,never}` (with `--no-color` as an alias for `never`)
controls ANSI colour in the human-readable renders of commands such as `lint`,
`status`, `doctor`, `critical-path`, `impact`, and `staleness`. It is accepted
both before and after the subcommand. The default `auto` enables colour only
when stdout is a TTY and the `NO_COLOR` environment variable is unset, so
machine-readable (`--json`) output and captured text are never colourised.

### MCP entry point

```text
isabelle-blueprint-mcp [--project-dir DIR]
                       [--transport stdio|streamable-http]
                       [--host HOST]
                       [--port PORT]
                       [--path PATH]
                       [--allow-writes]
```

`isabelle-blueprint-mcp` requires the optional `mcp` extra
(`pip install "isabelle-blueprint[mcp]"`). Plain installs
(`pip install isabelle-blueprint`) keep the base CLI and GitHub Action
lightweight and do not install the MCP runtime dependency. The entry point
serves one configured blueprint project, or a repository containing multiple
project subdirectories, over MCP. The default transport is `stdio`;
`streamable-http` uses
`--host` (default `127.0.0.1`), `--port` (default `8000`), and `--path` (default
`/mcp`).

Read tools are always registered: `version`, `list_projects`, `status`,
`roadmap`, `list_tasks`, `next_task`, `agent_run_plan`, `agent_context`,
`explain_node`, `lint`, `critical_path`, `impact`, `stats`, `staleness`,
`history`, `burndown`, `portfolio`, `compat`, `suggest_facts`, `theory_index`,
`graph`, `schema`, `doctor`, `preview_rename_node`, and `list_assignments`. The
write tools `record_attempt` and `assign_node` are registered only with
`--allow-writes`.
Project-specific tools accept an optional `project` selector. It may be a
project id from `list_projects`, a relative path, an absolute path under
`--project-dir`, or a unique configured project name. If the launch directory is
itself a project, it is the default for legacy calls; otherwise multiple
discovered projects require an explicit selector.

Resources include `blueprint://projects`, default-project resources
`blueprint://project`, `blueprint://nodes/{node_id}`, `blueprint://tasks`,
`blueprint://roadmap`, `blueprint://agent-context`, selected-project resources
under `blueprint://projects/{project}/...`, and `blueprint://schemas/{name}`.
The `prove_task` prompt returns the selected ready-task proof prompt and accepts
the same optional `project` selector.

`--allow-writes` registers only the low-risk write tools `record_attempt` and
`assign_node`. Without the flag, write tools are omitted from `tools/list`.
Destructive source rewrites are not exposed; `preview_rename_node` is always
dry-run only. See [`docs/mcp.md`](mcp.md) for the MCP-specific contract and
client configuration examples.

---

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | A `BlueprintError` reached `main()` (e.g. parser/validator error, missing config) |
| `2` | argparse usage error, a structural validation failure on `check`/`dump`, `lint --strict` found an error-severity finding, or `lint --fix` refused to rewrite (duplicate ids or cycles present) |
| `3` | `check --strict` or `dump --strict` ran in degraded mode (Isabelle unavailable, or the build/dump never ran) |
| `4` | `check` found Isabelle but `isabelle build` exited non-zero |
| `5` | A policy gate fired: `--fail-on STATUS` matched a node on `check`/`report`/`status`, `diff --fail-on-regression` found a regression, or `gate` failed one of its checks |
| `6` | `--strict` was passed and the subcommand could not produce its primary side-effect (e.g. `comment --strict` couldn't resolve the PR context) |
| `7` | `doctor --strict` found a setup error |
| `8` | Live serving was requested in CI without `--allow-ci` |
| `9` | `roadmap --strict` found cycles, problem nodes, stale nodes, or missing dependencies |
| `10` | `fmt --check` found a Markdown blueprint that is not in canonical form |

`--strict` is opt-in for every subcommand that exposes it. Without `--strict`,
a missing external dependency is downgraded to an informational message and
exit `0`.

---

## Subcommands

### `init`

```text
isabelle-blueprint init [project_dir] [--force] [--format markdown|latex] [--template NAME]
```

Scaffolds a fresh blueprint project: `blueprint.md` (or `blueprint.tex` with
`--format latex`), `isabelle-blueprint.toml`, and a GitHub Actions workflow.
Fails if any target file already exists unless `--force` is given. `--format`
defaults to `markdown`. `--template` (added in v1.1) accepts `minimal`, `afp`,
`research-paper`, `course-notes`, or `agent-ready`.

### `check`

```text
isabelle-blueprint check [project_dir]
                         [--isabelle PATH]
                         [--timeout SECONDS]
                         [--strict]
                         [--incremental]
                         [--jobs N]
                         [--watch]
                         [--interval SECONDS]
                         [--fail-on STATUS ...]
```

Validates the blueprint structure and, if Isabelle is available, runs the
generated `Blueprint_Check.thy` wrapper through `isabelle build` to confirm
each declared fact exists and isn't tainted by `sorry` / oracles.

- `--isabelle PATH` overrides the `isabelle` binary location.
- `--timeout SECONDS` overrides `[isabelle].timeout` from the config.
- `--strict` exits 3 if Isabelle isn't available or the build never ran, and
  exits 4 if the build ran but `isabelle build` returned non-zero.
- `--incremental` (added in v0.6) reuses results from
  `build/check-cache.json` for facts whose blueprint inputs, theory/session
  pins, and upstream dependencies are unchanged.
- `--jobs N` (added in v0.6) forwards `-j N` to `isabelle build` to
  parallelise upstream session builds.
- `--watch` re-runs the check whenever the blueprint sources change, polling
  every `--interval SECONDS` (default `1.0`). Only blueprint inputs are
  watched; generated reports are excluded to avoid self-triggering.
- `--fail-on STATUS` exits 5 if any node ends in one of the named
  formal statuses. Repeat the flag to select multiple statuses; the alias
  `problem` expands to all problem statuses
  (`not_found`, `broken`, `failed_check`, `tainted`).

### `graph`

```text
isabelle-blueprint graph [project_dir] [--format {all,dot,json,svg,mermaid}]
```

Emits the dependency graph as `build/graph.dot` and `build/graph.json`; also
renders `build/graph.svg` if Graphviz `dot` is on `PATH`.

- `--format` (default `all`) selects which artifacts to emit. `mermaid` writes
  `build/graph.mmd`; `dot`/`json`/`svg` emit just that artifact; `all`
  preserves the historical behaviour and also includes the Mermaid output.

### `lint`

```text
isabelle-blueprint lint [project_dir] [--json] [--format text|json|sarif]
                        [--strict] [--fix] [--fix-dry-run]
```

Runs structural and quality checks over the blueprint and prints findings with
a severity (`error`/`warning`/`info`). Codes include `duplicate-id`,
`missing-dependency`, `cycle`, `broken-formal-status`, `stale-formal-status`,
`empty-statement`, `missing-informal-proof`, `no-isabelle-fact`, and
`isolated-node`.

- `--format` selects the output: `text` (default), `json`, or `sarif` (a
  SARIF 2.1.0 document suitable for GitHub code scanning).
- `--json` is a backwards-compatible alias for `--format json`. Combining
  `--json` with a conflicting `--format` value is an error (exit 1).
- `--strict` exits 2 if any error-severity finding is present.
- `--fix` (added in v1.13) drops `uses` entries that reference undefined node
  ids and rewrites the affected Markdown files in place (LaTeX sources are
  skipped). It refuses to write (exit `2`) when duplicate ids or dependency
  cycles are present. `--fix-dry-run` reports the changes without writing. A
  summary goes to stderr (or the `fix` block of the `--json` payload).

### `diff`

```text
isabelle-blueprint diff <baseline.json> [project_dir] [--json] [--fail-on-regression]
```

Compares the current parsed and checked project against a saved `project.json`
baseline, reporting added/removed nodes, per-node status changes, and
regressions.

- `--json` emits the machine-readable diff.
- `--fail-on-regression` exits 5 if any regression is detected (a proof coming
  undone, a healthy status becoming a problem status, a removed node, or a
  slide down the confidence ladder such as `found` -> `named`/`missing`).

### `history`

```text
isabelle-blueprint history [project_dir] [--json] [--limit N]
```

Summarises `trends.json`, printing the recorded series and the latest deltas.
Reads only the trends file, so it keeps working even when the current blueprint
fails to parse.

- `--json` emits the machine-readable summary.
- `--limit N` restricts the summary to the most recent `N` entries.

### `burndown`

```text
isabelle-blueprint burndown [project_dir] [--json] [--limit N] [--window N] [--fail-when-stalled]
```

Forecasts an ETA to full *proved* coverage from `trends.json`. Like `history`, it
reads only the trend store, so it keeps forecasting when the current blueprint
fails to parse. The ETA is derived from the slope of **remaining** work over time
(so a growing `formal_target_count` is reflected — proving faster does not help if
the target grows just as fast), with proved/target/net-burndown velocities
reported for context.

The `status` is one of `no_history`, `no_targets`, `complete`,
`insufficient_history`, `on_track`, `stalled`, `scope_growing`, `regressing`, or
`beyond_horizon`.

- `--json` emits the machine-readable forecast (including the velocity blocks and
  per-snapshot points).
- `--limit N` only displays the most recent `N` snapshots; the velocity/ETA
  always use the full usable series.
- `--window N` sets how many recent snapshots feed the "recent" velocity used for
  the forecast (default `5`).
- `--fail-when-stalled` exits non-zero (`5`) when work remains but the status is
  `stalled`, `regressing`, `scope_growing`, or `beyond_horizon`.

### `portfolio`

```text
isabelle-blueprint portfolio [root_dir] [--json | --csv | --markdown] [--fail-on-problem] [--min-coverage PCT]
```

Scans `root_dir` (default `.`) for every IsabelleBlueprint project and rolls them
up into a single dashboard: per-project coverage, health, problem/cycle flags, and
ready-task counts, plus portfolio-wide totals. Project discovery mirrors the MCP
catalog — a directory is a project when it holds an `isabelle-blueprint.toml` or
`blueprint.md` marker, nested projects are not descended into, and noisy
build/vendor directories (and dotted/symlinked directories) are skipped.

Loading is best-effort: a project that fails to load (missing blueprint, malformed
TOML, unreadable file) is reported as an `error` entry and excluded from the
aggregate counts rather than aborting the whole roll-up. `coverage_percent` is
`null` when a project (or the portfolio) has no formal targets — treat it as
"unknown", not `0%`.

- `--json` emits the machine-readable roll-up (`schema_version`, `root`, `totals`,
  and a `projects` list).
- `--csv` emits one CSV row per project (a header followed by name, path, counts,
  and status).
- `--markdown` emits the roll-up as Markdown (a heading, a totals line, and a
  project table).
- `--fail-on-problem` exits non-zero (`5`) when any project has problems, has a
  dependency cycle, or fails to load.
- `--min-coverage PCT` is a cross-project coverage floor (an integer from `0` to
  `100`): it exits non-zero (`5`) when any project's `coverage_percent` is below
  `PCT`. Projects with undefined coverage (`coverage_percent` is `null` — no
  formal targets, or a load error) are excluded from failures. In text mode the
  offending projects are named on stderr; in `--json` mode an additive
  `coverage_gate` object is added alongside the existing keys with shape
  `{min_coverage, failing_projects, ok}` (`failing_projects` is the list of
  offending project ids, `ok` is `true` when none fail). The object is present
  only when `--min-coverage` is supplied. Composes with `--fail-on-problem`.

### `assign`

```text
isabelle-blueprint assign [node_id] [--project-dir DIR] [--owner OWNER] [--note NOTE] [--clear] [--json]
```

Records, lists, and clears per-node ownership in an `assignments.json` store.
With no `node_id` it lists current assignments.

- `--owner OWNER` records `OWNER` as the owner of `node_id`.
- `--note NOTE` stores an optional note alongside the assignment.
- `--clear` removes the assignment for `node_id`.
- `--json` emits the machine-readable store.

Mutating operations load the store strictly, so a corrupt file is reported
rather than silently overwritten.

### `rename`

```text
isabelle-blueprint rename <old_id> <new_id> [--project-dir DIR] [--dry-run] [--json]
```

Rewrites blueprint sources (Markdown ids and `uses`, LaTeX `\label`/`\uses`)
and re-keys agent/sync stores so a node id can be changed in one step. Errors
if `new_id` already exists or `old_id` is absent.

- `--dry-run` previews the changes without writing.
- `--json` emits the machine-readable result.

A re-parse safety check runs before any write, and source writes roll back on a
mid-operation failure.

### `fmt`

```text
isabelle-blueprint fmt [project_dir] [--check] [--json]
```

Rewrites Markdown blueprint sources into the canonical interchange form (one
node per `:::` block, fixed metadata order, the full three-axis status block).

- default: rewrites any non-canonical Markdown source in place.
- `--check`: reports drift and exits `10` without writing (CI gate).
- `--json`: emits `{check_only, changed, files}`.

LaTeX sources are reported as skipped (the LaTeX writer emits a whole standalone
document, so in-place reformatting is out of scope).

### `dump`

```text
isabelle-blueprint dump [project_dir]
                        [--isabelle PATH]
                        [--timeout SECONDS]
                        [--from DIR]
                        [--strict]
                        [--json]
```

Runs `isabelle dump` (or inspects a pre-existing dump tree via `--from`) and
applies the PIDE-level proof information to each node's status. `--json` prints
the dump report to stdout (the same JSON written to `[build]/dump_report.json`)
instead of the `dump report -> PATH` line; a blueprint-validation failure is
reported as a JSON object and still exits `2`.

### `compat`

```text
isabelle-blueprint compat [project_dir]
                          [--isabelle PATH]
                          [--strict]
                          [--json]
```

Checks the configured Isabelle and AFP versions against the local install and
reports any session-visibility or version-pin mismatches. `--json` prints the
compatibility report to stdout (the same JSON written to
`[build]/compat_report.json`) instead of the human `report -> PATH` and
per-issue lines.

### `web`

```text
isabelle-blueprint web [project_dir]
                    [--watch]
                    [--serve]
                    [--host HOST]
                    [--port PORT]
                    [--interval SECONDS]
                    [--allow-ci]
```

Renders the static HTML site under `site/`: index, per-node pages, dependency
graph viewer, status table, tasks view, roadmap page, roadmap JSON, and trend
chart. `--watch` (added in v1.1) re-renders when blueprint/check/report inputs
change. `--serve` also starts a local HTTP server on `127.0.0.1:8000` by
default.

The graph page also surfaces a **critical-path panel** (the longest remaining
dependency chain to a goal, plus the highest-leverage bottlenecks) and, when an
`assignments.json` store exists (see `assign`), **owner badges** with an owner
filter over the dependency-levels listing; critical-path nodes are flagged with a
`★` marker on the graph and per-node pages. The same analysis is written to
`site/critical-path.json` for automation. These overlays are additive: with no
assignments the owner filter is omitted, and an all-proved project shows an
empty-state callout instead of a chain.

### `serve`

```text
isabelle-blueprint serve [project_dir]
                         [--host HOST]
                         [--port PORT]
                         [--interval SECONDS]
                         [--allow-ci]
```

Equivalent to `web --watch --serve`, but clearer for local live-preview use.

### `tasks`

```text
isabelle-blueprint tasks [project_dir]
                         [--github-issues]
                         [--github-issues-file FILENAME]
                         [--github-sync]
                         [--github-sync-confirm]
                         [--github-sync-pull]
                         [--repo OWNER/REPO]
                         [--token-env ENVVAR]
                         [--github-sync-state PATH]
                         [--github-label LABEL]
                         [--github-assignee USER]
                         [--kind KIND]
                         [--priority high|medium|low]
                         [--difficulty low|medium|high]
                         [--memory-state fresh|attempted|stale]
                         [--last-outcome OUTCOME]
                         [--exclude-node NODE_OR_TASK]
                         [--tracker-export jira|linear]
                         [--summary]
                         [--watch] [--interval SECONDS]
```

Emits agent-ready task artefacts under `build/`: `tasks.json`, `tasks.md`,
and one `prompts/<id>.md` prompt per actionable obligation. v1.1 adds task
metadata under `metadata` (`priority`, `difficulty`, dependency depth,
downstream blocking count, suggested order, and nearby fact suggestions) plus
top-level `suggested_next_task`. v1.2 adds optional per-task `memory`
summaries read from `.isabelle-blueprint/agent-memory.json`.

`--github-issues` writes issue drafts to `build/github-issues.json` without
calling GitHub. `--github-sync` writes `build/github-sync-plan.json`; by
default this is a dry-run and performs no network calls. Passing
`--github-sync-confirm` creates or updates issues using the token from
`--token-env` (default `GITHUB_TOKEN`) and the repo from `--repo` or
`GITHUB_REPOSITORY`. The sync is idempotent: issue bodies carry a hidden
`isabelle-blueprint:task` marker and the persistent mapping defaults to
`.isabelle-blueprint/github-sync.json`.

`--github-label` and `--github-assignee` (added in v1.6) are repeatable and
affect generated issue drafts and sync payloads. Sync plans also include
`would_close` actions for completed nodes that still have a tracked issue.

`--github-sync-pull` (added in v1.12) is the **read-only** reverse direction: it
fetches each tracked issue's current `open`/`closed` state (a deleted issue is
reported as `missing`) into `build/github-sync-state.json` and notes on stderr
which tasks are closed upstream. It never mutates issues or the blueprint, and
uses the same `--repo`/`--token-env`/`--github-sync-state` inputs.

The ready-task filters mirror `next` and `attempt`: repeat `--kind`,
`--priority`, `--difficulty`, `--memory-state`, `--last-outcome`, or
`--exclude-node` to narrow `tasks.json`, `tasks.md`, and optional
`github-issues.json` issue drafts. Prompt files under `build/prompts/` remain
synchronised with the full ready-task set so filtered runs do not delete
still-ready prompts. `--github-sync` remains a full reconciliation of all ready
tasks; filters only affect `tasks.json`, `tasks.md`, and issue drafts.

`--watch` re-emits the task artefacts whenever the configuration or blueprint
sources change, polling every `--interval` seconds (default `1.0`). Stop with
Ctrl-C.

`--tracker-export {jira,linear}` (added in v1.13) additionally writes a CSV of
the ready tasks to `build/tasks-<tracker>.csv`, ready to import into Jira or
Linear. Difficulty maps to story points / estimate. The CSV honours the same
ready-task filters as the other task artefacts.

`--summary` prints a compact aligned table of the ready tasks
(columns: task id, node id, kind, priority, difficulty, blocked-by count) to
stdout and writes no files. It honours the same ready-task filters and cannot be
combined with the write/side-effect flags
(`--github-issues`/`--github-sync`/`--github-sync-confirm`/`--github-sync-pull`/`--tracker-export`),
which error out rather than being silently ignored.

### `next`

```text
isabelle-blueprint next [project_dir]
                        [--node NODE_OR_TASK]
                        [--json]
                        [--output PATH]
                        [--kind KIND]
                        [--priority high|medium|low]
                        [--difficulty low|medium|high]
                        [--memory-state fresh|attempted|stale]
                        [--last-outcome OUTCOME]
                        [--exclude-node NODE_OR_TASK]
```

Prints the Markdown prompt for the next ready proof task, using the same stable
task ordering as `tasks`, `roadmap`, and `agent-context`. This command is
read-only and does not require prompt files to have been generated first.

- Without `--node`, the selected task is the highest-priority ready task.
- `--node` accepts either a task id such as `task-main` or a blueprint node id
  such as `main`. Exact task ids are resolved before node ids when names could
  overlap.
- `--json` emits a clean payload with `task`, `prompt`, `prompt_path`,
  `message`, filter metadata, and ready-task counts. When no ready task exists,
  the command exits 0 with `task`, `prompt`, and `prompt_path` set to `null`.
  Selecting an unknown or currently blocked/proved node is a `BlueprintError`
  and exits 1.
- `--output PATH` (added in v1.5.2) writes the selected prompt to `PATH`,
  creating parent directories as needed. It does not write anything when no
  ready task exists or when selector validation fails. Text output still prints
  the prompt to stdout and reports the written path on stderr; JSON output
  records the absolute path in `prompt_path`.
- `--kind`, `--priority`, and `--difficulty` (added in v1.7) are repeatable
  filters for interactive selection. They narrow automatic selection and must
  also match an explicit `--node` selector when one is supplied. They do not
  rewrite `build/tasks.json`; use `tasks` for the full canonical queue.
- `--memory-state` (added in v1.7.1) is repeatable and filters tasks by
  prior attempt memory: `fresh` has no recorded attempts, `attempted` has any
  memory summary, and `stale` means the latest attempt was recorded against
  older task inputs.
- `--last-outcome` (added in v1.7.1) is repeatable and filters tasks by the
  latest recorded memory outcome. Choices match `memory --outcome` /
  `attempt --record-outcome` values: `blocked`, `failed`, `needs_human`,
  `note`, or `succeeded`.
- `--exclude-node` (added in v1.7.1) is repeatable and skips matching ready
  node ids or task ids during selection without rewriting the canonical
  `build/tasks.json` queue.

### `attempt`

```text
isabelle-blueprint attempt [project_dir]
                          [--node NODE_OR_TASK]
                          [--output PATH]
                          [--json]
                          [--check]
                          [--isabelle PATH]
                          [--timeout SECONDS]
                          [--incremental]
                          [--jobs N]
                          [--kind KIND]
                          [--priority high|medium|low]
                          [--difficulty low|medium|high]
                          [--memory-state fresh|attempted|stale]
                          [--last-outcome OUTCOME]
                          [--exclude-node NODE_OR_TASK]
                          [--record-outcome OUTCOME]
                          [--summary TEXT]
                          [--details TEXT]
                          [--next-step TEXT]
                          [--actor TEXT]
                          [--tool TEXT]
                          [--max-attempts N]
                          [--sledgehammer]
```

Added in v1.6. Prepares a selected ready proof task for a human or agent proof
attempt. By default it writes the prompt to
`build/attempts/<task-id>.md`. `--node` accepts the same node/task selectors as
`next`. `--check` runs the normal `check` pipeline after writing the prompt.
`--record-outcome` records post-attempt memory and requires a non-empty
`--summary`; valid outcomes match the `memory --outcome` choices.
`--kind`, `--priority`, `--difficulty`, `--memory-state`, and
`--last-outcome`, and `--exclude-node` select from the same filtered ready-task
view as `next`.
Recording an outcome updates the selected node's memory, so a task selected via
`--memory-state fresh` will no longer match `fresh` on the next invocation.

`--json` emits `task`, `prompt_path`, `check`, `memory`, `message`, filter
metadata, and ready-task counts. When no ready task exists, those object fields
are `null` and the command exits 0. If filters exclude existing ready tasks,
`message` reports that filtered state instead of implying the project is empty.

`--sledgehammer` (added in v1.13) appends an Isabelle `sledgehammer` guidance
appendix and a proof skeleton (seeded with the target fact and dependency facts)
to the generated prompt.

### `agent-run`

```text
isabelle-blueprint agent-run [project_dir]
                            [--node NODE_OR_TASK]
                            (--command TEMPLATE | --exec PROGRAM [--arg ARG ...])
                            [--allow-missing-prompt]
                            [--timeout SECONDS]
                            [--max-output-bytes N]
                            [--output PATH]
                            [--dry-run]
                            [--json]
                            [--kind KIND]
                            [--priority high|medium|low]
                            [--difficulty low|medium|high]
                            [--memory-state fresh|attempted|stale]
                            [--last-outcome OUTCOME]
                            [--exclude-node NODE_OR_TASK]
                            [--failure-outcome failed|blocked|needs_human]
                            [--no-record]
                            [--summary TEXT]
                            [--details TEXT]
                            [--next-step TEXT]
                            [--actor TEXT]
                            [--tool TEXT]
                            [--max-attempts N]
                            [--fail-on-failure]
```

Added in v1.10. Selects the next ready task (like `next`/`attempt`), renders its
prompt, runs an **external solver** against it, and records the outcome in agent
memory — closing the select → prompt → run → record loop in one command. The
solver is run **without a shell**; placeholder values are substituted per-argv
token so they cannot inject extra arguments.

Supply the command in one of two mutually exclusive ways:

- `--exec PROGRAM` plus repeated `--arg ARG` is the **argv-native** form and is
  recommended on Windows because it never tokenises backslash paths. Because
  argparse consumes a leading-dash value as an option, pass flag-style arguments
  with the `--arg=-c` form (not `--arg -c`).
- `--command "TEMPLATE"` is a convenience string tokenised with POSIX `shlex`
  quoting.

Both forms support the placeholders `{prompt_file}` (absolute path to the
rendered prompt), `{node_id}`, `{task_id}`, and `{project_dir}`. Unknown
`{placeholder}` tokens are rejected. The command must reference `{prompt_file}`
unless `--allow-missing-prompt` is given, since otherwise the solver never sees
the prompt. The prompt is passed by file (not stdin).

The prompt is written to `build/agent-run/<task>.md` by default; `--output`
overrides this (relative paths resolve against the project dir). `--timeout`
(default 900s) kills the solver and its child process tree. `--max-output-bytes`
(default 10 MiB; `0` disables) caps captured stdout+stderr so a runaway solver
cannot flood the disk. Only bounded tails of stdout/stderr are surfaced and
recorded.

Outcome mapping: exit 0 → `succeeded`; non-zero / timeout / output-limit →
`--failure-outcome` (default `failed`); a spawn error (the executable could not
start) → `blocked`. A spawn error is treated as a harness/config failure, **not**
a proof attempt: it is never recorded against the node and always exits 1.

`--dry-run` selects and renders the task and resolves the command **without**
running it, writing the prompt, or recording memory. `--no-record` runs the
solver but skips the memory write. By default the command exits 0 even when the
solver fails (the harness succeeded); pass `--fail-on-failure` to exit 5 when the
recorded outcome is not `succeeded`. The ready-task filters and `--node`
selector behave exactly as in `next`/`attempt`.

`--json` emits the run result (`task`, `command`, `outcome`, `return_code`,
`recorded`, `memory`, `stdout_tail`, `stderr_tail`, `prompt_path`, filter
metadata, and counts). When no ready task exists those fields are `null` and the
command exits 0.

### `report`

```text
isabelle-blueprint report [project_dir] [--fail-on STATUS ...]
                          [--watch] [--interval SECONDS]
```
Writes the machine-readable status payload:

- `build/project.json` — the full node graph (see
  [`docs/json-contract.md`](json-contract.md))
- `build/report.md` — the Markdown status summary
- `build/summary.json` — compact totals (name, node count, formal status
  counts)
- `build/badge.json` — shields.io endpoint payload
- `build/badge.svg` — self-contained flat SVG badge
- `build/trends.json` — bounded coverage / problem-count history (added in
  v0.8, capped at 500 entries, deduped per `(commit_sha, branch)`)
- `build/fact-suggestions.json` — nearby fact names for unresolved formal
  targets, when suggestions are available (added in v1.1)
- `build/plugin-annotations.json` — status-provider annotations, when plugins
  emit any (wired into report in v1.2)

v1.2 also invokes experimental report-renderer plugins from the
`isabelle_blueprint.report_renderers` entry-point group. Renderers receive
`(project, build_dir)` and may return artifact paths/dicts; failures are
warnings and do not break the built-in report.

When `$GITHUB_OUTPUT` is set, the stable scalar keys
(`coverage_percent`, `node_count`, `formal_target_count`, `proved_count`,
`found_count`, `problem_count`, `has_cycles`) are emitted to it. When
`$GITHUB_STEP_SUMMARY` is set, a compact Markdown summary is appended to it.

`--fail-on STATUS` exits 5 if any node has one of the named formal
statuses after the report is written. Repeat the flag to select multiple
statuses (the `problem` alias expands to all
problem statuses). Report artifacts are still emitted before the gate fires.

`--watch` re-runs the report whenever the configuration or blueprint sources
change (generated outputs under `build/` are ignored to avoid self-triggering),
polling every `--interval` seconds (default `1.0`). Stop with Ctrl-C. A
`--fail-on` gate is evaluated on each pass but does not stop the watch loop.

### `status`

```text
isabelle-blueprint status [project_dir] [--json] [--top-tasks N]
                          [--kind KIND]
                          [--priority high|medium|low]
                          [--difficulty low|medium|high]
                          [--memory-state fresh|attempted|stale]
                          [--last-outcome OUTCOME]
                          [--exclude-node NODE_OR_TASK]
                          [--fail-on STATUS ...]
                          [--watch] [--interval SECONDS]
```

Prints a read-only project health overview without writing report artifacts.
The text form includes the project health classification, coverage, node/problem
counts, cycle status, ready-task count, and the next suggested task when one is
available. `--json` emits the same payload documented by the packaged
`status` JSON Schema.

`--top-tasks N` includes the first `N` ready-task summaries from the same stable
ordering used by `tasks`, `next`, `roadmap`, and `agent-context`. In JSON mode
this adds `top_ready_tasks`; when present, `top_ready_tasks[0]` is the same task
summary as `next_task`.

The ready-task filters mirror `next`, `attempt`, and `tasks`: repeat `--kind`,
`--priority`, `--difficulty`, `--memory-state`, `--last-outcome`, or
`--exclude-node` to narrow `next_task` and `top_ready_tasks`. Project health,
metrics, and `ready_task_count` always describe the full project so a focused
query never changes the reported health classification. When filters are
active, JSON payloads add a `filters` object recording the requested view and a
`filtered_ready_task_count` integer; the text form prints a `Filters:` line
and annotates `Ready tasks: X total, Y match filters`. Filters matching zero
tasks emit a short note to stderr listing how many ready tasks were excluded.

`--fail-on STATUS` exits 5 if any node has one of the named formal
statuses. Repeat the flag to select multiple statuses (the `problem` alias
expands to all problem statuses). The gate is
evaluated against the full project, independent of the ready-task filters.

`--watch` re-renders the overview whenever the configuration or blueprint
sources change, polling every `--interval` seconds (default `1.0`). Stop with
Ctrl-C.

### `roadmap`

```text
isabelle-blueprint roadmap [project_dir]
                           [--json]
                           [--strict]
                           [--status STATUS]
                           [--stage N]
                           [--kind KIND]
                           [--since PATH]
                           [--write]
                           [--out DIR]
```

Prints a staged proof-work roadmap without modifying the project by default.
The roadmap groups nodes into topological dependency stages, classifies each
node as `complete`, `ready`, `blocked`, `problem`, or `stale`, includes blocker
details, and surfaces dependency cycles instead of hiding them.

- `--json` emits the same payload documented by the packaged `roadmap` JSON
  Schema. When filters are supplied, `summary`, `metrics`, `cycles`, and
  suggestions still describe the full roadmap; only `stages` is filtered and a
  `filters` object records the requested view.
- `--strict` exits 9 when the full roadmap has dependency cycles, `problem`
  nodes, `stale` nodes, or blocked nodes caused by missing dependencies. Strict
  checks intentionally ignore filters so CI gates cannot hide failures.
- `--status`, `--stage`, and `--kind` filter the displayed terminal/JSON roadmap
  stages. Each flag can be repeated to include multiple values.
- `--since PATH` compares the full current roadmap against a previous
  `roadmap.json` file, or a directory containing one, and includes added,
  removed, newly complete, newly ready, newly blocked, newly problem, newly
  stale, and otherwise changed nodes. Filtered JSON payloads are rejected as
  baselines because they cannot represent removed or changed nodes reliably.
- `--write` writes `roadmap.json` and `roadmap.md` under the configured
  `build_dir`. Written artifacts are always the unfiltered current roadmap so
  downstream consumers can keep treating `build/roadmap.json` as canonical.
- `--out DIR` changes the directory used by `--write`.

`suggested_next_task` follows the same stable task ordering as `tasks`: priority
(`high`, `medium`, `low`), then difficulty (`low`, `medium`, `high`), then
dependency depth, then node id. `suggested_path` starts from that task when one
is ready; otherwise it starts from the first incomplete node by stage and id. It
then follows the longest incomplete downstream chain, breaking ties by the total
number of downstream nodes blocked and then by node id.

### `critical-path`

```text
isabelle-blueprint critical-path [project_dir]
                                 [--json]
                                 [--markdown]
                                 [--mermaid]
                                 [--csv]
                                 [--top N]
                                 [--goal NODE]
                                 [--min-leverage N]
                                 [--fail-on-cycle]
                                 [--write]
```

Prints a longest-pole analysis of the remaining (incomplete) proof work without
modifying the project. A node is *complete* when its formal status is `found` or
`proved`; everything else is *incomplete*. A *goal* is an incomplete node that no
other incomplete node depends on (terminal remaining work).

- For each goal it computes the *critical path*: the longest chain of incomplete
  dependency ancestors that must be finished first. A node with no incomplete
  dependencies has depth 1. The single deepest goal chain is reported as
  `longest`.
- *Bottlenecks* rank incomplete nodes by *leverage* — the number of incomplete
  transitive dependents they unblock. `--top N` limits how many bottlenecks are
  shown (default 5; must be a positive integer).
- `--goal NODE` focuses the terminal view on a single goal's chain. It does not
  affect `--json` output.
- `--min-leverage N` filters the bottleneck/leverage ranking to nodes that
  unblock at least `N` incomplete descendants (leverage ≥ `N`), focusing on the
  highest-impact work. `N` must be a non-negative integer; the default `0`
  applies no filter. The filter applies to the text, JSON, Markdown, CSV, and
  Mermaid (bottleneck-highlight) outputs.
- Dependency cycles are excluded from depth/path/leverage ranking and reported in
  a separate `cycles` section. References to unknown dependency ids
  (`missing_dependencies`) and complete nodes that still depend on incomplete
  ones (`inconsistent`) are surfaced separately.
- `--json` emits a schema-versioned payload (`schema_version`, `project`,
  `remaining_count`, `goal_count`, `longest`, `goals`, `bottlenecks`, `cycles`,
  `missing_dependencies`, `inconsistent`).
- `--fail-on-cycle` exits 2 when the project contains dependency cycles,
  matching `lint --strict` error semantics.

All ordering is deterministic: dependency and dependent iteration is sorted by
id, goals are ordered by descending depth then id, and bottlenecks by descending
leverage then id.

### `impact`

```text
isabelle-blueprint impact [project_dir]
                          [--node NODE]
                          [--json]
                          [--top N]
```

Prints the *downstream* blast radius of the blueprint without modifying the
project. It is the dependent-facing complement to `critical-path`: where
`critical-path` walks upstream over remaining work, `impact` walks downstream
over *all* dependents regardless of formal status.

- With `--node NODE` it reports a single node's blast radius: its
  `direct_dependents`, the transitive `blast_radius` (each affected node with its
  shortest dependency `distance` from the target), the `affected_goals`
  (terminal targets that rest on the node), and `complete_affected` (currently
  trusted `found`/`proved` dependents that would go stale if the node changed).
  An unknown node id is a fatal error (exit 1).
- Without `--node` it ranks every node by `blast_radius_count` (descending, ties
  broken by id), surfacing the highest-leverage foundations.
- `--top N` limits how many rows the text/JSON output shows (default 10; must be
  a positive integer).
- `--json` emits a schema-versioned payload. The single-node shape has
  `node_id`, `title`, `formal_status`, `in_cycle`, `direct_dependent_count`,
  `blast_radius_count`, `direct_dependents`, `blast_radius`, `affected_goals`,
  and `complete_affected`. The ranking shape has `schema_version`, `project`,
  `node_count`, `rankings`, and `cycles`.

Distances are shortest-hop (BFS) and traversal is cycle-safe. All ordering is
deterministic: blast-radius entries by ascending distance then id, dependent and
goal lists by id, and rankings by descending blast radius then id.

### `agent-context`

```text
isabelle-blueprint agent-context [project_dir]
                                  [--json]
                                  [--markdown]
                                  [--write]
                                  [--max-tasks N]
                                  [--kind KIND]
                                  [--priority high|medium|low]
                                  [--difficulty low|medium|high]
                                  [--memory-state fresh|attempted|stale]
                                  [--last-outcome OUTCOME]
                                  [--exclude-node NODE_OR_TASK]
```

Builds an AI-agent handoff bundle that projects existing status, roadmap, task,
and memory data into one stable context surface. The command is read-only by
default and prints a Markdown brief to stdout.

- `--json` emits the payload documented by the packaged `agent-context` JSON
  Schema. It does not write files unless `--write` is also supplied.
- `--markdown` prints the same Markdown handoff that `--write` records in
  `build/agent-context.md` to stdout. It is mutually exclusive with `--json`; the
  flag itself writes no files, but `--write` may still be passed to also emit
  artifacts, and the ready-task filters compose with it.
- `--write` refreshes `build/project.json`, `build/tasks.json`,
  `build/tasks.md`, `build/prompts/<task-id>.md`, `build/roadmap.json`,
  `build/roadmap.md`, `build/agent-context.json`, and
  `build/agent-context.md`. When combined with `--json`, artifact path messages
  are written to stderr so stdout remains valid JSON.
- `--max-tasks N` caps how many ready-task summaries are embedded in the
  context payload (default 5). `ready_task_count` always reports the full number
  of ready tasks, and `ready_tasks_truncated` tells consumers whether to read
  `build/tasks.json` for the complete queue.

The ready-task filters mirror `next`, `attempt`, `tasks`, and `status`: repeat
`--kind`, `--priority`, `--difficulty`, `--memory-state`, `--last-outcome`, or
`--exclude-node` to narrow the embedded `ready_tasks` list (and its Markdown
rendering). `ready_task_count`, `suggested_next_task`, `suggested_path`,
`warnings`, and `artifacts` continue to describe the full project so the bundle
remains a faithful snapshot. When filters are active, JSON payloads add a
`filters` object and a `filtered_ready_task_count` integer, the Markdown brief
prints `Filters:` and `Filtered ready tasks:` lines, the embedded section is
titled `Ready tasks matching filters`, and the active filter flags are appended
to the `refresh_context`, `write_context`, and `next_task_prompt` command argv
so repeating the recommended commands preserves the same view. `prepare_attempt`
and `record_attempt` deliberately omit the filter flags because they target a
specific suggested node. `--write` always writes canonical (unfiltered)
`build/tasks.json`, `build/tasks.md`, `build/prompts/`, and `build/roadmap.*`;
only `build/agent-context.{json,md}` reflects the active filter view.

All artifact paths embedded in the payload are project-root-relative POSIX-style
strings when the artifact lives under the project root. Existing `status`,
`roadmap`, and `tasks` ordering and classification rules are reused rather than
recomputed independently.
Recommended command bundles include direct `attempt --check` guidance when a
suggested task exists, plus the lower-level memory-recording command for
post-attempt notes.

### `comment`

```text
isabelle-blueprint comment [project_dir] [--preview] [--strict]
```

Builds a Markdown status comment and posts (or updates, idempotently via the
hidden `<!-- isabelle-blueprint:status -->` marker) it on the current pull
request. Added in v0.9.

- Without `--preview`, reads `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and the PR
  number from `GITHUB_EVENT_PATH`. When any of those are missing the command
  prints `pr comment skipped: <reason>` and exits 0 (or 6 with `--strict`).
- `--preview` writes the body to `build/pr-comment.md` instead of touching
  GitHub. Always exits 0.

### `doctor`

```text
isabelle-blueprint doctor [project_dir]
                          [--isabelle PATH]
                          [--json]
                          [--output PATH]
                          [--strict]
```

Diagnoses local setup: Python/package version, config loading, blueprint
validation, writable output directories, Graphviz, Isabelle, and AFP paths.
`--json` emits the structured report. `--strict` exits 7 when any diagnostic is
an error.

### `memory`

```text
isabelle-blueprint memory [project_dir]
                          [--node NODE_ID]
                          [--memory-file PATH]
                          [--record]
                          [--outcome note|blocked|failed|succeeded|needs_human]
                          [--summary TEXT]
                          [--details TEXT]
                          [--next-step TEXT]
                          [--actor TEXT]
                          [--tool TEXT]
                          [--max-attempts N]
                          [--json]
```

Records or lists persistent proof-attempt memory. Without `--record`, the
command lists attempts from `.isabelle-blueprint/agent-memory.json` (or
`--memory-file`). With `--record`, `--node` and a non-empty `--summary` are
required. The command stores a hash of the node's current task inputs so later
task prompts can mark stale attempt notes.

### `explain`

```text
isabelle-blueprint explain [project_dir] [--node NODE_ID] [--json]
```

Explains why nodes are in their current status. This command is intentionally
node-focused: `doctor` diagnoses the local environment, while `explain`
diagnoses blueprint/status issues such as missing dependencies, cycles,
unresolved facts, stale cache entries, tainted proofs, and check failures.

### `import-theory`

```text
isabelle-blueprint import-theory [THEORY.thy ...]
                                      [--root DIR]
                                      [--session NAME]
                                      [--project-name NAME]
                                      [--output PATH]
                                      [--review-output PATH]
                                      [--force]
```

Scans Isabelle theory files for top-level `lemma`, `theorem`, `corollary`,
`proposition`, and `definition` declarations and emits reviewable Markdown
blueprint stubs. This importer is best-effort and intentionally conservative:
it strips nested `(* ... *)` comments and supports common top-level declaration
forms, but generated statements, dependencies, and proof sketches must be
reviewed by a human.

`--review-output PATH` (added in v1.6) writes JSON review metadata including the
line, qualified name, node id, and best-effort dependency suggestions for each
imported fact. `--force` gates both `--output` and `--review-output`.

`--root DIR` (added in v1.10) imports every theory the session `ROOT` under
`DIR` declares instead of explicit file paths, inferring cross-theory `uses`
dependencies from the source reference graph. Dependencies are restricted to
facts that come earlier in a global import-topological order, so the generated
blueprint is acyclic. `--session NAME` selects one session when the ROOT
declares several; a multi-session ROOT with no `--session` is an error. Passing
both file paths and `--root`, or neither, is an error. An import cycle between
theories is reported as an error (import the files individually to bypass).
Importing explicit file paths is unchanged.

### `theory-index`

```text
isabelle-blueprint theory-index [THEORY.thy ...]
                                     [--root DIR]
                                     [--session NAME]
                                     [--json]
                                     [--callers NAME]
                                     [--callees NAME]
                                     [--transitive]
                                     [--deps THEORY]
                                     [--sorry]
                                     [--unreferenced]
```

Source-only analysis of Isabelle `.thy` files; it never invokes the `isabelle`
binary, so it runs on partial checkouts and in CI without a build. Theory files
are resolved from explicit positional paths, `--root DIR` (optionally
`--session NAME`), or — when neither is given — the nearest discovered `ROOT`.

Exactly one section is printed per invocation, in this precedence: `--callers
NAME` and `--callees NAME` list entries on either side of the reference (call)
graph (add `--transitive` for the closure); `--deps THEORY` prints a theory's
imports and importers; `--sorry` lists `sorry`/`oops` markers with their
enclosing entry; `--unreferenced` lists entries no other indexed entry
references. With no section flag, a text summary is printed (or the full
structured index with `--json`); `--json` also formats the individual sections.

`--unreferenced` is a reference-graph signal, **not** dead-code analysis, and
reference matching is best-effort textual (it honours primes and dotted
qualified names but does not model mixfix operators or generated facts such as
`foo.simps`). The ROOT/session parser is adapted from
[`ott2/isabelle-query`](https://github.com/ott2/isabelle-query) (MIT).

### `schema`

```text
isabelle-blueprint schema [name] [--out DIR]
```

Prints a packaged JSON Schema, lists schema names when `name` is omitted, or
writes one/all schemas to `DIR`. Available names are `project`, `graph`,
`tasks`, `summary`, `status`, `roadmap`, `agent-context`, `config`,
`plugin-annotations`, `agent-memory`, `path`, `scorecard`, `tags`, and
`tag-cooccurrence`.

### `stats`

```text
isabelle-blueprint stats [project_dir] [--json]
```

Aggregates agent-memory analytics from
`.isabelle-blueprint/agent-memory.json`: total recorded attempts broken down by
outcome (`succeeded`, `failed`, `blocked`, `needs_human`, `note`), a success
rate per node kind, and a per-node summary of attempt counts and the latest
outcome. The text form is a compact report; `--json` emits the same data in a
lightweight shape. This analytics payload is **not** part of the frozen JSON
contract and may evolve.

### `staleness`

```text
isabelle-blueprint staleness [project_dir]
                             [--json] [--top N] [--max-causes N]
                             [--fail-on-problem]
```

Audits every **trusted** node (formal status `found` or `proved`) and walks its
dependencies to decide whether that trust is justified. A trusted node is
reported as *stale* when it rests on a dependency that undermines it, with each
offending dependency recorded as a *cause* whose `reason` is one of (strongest
first): `missing` (a `uses:` entry points at a non-existent node), `cycle` (the
node is in a dependency cycle), `problem` (a dependency is
`not_found`/`broken`/`tainted`/`failed_check`), `incomplete` (a dependency is
`named`/`missing`, i.e. unproven), `stale_dep` (a dependency is itself `stale`),
or `outdated` (a dependency's `last_checked` is strictly newer than this node's,
so the node was verified before the dependency moved). Reasons roll up into three
severity buckets — `problem`, `incomplete`, `outdated` — and a node's severity is
the strongest bucket among its causes.

`--top` limits the number of stale nodes shown (and kept in `--json`), and
`--max-causes` limits the causes listed per node; `cause_count` always reports
the true total. `--fail-on-problem` exits non-zero (5) when any trusted node has
a `problem`-severity cause (broken or missing dependency), which is useful in
CI. The `--json` payload carries a `schema_version` but, like the other
analytics commands, is **not** part of the frozen JSON contract and may evolve.

### `gate`

```text
isabelle-blueprint gate [project_dir] [--json] [--min-coverage PCT]
                        [--fail-on STATUS ...]
```

Added in v1.13. Runs a single pass/fail CI gate combining lint errors,
dependency cycles, an optional minimum proved-coverage threshold
(`--min-coverage PCT`, which also fails when coverage is undefined), and a status
policy (`--fail-on STATUS`, repeatable; the `problem` alias expands to all
problem formal statuses). Exits `5` on failure, `0` when clean. `--json` emits
the structured gate result.

### `prometheus`

```text
isabelle-blueprint prometheus [project_dir] [--output PATH] [--no-burndown]
```

Added in v1.13. Emits blueprint status as a Prometheus text-exposition payload:
gauges for node/target/proved/found/problem counts, coverage percent, and a
cycles flag, plus an optional burndown ETA gauge. `--output PATH` writes to a
file (e.g. a node-exporter textfile) instead of stdout; `--no-burndown` skips
reading `trends.json`. Always exits 0.

### `hooks`

```text
isabelle-blueprint hooks [project_dir] [--write] [--force]
```

Added in v1.13. Prints a `.pre-commit-config.yaml` wiring `fmt --check` and
`lint --strict`. `--write` writes it into the project; it refuses to overwrite an
existing file unless `--force` is given, exiting `1` in that case. Printing to
stdout (no `--write`) always exits `0`.

### `notify`

```text
isabelle-blueprint notify [project_dir] [--format slack|teams|discord|generic]
                          [--url WEBHOOK] [--send] [--allow-http]
                          [--timeout SECONDS] [--no-burndown]
```

Added in v1.13. Builds a webhook payload summarising blueprint status for the
chosen `--format` (default `slack`). By default it prints the payload (a dry run)
and makes no network calls; `--send` POSTs it to `--url`. Sending is HTTPS-only
unless `--allow-http` is given, uses a `--timeout` (default 10s), and does not
follow redirects. `--no-burndown` skips the burndown ETA.

### `blame`

```text
isabelle-blueprint blame [project_dir] [--node-id ID] [--json]
```

Added in v1.13. Reports per-node provenance by correlating each node's source
file/line with `git log` and recorded agent-memory attempts. `--node-id` scopes
to a single node (an unknown id is a fatal error, exit 1); `--json` emits the
structured report. Degrades gracefully when the project is not a git checkout.

### `search-facts`

```text
isabelle-blueprint search-facts [project_dir] [--theory PATH ...] [--root DIR]
                                [--session NAME] [--query TEXT] [--kind KIND ...]
                                [--limit N] [--json]
```

Added in v1.13. Scans Isabelle `.thy` roots for fact/lemma/theorem names. With
`--query` it performs a free-text search over the discovered names; otherwise it
suggests candidate facts for nodes that reference a fact whose formal target is
still unresolved (`not_found`/`failed_check`/`broken`/`named`) — nodes with a
`missing` formal status have no fact to match and are skipped.
`--theory` adds extra `.thy` files/roots, `--root DIR` searches every theory a
session ROOT declares (with `--session NAME` to disambiguate), `--kind`
(repeatable) filters by declaration kind, and `--limit` caps the results
(default 10). `--json` emits structured output.

### `effort`

```text
isabelle-blueprint effort [project_dir] [--json]
```

Added in v1.13. Reports effort-weighted formalization progress from the optional
per-node `effort` weight. Weighted coverage is the proved share of formal-target
effort; nodes without an explicit `effort` are weighted as `1`. `--json` emits
the structured report (`proved_effort`, `formal_target_effort`,
`remaining_effort`, `coverage_percent`, `total_effort`, `explicit_effort_count`,
`default_effort`). Always exits 0.

The `--nodes` flag additionally lists each node with its `effort` weight, formal
status, and whether it counts toward proved effort, so you can see *where* the
remaining effort sits. It composes with the other output formats: a per-node
table beneath the summary (text/Markdown), per-node CSV rows (`--csv`), and an
additive `nodes` array (`{id, effort, formal_status, proved}`) under `--json`.
Without `--nodes` the output is unchanged.
### `tag-cooccurrence`

```text
isabelle-blueprint tag-cooccurrence [project_dir] [--json] [--min N]
```

Reports which tags appear together on the same nodes. For each unordered pair of
distinct tags it counts the nodes carrying both, ranked by descending shared
count (ties broken alphabetically by the pair). Nodes with fewer than two tags
contribute no pairs, and repeated tags within a node are de-duplicated. Only
pairs shared by at least one node are reported; `--min N` (an integer `>= 1`,
default `1`) filters out pairs shared by fewer than `N` nodes. Text output is a
ranked table (tag A, tag B, shared node count); `--json` emits the structured
report (`project`, `min_shared`, `pair_count`, and `pairs` carrying `tags`,
`shared_count`, and `node_ids`). Always exits 0.

### `version`

```text
isabelle-blueprint version [--json]
```

Prints the package version. `--json` emits a machine-readable object with the
package `version`, the running `python` version, and the list of available
schema `schemas`. (The top-level `--version` flag remains available and prints
`isabelle-blueprint <version>`.)

### `completion`

```text
isabelle-blueprint completion {bash,zsh,fish,powershell}
                              [--install] [--dest PATH]
```

Emits a shell completion script for the named shell to stdout. The script
completes the subcommand names, then the options of the chosen subcommand (any
word starting with `-`), and otherwise falls back to file completion. The option
lists are generated from the live parser, so they never drift from the flags a
subcommand actually accepts. It has no runtime dependencies; redirect it into
your shell's completion directory or source it from your shell profile. The
PowerShell script registers a native argument completer — load it with
`isabelle-blueprint completion powershell | Out-String | Invoke-Expression`
(add that line to your `$PROFILE` to persist it).

`--install` writes the script to the shell's conventional completion location
instead of stdout (honouring `XDG_DATA_HOME`/`XDG_CONFIG_HOME` where relevant)
and prints the destination plus any activation hint. `--dest PATH` writes to an
explicit path (creating parent directories as needed); it implies install
behaviour. Both are convenience wrappers and emit the same script content.

### `new`

```text
isabelle-blueprint new <kind> <id>
                       [project_dir]
                       [--title TITLE]
                       [--fact FACT | --no-fact]
                       [--uses ID ...]
                       [--status STATUS]
                       [--format markdown|latex]
                       [--append]
                       [--blueprint PATH]
```

Prints a ready-to-edit node stub to stdout, or appends it to the project
blueprint with `--append`. `--blueprint PATH` (added in v0.7) selects which
blueprint file receives the stub when the project has multiple blueprints.
Without `--append`, `--format` defaults to `markdown`; with `--append`, the
target suffix selects Markdown or LaTeX automatically. Passing a mismatched
`--format` for the selected blueprint is rejected.

---

## Backwards-compatibility guarantees

For the v1.x line:

1. **Subcommand names** (`init`, `check`, `graph`, `dump`, `compat`, `web`,
   `serve`, `tasks`, `next`, `attempt`, `report`, `status`, `roadmap`,
   `comment`, `doctor`, `memory`, `explain`, `import-theory`, `theory-index`,
   `schema`, `new`, `fmt`,
   `stats`, `version`, `completion`)
   will not be renamed or removed.
2. **Flag names and short forms** documented above will not be renamed or
   removed; their default values will not change.
3. **Exit codes** for documented conditions will not change.
4. **Files emitted by `report`** at the paths listed above will continue to
   exist with the JSON shapes documented in
   [`docs/json-contract.md`](json-contract.md).
5. **GitHub Actions output keys** listed under `report` will not be renamed
   or removed.

What is **not** part of the contract:

- The exact Markdown / HTML formatting of `report.md`, `pr-comment.md`, and
  the rendered `site/` pages.
- The wire format of `build/graph.dot` and `build/graph.json` beyond "valid
  DOT" / "valid JSON".
- The contents of `build/check-cache.json` (this is an internal cache; do not
  parse it from outside the tool).
