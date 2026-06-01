# CLI contract

This document is the **frozen public surface** of the `isabelle-blueprint`
command-line tool as of v1.1.0. Subcommand names, flag names, default values,
and exit-code semantics listed here will not change without a major version
bump. New flags and subcommands may be added in minor releases provided the
existing ones keep behaving the same way.

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

`--strict` is opt-in for every subcommand that exposes it. Without `--strict`,
a missing external dependency is downgraded to an informational message and
exit `0`.

---

## Subcommands

### `init`

```text
isabelle-blueprint init [project_dir] [--force] [--template NAME]
```

Scaffolds a fresh blueprint project: `blueprint.md`, `isabelle-blueprint.toml`,
and a GitHub Actions workflow. Fails if any target file already exists unless
`--force` is given. `--template` (added in v1.1) accepts `minimal`, `afp`,
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
graph viewer, status table, tasks view, and trend chart. `--watch` (added in
v1.1) re-renders when blueprint/check/report inputs change. `--serve` also
starts a local HTTP server on `127.0.0.1:8000` by default.

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
```

Emits agent-ready task artefacts under `build/`: `tasks.json`, `tasks.md`,
and one `prompts/<id>.md` prompt per actionable obligation. v1.1 adds task
metadata under `metadata` (`priority`, `difficulty`, dependency depth,
downstream blocking count, suggested order, and nearby fact suggestions) plus
top-level `suggested_next_task`. `--github-issues` writes issue drafts to
`build/github-issues.json` without calling GitHub.

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

When `$GITHUB_OUTPUT` is set, the stable scalar keys
(`coverage_percent`, `node_count`, `formal_target_count`, `proved_count`,
`found_count`, `problem_count`, `has_cycles`) are emitted to it. When
`$GITHUB_STEP_SUMMARY` is set, a compact Markdown summary is appended to it.

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

### `schema`

```text
isabelle-blueprint schema [name] [--out DIR]
```

Prints a packaged JSON Schema, lists schema names when `name` is omitted, or
writes one/all schemas to `DIR`. Available names are `project`, `graph`,
`tasks`, `summary`, `config`, and `plugin-annotations`.

### `new`

```text
isabelle-blueprint new <kind> <id>
                       [project_dir]
                       [--title TITLE]
                       [--fact FACT | --no-fact]
                       [--uses ID ...]
                       [--status STATUS]
                       [--append]
                       [--blueprint PATH]
```

Prints a ready-to-edit node stub to stdout, or appends it to the project
blueprint with `--append`. `--blueprint PATH` (added in v0.7) selects which
blueprint file receives the stub when the project has multiple blueprints.

---

## Backwards-compatibility guarantees

For the v1.x line:

1. **Subcommand names** (`init`, `check`, `graph`, `dump`, `compat`, `web`,
   `serve`, `tasks`, `report`, `comment`, `doctor`, `schema`, `new`) will not
   be renamed or removed.
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
