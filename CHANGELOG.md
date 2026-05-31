# Changelog

All notable changes to **IsabelleBlueprint** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.1] - 2025

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

## [0.5.0] - 2025

The v0.5 Beta milestone. Covered the original roadmap end-to-end: Markdown +
LaTeX blueprint parsers, AFP / version-pin compatibility checks, PIDE `dump`
integration with `sorry` / oracle detection, the static HTML status site,
agent task generation, and the VS Code extension surface.

See the [Status — v0.5](README.md#status--v05) section of the README for the
full feature list.

[Unreleased]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Arthur742Ramos/isa-blueprint/releases/tag/v0.5.0
