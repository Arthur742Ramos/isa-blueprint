# IsabelleBlueprint

> Project planning, dependency tracking, documentation, and AI-task orchestration for **Isabelle/HOL** formalization projects.

[![blueprint](https://github.com/Arthur742Ramos/isa-blueprint/actions/workflows/blueprint.yml/badge.svg)](https://github.com/Arthur742Ramos/isa-blueprint/actions/workflows/blueprint.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org)
[![license: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

IsabelleBlueprint lets you write a Markdown "blueprint" of the theorems, definitions, and lemmas you intend to formalize, link them to concrete Isabelle facts, validate the dependency graph, render a browsable HTML status site, and emit ready-to-execute prompts for AI agents working on the proofs.

It is heavily inspired by [Patrick Massot's *Lean Blueprint*](https://github.com/PatrickMassot/leanblueprint), but it is **Isabelle-aware from the ground up** and **Python-first** (no LaTeX toolchain required).

---

## Status — v0.1 (MVP)

This is the initial Python MVP. It ships everything you need to plan a formalization project, validate it against a real Isabelle session, share a public status page, and hand work to AI agents. Several roadmap items intentionally remain for later releases (see [Roadmap](#roadmap)).

What works today:

- ✅ Markdown blueprint parser (fenced `:::` blocks + YAML metadata)
- ✅ Three-axis status model: blueprint × formal × agent
- ✅ Dependency validation (cycles, missing references, duplicates)
- ✅ Graphviz output (`graph.dot`, `graph.json`, optional `graph.svg`)
- ✅ Isabelle fact-existence checker (`Blueprint_Check.thy` generator + `isabelle build` wrapper)
- ✅ Static HTML site (index, per-node pages, dependency graph, status, tasks)
- ✅ Agent task pack (`tasks.json`, `tasks.md`, per-task Markdown prompts)
- ✅ JSON / Markdown status reports
- ✅ `init` scaffolder with default config and GitHub Actions workflow
- ✅ Minimal end-to-end example under [`examples/minimal/`](examples/minimal)
- ✅ pytest suite + cross-platform CI (Ubuntu + Windows, Python 3.11/3.12/3.13)

What is **deliberately** out of scope for v0.1: a LaTeX parser, PIDE / `dump` integration, `sorry` / oracle detection, AFP compatibility checks, and a VS Code extension. See [Roadmap](#roadmap).

---

## Install

```bash
pip install isabelle-blueprint
```

or from a checkout:

```bash
git clone https://github.com/Arthur742Ramos/isa-blueprint
cd isa-blueprint
pip install -e ".[dev]"
```

Optional system dependencies:

| Tool       | Used for                                       | Required? |
|------------|------------------------------------------------|-----------|
| `isabelle` | per-fact existence check via `isabelle build`  | optional — without it, `check` still validates the blueprint structure |
| `dot` (Graphviz) | SVG rendering of the dependency graph    | optional — `graph.dot` / `graph.json` are always emitted |

---

## Quickstart

```bash
# 1. Scaffold a new project (creates blueprint.md + isabelle-blueprint.toml + CI workflow)
isabelle-blueprint init my-project
cd my-project

# 2. Edit blueprint.md, adding your definitions, lemmas, and theorems.
#    See examples/minimal/blueprint.md for the syntax.

# 3. Validate structure and (optionally) check Isabelle fact existence.
isabelle-blueprint check

# 4. Emit the dependency graph (DOT + JSON; SVG if Graphviz is installed).
isabelle-blueprint graph

# 5. Render the static HTML site to ./site
isabelle-blueprint web

# 6. Generate ready-to-execute agent tasks and per-task prompts.
isabelle-blueprint tasks

# 7. Produce JSON and Markdown status reports.
isabelle-blueprint report
```

Try it on the bundled example:

```bash
isabelle-blueprint check  examples/minimal
isabelle-blueprint web    examples/minimal
isabelle-blueprint tasks  examples/minimal
isabelle-blueprint report examples/minimal
# Open examples/minimal/site/index.html in a browser.
```

---

## CLI reference

All subcommands take an optional positional `project_dir` (default `.`) and read configuration from `isabelle-blueprint.toml` inside it.

| Subcommand | What it does                                                                                        | Key outputs                                                       |
|------------|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| `init`     | Scaffold `blueprint.md`, `isabelle-blueprint.toml`, and `.github/workflows/blueprint.yml`.          | files in the project directory                                    |
| `check`    | Parse + validate the blueprint, generate `Blueprint_Check.thy`, optionally run `isabelle build`, and stamp each node with its formal status. | `build/check_report.json`, `build/Blueprint_Check.thy`            |
| `graph`    | Emit the dependency graph in DOT and JSON; SVG if Graphviz is installed.                            | `build/graph.dot`, `build/graph.json`, `build/graph.svg`          |
| `web`      | Render the static HTML site (index, status, graph, tasks, per-node pages).                          | `site/index.html`, `site/nodes/*.html`, `site/graph.svg`          |
| `tasks`    | Emit an AI-agent task pack — one JSON record per node, plus a Markdown overview and per-task prompts. | `build/tasks.json`, `build/tasks.md`, `build/prompts/*.md`        |
| `report`   | Write JSON and Markdown summary reports of the project state.                                       | `build/project.json`, `build/report.md`, `build/summary.json`     |

Flags worth knowing:

- `isabelle-blueprint check --isabelle /path/to/isabelle` — override the Isabelle binary.
- `isabelle-blueprint check --strict` — exit non-zero when Isabelle is unavailable or the build did not run.
- `isabelle-blueprint init --force` — overwrite existing scaffolded files.

---

## Three-axis status model

Most blueprint tools collapse "is this proved?" into a single status. IsabelleBlueprint keeps three independent axes per node — because the informal write-up, the formal proof, and the AI agent's progress can each be in very different shapes:

| Axis           | Values                                                                                                | Meaning                                                       |
|----------------|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| **blueprint**  | `stub` · `drafted` · `reviewed`                                                                       | State of the informal Markdown write-up.                      |
| **formal**     | `missing` · `named` · `not_found` · `found` · `proved` · `tainted` · `stale` · `broken`               | What we know about the corresponding Isabelle fact.           |
| **agent**      | `blocked` · `ready` · `in_progress` · `attempted` · `needs_human` · `done`                            | Where the (human or AI) prover is in the work queue.          |

The `web` and `report` outputs color-code each axis independently so reviewers can see at a glance where the project needs writing, formalization, or human review.

> ⚠️ v0.1 does **not** claim a node is "proved" just because the named fact exists. `proved` is reserved for a future release that integrates PIDE/dump inspection and `sorry` / oracle detection. The `found` state means: "the Isabelle session built and the named fact exists." That is genuine signal — but not a proof certificate.

---

## Blueprint syntax (Markdown)

Each node is a fenced block. The opening fence carries the kind and id; the body is split into metadata (YAML) and free-form Markdown by a second `:::` line:

````markdown
::: theorem {#sum-divides}
title: Sum divides product
isabelle: Arith_Demo.sum_divides
uses:
  - def-divides
  - lem-add-comm
status:
  blueprint: drafted
  formal: named
:::

If $a \mid b$ and $a \mid c$, then $a \mid (b + c)$.

## Proof

Unfold the definition of divides and use commutativity of addition.
:::
````

- **Kinds** the parser understands: `definition`, `lemma`, `theorem`, `proposition`, `corollary`, `example`, `note`. Unknown kinds become `other`.
- **`uses`** is a list of node ids — they drive the dependency graph and the topological order of agent tasks.
- **`isabelle`** can be a string (`Theory.fact_name`) or a YAML mapping (`{theory: ..., fact: ..., session: ...}`).
- Both fence styles are accepted: `::: theorem {#id}` *and* `::: {.theorem #id}`.

See [`examples/minimal/blueprint.md`](examples/minimal/blueprint.md) for a complete working example.

---

## Configuration (`isabelle-blueprint.toml`)

```toml
[project]
name      = "My formalization"
blueprint = "blueprint.md"

[isabelle]
session    = "My_Session"   # passed to `isabelle build -b`
# executable = "isabelle"   # path to the binary if not on PATH
# dirs       = ["."]        # extra -d directories

[output]
build_dir = "build"
site_dir  = "site"
```

Everything is optional — the defaults shown above are also what `init` writes for you.

---

## Roadmap

Items planned for future releases (not in v0.1):

- **v0.2** — LaTeX blueprint parser (round-trip with Lean Blueprint-style sources).
- **v0.3** — PIDE / `dump` integration for true *proved* status, plus `sorry` and oracle detection.
- **v0.4** — AFP compatibility / version-pin checks.
- **v0.5** — VS Code extension surfacing blueprint state inline in the editor.

Contributions toward any of these are very welcome.

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

The test suite is fast (~1s) and runs on Ubuntu and Windows in CI across Python 3.11–3.13.

---

## License

MIT — see [LICENSE](LICENSE).

Inspired by [Lean Blueprint](https://github.com/PatrickMassot/leanblueprint) by Patrick Massot.
