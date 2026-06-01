# Changelog

All notable changes to **IsabelleBlueprint** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.1...v1.0.0
[0.5.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Arthur742Ramos/isa-blueprint/releases/tag/v0.5.0
