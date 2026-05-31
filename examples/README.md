# Examples

A gallery of runnable IsabelleBlueprint projects. Each directory is a
self-contained blueprint with its own `isabelle-blueprint.toml`, a `ROOT`,
a skeleton theory, and a `README.md` explaining what it demonstrates.

The first four don't require a working Isabelle install to explore —
`report`, `graph`, and `tasks` run purely from the blueprint sources. (`check`
is the only command that talks to a real `isabelle` binary.) The last one,
[`afp-gale-stewart/`](afp-gale-stewart/), is the real integration example: its
`check` builds an actual [Archive of Formal Proofs](https://www.isa-afp.org)
entry, though its `report`/`graph`/`tasks` still work without Isabelle.

| Example | Format | Nodes | Coverage | Highlights |
| --- | --- | ---: | ---: | --- |
| [`minimal/`](minimal/) | Markdown | 4 | 0% | Smallest possible blueprint; every subcommand, no Isabelle needed. |
| [`group-theory/`](group-theory/) | Markdown | 10 | 50% | Multi-level dependency DAG mixing `missing` / `named` / `found` / `proved` — the colourful graph demo. |
| [`latex-blueprint/`](latex-blueprint/) | LaTeX | 8 | 50% | `.tex` ingestion with `\isabelle` / `\uses` / `\isabelleok`. |
| [`agent-workflow/`](agent-workflow/) | Markdown | 8 | 38% | Task orchestration (ready vs blocked) plus `compat` version/AFP pinning. |
| [`afp-gale-stewart/`](afp-gale-stewart/) | Markdown | 7 | 100% | **Real AFP entry**: cross-session `check` proving Gale–Stewart determinacy, all 7 facts `proved`. |

## Quick tour

```bash
# Status report (Markdown table + JSON summary)
isabelle-blueprint report examples/group-theory

# Dependency graph (Graphviz DOT + JSON; render DOT with `dot`,
# or see the README for an equivalent Mermaid diagram)
isabelle-blueprint graph examples/group-theory

# What can an agent work on right now?
isabelle-blueprint tasks examples/agent-workflow

# Toolchain / AFP compatibility check
isabelle-blueprint compat examples/agent-workflow
```

## What each example teaches

- **minimal** — the authoring template. Three arithmetic facts, four
  nodes, zero external dependencies. Start here to learn the `:::` node
  syntax.
- **group-theory** — a realistic Markdown blueprint with ten nodes across
  three dependency levels. Statuses span `missing`, `named`, `found`, and
  `proved`, so the graph and report show several colours and a 50% coverage
  bar.
- **latex-blueprint** — the same idea expressed in LaTeX, for projects that
  keep their blueprint alongside a paper. Shows how `\isabelleok` upgrades
  a `named` fact to `found`.
- **agent-workflow** — tuned for the `tasks` command: three formalised
  base definitions unblock exactly two actionable tasks while the rest of
  the chain stays blocked. Also demonstrates the `[isabelle] version` pin
  and `[afp]` entry used by `compat`.
- **afp-gale-stewart** — the real end-to-end integration test. Every node
  points at a fact that genuinely exists in the published AFP entry
  `GaleStewart_Games`, and `check` builds a single wrapper session spanning
  the AFP entry *and* a local corollary session — all seven facts come back
  `proved`. See its [README](afp-gale-stewart/README.md) for the captured
  run and how to adapt the paths to your own AFP checkout.
