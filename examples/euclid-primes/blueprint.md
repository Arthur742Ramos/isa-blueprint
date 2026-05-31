# Infinitude of the primes

Euclid's theorem: there is no largest prime. Given any finite list of primes,
the number `N = n! + 1` has a prime divisor larger than `n`, so the primes never
run out. A six-node blueprint with a small fan-in DAG and a couple of open
obligations near the top.

```
isabelle-blueprint report examples/euclid-primes
isabelle-blueprint graph  examples/euclid-primes
isabelle-blueprint tasks  examples/euclid-primes
```

::: definition {#prime-pred}
title: Primality
isabelle: Euclid_Demo.prime
tags: [prime]
status:
  blueprint: reviewed
  formal: found

`p` is prime when `p > 1` and its only divisors are `1` and `p`. This is the
library predicate `prime`.
:::

::: lemma {#dvd-factorial}
title: Small numbers divide the factorial
isabelle: Euclid_Demo.dvd_factorial
tags: [factorial]
status:
  blueprint: reviewed
  formal: proved

If `0 < k` and `k \<le> n` then `k dvd fact n`.

## Proof

`fact n` is the product `1 * 2 * ... * n`, and `k` appears as one of the
factors whenever `1 \<le> k \<le> n`.
:::

::: lemma {#prime-divisor}
title: Every number above one has a prime divisor
isabelle: Euclid_Demo.prime_divisor
uses:
  - prime-pred
tags: [prime]
status:
  blueprint: reviewed
  formal: proved

If `1 < m` then there is a prime `p` with `p dvd m`.

## Proof

Strong induction on `m`: either `m` is itself prime, or it has a proper divisor
`d` with `1 < d < m`, whose prime divisor (by induction) also divides `m`.
:::

::: definition {#euclid-number}
title: Euclid number
isabelle: Euclid_Demo.euclid_number
tags: [factorial]
status:
  blueprint: reviewed
  formal: found

For a bound `n`, the Euclid number is `N n = fact n + 1`.
:::

::: lemma {#prime-gt-bound}
title: A prime divisor beyond the bound
isabelle: Euclid_Demo.prime_gt_bound
uses:
  - dvd-factorial
  - prime-divisor
  - euclid-number
tags: [prime, factorial]
status:
  blueprint: written
  formal: named

Every prime divisor `p` of `N n = fact n + 1` satisfies `p > n`.

## Proof

`N n > 1`, so `prime-divisor` gives a prime `p dvd N n`. If `p \<le> n` then
`p dvd fact n` by `dvd-factorial`, hence `p dvd (N n - fact n) = 1`, which is
impossible for a prime. *(Isabelle proof drafted, not yet checked.)*
:::

::: theorem {#infinitude-primes}
title: There are infinitely many primes
isabelle: Euclid_Demo.infinitude_primes
uses:
  - prime-gt-bound
  - prime-pred
tags: [prime]
status:
  blueprint: written
  formal: missing

For every `n` there is a prime `p > n`; the set of primes is infinite.

## Proof

Apply `prime-gt-bound` to the Euclid number `N n`: its prime divisor is a prime
exceeding `n`. Since `n` was arbitrary, no finite bound contains all primes.
*(The open top-level obligation.)*
:::
