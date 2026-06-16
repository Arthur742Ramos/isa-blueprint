# Changelog

All notable changes to **IsabelleBlueprint** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`portfolio --sort {name,coverage,nodes,problems}`** orders the listed
  projects (`name` ascending; `coverage`/`nodes`/`problems` descending) across
  text/JSON/CSV/Markdown output; default discovery order is unchanged.
- **`lint` `self-dependency` rule** flags any node whose `uses` list contains
  its own id (a node depending on itself) as an `error`-severity finding, naming
  the offending node id; also surfaced in SARIF output.
- **`history --markdown`** renders the trend snapshots as a Markdown table (one
  row per snapshot: timestamp plus the coverage / count metrics), respecting
  `--limit`. Mutually exclusive with `--json` and `--csv`; default text output is
  unchanged.
- **`blame --markdown`** renders per-node provenance (node, source location,
  last git author/commit, agent memory note) as a Markdown table, for all nodes
  or a single `--node-id`. Mutually exclusive with `--json` and `--table`;
  default text output is unchanged.
- **`path --markdown`** renders the shortest dependency path as a Markdown
  document (a heading naming source/target, a direction line, and the chain as
  an ordered list; with `--all` each shortest path is its own section).
  Mutually exclusive with `--json`; default text output is unchanged.
- **`critical-path --mermaid`** emits a Mermaid `flowchart` of the longest
  remaining incomplete dependency chain (or a single goal's chain via `--goal`),
  with high-leverage bottleneck nodes highlighted. Mutually exclusive with
  `--json` and `--markdown`.
- **`critical-path --csv`** emits the bottleneck/leverage ranking as CSV
  (`node_id`, `kind`, `leverage`, `on_critical_path`), honouring `--top` and
  `--goal`. Mutually exclusive with the other output-format flags; default text
  output is unchanged.
- **`lint --format markdown`** renders the lint findings as a Markdown document
  (heading, a summary count line, and a table of findings: code, severity, node,
  message, with `|` escaped in cells). Existing text/json/sarif output and the
  `--strict` exit behaviour are unchanged.
- **`gate --markdown`** renders the pass/fail gate result as a Markdown report
  (a heading, an overall PASS/FAIL line, and a table of each check with name,
  ok, and detail). Mutually exclusive with `--json`; the exit code and existing
  `--min-coverage`/`--min-grade`/`--fail-on` behaviour are unchanged.
- **`status --markdown`** renders the health overview as Markdown: a heading
  with the project name and health label, a metrics table
  (coverage/proved/problems/stale/ready-tasks/cycle-status), and a short
  next-task line. Mutually exclusive with `--json`; the existing filter and
  `--fail-on` flags keep working and default text output is unchanged.
- **`staleness --fail-on-outdated`** exits `5` when any trusted node is flagged
  as outdated (rests on a dependency that is stale or was re-checked more
  recently than the node). It composes with `--fail-on-problem` (either gate can
  trip), prints a stderr note with the outdated node count in text mode, and
  leaves behaviour unchanged when absent.
- **`scorecard --min-component NAME=PCT`** is a repeatable CI gate that exits `5`
  when the named component score (coverage/integrity/structure/freshness/
  documentation/readiness) is below `PCT` percent; it composes with
  `--min-grade`/`--min-score` and adds an additive `component_gates` array to
  `--json`. A component with no defined score never fails the gate.
- **`impact --format mermaid`** emits a Mermaid `flowchart` of a node's
  downstream blast radius (requires `--node`), mirroring `--format dot` with the
  focus node highlighted for zero-dependency inline rendering on GitHub/GitLab.
- **`explain --markdown`** renders the per-node status explanations as a
  Markdown document (a heading with the node id/title, a status block listing
  blueprint/formal/agent status, a dependency list, and the
  reasons/suggestions/next steps). Mutually exclusive with `--json`; default
  text output is unchanged.
- **`diff --fail-on-change`** is a stricter CI gate than `--fail-on-regression`:
  it exits `5` when there is *any* difference vs the baseline (an added node, a
  removed node, or any status change), not just regressions. It composes with
  `--json`/`--markdown` (the gate only affects the exit code).
- **`portfolio --markdown`** renders the cross-project roll-up as Markdown: a
  heading, a totals summary line, and a table with one row per project (name,
  node count, coverage, proved, problems, cycles, health). Mutually exclusive
  with `--json` and `--csv`.
- **Packaged JSON Schemas for the `path`, `scorecard`, and `tags` commands.**
  These commands emit versioned `--json` payloads but shipped without published
  schemas, unlike the rest of the CLI. They are now registered packaged schemas
  (`isabelle-blueprint schema path|scorecard|tags`, included in `schema --out`
  and over MCP), and contract tests assert each command's JSON conforms to its
  schema and that every packaged schema is a valid draft 2020-12 schema.
- **`scorecard` command** distills the whole blueprint into a single composite
  quality score (0–100) and letter grade (A+…F), with a weighted component
  breakdown: coverage, integrity (problem-free), structure (acyclic + no missing
  deps), freshness, documentation completeness, and agent readiness. Components
  with no applicable nodes drop out and the remaining weights are renormalised.
  `--json` emits the structured score; also available as the MCP `scorecard` tool.
  `--min-grade GRADE` turns it into a CI gate: exit `5` when the overall grade
  falls below `GRADE` (case-insensitive, e.g. `--min-grade B-`), matching the
  fail flags on `gate`/`staleness`/`diff`/`burndown`. An ungradeable (empty)
  project never trips the gate, and `--json` adds a `gate` object reporting the
  threshold and whether it was met.
- **`tags` command** rolls up nodes by tag: node count, formal targets,
  proved/found/problem counts, and per-tag proved-coverage, plus an untagged
  count. Nodes with multiple tags are counted under each. `--json` emits the
  structured rollup; also available as the MCP `tags` tool.
- **`path SOURCE TARGET` command** finds the shortest dependency path between two
  nodes along `uses` edges, auto-detecting direction (`depends-on` vs
  `depended-on-by`) and reporting reachability plus the full chain. `--json`
  emits the structured result; also available as the MCP `path` tool.
- **`graph --focus NODE [--depth N]`** prunes the graph to a node's
  neighbourhood (ancestors + descendants within `N` undirected hops; omit
  `--depth` for the whole connected component, `--depth 0` for just the node)
  across every format. The MCP `graph` tool gains matching `focus`/`depth`
  parameters.
- **`graph --format graphml`** exports the dependency graph as GraphML (with
  title/kind/status/colour node attributes) for Gephi, Cytoscape, and yEd.
  Included in `--format all` and the MCP `graph` tool's formats.
- **`gate` command** runs a single pass/fail CI gate combining lint errors,
  dependency cycles, a minimum proved-coverage threshold (`--min-coverage`), and
  a status policy (`--fail-on`, repeatable, with a `problem` alias for all
  problem statuses). Exits `5` on failure, `0` when clean, and `--json` emits the
  structured result. Replaces having to wire `lint`, `status`, and coverage
  checks together by hand in CI.
- **`prometheus` command** renders blueprint status as a Prometheus
  text-exposition payload (gauges for node/target/proved/found/problem counts,
  coverage, and cycles), with an optional burndown ETA gauge. `--output` writes
  to a node-exporter textfile; `--no-burndown` skips reading `trends.json`.
- **`hooks` command** prints (or `--write`s) a `.pre-commit-config.yaml` wiring
  `fmt --check` and `lint --strict`, so contributors get canonical-format and
  lint enforcement locally. `--force` overwrites an existing config.
- **`notify` command** builds a Slack/Teams/Discord/generic webhook payload from
  the current status (`--format`) and either prints it (default, dry-run) or
  POSTs it with `--send`. Defaults are deliberately safe: dry-run unless
  `--send`, HTTPS-only, and no redirect following.
- **`blame` command** reports per-node provenance by correlating each node's
  source file/line with `git log` and recorded agent-memory attempts, so you can
  see who/what last touched a node. `--node-id` scopes to one node; `--json`
  emits structured output.
- **`search-facts` command** scans Isabelle `.thy` roots for fact/lemma/theorem
  names. With `--query` it does a free-text search; otherwise it suggests
  candidate facts for nodes that reference a fact whose formal target is still
  unresolved (`not_found`/`failed_check`/`broken`/`named`); nodes with no fact
  reference yet (`missing`) are skipped. `--kind` (repeatable), `--limit`, and
  `--json` refine the output.
- **`effort` command** reports effort-weighted formalization progress from an
  optional per-node `effort` weight (a story-point-style estimate). Weighted
  coverage is the proved share of formal-target effort; nodes without an explicit
  `effort` are weighted as `1`. `--json` emits the structured report.
- **Optional `effort` node metadata** is now parsed, validated (positive
  integer), round-tripped through both the Markdown (`effort: N`) and LaTeX
  (`\effort{N}`) interchange writers, and included in `build/project.json` and
  the JSON schema.
- **`lint --fix`** drops `uses` entries that reference undefined node ids and
  rewrites the affected Markdown files in place (LaTeX sources are skipped). It
  refuses to touch files (exit `2`) when duplicate ids or dependency cycles are
  present, since those need a human decision. `--fix-dry-run` reports the changes
  without writing.
- **`tasks --tracker-export {jira,linear}`** writes a CSV of agent tasks ready to
  import into Jira or Linear, mapping difficulty to story points / estimate.
- **`attempt --sledgehammer`** appends Isabelle `sledgehammer` guidance and a
  proof skeleton (seeded with the target fact and dependency facts) to the
  generated attempt prompt.
- **End-to-end test suite (`tests/test_e2e.py`).** A black-box harness drives the
  packaged `python -m isabelle_blueprint` entry point as a subprocess across the
  full lifecycle (scaffold every template, `new --append`, report, status,
  roadmap, tasks, graph, agent-context, diff, gate, fmt, LaTeX, and error paths),
  asserting real exit codes and on-disk artifacts. It also validates that the
  JSON emitted by every published command conforms to the JSON Schemas shipped in
  the wheel, and that those schemas are themselves valid draft 2020-12 schemas —
  turning the README's "stable contracts" promise into an enforced guarantee. A
  new CI `e2e` job runs the suite against the actually-built wheel (`jsonschema`
  is now a dev dependency).
- **`blame --node ID`** is now accepted as an alias for `blame --node-id ID`, so
  the single-node flag matches `impact`/`memory`/`explain`/`next`. The original
  `--node-id` spelling keeps working.
- **`compat --json` and `dump --json`** emit their report to stdout (the same
  JSON already written to disk), closing the last machine-readability gaps in an
  otherwise JSON-everywhere CLI. Exit codes and the default human output are
  unchanged; under `--json` the per-issue / `report -> path` lines are replaced
  by the structured payload, and `dump --json` reports a blueprint-validation
  failure as a JSON object (exit `2`).
- `graph --format d2` emits a [D2](https://d2lang.com) (`build/graph.d2`)
  dependency graph; it is opt-in only and left out of the default `all` set, so
  existing `graph` output is unchanged. The MCP `graph` tool also accepts
  `format="d2"`, keeping the CLI and MCP graph formats in parity.
- **`duplicate-title` lint rule** flags two or more nodes that share an
  identical (case-insensitive, trimmed) non-empty title as a warning, catching
  accidental copy-paste collisions; it surfaces in `lint --json` and SARIF.
- **`tags --tag NAME`** restricts the roll-up to the named tag(s) (repeatable);
  an unknown tag yields a zero/empty row rather than an error, so the filter
  behaves additively. Project-wide `total_nodes`/`untagged_count` and the JSON
  shape are unchanged.
- **`assign --json`** now also emits additive `count` (number of assignment
  records) and `owners` (a `node_id -> owner` map) keys alongside the existing
  `project` and `assignments` fields, so consumers no longer have to derive the
  total or a lookup table themselves. Existing keys and the persisted
  `assignments.json` store format are unchanged.
- **`history --csv`** exports the recorded trend snapshots as CSV (a header row
  plus one row per snapshot, carrying the timestamp and the same numeric
  coverage/count metrics shown in text mode). It is mutually exclusive with
  `--json`, respects `--limit`, and leaves the default text output unchanged,
  so trend history can be piped into spreadsheets and plotting tools without
  post-processing JSON.
- **`fmt --diff`** previews canonicalisation as a unified diff without writing,
  exiting `10` on drift. Diff mode implies check-only semantics, so the
  `--json` payload reports `check_only: true` to reflect that nothing was
  written.
- **`critical-path --write`** persists `critical-path.json` and a plain-Markdown
  `critical-path.md` into the configured build dir alongside the printed report.
  The Markdown mirrors the printed output (honouring `--goal`) and never embeds
  ANSI colour codes; printing and exit codes are otherwise unchanged.
- **`prometheus --label KEY=VALUE`** injects extra static labels onto every
  emitted metric line; repeatable, with last-wins on duplicate keys. Label names
  must be valid Prometheus identifiers and may not begin with the reserved `__`
  prefix; invalid names exit `2`.
- **`effort --by-tag`** additionally groups effort-weighted progress per tag
  (nodes with multiple tags count under each), always including an `(untagged)`
  bucket that sorts last. The per-tag breakdown is opt-in, so the default output
  and the non-`--by-tag` JSON payload are unchanged.
- **`scorecard --min-score N`** adds a numeric CI gate alongside `--min-grade`:
  exit `5` when the overall score falls below `N` (an integer `0`–`100`). It
  composes with `--min-grade` (fails if either threshold is unmet), an
  ungradeable (empty) project never trips it, and `--json` adds
  `min_score`/`meets_min_score` to the `gate` object.
- **`critical-path --markdown`** prints the report as plain Markdown to stdout
  (no ANSI colour even on a TTY), distinct from `--write`'s file artifacts. It
  honours `--goal`/`--top` and is mutually exclusive with `--json`; the default
  text output is unchanged.
- **`gate --min-grade GRADE`** adds a scorecard-grade threshold to the CI gate:
  it additionally fails (exit `5`) when the project scorecard grade is below
  `GRADE` (case-insensitive A+…F, reusing the `scorecard` grades), and the JSON
  `checks` array gains a `min_grade` entry. An ungradeable project (no gradeable
  components) also fails the check — unlike `scorecard --min-grade`, the gate
  cannot show an unknown grade clears the bar. Without the flag, gate output and
  exit code are unchanged.
- **`stats --markdown`** renders the agent-memory analytics as a Markdown
  document (summary, outcomes, and per-node tables) to stdout; mutually
  exclusive with `--json` and leaves the default text output unchanged.
- **`theory-index --counts`** prints a compact numeric summary of the
  source-only index (theory count, total entries, entries carrying a
  `sorry`/`oops`, unreferenced-entry count, and total in-project import edges)
  without needing Isabelle. With `--json` it emits an additive `counts` object;
  the default index output is unchanged.
- **`blame --table`** renders a compact one-row-per-node provenance table (node,
  source, last git commit, agent attempts) as an alternative to the default
  detailed multi-line view, for quickly scanning provenance across all nodes.
- **`portfolio --csv`** exports the roll-up as CSV (header plus one row per
  project: name, path, node count, coverage, proved, problems, cycles flag, and
  health/status), mutually exclusive with `--json`; the default text view is
  unchanged.
- **`staleness --markdown`** renders the trust audit as a portable Markdown table
  (heading, summary line, and one row per flagged trusted node with its
  problem/incomplete/outdated severity and causes). Mutually exclusive with
  `--json`; honours `--top` / `--max-causes`; default text output is unchanged.
- **`search-facts --markdown`** renders the candidate-fact results as a Markdown
  table (fact name, score, source theory) under a query heading, for pasting
  into issues or notes. Mutually exclusive with `--json`; text output unchanged.
- **`diff --markdown`** renders the project-vs-baseline comparison as a Markdown
  summary (sections for added, removed, and changed nodes, with regressions
  flagged) suitable for a PR comment or step summary. It is mutually exclusive
  with `--json`, preserves the `--fail-on-regression` exit `5` behaviour, and
  leaves the default text output unchanged.
- **`tags --fail-under PCT`** turns the tag roll-up into a per-tag CI gate: exit
  `5` when any gated tag's proved-coverage is below `PCT` (an integer `0`–`100`),
  listing the offending tags on stderr. Honours `--tag`, tags with no formal
  targets never fail, and `--json` adds a `gate` object
  (`fail_under`/`failing_tags`/`ok`).
- **`effort --fail-under PCT`** turns the effort report into a CI gate: exit `5`
  when effort-weighted coverage is below `PCT` percent (0–100, float or int), or
  undefined, matching the fail flags on `gate`/`staleness`/`diff`/`burndown`.
  `--json` adds an additive `gate` object (`fail_under`, `effort_percent`,
  `meets`); without the flag, behaviour and exit code are unchanged.
- **`roadmap --mermaid`** emits a Mermaid `flowchart` of the staged plan (one
  `subgraph` per dependency stage, nodes labelled by id, edges following `uses`
  between stages) to stdout. Mutually exclusive with `--json`, and it honours the
  existing `--status`/`--stage`/`--kind` filters.
- **`stats --min-success-rate PCT`** turns the agent-memory analytics into a CI
  gate: exit `5` when the overall proof-attempt success rate falls below `PCT`
  percent (0–100), matching the exit-5 convention used by `gate`/`diff`/`burndown`.
  Text mode prints a stderr policy message; `--json` adds an additive `gate`
  object (`min_success_rate`, `success_rate`, `meets`). The gate compares the
  exact (unrounded) success rate so verdicts are stable near the threshold. When
  there are no resolved attempts the gate is not enforced; without the flag,
  behaviour is unchanged.
- **`burndown --markdown`** renders the velocity/ETA forecast as a Markdown
  summary (heading, a status/remaining/eta_days/eta_date/forecast table, and a
  short note when stalled/regressing/scope-growing); mutually exclusive with
  `--json`.
- **`tags --markdown`** renders the per-tag roll-up as a Markdown table (tag,
  nodes, formal targets, proved, found, problems, proved-coverage%) plus an
  untagged-count line. Mutually exclusive with `--json`; composes with `--tag`
  and `--fail-under`, and tag cells escape `|`.
- **`effort --markdown`** renders the effort-weighted report as a Markdown
  document with a summary table (total/proved/remaining effort and coverage
  percent), plus a per-tag table when combined with `--by-tag`. Mutually
  exclusive with `--json`; composes with `--fail-under` (the gate still sets
  exit `5`).
- **`graph --roots-only`** prunes the emitted graph (every format) to root nodes
  — those nothing else `uses` (no incoming dependency edges, the end-goals);
  composes with `--focus`/`--depth` and is a no-op without the flag.
- **`scorecard --markdown`** also writes the rendered Markdown scorecard to
  `build/scorecard.md` under the configured `build_dir`. Composes with the
  `--min-grade`/`--min-score` gates and `--json`; stdout and the exit code are
  unchanged.
- **`theory-index --mermaid`** emits a Mermaid `flowchart` of the theory import
  graph (one node per theory, one `A --> B` edge per in-project import) to
  stdout. Source-only (no Isabelle needed), a standalone output mode that errors
  if combined with `--json` or any query flag
  (`--callers`/`--callees`/`--deps`/`--sorry`/`--unreferenced`/`--counts`), and
  it honours the existing `--root`/`--session` resolution.
  between stages) to stdout. Mutually exclusive with `--json`/`--csv`, and it
  honours the existing `--status`/`--stage`/`--kind` filters.
- **`roadmap --csv`** emits one CSV row per node in the staged plan (columns:
  `stage`, `node_id`, `kind`, `formal_status`, `agent_status`,
  `blocked_by_count`) plus a header to stdout. Mutually exclusive with
  `--json`/`--mermaid`, and it honours the existing `--status`/`--stage`/`--kind`
  filters.
- **`impact --format csv`** exports the blast-radius analysis as CSV: one row
  per node ranked by blast radius (columns: `node_id`, `direct_dependent_count`,
  `blast_radius_count`, `affected_goal_count`), or one row per dependent (columns:
  `dependent_id`, `distance`) when `--node` is given.
- **`portfolio --min-coverage PCT`** is a cross-project coverage floor: it exits
  `5` when any project's proved-coverage is below `PCT`, naming the offending
  projects on stderr (text mode) and adding a `coverage_gate` object in `--json`
  mode. Projects with undefined coverage (no formal targets, or load errors) are
  excluded from failures. Composes with `--fail-on-problem`; absent the flag,
  behaviour is unchanged.
- **`tags --csv`** emits one CSV row per tag (columns: `tag`, `nodes`,
  `formal_targets`, `proved`, `found`, `problems`, `proved_coverage_percent`)
  plus a header and a trailing `(untagged)` count row to stdout. Mutually
  exclusive with `--json`/`--markdown`; honours `--tag` and the `--fail-under`
  gate.
- **`graph --leaves-only`** prunes the emitted graph (every format) to leaf
  nodes — those that use nothing (the foundational axioms/definitions).
  Composes with `--focus`/`--depth`/`--format`; mutually exclusive with
  `--roots-only`; default graph output is unchanged.
- **`staleness --csv`** emits one CSV row per flagged trusted node (columns:
  `node_id`, `severity`, `cause_count`, `first_cause`) plus a header to stdout.
  Mutually exclusive with `--json`/`--markdown`; honours `--top`/`--max-causes`
  and composes with the `--fail-on-problem`/`--fail-on-outdated` gates.
- **`notify --format markdown`** prints a plain Markdown notification body
  (heading with project name + coverage, a one-line status summary, the metric
  lines, and the optional burndown ETA) to stdout as a local preview. It is
  never POSTed: combining it with `--send` errors that markdown is preview-only.
  Existing webhook formats and `--send` behaviour are unchanged.
- **`lint` adds a `singleton-tag` rule** (INFO) flagging any tag used by exactly
  one node across the blueprint (likely a typo or orphaned category); the message
  names the tag and the single node carrying it. Purely additive: it never fires
  for tags shared by two or more nodes.
- **`agent-context --markdown`** prints the agent-context Markdown handoff (the
  same content `render_agent_context` / `--write` produces in `agent-context.md`)
  to stdout; the flag itself writes no files, but `--write` may still be passed
  to also emit artifacts. Mutually exclusive with `--json`; the existing filter
  flags compose with it and default behaviour is unchanged.
- **`roadmap --markdown`** renders the staged plan as Markdown: a heading and one
  `## Stage N` section per stage with a table of that stage's nodes (id, kind,
  formal status, agent status, blocker count, with `|` escaped in cells).
  Respects the `--status`/`--stage`/`--kind` filters and joins the existing
  `--json`/`--mermaid`/`--csv` mutually-exclusive group; default text output is
  unchanged.
- **`tasks --summary`** prints a compact aligned table of the ready tasks
  (columns: task id, node id, kind, priority, difficulty, blocked-by count) to
  stdout and writes no files. Composes with the selection filters
  (`--kind`/`--priority`/`--difficulty`/etc.); default behaviour is unchanged.
- **`effort --csv`** exports the effort-weighted report as CSV: a single summary
  row (columns: `total_effort`, `formal_target_effort`, `proved_effort`,
  `found_effort`, `remaining_effort`, `coverage_percent`), or one row per tag
  plus the untagged bucket (`tag`, `total_effort`, `proved_effort`,
  `remaining_effort`, `coverage_percent`) with `--by-tag`. Mutually exclusive
  with `--json`/`--markdown`; composes with `--by-tag` and the `--fail-under`
  gate.
- **`doctor --require TOOL`** (repeatable; choices `graphviz`, `isabelle`) turns
  doctor into a CI precondition gate: it exits `5` when any required tool is
  unavailable. In `--json` mode it adds an additive `requirements` array of
  `{tool, available, required}` entries. Without `--require`, doctor stays
  informational and its behaviour/exit are unchanged.

### Changed

- **Task and roadmap generation share a single node index** instead of rebuilding
  `project.by_id()` once per node inside their readiness/blocker checks. This
  removes an O(n²) rebuild on a hot path (`generate_tasks` and `build_roadmap`
  run on `status`, `report`, `portfolio`, `roadmap`, and `agent-context`). Output
  is unchanged; a regression test asserts the index build count no longer scales
  with node count.
- **Coverage percentage is computed in one place.** The status metric, the
  effort-weighted report, and the portfolio roll-up now all call a single
  `report.metrics.coverage_percent()` helper (truncate-not-round, with the
  sub-1% clamp), so the badge, README, CI summary, and dashboards can no longer
  drift apart as three hand-copied formulas. No output change.
- **`gate` and `diff` now colourise their verdicts** (green pass / red fail and
  red `[regression]` markers) when colour is enabled, matching the other health
  commands (`lint`, `scorecard`, `status`, `staleness`). Plain-text and
  machine-readable output are byte-for-byte unchanged; honours `--color` /
  `--no-color` / `NO_COLOR`.
- **Coverage gate raised from 85% to 87%.** The Isabelle subprocess shim
  (`isabelle._run.run_capture`) — the anti-hang machinery every `check`/`dump`
  call relies on — gained a dedicated behavioural test suite that drives real
  short-lived subprocesses through the happy path, stdin-EOF, non-UTF-8 decode,
  `timeout` tree-kill, and `max_output_bytes` flood-cap paths.

### Fixed

- **`graph --format svg` can no longer hang** on a wedged or pathological
  Graphviz `dot` process: `render_svg` now bounds the subprocess with a timeout
  (default 30s) and degrades to an SVG comment instead of blocking the caller
  indefinitely.
- **`diff` now rejects a baseline `project.json` with duplicate node ids.**
  The loader previously kept the last duplicate silently, which could mask a
  regression on the dropped node; a corrupted snapshot now fails fast with a
  clear error.
- **`search-facts` handles a non-positive `--limit` correctly.** A negative
  limit used to fall through to `hits[:limit]` and silently drop the
  lowest-ranked match instead of returning nothing.
- **Package version no longer drifts from the release.** `isabelle_blueprint.__version__`
  was a hand-maintained literal still reading `1.11.0` after the `1.12.0` release,
  so `--version`, `version --json`, `doctor`, the MCP server banner, SARIF runs,
  and `agent-context` all reported the wrong version. `__version__` is now
  single-sourced from installed distribution metadata (with a source-tree literal
  fallback), and a packaging test asserts both track `pyproject.toml`.

## [1.12.0] - 2026-06-06

### Added

- **`fmt` command** rewrites Markdown blueprints into the canonical interchange
  form (one node per `:::` block, fixed metadata order, the full three-axis
  status block). `fmt --check` reports drift and exits non-zero (10) without
  writing, giving CI a cheap "is the blueprint canonical?" gate. LaTeX sources
  are reported as skipped (the LaTeX writer emits a whole standalone document).
- **`explain` now surfaces dependency provenance for proof trust.** Because
  `sorry`/oracle taint propagates downstream, a `tainted`/`found` node is only as
  trustworthy as its dependencies. `explain` now points at the direct
  dependencies that are themselves tainted/broken (the likely cause) or simply
  not proved yet (the remaining blockers), using the already-known per-node
  statuses.
- **`tasks --github-sync-pull`** adds the read side of GitHub issue sync. It
  fetches the current open/closed state of every tracked issue into
  `build/github-sync-state.json` (and notes which are closed upstream) **without
  mutating** any issue or the blueprint, so closed-as-done tasks can be
  reconciled. A deleted/unreachable issue is reported as `missing`.
- **MCP `list_assignments` read tool** (plus `blueprint://assignments` and
  `blueprint://projects/{project}/assignments` resources) exposes recorded
  per-node ownership over MCP **without** `--allow-writes`. Previously the only
  assignment surface was the write-gated `assign_node` tool, so a read-only
  agent could not discover who owns a node before starting work — even though
  CLI `assign` (no flags) lists ownership without writing. Mirrors CLI `assign`
  list mode.

### Fixed

- **`dump --from-dir` now reports `isabelle_available` truthfully.** Offline
  inspection of an existing PIDE dump directory hard-coded `isabelle_available`
  to `false` (it was derived from whether an Isabelle process had been launched),
  so the JSON dump report claimed Isabelle was unavailable even when it was on
  PATH. `inspect_dump_dir` now resolves the configured executable on PATH
  independently of whether a process was run.
- **Invalid blueprint `status` values now raise a clean `ParseError` instead of
  leaking a raw enum `ValueError` (with traceback).** A typo in an explicit
  status axis — `status.formal: typo` in Markdown, `\blueprintstatus{typo}` in
  LaTeX — previously crashed the parser with an uncaught
  `ValueError: 'typo' is not a valid FormalStatus` traceback, since the CLI/MCP
  boundary only catches `BlueprintError`. Both parsers now coerce status tokens
  through a shared `coerce_status` helper that reports `error: invalid formal
  status 'typo'; expected one of: …`, matching every other parse error.
- **GitHub issue sync no longer adopts an unrelated issue from search.** When
  local sync state was missing, `sync_github_issues` reused the first issue
  returned by GitHub's free-text search — which can match any issue that merely
  mentions the node id — and would then update or even *close* that foreign
  issue. It now only adopts a searched issue whose body carries the exact
  `<!-- isabelle-blueprint:task node_id=… -->` marker this tool injects.
- **GitHub sync state is now written atomically** (temp sibling + rename),
  matching the agent-memory and assignment stores. An interrupted write can no
  longer leave a truncated `github-sync` state file that a later run rejects as
  corrupt.
- **PR status comments flatten multi-line text into list items.** A node title
  or Isabelle `check_error` containing newlines previously terminated its
  Markdown list item early and spilled the remainder into the comment body. Such
  fields are now collapsed to a single line before rendering.
- **Agent-memory and assignment stores are now written atomically** (temp
  sibling + rename) instead of truncate-in-place. A concurrent reader — e.g. the
  MCP `stats` or new `list_assignments` tool running while a write tool updates
  the store — can no longer observe a half-written file and treat it as corrupt.
- **MCP `compat`/`history`/`burndown`/`theory_index` (and the `agent_run_plan`
  prompt-path helper) no longer leak a raw `ValueError`/`OSError`** on a
  malformed `isabelle-blueprint.toml`. They now load configuration through the
  same `load_config_checked` boundary introduced in 1.11.0, so a bad config
  surfaces as a clean `BlueprintError` consistent with every other entrypoint.
- **MCP `assign_node` rejects a whitespace-only owner.** The `if not owner`
  guard treated `"   "` as truthy, so a blank owner was persisted (and rendered
  as an empty owner badge in the static site). The guard now also rejects
  whitespace-only owners, and a valid owner is stored stripped.

### Changed

- **MCP `lint`, `graph`, and the staleness resources load more cheaply.** They
  used the full `_snapshot` loader (which also computes fact suggestions, agent
  memory, and the ready-task list) but only needed the parsed project, so they
  now use the lean `load_project_with_check` loader — matching `critical_path`
  and `impact` and avoiding wasted work per call.

## [1.11.0] - 2026-06-05

### Fixed

- **Coverage percentage no longer rounds to a false 100% (or 0%).** The
  `status`/`report` `coverage_percent` metric (and the portfolio roll-up)
  previously used `round(proved / formal_targets * 100)`, so a project at
  999/1000 proved reported **100%** — and was mislabelled `complete` by the
  health check — while 1/1000 reported **0%**. Coverage is now truncated
  (`proved * 100 // formal_targets`), so 100 means genuinely all-proved; a
  non-zero ratio that truncates below 1% is clamped up to **1%**, so 0% is
  reserved for "nothing proved". Exact fractions (33%, 50%, 100%) are unchanged.
- **`discover_roots` no longer skips every ROOT when the project lives under a
  dotted directory.** The hidden-directory filter compared the *absolute* path
  components, so any project under e.g. `~/.local/share/...` or a `.worktrees/`
  checkout had all of its ROOT files silently skipped. The check is now relative
  to the search root, so only dot-directories *inside* the project are pruned.
- **`diff --json` `regression_count` now includes removed nodes.** A removed
  proved node counts as a regression for `has_regression` and the rendered
  "N regression(s)" headline, but the JSON `regression_count` counted only
  changed nodes, so the field disagreed with the rest of the report. It now
  matches.
- **Agent-task prompt filenames are sanitised for unsafe node ids.** Node ids
  containing path separators or Windows-illegal characters (`:`, `/`, `\`, …)
  could escape the `prompts/` directory or fail to write. The `tasks` and
  `attempt`/`next` commands now route prompt filenames through a shared helper:
  filesystem-safe ids keep the documented `build/prompts/<task-id>.md` layout
  verbatim, while unsafe ids are slugified and hash-suffixed so they stay inside
  the prompts directory and never collide. (The stale-prompt sweep uses the same
  mapping, so sanitised prompts are not deleted on rewrite.)
- **Mermaid graph node ids are now collision-free.** `_mermaid_id` collapsed
  every non-alphanumeric character to `_`, so blueprint ids differing only in
  their separators (`a.b` vs `a-b`) rendered as the same Mermaid node and lost
  edges. Disallowed characters are now escaped by codepoint, making the mapping
  injective.
- **Theory import reports the correct line numbers** for declarations that
  follow blank lines (the multiline `^\s*` anchor could match a preceding blank
  line and report a line too early), and **tolerates non-UTF-8 bytes** in theory
  sources and `ROOT`/`ROOTS` files (reads now use `errors="replace"` instead of
  crashing with a `UnicodeDecodeError` that the surrounding `except OSError`
  did not catch).
- **`parse_root_directories` now accepts unquoted directory names.** A
  `directories src lib` clause (bare, unquoted — valid Isabelle) was silently
  ignored because only double-quoted names were collected; quoted and unquoted
  forms are now both handled.
- **Malformed configuration and bad `init` targets produce a clean error**
  instead of a raw traceback. A malformed `isabelle-blueprint.toml` now surfaces
  as a one-line `error: could not load configuration …` (wrapped at the
  `load_project` boundary, so `load_config` still raises `ValueError` for its
  existing callers), and `init` pointed at a path that exists as a regular file
  reports `… is not a directory` rather than leaking a `FileExistsError`.

### Changed

- **`assign` validates flag combinations that were previously silent no-ops.**
  Running `assign --owner NAME` with no node id (the owner was discarded),
  `assign NODE --note TEXT` with no `--owner` (the note was dropped, since a
  note is only stored alongside an owner), `assign --clear` with no node id, or
  `assign NODE --clear --owner NAME` (the `--clear` branch runs first, so the
  owner/note would be ignored) now raise a clear `BlueprintError` instead of
  silently listing assignments and exiting 0 — matching the existing validation
  on sibling commands and the MCP `assign_node` tool.
- **`check`/`attempt` `--jobs` rejects non-positive values.** `--jobs 0` and
  `--jobs -N` were accepted and silently forwarded as a no-op; they are now
  rejected like the other count flags (argparse exit 2).
- **`agent-run` fails fast on a corrupt agent-memory store.** When recording is
  enabled, a corrupt `agent-memory.json` was only detected at record time —
  *after* the (possibly expensive) solver had already run — discarding the
  completed attempt. The store is now validated before the solver is spawned, so
  the failure is reported up front. `--no-record` runs are unaffected.
- Documentation corrections: the frozen exit-code contract now documents codes
  `3` (degraded `check`/`dump --strict`) and `4` (`isabelle build` non-zero)
  and no longer attributes them to code `6` (which is `comment --strict` only);
  the always-registered MCP read-tool list is complete (24 tools); the `--color`
  scope lists every colourising command; the GitHub Action `coverage_percent`
  output is described as proved-only; and the README/example gallery coverage
  figures and quoted `report` excerpts were regenerated against the current tool
  output.

### Added

- The VS Code extension gains parity with the new analytics and the owner
  store: three commands — **Audit Staleness** (`staleness`), **Forecast
  Burndown** (`burndown`), and **Show Critical Path** (`critical-path`) — run the
  read-only analyses straight into the output panel, and the **Blueprint Nodes**
  tree now shows `@owner` annotations (full owner in the tooltip) sourced from
  `.isabelle-blueprint/assignments.json`, refreshing automatically when
  assignments change. The analyses already expose dedicated MCP tools and the
  extension is a separate consumer, so no new MCP surface was needed.
- The static site's graph page now overlays a **critical-path panel** — the
  longest remaining dependency chain to a goal plus the highest-leverage
  bottlenecks (reusing the same analysis as the `critical-path` command) — and,
  when an `assignments.json` store is present, **owner badges** with an owner
  filter over the dependency-levels listing (wired through the existing generic
  `filters.js`, so no new JavaScript). Critical-path nodes are flagged with a
  `★` marker on both the graph and per-node pages, and the full analysis is also
  written to `site/critical-path.json` for automation. The overlays are
  additive and backward-compatible: stale assignment ids (no matching node) are
  ignored, projects with no assignments omit the owner filter, and an all-proved
  project renders an empty-state callout. (The critical-path analysis already
  has a dedicated `critical_path` MCP tool, so no new MCP surface was needed.)
- New `agent-run` command (and matching read-only `agent_run_plan` MCP tool) that
  closes the proof loop end-to-end: it selects the next ready task (using the same
  filters and `--node` selector as `next`/`attempt`), renders the prompt, runs an
  **external solver** against it, classifies the result, and records the outcome in
  agent memory — all in one command. The solver is run **without a shell**: supply
  it argv-native via `--exec PROGRAM --arg ARG ...` (recommended on Windows; use
  the `--arg=-c` form for dash-led values) or as a POSIX-`shlex` `--command`
  string. Placeholder values (`{prompt_file}`, `{node_id}`, `{task_id}`,
  `{project_dir}`) are substituted per argv token so they cannot inject extra
  arguments, and unknown placeholders are rejected. A configurable `--timeout`
  (default 900s, with child-process-tree kill) and `--max-output-bytes` cap
  (default 10 MiB; `0` disables) guard against hangs and runaway output; only
  bounded stdout/stderr tails are surfaced and recorded. Exit 0 → `succeeded`;
  non-zero / timeout / output-limit → `--failure-outcome` (default `failed`); a
  spawn error → `blocked` and is **never** recorded (it is a harness/config
  failure, not a proof attempt) and always exits 1. `--dry-run` previews the
  resolved command without running, writing the prompt, or recording; `--no-record`
  runs without writing memory; `--fail-on-failure` exits 5 when the outcome is not
  `succeeded`. The MCP `agent_run_plan` tool **plans** the invocation (returning the
  selected task, the substituted `command_argv_preview`, the `prompt_path`, the
  exact `cli_argv`, and the outcome mapping) but never executes a command or writes
  a file — actually running the solver is intentionally CLI-only because spawning
  local processes is a different trust boundary from the server's read/append-JSON
  surface. `run_capture` gained an optional `max_output_bytes` poll-based cap
  (raising the new `OutputLimitExceeded`); the default `None` path is byte-for-byte
  unchanged, so the Isabelle wrapper callers are unaffected.
- New `portfolio` command (and matching `portfolio` MCP read tool plus
  `blueprint://portfolio` resource) rolls up status across **every** blueprint
  project under a directory tree into one dashboard — per-project coverage,
  health, problem/cycle flags, and ready-task counts, plus portfolio-wide totals.
  This is the cross-project view that single-project `status` cannot give, aimed
  at monorepos and umbrella repositories. Project discovery mirrors the MCP
  catalog (marker files, nested-project pruning, build/vendor skip dirs), and
  loading is best-effort: a project that fails to load (missing blueprint,
  malformed TOML, unreadable file) is reported as an error entry rather than
  aborting the roll-up. `coverage_percent` is `null` when there are no formal
  targets. Supports `--json` and `--fail-on-problem` (exit 5 when any project has
  problems, a dependency cycle, or fails to load). The MCP tool is workspace-wide
  and takes no `project` argument.
- New `burndown` command (and matching `burndown` MCP read tool plus
  `blueprint://burndown` resources) forecasts an ETA to full *proved* coverage
  from the recorded `trends.json` history. The forecast regresses **remaining**
  work over time rather than completed velocity, so a growing
  `formal_target_count` is reflected — proving faster does not move the date if
  the target grows just as fast. It reports proved/target/net-burndown
  velocities (overall and over a recent window), classifies the project as
  `on_track`, `stalled`, `regressing`, `scope_growing`, `complete`, or
  `beyond_horizon`, and supports `--window`, `--limit`, and `--fail-when-stalled`
  (exit 5) for CI. Like `history`, it reads only the trend store, so it keeps
  forecasting when the current blueprint fails to parse.
- New `staleness` command (and matching `staleness` MCP read tool plus
  `blueprint://staleness` resources) audits every trusted (`found`/`proved`)
  node and walks its dependencies to flag the ones whose green status is not
  actually justified — because a dependency is broken/tainted/missing
  (`problem`), unproven (`incomplete`), itself `stale`, or was re-checked more
  recently than the node (`outdated`). It also flags trusted nodes that sit in a
  dependency cycle or `uses:` a non-existent node, counts trusted nodes that have
  never been checked (unknown freshness), and supports `--top`, `--max-causes`,
  and `--fail-on-problem` (exit 5) for CI. This is the project-wide inverse of
  `impact`: where `impact` asks "what rests on X?", `staleness` asks "is X's
  trust well-founded?".
- `completion --install` / `completion --dest PATH` write the generated script
  straight to the shell's conventional completion location (or an explicit path),
  creating parent directories and printing the destination plus any activation
  hint, so users no longer have to know where each shell looks for completions.
- Shell completion scripts now complete **per-subcommand options**, not just
  subcommand names. After a subcommand, any word starting with `-` completes
  that subcommand's flags (e.g. `lint --<tab>` offers `--json`, `--strict`, …),
  otherwise the shell falls back to file completion. The option lists are
  generated from the live argparse parser for every shell (bash, zsh, fish, and
  PowerShell), so they never drift from the real flags.
- `completion powershell` generates a PowerShell completion script that registers
  a native argument completer (`Register-ArgumentCompleter`) for the subcommand
  names, falling back to PowerShell's default file completion for arguments. Load
  it with `isabelle-blueprint completion powershell | Out-String | Invoke-Expression`
  (add that line to your `$PROFILE` to persist it). This brings Windows/pwsh to
  parity with the existing bash/zsh/fish scripts and, like them, is generated
  from the live subcommand list so it never drifts from the parser.
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

[Unreleased]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.10.0...HEAD
[1.10.0]: https://github.com/Arthur742Ramos/isa-blueprint/compare/v1.9.0...v1.10.0
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
