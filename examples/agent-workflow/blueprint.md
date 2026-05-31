# Verified insertion sort

A blueprint built around an **agent workflow**: it tracks proof
obligations for a small verified-sorting development and is tuned so the
`tasks` command surfaces a clear mix of *ready*, *blocked*, and
*already-formalised* nodes.

It also shows the **compatibility configuration** — an Isabelle version
pin plus an AFP entry dependency — read by `isabelle-blueprint compat`.

## The development

We define list reversal and append, prove a couple of helper lemmas, then
specify insertion sort and its correctness theorems.

::: definition {#list-rev}
title: List reversal
isabelle: Sorting.rev_def
tags:
  - lists
status:
  blueprint: reviewed
  formal: found
:::
`rev []` is `[]` and `rev (x # xs)` is `rev xs @ [x]`.
:::

::: definition {#append}
title: List append
isabelle: Sorting.append_def
tags:
  - lists
status:
  blueprint: reviewed
  formal: found
:::
`[] @ ys` is `ys` and `(x # xs) @ ys` is `x # (xs @ ys)`.
:::

::: lemma {#rev-append}
title: Reverse of an append
isabelle: Sorting.rev_append
uses:
  - list-rev
  - append
tags:
  - lists
status:
  blueprint: written
  formal: missing
:::
`rev (xs @ ys) = rev ys @ rev xs`.

## Proof
Induction on `xs`, using associativity of append.
:::

::: lemma {#rev-rev}
title: Reverse is an involution
isabelle: Sorting.rev_rev
uses:
  - rev-append
tags:
  - lists
status:
  blueprint: written
  formal: missing
:::
`rev (rev xs) = xs`.

## Proof
Induction on `xs`, rewriting with the reverse-of-append lemma.
:::

::: definition {#sorted}
title: Sortedness
isabelle: Sorting.sorted_def
tags:
  - sorting
status:
  blueprint: reviewed
  formal: found
:::
A list is **sorted** when each element is `\<le>` the next.
:::

::: definition {#insertion-sort}
title: Insertion sort
isabelle: Sorting.isort_def
uses:
  - sorted
tags:
  - sorting
status:
  blueprint: written
  formal: missing
:::
`isort` inserts each element into its sorted position in the recursively
sorted tail.
:::

::: theorem {#isort-sorted}
title: Insertion sort produces a sorted list
isabelle: Sorting.isort_sorted
uses:
  - insertion-sort
tags:
  - sorting
  - correctness
status:
  blueprint: written
  formal: missing
:::
`sorted (isort xs)` holds for every list `xs`.

## Proof
Induction on `xs`, with a helper lemma that insertion preserves
sortedness.
:::

::: theorem {#isort-permutation}
title: Insertion sort is a permutation
isabelle: Sorting.isort_perm
uses:
  - insertion-sort
tags:
  - sorting
  - correctness
status:
  blueprint: stub
  formal: missing
:::
`mset (isort xs) = mset xs`: insertion sort returns a permutation of its
input.
:::
