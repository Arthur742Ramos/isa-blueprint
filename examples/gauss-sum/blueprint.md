# Gauss's summation formula

A three-node, fully-proved blueprint: the closed form for the sum of the first
`n` natural numbers, `1 + 2 + ... + n = n * (n + 1) / 2`. Every node carries a
checked Isabelle fact, so the dependency graph is **all green** and coverage is
**100%** — this is what a finished formalization looks like in IsabelleBlueprint.

Run it from the project root:

```
isabelle-blueprint report examples/gauss-sum
isabelle-blueprint graph  examples/gauss-sum
isabelle-blueprint web    examples/gauss-sum
```

::: definition {#triangular}
title: The triangular-number function
isabelle: Gauss_Demo.triangular_def
tags: [arithmetic, definition]
status:
  blueprint: reviewed
  formal: proved

We write `T n` for the `n`-th triangular number, defined by the recursion
`T 0 = 0` and `T (Suc n) = T n + Suc n`. Informally `T n = 1 + 2 + ... + n`.
:::

::: lemma {#triangular-step}
title: Doubling identity for the recursion
isabelle: Gauss_Demo.triangular_step
uses:
  - triangular
status:
  blueprint: reviewed
  formal: proved

For every natural number `n`, `2 * T (Suc n) = 2 * T n + 2 * Suc n`.

## Proof

Unfold the recursive equation `T (Suc n) = T n + Suc n` from the definition and
multiply through by two. Pure rewriting; no induction required.
:::

::: theorem {#gauss-formula}
title: Closed form for the triangular numbers
isabelle: Gauss_Demo.gauss_formula
uses:
  - triangular
  - triangular-step
status:
  blueprint: reviewed
  formal: proved

For every natural number `n`, `2 * T n = n * (n + 1)`, equivalently
`T n = n * (n + 1) / 2`.

## Proof

By induction on `n`. The base case `2 * T 0 = 0` holds by definition. For the
step, apply the doubling identity `triangular-step` and the inductive
hypothesis, then close the goal by linear arithmetic.
:::
