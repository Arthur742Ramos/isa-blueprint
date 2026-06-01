# CLI contract

This document is the **frozen public surface** of the `isabelle-blueprint`
command-line tool as of v1.6.0. Subcommand names, flag names, default values,
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

---

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | A `BlueprintError` reached `main()` (e.g. parser/validator error, missing config) |
| `2` | argparse usage error |
| `6` | `--strict` was passed and the subcommand could not produce its primary side-effect (e.g. `check --strict` couldn't run Isabelle; `comment --strict` couldn't resolve the PR context) |
| `7` | `doctor --strict` found a setup error |
| `8` | Live serving was requested in CI without `--allow-ci` |
| `9` | `roadmap --strict` found cycles, problem nodes, stale nodes, or missing dependencies |

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
```

Validates the blueprint structure and, if Isabelle is available, runs the
generated `Blueprint_Check.thy` wrapper through `isabelle build` to confirm
each declared fact exists and isn't tainted by `sorry` / oracles.

- `--isabelle PATH` overrides the `isabelle` binary location.
- `--timeout SECONDS` overrides `[isabelle].timeout` from the config.
- `--strict` exits 6 if Isabelle isn't available or the build never ran.
- `--incremental` (added in v0.6) reuses results from
  `build/check-cache.json` for facts whose blueprint inputs, theory/session
  pins, and upstream dependencies are unchanged.
- `--jobs N` (added in v0.6) forwards `-j N` to `isabelle build` to
  parallelise upstream session builds.

### `graph`

```text
isabelle-blueprint graph [project_dir]
```

Emits the dependency graph as `build/graph.dot` and `build/graph.json`; also
renders `build/graph.svg` if Graphviz `dot` is on `PATH`.

### `dump`

```text
isabelle-blueprint dump [project_dir]
                        [--isabelle PATH]
                        [--timeout SECONDS]
                        [--from DIR]
                        [--strict]
```

Runs `isabelle dump` (or inspects a pre-existing dump tree via `--from`) and
applies the PIDE-level proof information to each node's status.

### `compat`

```text
isabelle-blueprint compat [project_dir]
                          [--isabelle PATH]
                          [--strict]
```

Checks the configured Isabelle and AFP versions against the local install and
reports any session-visibility or version-pin mismatches.

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
                         [--repo OWNER/REPO]
                         [--token-env ENVVAR]
                         [--github-sync-state PATH]
                         [--github-label LABEL]
                         [--github-assignee USER]
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

### `next`

```text
isabelle-blueprint next [project_dir] [--node NODE_OR_TASK] [--json] [--output PATH]
```

Prints the Markdown prompt for the next ready proof task, using the same stable
task ordering as `tasks`, `roadmap`, and `agent-context`. This command is
read-only and does not require prompt files to have been generated first.

- Without `--node`, the selected task is the highest-priority ready task.
- `--node` accepts either a task id such as `task-main` or a blueprint node id
  such as `main`. Exact task ids are resolved before node ids when names could
  overlap.
- `--json` emits a clean payload with `task`, `prompt`, `prompt_path`, and
  `message`. When no ready task exists, the command exits 0 with `task`,
  `prompt`, and `prompt_path` set to `null`. Selecting an unknown or currently
  blocked/proved node is a `BlueprintError` and exits 1.
- `--output PATH` (added in v1.5.2) writes the selected prompt to `PATH`,
  creating parent directories as needed. It does not write anything when no
  ready task exists or when selector validation fails. Text output still prints
  the prompt to stdout and reports the written path on stderr; JSON output
  records the absolute path in `prompt_path`.

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
                          [--record-outcome OUTCOME]
                          [--summary TEXT]
                          [--details TEXT]
                          [--next-step TEXT]
                          [--actor TEXT]
                          [--tool TEXT]
                          [--max-attempts N]
```

Added in v1.6. Prepares a selected ready proof task for a human or agent proof
attempt. By default it writes the prompt to
`build/attempts/<task-id>.md`. `--node` accepts the same node/task selectors as
`next`. `--check` runs the normal `check` pipeline after writing the prompt.
`--record-outcome` records post-attempt memory and requires a non-empty
`--summary`; valid outcomes match the `memory --outcome` choices.

`--json` emits `task`, `prompt_path`, `check`, `memory`, and `message`. When no
ready task exists, those object fields are `null` and the command exits 0.

### `report`

```text
isabelle-blueprint report [project_dir]
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

### `status`

```text
isabelle-blueprint status [project_dir] [--json]
```

Prints a read-only project health overview without writing report artifacts.
The text form includes the project health classification, coverage, node/problem
counts, cycle status, ready-task count, and the next suggested task when one is
available. `--json` emits the same payload documented by the packaged
`status` JSON Schema.

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

### `agent-context`

```text
isabelle-blueprint agent-context [project_dir]
                                  [--json]
                                  [--write]
                                  [--max-tasks N]
```

Builds an AI-agent handoff bundle that projects existing status, roadmap, task,
and memory data into one stable context surface. The command is read-only by
default and prints a Markdown brief to stdout.

- `--json` emits the payload documented by the packaged `agent-context` JSON
  Schema. It does not write files unless `--write` is also supplied.
- `--write` refreshes `build/project.json`, `build/tasks.json`,
  `build/tasks.md`, `build/prompts/<task-id>.md`, `build/roadmap.json`,
  `build/roadmap.md`, `build/agent-context.json`, and
  `build/agent-context.md`. When combined with `--json`, artifact path messages
  are written to stderr so stdout remains valid JSON.
- `--max-tasks N` caps how many ready-task summaries are embedded in the
  context payload (default 5). `ready_task_count` always reports the full number
  of ready tasks, and `ready_tasks_truncated` tells consumers whether to read
  `build/tasks.json` for the complete queue.

All artifact paths embedded in the payload are project-root-relative POSIX-style
strings when the artifact lives under the project root. Existing `status`,
`roadmap`, and `tasks` ordering and classification rules are reused rather than
recomputed independently.

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
isabelle-blueprint import-theory THEORY.thy [THEORY.thy ...]
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

### `schema`

```text
isabelle-blueprint schema [name] [--out DIR]
```

Prints a packaged JSON Schema, lists schema names when `name` is omitted, or
writes one/all schemas to `DIR`. Available names are `project`, `graph`,
`tasks`, `summary`, `status`, `roadmap`, `agent-context`, `config`,
`plugin-annotations`, and `agent-memory`.

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
   `comment`, `doctor`, `memory`, `explain`, `import-theory`, `schema`, `new`)
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
