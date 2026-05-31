# Gale–Stewart determinacy

A **real-world, AFP-backed** blueprint. Every node below points at a fact
that genuinely exists in the Archive of Formal Proofs entry
[`GaleStewart_Games`](https://www.isa-afp.org/entries/GaleStewart_Games.html),
which formalises the **Gale–Stewart theorem**: every *closed* infinite game
of perfect information is determined — one of the two players always has a
winning strategy.

This blueprint exercises the full toolchain end to end:

- `compat` reads the Isabelle version pin **and** the `[afp]` dependency.
- `check` generates an Isabelle theory that imports the real AFP session,
  references each fact with `@{thm …}`, asks Isabelle to confirm it exists,
  and records whether it is `proved` (no skipped proofs, no oracles) in
  `build/Blueprint_Proof_Status.tsv`.
- The final node, [`closed-determinacy`](#closed-determinacy), references a
  **local** corollary (`Gale_Stewart_Blueprint.thy`) that is itself layered
  on top of the AFP entry — so the check resolves facts from two sessions at
  once.

## The development

Gale–Stewart games are played on sequences of moves. A *strategy* tells a
player how to move from any position; a *play* is the infinite sequence the
two strategies jointly produce. The theorem says that for closed payoff sets
the game is determined.

::: definition {#play}
title: Plays of a game
isabelle:
  fact: GSgame.play_def
  theory: GaleStewartGames
  session: GaleStewart_Games
tags:
  - games
status:
  blueprint: reviewed
  formal: found
:::
A **play** is an infinite sequence of moves that both players contribute to
as the game unfolds.
:::

::: definition {#induced-play}
title: Play induced by a strategy
isabelle:
  fact: GSgame.induced_play_def
  theory: GaleStewartGames
  session: GaleStewart_Games
uses:
  - play
tags:
  - games
status:
  blueprint: reviewed
  formal: found
:::
Fixing a strategy and an initial position **induces** a unique play: the
sequence of moves obtained by following the strategy forever.
:::

::: definition {#winning-strategy}
title: Winning strategy for Even
isabelle:
  fact: GSgame.strategy_winning_by_Even_def
  theory: GaleStewartGames
  session: GaleStewart_Games
uses:
  - induced-play
tags:
  - games
  - strategies
status:
  blueprint: reviewed
  formal: found
:::
A strategy is **winning for Even** when every play it induces from the start
lands in Even's payoff set.
:::

::: lemma {#at-most-one-winner}
title: At most one player wins
isabelle:
  fact: GSgame.at_most_one_player_winning
  theory: GaleStewartGames
  session: GaleStewart_Games
uses:
  - winning-strategy
tags:
  - games
status:
  blueprint: reviewed
  formal: found
:::
The two players cannot **both** have a winning strategy: at most one of them
wins the game.

## Proof
Two winning strategies would induce a single play that lies in both payoff
sets, which are disjoint.
:::

::: lemma {#position-determined}
title: Every position is determined
isabelle:
  fact: closed_GSgame.every_position_is_determined
  theory: GaleStewartDeterminedGames
  session: GaleStewart_Games
uses:
  - winning-strategy
tags:
  - games
  - determinacy
status:
  blueprint: reviewed
  formal: found
:::
For a **closed** game, from any reachable position one of the two players
has a winning strategy.

## Proof
The Gale–Stewart argument: if Even has no winning strategy then Odd can
maintain "non-loss" forever, and closedness turns that into an actual win.
:::

::: theorem {#game-determined}
title: Closed games are determined
isabelle:
  fact: closed_GSgame.every_game_is_determined
  theory: GaleStewartDeterminedGames
  session: GaleStewart_Games
uses:
  - position-determined
  - at-most-one-winner
tags:
  - games
  - determinacy
  - headline
status:
  blueprint: reviewed
  formal: found
:::
**Gale–Stewart.** Every closed game is determined from the empty position —
`winning_position_Even [] \<or> winning_position_Odd []`.

## Proof
Specialise [`position-determined`](#position-determined) to the empty
position, which is a valid starting position.
:::

::: corollary {#closed-determinacy}
title: Determinacy corollary (local)
isabelle:
  fact: closed_GSgame.closed_game_determinacy
  theory: Gale_Stewart_Blueprint
  session: Gale_Stewart_Blueprint
uses:
  - game-determined
tags:
  - games
  - determinacy
status:
  blueprint: written
  formal: found
:::
A **local** restatement, proved in `Gale_Stewart_Blueprint.thy` directly
from the AFP theorem. Referencing it forces `check` to resolve facts from
both the AFP session and this example's own session in a single build.
:::
