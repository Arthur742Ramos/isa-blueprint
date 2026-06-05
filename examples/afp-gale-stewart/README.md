# `afp-gale-stewart` — a real Archive of Formal Proofs blueprint

This is the project's **end-to-end integration example**. Unlike the other
examples (which are illustrative blueprints you can explore without Isabelle),
every node here points at a fact that **genuinely exists** in a published
[Archive of Formal Proofs](https://www.isa-afp.org) entry, and the numbers
quoted below come from a **real `isabelle build`** run against that entry.

It proves out the whole pipeline:

- `[afp]` dependency declaration + `compat` version/AFP pinning,
- cross-session fact resolution (`check` builds **one** wrapper session that
  spans the AFP entry **and** a local session at the same time),
- `proved`-vs-`tainted` status derived from Isabelle's own oracle inspection.

## The mathematics

The blueprint formalises the **Gale–Stewart theorem** via the AFP entry
[`GaleStewart_Games`](https://www.isa-afp.org/entries/GaleStewart_Games.html):
every *closed* infinite game of perfect information is *determined* — one of
the two players always has a winning strategy.

Seven nodes map onto the AFP development:

| Node | Kind | Isabelle fact | Source |
| --- | --- | --- | --- |
| `play` | definition | `GSgame.play_def` | AFP `GaleStewartGames` |
| `induced-play` | definition | `GSgame.induced_play_def` | AFP `GaleStewartGames` |
| `winning-strategy` | definition | `GSgame.strategy_winning_by_Even_def` | AFP `GaleStewartGames` |
| `at-most-one-winner` | lemma | `GSgame.at_most_one_player_winning` | AFP `GaleStewartGames` |
| `position-determined` | lemma | `closed_GSgame.every_position_is_determined` | AFP `GaleStewartDeterminedGames` |
| `game-determined` | theorem | `closed_GSgame.every_game_is_determined` | AFP `GaleStewartDeterminedGames` |
| `closed-determinacy` | corollary | `closed_GSgame.closed_game_determinacy` | **local** (`Gale_Stewart_Blueprint.thy`) |

`GSgame` and `closed_GSgame` are **locales**, so each `isabelle:` reference in
[`blueprint.md`](blueprint.md) uses the mapping form with an explicit `theory`
and `session` — the checker resolves locale-qualified facts against the right
theory rather than guessing.

The final node is special: `Gale_Stewart_Blueprint.thy` defines a thin local
corollary *on top of* the AFP entry, so the single `check` run has to resolve
facts from **two** sessions — the AFP `GaleStewart_Games` and the local
`Gale_Stewart_Blueprint`.

## Files

| File | Purpose |
| --- | --- |
| [`blueprint.md`](blueprint.md) | The 7-node blueprint; each node maps to a real fact. |
| [`Gale_Stewart_Blueprint.thy`](Gale_Stewart_Blueprint.thy) | Local corollary layered on the AFP entry. |
| [`ROOT`](ROOT) | Local session with the AFP `GaleStewart_Games` entry as its parent. |
| [`isabelle-blueprint.toml`](isabelle-blueprint.toml) | Version pin, local session, AFP `thys` on the build path, `[afp]` dependency. |

## What a real run produces

The output below is captured verbatim from this machine (Isabelle2025-2 with a
full AFP checkout in which `GaleStewart_Games` is already built).

### 1. Compatibility (`compat`)

```bash
isabelle-blueprint compat
```

`build/compat_report.json` reports a clean bill of health — the pinned version
matches the installed one and the declared AFP entry is visible:

```json
{
  "ok": true,
  "issues": [],
  "expected_isabelle_version": "Isabelle2025-2",
  "actual_isabelle_version": "Isabelle2025-2",
  "configured_session": "Gale_Stewart_Blueprint",
  "afp_entry": "GaleStewart_Games",
  "isabelle_available": true
}
```

### 2. Proof check (`check`)

```bash
isabelle-blueprint check
```

`check` generates `build/Blueprint_Check_Wrapper.thy`, then invokes a single
build that puts the local project, the local session, and the AFP `thys`
directory on the path:

```text
isabelle build -d build -d . -d <afp>/thys Blueprint_Check_Wrapper
```

On this machine the build returns **0** in **~238 s** and every fact resolves:

```json
{
  "ran": true,
  "isabelle_available": true,
  "return_code": 0,
  "proof_checked": true,
  "duration_seconds": 237.8
}
```

`build/Blueprint_Proof_Status.tsv` stamps all seven facts `proved` with an
empty oracle column (`-`) — i.e. they exist **and** carry no `sorry`, skipped
proof, or oracle dependency:

```text
game-determined       closed_GSgame.every_game_is_determined        proved  -
position-determined   closed_GSgame.every_position_is_determined    proved  -
at-most-one-winner    GSgame.at_most_one_player_winning             proved  -
induced-play          GSgame.induced_play_def                       proved  -
play                  GSgame.play_def                               proved  -
winning-strategy      GSgame.strategy_winning_by_Even_def           proved  -
closed-determinacy    closed_GSgame.closed_game_determinacy         proved  -
```

> Plain `check` already records proof status — there is no separate `--prove`
> flag. A node is `proved` only when Isabelle finds no oracle/skip dependency;
> otherwise it is `tainted`.

### 3. Status report (`report`)

```bash
isabelle-blueprint report
```

`build/report.md` folds the formal status back over the blueprint. The
headline metric is now **coverage = proved / formal targets**; in the
checked-in blueprint all seven facts are stored as `found`, so coverage reads
**0%** until a real `check` against the AFP upgrades them to `proved`:

```text
# Gale-Stewart determinacy (AFP) - blueprint status

- Nodes: **7**
- Formal targets (with Isabelle ref): **7**
- Proved: **0**
- Found (exists, not yet trusted): **7**
- Problems (broken/not_found/tainted/failed_check): **0**
- Coverage (proved / formal targets): **0%** (0/7)

| Formal status | Count |
| --- | ---: |
| `found` | 7 |
```

`graph` and `tasks` work too; `graph` emits `build/graph.dot` and
`build/graph.json` (install Graphviz `dot` if you also want `graph.svg`).

## Adapting this example to your machine

The committed `isabelle-blueprint.toml` and `ROOT` reference **absolute paths
specific to the machine this example was built on**, and the AFP dependency is
marked `required = true`. To run `check` yourself, edit three things:

1. **AFP `thys` path** — in `isabelle-blueprint.toml`, point `[isabelle].dirs`
   at *your* AFP checkout's `thys` directory (this is what `isabelle build`
   uses via `-d`).
2. **AFP root** — set `[afp].root` to the top of your AFP checkout (used by
   `compat`).
3. **Version pin** — set `[isabelle].version` to your installed Isabelle (e.g.
   `Isabelle2025-2`), or comment it out to skip the version check.

You also need the AFP `GaleStewart_Games` entry available to `isabelle build`
(building it on first run can take a while, since it pulls in `Parity_Game`).

Everything except `check` (`report`, `graph`, `tasks`, and the structural part
of `compat`) runs without Isabelle, so you can explore the blueprint structure
on any machine.
