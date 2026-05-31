# Irrationality of the square root of two

The classic *reductio ad absurdum*: if `sqrt 2 = p / q` in lowest terms then both
`p` and `q` must be even, contradicting coprimality. This blueprint is
deliberately **work-in-progress**: it mixes formal statuses
(`proved` / `found` / `named` / `missing`) so the graph and the generated site
show off the **status colours** and the agent task list.

```
isabelle-blueprint report examples/sqrt2-irrational
isabelle-blueprint graph  examples/sqrt2-irrational
isabelle-blueprint tasks  examples/sqrt2-irrational
```

::: lemma {#even-square}
title: A number whose square is even is itself even
isabelle: Sqrt2_Demo.even_square
tags: [parity]
status:
  blueprint: reviewed
  formal: proved

If `n\<^sup>2` is even then `n` is even.

## Proof

Contrapositive: an odd `n = 2k + 1` has `n\<^sup>2 = 4k\<^sup>2 + 4k + 1`, which is odd.
:::

::: lemma {#lowest-terms}
title: Every rational has a coprime representation
isabelle: Sqrt2_Demo.lowest_terms
tags: [rational]
status:
  blueprint: reviewed
  formal: found

Any rational number can be written as `p / q` with `q \<noteq> 0` and
`gcd p q = 1`.

## Proof

Divide numerator and denominator by their greatest common divisor; this is
`Rat.quotient_of` in the Isabelle library.
:::

::: lemma {#even-numerator}
title: The numerator is even
isabelle: Sqrt2_Demo.even_numerator
uses:
  - even-square
  - lowest-terms
tags: [parity, rational]
status:
  blueprint: reviewed
  formal: proved

Suppose `(p / q)\<^sup>2 = 2` with `gcd p q = 1`. Then `p` is even.

## Proof

From `p\<^sup>2 = 2 * q\<^sup>2` the numerator square is even, so by
`even-square` the numerator `p` is even.
:::

::: lemma {#even-denominator}
title: The denominator is even too
isabelle: Sqrt2_Demo.even_denominator
uses:
  - even-numerator
  - even-square
tags: [parity, rational]
status:
  blueprint: written
  formal: named

Under the same hypotheses, `q` is also even — contradicting `gcd p q = 1`.

## Proof

Write `p = 2k`. Substituting into `p\<^sup>2 = 2 * q\<^sup>2` gives
`q\<^sup>2 = 2 * k\<^sup>2`, so `q\<^sup>2` is even and `even-square` makes `q`
even. *(Isabelle proof drafted but not yet machine-checked.)*
:::

::: theorem {#sqrt2-irrational}
title: The square root of two is irrational
isabelle: Sqrt2_Demo.sqrt2_irrational
uses:
  - even-denominator
  - lowest-terms
tags: [irrationality]
status:
  blueprint: written
  formal: missing

There is no rational number `r` with `r\<^sup>2 = 2`; equivalently `sqrt 2` is
irrational.

## Proof

If such an `r` existed, take its coprime representation `p / q`
(`lowest-terms`). Then `even-numerator` and `even-denominator` make both `p` and
`q` even, contradicting `gcd p q = 1`. *(Not yet formalised — this is the open
obligation.)*
:::
