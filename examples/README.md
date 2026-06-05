# Examples

A gallery of runnable IsabelleBlueprint projects. Each directory is a
self-contained blueprint with its own `isabelle-blueprint.toml`, a `ROOT`,
a skeleton theory, and a `README.md` explaining what it demonstrates.

All but the last don't require a working Isabelle install to explore —
`report`, `graph`, and `tasks` run purely from the blueprint sources. (`check`
is the only command that talks to a real `isabelle` binary.) The last one,
[`afp-gale-stewart/`](afp-gale-stewart/), is the real integration example: its
`check` builds an actual [Archive of Formal Proofs](https://www.isa-afp.org)
entry, though its `report`/`graph`/`tasks` still work without Isabelle.

| Example | Format | Nodes | Coverage | Highlights |
| --- | --- | ---: | ---: | --- |
| [`gauss-sum/`](gauss-sum/) | Markdown (`:::` grammar) | 3 | 100% | **Trivial / all-green.** Gauss's `1+…+n = n(n+1)/2` by induction — every node `proved`. |
| [`sqrt2-irrational/`](sqrt2-irrational/) | Markdown | 5 | 50% | **Intermediate.** Reductio that `√2` is irrational; parity + coprimality lemmas → mixed-colour graph, one ready task. |
| [`euclid-primes/`](euclid-primes/) | Markdown | 6 | 40% | **Intermediate.** Euclid's infinitude of primes; partially-formalised DAG, one ready task. |
| [`fundamental-arithmetic/`](fundamental-arithmetic/) | Markdown | 10 | 33% | **Advanced.** Existence + uniqueness of prime factorisation; 10-node DAG, two agent-ready tasks. |
| [`minimal/`](minimal/) | Markdown | 4 | 0% | Smallest possible blueprint; every subcommand, no Isabelle needed. |
| [`group-theory/`](group-theory/) | Markdown | 10 | 28% | Multi-level dependency DAG mixing `missing` / `named` / `found` / `proved` — the colourful graph demo. |
| [`latex-blueprint/`](latex-blueprint/) | LaTeX | 8 | 0% | `.tex` ingestion with `\isabelle` / `\uses` / `\isabelleok`. |
| [`agent-workflow/`](agent-workflow/) | Markdown | 8 | 0% | Task orchestration (ready vs blocked) plus `compat` version/AFP pinning. |
| [`afp-gale-stewart/`](afp-gale-stewart/) | Markdown | 7 | 0% | **Real AFP entry**: cross-session `check` of Gale–Stewart determinacy; all 7 facts `found` (coverage counts only `proved`). |

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

- **gauss-sum** — the smallest *finished* blueprint, written in the lighter
  `::: kind {#id}` grammar. Three nodes, all `proved`, so the graph is entirely
  green and coverage reads 100%. Start here to see what "done" looks like.
- **sqrt2-irrational** — an intermediate, deliberately in-progress proof that
  `√2` is irrational. Five nodes span `proved` / `found` / `named` / `missing`,
  making it the best reference for the status colours and a single agent-ready
  task surfaced by `tasks`.
- **euclid-primes** — Euclid's infinitude of the primes across six nodes with
  two open obligations near the top. A clean mid-size DAG for `report`, the
  partially-green `graph`, and the `tasks` list (one ready item).
- **fundamental-arithmetic** — the advanced showcase: existence *and*
  uniqueness of prime factorisation over a ten-node, multi-level DAG. Mixed
  statuses leave two actionable agent tasks ready while deeper theorems stay
  blocked.
- **minimal** — the authoring template. Three arithmetic facts, four
  nodes, zero external dependencies. Start here to learn the `:::` node
  syntax.
- **group-theory** — a realistic Markdown blueprint with ten nodes across
  three dependency levels. Statuses span `missing`, `named`, `found`, and
  `proved`, so the graph and report show several colours and a partially
  filled coverage bar.
- **latex-blueprint** — the same idea expressed in LaTeX, for projects that
  keep their blueprint alongside a paper. Shows how `\isabelleok` upgrades
  a `named` fact to `found`.
- **agent-workflow** — tuned for the `tasks` command: three formalised
  base definitions unblock exactly two actionable tasks while the rest of
  the chain stays blocked. Also demonstrates the `[isabelle] version` pin
  and `[afp]` entry used by `compat`.
- **afp-gale-stewart** — the real end-to-end integration test. Every node
  points at a fact that genuinely exists in the published AFP entry
  `GaleStewart_Games`. The checked-in blueprint stores all seven facts as
  `found` (so `report` shows 0% *proved* coverage until you run a check), and
  `check` builds a single wrapper session spanning the AFP entry *and* a local
  corollary session — upgrading all seven facts to `proved`. See its
  [README](afp-gale-stewart/README.md) for the captured run and how to adapt
  the paths to your own AFP checkout.
