# Fundamental theorem of arithmetic

Every integer greater than one factors into primes, and that factorization is
**unique** up to ordering. This is the most advanced example in the gallery: a
ten-node, multi-level DAG that mixes proved lemmas, a named obligation, and
several open theorems — including two the `tasks` command flags as **ready** for
an agent to pick up.

```
isabelle-blueprint report examples/fundamental-arithmetic
isabelle-blueprint graph  examples/fundamental-arithmetic
isabelle-blueprint tasks  examples/fundamental-arithmetic
```

::: definition {#prime-pred}
title: Primality
isabelle: FTA_Demo.prime
tags: [prime]
status:
  blueprint: reviewed
  formal: found

`p` is prime when `p > 1` and its only divisors are `1` and `p` (the library
predicate `prime`).
:::

::: definition {#mset-prod}
title: Product over a multiset
isabelle: FTA_Demo.prod_mset
tags: [multiset]
status:
  blueprint: reviewed
  formal: found

`prod_mset M` multiplies together all elements of the multiset `M`, with the
empty multiset giving `1`.
:::

::: definition {#factor-list}
title: Prime factorization
isabelle: FTA_Demo.prime_factorization
uses:
  - prime-pred
  - mset-prod
tags: [prime, multiset]
status:
  blueprint: reviewed
  formal: found

A prime factorization of `n` is a multiset `M` of primes with
`prod_mset M = n`.
:::

::: lemma {#dvd-prime}
title: Euclid's lemma
isabelle: FTA_Demo.dvd_prime
uses:
  - prime-pred
tags: [prime]
status:
  blueprint: reviewed
  formal: proved

If `p` is prime and `p dvd a * b` then `p dvd a` or `p dvd b`.

## Proof

A standard consequence of `prime` in `HOL-Computational_Algebra`; the prime
divides one factor whenever it divides the product.
:::

::: lemma {#prime-divisor}
title: Every number above one has a prime divisor
isabelle: FTA_Demo.prime_divisor
uses:
  - prime-pred
tags: [prime]
status:
  blueprint: reviewed
  formal: proved

If `1 < m` then there is a prime `p` with `p dvd m`.

## Proof

Strong induction on `m`: either `m` is prime, or it splits into a proper
divisor whose prime factor (by induction) also divides `m`.
:::

::: lemma {#prime-dvd-prod}
title: A prime dividing a product of primes
isabelle: FTA_Demo.prime_dvd_prod_mset
uses:
  - dvd-prime
  - mset-prod
tags: [prime, multiset]
status:
  blueprint: written
  formal: missing
  agent: ready

If `p` is prime and `p dvd prod_mset M`, then `p` equals one of the primes in
`M`.

## Proof

Induction on the multiset `M`, applying `dvd-prime` at each step. *(Ready for an
agent: every dependency is already formalised.)*
:::

::: theorem {#existence}
title: Existence of a prime factorization
isabelle: FTA_Demo.factorization_exists
uses:
  - prime-divisor
  - factor-list
tags: [prime, existence]
status:
  blueprint: written
  formal: named

Every `n > 1` has at least one prime factorization.

## Proof

Strong induction on `n`: peel off a prime divisor from `prime-divisor` and
factor the quotient. *(Stated in the theory, proof not yet checked.)*
:::

::: theorem {#uniqueness}
title: Uniqueness of the prime factorization
isabelle: FTA_Demo.factorization_unique
uses:
  - prime-dvd-prod
  - factor-list
  - existence
tags: [prime, uniqueness]
status:
  blueprint: written
  formal: missing
  agent: ready

Any two prime factorizations of the same `n` are equal as multisets.

## Proof

If `M` and `N` both multiply to `n`, pick a prime `p` in `M`; by
`prime-dvd-prod` it also lies in `N`. Cancel `p` and recurse. *(Becomes ready
once `prime-dvd-prod` is formalised.)*
:::

::: theorem {#fta}
title: Fundamental theorem of arithmetic
isabelle: FTA_Demo.fundamental_theorem_arithmetic
uses:
  - existence
  - uniqueness
tags: [prime]
status:
  blueprint: written
  formal: missing

Every `n > 1` has a prime factorization that is unique up to ordering.

## Proof

Combine `existence` and `uniqueness`. *(The capstone obligation.)*
:::

::: remark {#canonical-form}
title: Canonical exponent form
isabelle: FTA_Demo.canonical_form
uses:
  - fta
tags: [prime]
status:
  blueprint: stub
  formal: missing

Grouping equal primes rewrites the factorization as a product of prime powers
`p\<^sub>1\<^bsup>e\<^sub>1\<^esup> \<dots> p\<^sub>k\<^bsup>e\<^sub>k\<^esup>` with distinct primes — the everyday "canonical" form.
:::
