# Minimal IsabelleBlueprint demo

This example exercises every IsabelleBlueprint subcommand without depending on a
real `isabelle` binary. It contains three little arithmetic facts about
`Nat.add` and zero.

Run it from the project root:

```
isabelle-blueprint check examples/minimal
isabelle-blueprint graph examples/minimal
isabelle-blueprint web   examples/minimal
isabelle-blueprint tasks examples/minimal
isabelle-blueprint report examples/minimal
```

If Isabelle is not on `PATH`, the checker degrades gracefully and every node is
shown with the *named* formal status (we know the name, we have not confirmed
the fact exists in any session).

## The roadmap

::: definition {#nat-add}
title: Natural-number addition
isabelle: Arith_Demo.add_def
status:
  blueprint: written
  formal: missing
tags: [nat, addition]
:::

We treat addition on `nat` as the standard recursive definition. The lemmas
below pin down two of its identity laws and then combine them.
:::

::: lemma {#add-zero-right}
title: Right identity for addition
isabelle: Arith_Demo.add_zero_right
uses:
  - nat-add
status:
  blueprint: written
  formal: missing
tags: [nat, identity]
:::

For every natural number $n$, $n + 0 = n$.

## Proof

By induction on $n$. The base case is the definition; the step case unfolds
addition and applies the inductive hypothesis.
:::

::: lemma {#add-zero-left}
title: Left identity for addition
isabelle: Arith_Demo.add_zero_left
uses:
  - nat-add
status:
  blueprint: written
  formal: missing
tags: [nat, identity]
:::

For every natural number $n$, $0 + n = n$.

## Proof

Direct from the recursive definition of addition.
:::

::: theorem {#add-zero-both}
title: Zero is a two-sided identity for addition
isabelle: Arith_Demo.add_zero_both
uses:
  - add-zero-right
  - add-zero-left
status:
  blueprint: written
  formal: missing
tags: [nat, identity, headline]
:::

Combining the two identity lemmas, $0$ is both a left and a right identity for
addition on the naturals.

## Proof

Apply `add-zero-left` and `add-zero-right` to the two halves of the
conjunction.
:::
