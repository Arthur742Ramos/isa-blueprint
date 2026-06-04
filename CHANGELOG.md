# Changelog

All notable changes to **IsabelleBlueprint** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Exposed the source-only `theory-index` analysis over MCP as a read tool
  (`theory_index`) plus matching `blueprint://theory-index` resources (with
  `blueprint://projects/{project}/theory-index` variants), so AI proof agents
  can read the cross-theory reference graph, import dependencies,
  `sorry`/`oops` markers, and unreferenced entries without shelling out to the
  CLI. Like `history`/`compat`, it never parses `blueprint.md`, so it works on
  partial checkouts, in CI, and even when the blueprint itself fails to load.
  Theory sources are resolved from `[isabelle].dirs`/`session` (falling back to
  a `ROOT` or `.thy` files at the project root); the `session` argument
  overrides the configured session. Resolution is best-effort across multiple
  configured roots — any root that is missing on disk, resolves no theory files,
  or lacks the selected session is reported under `warnings` (with CLI-specific
  session guidance rephrased for the MCP `session` argument) instead of aborting
  the whole index — and the payload echoes the resolved
  `source_roots`/`theory_files` for transparency.
- New `theory-index` command: source-only analysis of Isabelle `.thy` files that
  needs no `isabelle` binary, so it runs in CI and on partial checkouts. It
  resolves theories from explicit paths, `--root DIR` (optionally `--session
  NAME`), or the nearest discovered `ROOT`, and reports a cross-theory reference
  (call) graph (`--callers`/`--callees`, optionally `--transitive`), theory
  import dependencies (`--deps THEORY`, forward and reverse), `sorry`/`oops`
  markers with their enclosing entry (`--sorry`), and entries no other indexed
  entry references (`--unreferenced`). Emits a text summary by default or a full
  structured index with `--json`.
- `import-theory --root DIR` imports every theory a session `ROOT` declares
  (with `--session NAME` to disambiguate multi-session ROOTs) and infers
  cross-theory `uses` dependencies from the source reference graph, restricted to
  facts earlier in a global import-topological order so the generated blueprint
  stays acyclic. Importing explicit file paths is unchanged.
- New vendored ROOT/session parser (`isabelle_blueprint.isabelle.root`) and
  source index engine (`isabelle_blueprint.isabelle.source_index`). The ROOT
  parser is adapted from [`ott2/isabelle-query`](https://github.com/ott2/isabelle-query)
  (MIT) and understands `theories`/`directories` blocks, multi-session ROOTs,
  per-theory and session-level `in <subdir>` clauses, parents after `=`,
  option groups, comments, and cartouches. Theory `imports ... begin` clauses
  are read from comment-stripped source, so licence headers and commented-out
  import lines neither hide real imports nor inject phantom ones.

### Fixed

- ROOT parser: a per-theory `in "<subdir>"` override is no longer dropped when
  the preceding theory is flushed, so session theories declared in subdirectories
  now resolve correctly.

## [1.9.0] - 2026-06-04

### Added

- Exposed the `critical_path`, `impact`, and `stats` analyses as MCP read tools
  so AI proof agents can run longest-pole, downstream blast-radius, and
  agent-memory analytics over MCP without shelling out to the CLI. The tools
  mirror the CLI JSON payloads, accept the optional `project` selector, support
  `top` (and `node` for `impact`), and are always registered as pure reads.

- Exposed the `history`, `compat`, and `suggest_facts` analyses as MCP read
  tools, broadening the read surface for AI proof agents. `history` mirrors
  `history --json` (coverage trend deltas) and reads only `trends.json`, so it
  still works when the blueprint itself fails to parse; it accepts `limit`.
  `compat` mirrors the `compat` payload (Isabelle/AFP version pins and session
  visibility) but is read-only and never writes the report file; it accepts
  `isabelle`. `suggest_facts` returns fuzzy fact-name suggestions for unresolved
  formal targets. All three accept the optional `project` selector. The server
  also adds matching `blueprint://history` and `blueprint://fact-suggestions`
  resources (with `blueprint://projects/{project}/...` variants).

## [1.8.1] - 2026-06-04

### Added

- Added an optional MCP server entry point, `isabelle-blueprint-mcp`, for AI
  agents working on Isabelle projects. Install with `pip install
  "isabelle-blueprint[mcp]"`; plain `pip install isabelle-blueprint` keeps the
  base CLI and GitHub Action lightweight and does not include the MCP runtime
  dependency. The server exposes read tools/resources for
  status, roadmap, ready tasks, next-task prompts, agent context, explanations,
  lint findings, dependency graphs, schemas, and diagnostics. It also exposes a
  `prove_task` prompt, a dry-run rename preview, and launch-gated
  `--allow-writes` tools for low-risk proof-attempt memory and assignments.

- Added an `impact` command that computes the *downstream* blast radius of a
  node — what depends on it — as the dependent-facing complement to
  `critical-path`. Unlike `critical-path` leverage (which counts only incomplete
  work), `impact` counts dependents of *any* formal status, so a `proved`
  foundational lemma still shows a large blast radius. With `--node NODE` it
  reports the direct dependents, the transitive blast radius (each with its
  shortest dependency distance), the affected end goals, and the complete
  (`found`/`proved`) dependents that would go stale if the node changed; without
  `--node` it ranks every node by blast-radius size. Supports `--json`
  (schema-versioned payloads) and `--top N`. Traversal is cycle-safe and all
  ordering is deterministic.

- Added a `critical-path` command that performs longest-pole analysis of the
  remaining (incomplete) proof work. It reports the critical path of incomplete
  dependencies behind each goal (a remaining node that no other remaining node
  depends on), ranks bottleneck nodes by how many incomplete descendants they
  unblock (leverage), and separately surfaces dependency cycles, references to
  unknown dependencies, and complete nodes that still depend on incomplete ones.
  Supports `--json` (schema-versioned payload), `--top N` to limit the bottleneck
  list, `--goal NODE` to focus the text view on a single goal's chain, and
  `--fail-on-cycle` (exit code 2 when cycles are present).

### Added

- Added a `lint` command that runs structural and quality checks over the
  blueprint (duplicate ids, missing dependencies, dependency cycles, broken or
  stale formal status, empty statements, missing informal proofs, formal-intent
  nodes without an Isabelle reference, and isolated nodes). Supports `--json`
  and `--strict` (exit code 2 when any error-severity finding is present).
- Added a `diff <baseline.json>` command that compares the current parsed and
  checked project against a saved `project.json`, reporting added/removed nodes,
  per-node status changes, and regressions. A regression includes a proof coming
  undone, a healthy status turning into a problem status, and any slide down the
  confidence ladder (e.g. `found` -> `named`/`missing`). Supports `--json` and
  `--fail-on-regression` (exit code 5).
- Added a `history` command that summarises `trends.json`, printing the recorded
  series and the latest deltas. Supports `--json` and `--limit N`. Reads only the
  trends file so it keeps working even when the current blueprint fails to parse.
- Added an `assign` command backed by an `assignments.json` store for recording,
  listing, and clearing per-node ownership. Supports `--owner`, `--clear`, and
  `--json`. Mutations load the store strictly so a corrupt file is never
  silently overwritten.
- Added a `rename <old> <new>` command that rewrites blueprint sources (Markdown
  ids/`uses`, LaTeX `\label`/`\uses`) and re-keys agent/sync stores, with a
  `--dry-run` preview, a re-parse safety check, and best-effort rollback if a
  write fails part way through.
- Added a shared `--fail-on STATUS` policy flag to `check`, `report`, and
  `status` (exit code 5 when any node has a selected formal status; the
  `problem` alias expands to all problem statuses).
- Added `check --watch` (with `--interval`) to re-run the check whenever the
  blueprint sources change.
- Added `graph --format {all,dot,json,svg,mermaid}`, including a new Mermaid
  renderer that writes `graph.mmd` (default `all` preserves prior behaviour).
- Added ready-task filters to `isabelle-blueprint tasks`, matching `next` and
  `attempt` for kind, priority, difficulty, memory state, latest outcome, and
  explicit exclusions.
- Added ready-task filters to `isabelle-blueprint status` and
  `isabelle-blueprint agent-context` so `--top-tasks` / `--max-tasks`,
  `next_task`, and the embedded agent-context `ready_tasks` list can be narrowed
  by `--kind`, `--priority`, `--difficulty`, `--memory-state`, `--last-outcome`,
  and `--exclude-node`. Project health, metrics, `ready_task_count`,
  `suggested_next_task`, `suggested_path`, and `--write` artifacts continue to
  describe the full project so handoffs remain canonical.
- Extended `status` and `agent-context` JSON payloads with optional `filters`
  and `filtered_ready_task_count` fields (mirroring the `tasks --json` shape),
  and surfaced the active filter flags in the `agent-context` recommended
  command argv for `refresh_context`, `write_context`, and `next_task_prompt`.
- Added a global `--color {auto,always,never}` flag (and `--no-color` alias,
  honouring the `NO_COLOR` environment variable) that colourises the `lint`,
  `status`, and `doctor` renders. Defaults to `auto`, which stays off when the
  output is not a TTY so machine-readable output and captured text are unchanged.
- Added `lint --format {text,json,sarif}` with a SARIF 2.1.0 renderer so lint
  findings can be uploaded to GitHub code scanning and other SARIF consumers.
  `--json` remains a backwards-compatible alias for `--format json`.
- Added a `stats` command that aggregates agent-memory analytics (attempts by
  outcome, success rate per node kind, and a per-node breakdown). Supports
  `--json`; the JSON shape is lightweight and explicitly non-contract.
- Added a `version` command with `--json` that reports the package version, the
  running Python version, and the list of available schema names.
- Added a `completion` command that emits `bash`, `zsh`, and `fish` shell
  completion scripts for the subcommand names (no extra dependencies).
- Added `--watch` (with `--interval`) to `report`, `status`, and `tasks`,
  re-running the command whenever the blueprint sources change, mirroring the
  existing `check --watch`.

### Changed

- Improved task prompt generation so stale `build/prompts/task-*.md` files are
  removed only when their task is no longer ready, while filtered task runs keep
  still-ready prompts available.

## [1.7.1] - 2026-06-02

### Added

- Added repeatable `next` and `attempt` memory filters so agents can target
  fresh tasks, previously attempted tasks, stale-attempt tasks, or tasks with a
  specific latest attempt outcome.
- Added repeatable `next --exclude-node` and `attempt --exclude-node` selection
  filters so agents can skip known-bad, already assigned, or recently delegated
  ready tasks without rewriting the canonical task queue.

## [1.7.0] - 2026-06-01

### Added

- Added repeatable `next` and `attempt` filters for ready-task kind, priority,
  and difficulty so handoffs can target, for example, the next high-priority
  theorem without rewriting the canonical task queue.
- Added filter metadata to `next --json` and `attempt --json`, including the
  full ready-task count and the filtered ready-task count.
- Added a direct `prepare_attempt` recommendation to `agent-context` command
  bundles, pointing agents at the `attempt --check` workflow.

### Changed

- Improved explicit `next` / `attempt --node` diagnostics for blocked nodes by
  listing missing or incomplete dependency blockers, capped for readability.
- Improved filtered selection diagnostics so a ready task excluded by filters
  reports the mismatched kind, priority, or difficulty instead of looking
  unknown or blocked.

## [1.6.0] - 2026-06-01

### Added

- Added `isabelle-blueprint attempt`, a one-command proof handoff helper that
  writes the selected ready-task prompt to `build/attempts/`, can run `check`,
  and can record post-attempt memory in the existing agent-memory file.
- Added a static-site Roadmap page backed by the same roadmap model as the CLI,
  plus `site/roadmap.json`, filterable roadmap cards, copyable handoff commands,
  URL-persisted filters, and dark-mode-aware surfaces.
- Added extra GitHub issue draft/sync polish: repeatable `tasks --github-label`
  and `--github-assignee`, richer issue labels, assignee payloads, and dry-run
  close hints for completed task issues.
- Added richer PR comments with collapsible ready-task and problem-node details.
- Added `import-theory --review-output` and best-effort dependency suggestions
  inferred from references to earlier facts.
- Added VS Code proof-cockpit grouping plus node-level Explain and Record Memory
  commands and quick fixes for status diagnostics.
- Added a copyable plugin example under `examples/plugins/`.

## [1.5.2] - 2026-06-01

### Added

- Added `isabelle-blueprint next --output PATH` for writing the selected
  ready-task prompt to a specific file while keeping the command read-only with
  respect to project artifacts.
- Added a stable `prompt_path` key to `next --json`, set to the written prompt
  path when `--output` is used and `null` otherwise.

### Changed

- Improved the VS Code task prompt preview to generate a live ready-node prompt
  through the CLI when `build/prompts/task-<node>.md` has not been generated yet.

## [1.5.1] - 2026-06-01

### Added

- Added `isabelle-blueprint next`, a direct handoff command that prints the
  highest-priority ready task prompt or emits the same task/prompt bundle as
  JSON, with `--node` for selecting a specific ready node or task id.
- Added a VS Code `IsabelleBlueprint: Open Next Task Prompt` command that uses
  the CLI's next-task selection and opens the generated Markdown prompt without
  requiring pre-generated prompt files.
- Added automatic PyPI and GitHub Release publishing when the project version is
  bumped on `main`.

## [1.5.0] - 2026-06-01

### Added

- Added `isabelle-blueprint agent-context`, a one-command AI-agent handoff
  bundle that combines status metrics, roadmap suggestions, ready-task prompt
  paths, warning codes, artifact locations, and recommended follow-up commands.
- Added `agent-context --json` for clean machine-readable stdout,
  `agent-context --write` for `build/agent-context.json` /
  `build/agent-context.md` plus refreshed task prompts, roadmap artifacts, and
  `project.json`, and `--max-tasks` to cap embedded ready-task summaries.
- Added a packaged `agent-context` JSON Schema and VS Code command for
  generating the agent-context bundle from the active workspace.

## [1.4.1] - 2026-06-01

### Added

- Added `roadmap --strict` for CI gates that fail on cycles, problem nodes,
  stale nodes, or missing dependencies while still producing the requested
  roadmap output.
- Added repeatable `roadmap --status`, `--stage`, and `--kind` filters for
  focused terminal/JSON roadmap views without changing canonical
  `build/roadmap.json` artifacts.
- Added `roadmap --since` to compare against a previous `roadmap.json` and
  surface added, removed, newly ready, newly blocked, newly complete, newly
  stale, newly problematic, and otherwise changed nodes.
- Added a VS Code `IsabelleBlueprint: Run Roadmap` command.

## [1.4.0] - 2026-06-01

### Added

- Added `isabelle-blueprint roadmap`, a staged proof-work planner that groups
  nodes into topological stages, classifies each node as complete, ready,
  blocked, stale, or problem, surfaces cycles, and prints a deterministic
  suggested path through the next useful work.
- Added `roadmap --json` for machine-readable planning output and
  `roadmap --write` for shareable `build/roadmap.json` and `build/roadmap.md`
  artifacts.
- Added a packaged `roadmap` JSON Schema for roadmap integrations.

## [1.3.0] - 2026-06-01

### Added

- Added `isabelle-blueprint status`, a read-only terminal/JSON health overview
  that combines coverage, problem/stale counts, cycle state, ready-task count,
  and the next suggested proof task without writing report artifacts.
- Added a packaged `status` JSON Schema for `status --json` integrations.

## [1.2.0] - 2026-06-01

### Added

- Added persistent agent memory under `.isabelle-blueprint/agent-memory.json`
  plus `isabelle-blueprint memory` for recording and listing per-node proof
  attempts, blockers, next steps, and stale attempt context.
- Added `isabelle-blueprint explain` for node-level status diagnostics covering
  missing dependencies, cycles, unchecked names, unresolved facts, stale cache
  entries, tainted proofs, and check failures.
- Added `isabelle-blueprint import-theory`, a best-effort bootstrapper that
  scans Isabelle `.thy` declarations and emits reviewable Markdown blueprint
  stubs.
- Added dry-run-by-default GitHub issue synchronization for generated proof
  tasks via `tasks --github-sync`; confirmed sync uses stable hidden markers
  and `.isabelle-blueprint/github-sync.json` to avoid duplicate issues.
- Added agent-memory summaries to `tasks.json`, task prompts, and the static
  site's task board.
- Added experimental plugin entry-point helpers for node-kind providers and
  report renderers, and wired status-provider annotations plus renderer
  artifacts into `report`.
- Added VS Code commands for running `report`, `check`, and `tasks`, plus task
  prompt preview from the Blueprint Nodes tree.
- Added an `agent-memory` JSON Schema.

## [1.1.0] - 2026-06-01

### Added

- Added a manual TestPyPI dry-run workflow for trusted-publishing release rehearsals.
- Added GitHub Release automation for tagged PyPI releases, including built
  distribution artifacts.
- Added `isabelle-blueprint doctor` for local setup diagnostics.
- Added `isabelle-blueprint web --watch`, `web --serve`, and `serve` for live
  static-site preview.
- Added `isabelle-blueprint schema` plus packaged JSON Schemas for project,
  graph, tasks, summary, normalized config, and plugin annotations.
- Added smarter agent task metadata: priority, difficulty, dependency depth,
  downstream blocking count, suggested ordering, suggested next task, and
  optional GitHub issue draft JSON.
- Added fuzzy Isabelle fact suggestions for unresolved formal targets.
- Added site search, next-action cards, and trend deltas since the previous
  report.
- Added `init --template` starters for `minimal`, `afp`, `research-paper`,
  `course-notes`, and `agent-ready` projects.
- Added VS Code quick fixes for missing dependencies and go-to-definition
  navigation for node IDs.
- Added ruff and mypy as first-class CI gates alongside the existing pytest,
  smoke, and VS Code extension checks.
- Added trusted PyPI publishing workflow scaffolding for signed tag releases.
- Added a composite GitHub Action wrapper that installs IsabelleBlueprint and
  forwards the stable v1.0 report outputs.
- Added community-health files: contribution guide, security policy, code of
  conduct, pull request template, issue forms, Dependabot config, and funding
  placeholder.

## [1.0.0] - 2026-05-31

The first stable release. The CLI surface, JSON file shapes, and GitHub Action
outputs documented under [`docs/`](docs/) are now frozen public contracts:
breaking changes will only ship in a 2.0 line. Everything from the original
roadmap is shipped, plus the v0.6–v0.9 milestones added during the 1.0 push.

### Added

- **v0.6 — Incremental + parallel `check`.** `isabelle-blueprint check` now
  understands two new flags:
  - `--incremental` writes a per-fact cache to `build/check-cache.json`. On
    subsequent runs, facts whose blueprint inputs, theory/session pins, and
    upstream dependencies haven't changed are skipped and replayed from the
    cache, so re-verifying a large blueprint after a small edit no longer
    re-ships the whole wrapper theory through `isabelle build`.
  - `--jobs N` forwards `-j N` to `isabelle build` so upstream session builds
    parallelise without changing the wrapper theory we ship per check.
  Behaviour without either flag is byte-identical to v0.5.1.
- **v0.7 — Multi-blueprint projects.** A project may now compose several
  blueprint files into one dependency graph:
  - `isabelle-blueprint.toml` accepts `[project].blueprints = [...]`
    in addition to the existing `blueprint = "..."`. Every CLI command (check,
    graph, report, web, tasks, dump, comment) loads the union.
  - Duplicate node ids across blueprints fail loudly with a `BlueprintError`
    that names both source files instead of silently letting the later
    blueprint win.
  - `isabelle-blueprint new ... --append --blueprint <path>` lets you pick
    which blueprint receives the new stub when the project has more than one.
- **v0.8 — Graph filtering + trend charts.**
  - The dependency graph page (`graph.html`) ships an interactive sidebar that
    filters the SVG by formal status: blueprint-only, named, found, proved,
    tainted, problem, etc. Each status has its own checkbox; unchecking one
    dims the matching nodes (and edges that only touch them), and a Reset
    button re-checks every box to restore the full graph. Implemented as a
    small vanilla JS file (`static/graph.js`) with a no-op guard so non-graph
    pages and CSP-strict deployments are unaffected.
  - `isabelle-blueprint report` now appends a bounded (max 500) JSON history
    of every run to `build/trends.json`, keyed by `(commit_sha, branch)` so
    CI matrix re-runs replace rather than duplicate. The static site renders
    that history as a line chart of coverage / problem count via
    `static/trends.js`.
- **v0.9 — Plugin API + PR status comments.**
  - `isabelle_blueprint.plugins` discovers entry-points in the
    `isabelle_blueprint.status_providers` group. Providers receive the loaded
    `BlueprintProject` and return an iterable of annotation dicts. Failures
    (bad load, non-callable, exception during call, non-iterable result) are
    caught and surfaced as warnings so a broken third-party plugin can never
    break the CLI. Additional entry-point groups will be added in subsequent
    minor releases; this one is the stable starting point.
  - `isabelle_blueprint.report.pr_comment` posts (or updates, idempotently
    via a hidden `<!-- isabelle-blueprint:status -->` marker) a Markdown
    status comment on the current pull request. Reads PR number from
    `GITHUB_EVENT_PATH`, token from `GITHUB_TOKEN`, repo from
    `GITHUB_REPOSITORY`, and commit SHA from `GITHUB_SHA`. Uses only the
    standard library (`urllib`); no new runtime dependency.
  - New `isabelle-blueprint comment` subcommand. `--preview` writes the body
    to `build/pr-comment.md` instead of posting (useful for local iteration);
    `--strict` exits 6 when the PR context can't be resolved so CI can fail
    loudly if wired by accident.
- **`docs/cli-contract.md`** documenting every frozen subcommand and flag.
- **`docs/json-contract.md`** documenting the frozen shapes of `project.json`,
  `summary.json`, `badge.json`, and `trends.json`.

### Changed

- `pyproject.toml` classifier bumped from `Development Status :: 4 - Beta` to
  `Development Status :: 5 - Production/Stable`.
- README: dropped the pre-release install banner; updated the status section
  for v1.0; documented the `comment` subcommand; marked all roadmap items
  shipped.

## [0.5.1] - 2026-05-31

### Added

- **Shareable status badge.** `isabelle-blueprint report` now writes two badge
  artefacts alongside the existing reports:
  - `build/badge.json` — a [shields.io endpoint](https://shields.io/endpoint)
    payload (`schemaVersion: 1`, label, message, color) that you can point a
    shields.io URL at from any README or wiki.
  - `build/badge.svg` — a self-contained flat SVG you can commit, embed, or
    serve from GitHub Pages without depending on shields.io being up.
  Coverage thresholds map to colors gray → red → orange → yellow → green →
  brightgreen, and any `not_found` / `broken` / `failed_check` / `tainted`
  formal status forces the badge red regardless of percentage.
- **Interactive status table filtering.** The `status.html` page rendered by
  `isabelle-blueprint web` now ships with click-to-filter pills for the
  Blueprint, Formal, and Agent axes, plus a live "shown / total" counter and
  a clear button. Selections within one axis are OR'd, selections across axes
  are AND'd. Implemented as a small vanilla-JS file (`static/filters.js`) with
  a no-op guard, so per-node pages and CSP-strict deployments stay happy.
- **First-class GitHub Action outputs.** `isabelle-blueprint report` now
  emits a stable set of scalar outputs to `$GITHUB_OUTPUT` and a compact
  Markdown summary to `$GITHUB_STEP_SUMMARY` whenever those environment
  variables are present (which they always are inside GitHub-hosted runners).
  The output key set is now a frozen public contract:
  - `coverage_percent` (empty string when there are no formal targets)
  - `node_count`
  - `formal_target_count`
  - `proved_count`
  - `found_count`
  - `problem_count`
  - `has_cycles` (`"true"` / `"false"`)
- **`StatusMetrics` helper** in `isabelle_blueprint.report.metrics`. The badge,
  the GitHub Actions outputs, and the Markdown report now all go through a
  single `build_status_metrics(project)` so the three surfaces can never drift
  apart.
- **`Changelog` URL** added to `[project.urls]` in `pyproject.toml`, so PyPI's
  sidebar will surface it once v1.0 ships.
- **Re-exports** of the new public API from `isabelle_blueprint.report`:
  `StatusMetrics`, `build_status_metrics`, `output_values`,
  `stable_output_keys`, `build_endpoint_payload`, `render_badge_svg`,
  `write_badge_endpoint`, `write_badge_svg`, `emit_step_outputs`,
  `emit_step_summary`, `build_summary_markdown`.

### Changed

- **(Behaviour)** Markdown report coverage is now computed as
  `proved / formal_target_count` (i.e. only nodes that actually want a formal
  proof are in the denominator), and prints `_no formal targets assigned yet_`
  instead of `0%` when no node has a non-`missing` formal status. Previously
  it was `(proved + found) / total_nodes`, which made projects that hadn't
  yet picked formal targets look artificially under-covered, and which
  conflated "we found a fact with this name" with "we proved it". The new
  rule matches the badge and the GitHub Actions outputs.
- Broadened `pyproject.toml` `package-data` glob from explicit static-file
  enumeration to `render/templates/static/*`, so additions like `filters.js`
  ship in the wheel automatically.

### Fixed

- The status table filter UI degrades silently on pages that don't have a
  `.status-table` (e.g. per-node pages), instead of throwing in the browser
  console.

## [0.5.0] - 2026-05-31

The v0.5 Beta milestone. Covered the original roadmap end-to-end: Markdown +
LaTeX blueprint parsers, AFP / version-pin compatibility checks, PIDE `dump`
integration with `sorry` / oracle detection, the static HTML status site,
agent task generation, and the VS Code extension surface.

See the [Status — v0.5](README.md#status--v05) section of the README for the
full feature list.

[Unreleased]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.9.0...HEAD
[1.9.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.8.1...v1.9.0
[1.8.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.5.2...v1.6.0
[1.5.2]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.5.1...v1.5.2
[1.5.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.1...v1.0.0
[0.5.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Arthur742Ramos/isa-blueprint/releases/tag/v0.5.0
