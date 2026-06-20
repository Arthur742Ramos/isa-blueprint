# AGENTS.md

This guide is for coding agents making a focused change to **IsabelleBlueprint** (Python package `isabelle-blueprint`). Read it before editing; the README covers the "what/why" pitch.

## What this is

IsabelleBlueprint turns a human-authored **blueprint** of an Isabelle/HOL formalization (a Markdown `blueprint.md` or LaTeX `blueprint.tex`) into a dependency-tracked model, optionally verifies each node against Isabelle, and emits reports, graphs, and agent task lists. It ships a ~60-subcommand CLI, an MCP server, a GitHub Action, and a VS Code extension. Data flow is linear and identical for every command: blueprint source → parser → `BlueprintProject` → optional stored check report folds in node statuses → `DependencyGraph` → report/graph/agent/render generators write artifacts.

## Setup

- Python **3.11+** (`requires-python = ">=3.11"`; CI matrix is 3.11/3.12/3.13 on ubuntu + windows).
- From the repo root:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Runtime deps are stdlib + **PyYAML** and **Jinja2** only. Extras: `dev` (pytest, pytest-cov, ruff, mypy, mcp, jsonschema, types-PyYAML, build) and `mcp` (for the MCP server).

## Build, test & checks

Run all three and make them pass before committing (these match CI exactly):

```bash
python -m ruff check .
python -m mypy isabelle_blueprint
python -m pytest tests/ -q
```

Coverage is a separate CI gate (must stay ≥ 87%):

```bash
python -m pytest tests/ --cov=isabelle_blueprint --cov-report=term-missing --cov-fail-under=87
```

If you touch the VS Code extension (`vscode/`), also compile it (Node 22 in CI):

```bash
cd vscode && npm ci && npm run compile
```

Tool configs live in `pyproject.toml`: ruff (line-length 100, target py311, rules `E,W,F,I,UP,B`, excludes `examples`/`vscode`), mypy (type-checks `isabelle_blueprint` only — not tests), pytest (`testpaths=["tests"]`, `test_*.py`).

## Project layout

Package root: `isabelle_blueprint/`. Console scripts: `isabelle-blueprint` = `cli:main`, `isabelle-blueprint-mcp` = `mcp_server:main` (also `python -m isabelle_blueprint`).

| Path | Responsibility |
|------|----------------|
| `cli.py` | The ~5381-line monolith. One `cmd_<name>(args) -> int` per subcommand; all wired in `_build_parser()`; `main()` dispatches via `args.func(args)`. |
| `mcp_server.py` | MCP server exposing the same model/parser/graph/agents/report stack to AI agents. |
| `project_io.py` | Shared loaders: `load_project`, `load_config_checked`, `load_project_with_check`, `apply_stored_check_report`. **Use these — don't re-parse YAML/Markdown ad hoc.** |
| `config.py` | `BlueprintConfig` + `load_config` (reads `isabelle-blueprint.toml`); all artifact paths are properties. |
| `model/` | `node.py` (`BlueprintNode`, `NodeKind`, `IsabelleRef`), `status.py` (three status enums), `project.py` (`BlueprintProject`, `ValidationReport`). |
| `parser/` | `markdown.py` (`::: kind {#id}` blocks), `latex.py`; `parse_blueprint*` picks by suffix. Entry: `parse_blueprint_text`. |
| `graph/` | `dependency_graph.py` (`build_graph`, `DependencyGraph`), `graphviz_render.py` (DOT/JSON/SVG/D2 + Mermaid/GraphML). |
| `isabelle/` | All Isabelle integration: `checker.py`, `theory_gen.py`, `reconcile*.py`, `sledgehammer.py`, `fact_search.py`, `find_theorems.py`, `_run.py` (`run_capture` subprocess helper), etc. |
| `report/` | ~37 single-purpose report generators, mostly one per CLI command (scorecard, badge, roadmap, metrics, sarif, gate, ...). |
| `agents/` | Agent task orchestration: `tasks.py`, `memory.py`, `assignments.py`, `github_sync.py`, `runner.py`. |
| `render/` | Jinja2 static-site generation (`site.py` + `templates/`); backs `web`/`serve`. |
| `schemas/` | 22 `*.schema.json` output schemas; `schemas.py` (module) exposes `SCHEMA_NAMES`. |

### Adding a new CLI subcommand

1. Write a `cmd_<name>(args: argparse.Namespace) -> int` function in `cli.py`.
2. In `_build_parser()`, add `p_x = sub.add_parser("name", help=...)`, declare its args, and `p_x.set_defaults(func=cmd_x)`.
3. Put real logic in a `report/`, `agents/`, etc. module that returns data/strings; keep `cli.py` thin (I/O + exit code only).
4. If it emits JSON, add/extend a schema in `schemas/` (and keep `SCHEMA_NAMES` in sync), then validate in tests.

## Conventions & gotchas

- Every module: short docstring, then `from __future__ import annotations`.
- Typing: PEP 604 unions (`str | None`, not `Optional`), builtin generics, `@dataclass` with `field(default_factory=...)`, `enum.StrEnum`, `TypedDict` for parsed records. Dataclasses expose `to_dict() -> dict[str, Any]`.
- **No stdout in library code.** `model/`, `report/`, `parser/`, `graph/`, `agents/`, `isabelle/`, `render/` must NEVER `print` or `sys.exit` — return strings/dataclasses/dicts. Only `cli.py` (and the `mcp_server`/`completion`/`doctor`/`scaffold` entry points) do I/O and exit codes.
- Errors: raise from the `errors.py` hierarchy (`BlueprintError`, `ParseError`, `ValidationError`, `CheckerError`). `cli.main()` catches `BlueprintError` → `error: ...` to stderr + return 1; never let raw tracebacks escape.
- Diagnostics/warnings go to `sys.stderr`; the primary machine-readable result goes to stdout. JSON via `json.dumps(payload, indent=2)`.
- Color: `console.py` only, opt-in after `console.configure(...)`. Machine-readable output (JSON, SARIF, completion scripts) must NEVER pass through console helpers. Honors `NO_COLOR`; `--json` is never colorized.
- **Determinism:** sort all output (ids, lists) so diffs and schema tests stay reproducible.
- Never call `subprocess` directly for Isabelle — use `isabelle/_run.py` `run_capture(...)` (temp-file capture, process-tree kill on timeout, stdlib-only).
- The Isabelle layer must tolerate a missing `isabelle` binary: `checker.py`/`sledgehammer.py` always write a JSON report and emit a `note:` to stderr rather than failing. Preserve this graceful degradation.
- Suppress rules narrowly: `# noqa: <CODE> - reason` and `# type: ignore[code]`; no blanket disables.
- New `render/templates/*.j2`, `render/templates/static/*`, or `schemas/*.schema.json` must be added to `[tool.setuptools.package-data]` in `pyproject.toml` or they won't ship in the wheel.

## Compatibility contract (frozen v1)

Three surfaces are **frozen public contracts** — do not break them without a planned 2.0:

1. **CLI surface** (`docs/cli-contract.md`): subcommand names, documented flags/short-forms and their defaults, and exit codes are stable. Files emitted by `report` keep their paths and JSON shapes.
2. **JSON shapes** (`docs/json-contract.md`): `build/project.json`, `summary.json`, `badge.json/.svg`, `trends.json`, `tasks.json`, `roadmap.json`, `agent-context.json`, and documented stdout payloads (`status --json`, `next --json`, etc.).
3. **GitHub Action outputs** (`action.yml`): the keys `coverage_percent`, `node_count`, `formal_target_count`, `proved_count`, `found_count`, `problem_count`, `has_cycles` (same 7 also written to `$GITHUB_OUTPUT`).

Rules: never rename/remove a command, flag, or JSON key; never change a default behavior or the meaning of an existing field. You **may** add a new key (consumers ignore unknown keys) or extend an enum value set (consumers must handle unknown enum values defensively). Always prefer an **opt-in flag, a new field, or a new file** over any breaking change. A `compat` subcommand and `tests/test_compat.py` / `tests/test_e2e.py` (schema validation) guard this — JSON output is validated against `schemas/*.schema.json`.

Free to change (not contract): exact Markdown/HTML of `report.md`/`pr-comment.md`/`site/`, internal `build/check-cache.json`, and the evolving `stats --json` / `staleness --json` analytics payloads.

## Releases

Only relevant if your change ships a release. Bump **both** version literals in the **same commit**:

1. `pyproject.toml` → `[project].version`
2. `isabelle_blueprint/__init__.py` → `_FALLBACK_VERSION` (currently `"1.17.0"`)

`tests/test_packaging.py` enforces that they match. The `vscode/package.json` version is independent and is NOT one of these two. On push to `main`, `.github/workflows/publish.yml` detects the bump, re-runs the gates, auto-creates/pushes the `vX.Y.Z` tag, and publishes to PyPI via trusted publishing; a `github-release` job pulls notes from `CHANGELOG.md` (`## [X.Y.Z]`).

## PR expectations

- Keep PRs **focused** and small.
- Include a short user-visible summary of the change.
- Add tests/fixtures for any behavior change (most tests call `from isabelle_blueprint.cli import main` in-process and assert on `capsys` + return code; shared fixtures in `tests/conftest.py`).
- Confirm `ruff`, `mypy`, and `pytest` pass locally.
- Call out any intentional compatibility impact explicitly.
