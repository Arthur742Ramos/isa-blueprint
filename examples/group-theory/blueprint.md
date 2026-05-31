# Group theory blueprint

A worked, multi-level IsabelleBlueprint example. It builds the elementary
theory of groups: from the axioms, through the cancellation and
unique-inverse lemmas, up to the "socks-and-shoes" inverse law.

It is intentionally larger than [`examples/minimal/`](../minimal) so the
dependency graph branches across several layers and mixes a range of formal
statuses (`missing` / `named` / `found` / `proved`) — useful for screenshots,
the HTML site, and agent task generation.

## The roadmap

We start from the group axioms, prove the basic cancellation and
uniqueness lemmas, and combine them into the inverse laws. Each node links
to a fact in the `Group_Demo` Isabelle session.

::: definition {#group}
title: Group
isabelle: Group_Demo.group_def
tags:
  - foundations
status:
  blueprint: reviewed
  formal: found
:::
A **group** is a set $G$ with an associative binary operation
$\cdot : G \times G \to G$, an identity element $e$ such that
$e \cdot a = a \cdot e = a$, and for every $a$ an inverse $a^{-1}$ with
$a \cdot a^{-1} = a^{-1} \cdot a = e$.
:::

::: definition {#subgroup}
title: Subgroup
isabelle: Group_Demo.subgroup_def
uses:
  - group
tags:
  - foundations
status:
  blueprint: written
  formal: named
:::
A **subgroup** of a group $G$ is a subset $H \subseteq G$ that is closed
under the operation and inverses and contains the identity $e$.
:::

::: lemma {#left-cancel}
title: Left cancellation
isabelle: Group_Demo.left_cancel
uses:
  - group
tags:
  - cancellation
status:
  blueprint: reviewed
  formal: proved
:::
If $a \cdot b = a \cdot c$ then $b = c$.

## Proof
Multiply both sides on the left by $a^{-1}$ and apply associativity and the
inverse and identity axioms.
:::

::: lemma {#right-cancel}
title: Right cancellation
isabelle: Group_Demo.right_cancel
uses:
  - group
tags:
  - cancellation
status:
  blueprint: reviewed
  formal: proved
:::
If $b \cdot a = c \cdot a$ then $b = c$.

## Proof
Symmetric to left cancellation, multiplying on the right by $a^{-1}$.
:::

::: lemma {#identity-unique}
title: The identity is unique
isabelle: Group_Demo.identity_unique
uses:
  - group
tags:
  - uniqueness
status:
  blueprint: written
  formal: found
:::
If $e'$ also satisfies $e' \cdot a = a \cdot e' = a$ for all $a$, then
$e' = e$.

## Proof
Apply both identity laws to $e \cdot e'$.
:::

::: lemma {#inverse-unique}
title: Inverses are unique
isabelle: Group_Demo.inverse_unique
uses:
  - group
  - left-cancel
tags:
  - uniqueness
status:
  blueprint: written
  formal: found
:::
For each $a$ there is exactly one $b$ with $a \cdot b = b \cdot a = e$.

## Proof
If $a \cdot b = e = a \cdot b'$ then left cancellation gives $b = b'$.
:::

::: lemma {#inverse-of-inverse}
title: Inverse of the inverse
isabelle: Group_Demo.inverse_of_inverse
uses:
  - inverse-unique
tags:
  - inverses
status:
  blueprint: written
  formal: named
:::
$(a^{-1})^{-1} = a$.

## Proof
$a$ is an inverse of $a^{-1}$; by uniqueness of inverses it is *the*
inverse.
:::

::: lemma {#socks-shoes}
title: Socks-and-shoes law
isabelle: Group_Demo.socks_shoes
uses:
  - inverse-unique
tags:
  - inverses
status:
  blueprint: written
  formal: missing
:::
$(a \cdot b)^{-1} = b^{-1} \cdot a^{-1}$.

## Proof
Check that $b^{-1} \cdot a^{-1}$ is an inverse of $a \cdot b$ and invoke
uniqueness of inverses.
:::

::: theorem {#cancellation}
title: Cancellation theorem
isabelle: Group_Demo.cancellation
uses:
  - left-cancel
  - right-cancel
tags:
  - cancellation
status:
  blueprint: written
  formal: missing
:::
In a group, both left and right cancellation hold simultaneously, so the
operation is cancellative on both sides.

## Proof
Immediate from the left and right cancellation lemmas.
:::

::: theorem {#inverse-laws}
title: Inverse laws
isabelle: Group_Demo.inverse_laws
uses:
  - inverse-of-inverse
  - socks-shoes
tags:
  - inverses
status:
  blueprint: written
  formal: missing
:::
The inverse map is an involution and reverses products:
$(a^{-1})^{-1} = a$ and $(a \cdot b)^{-1} = b^{-1} \cdot a^{-1}$.

## Proof
Combine the inverse-of-the-inverse and socks-and-shoes lemmas.
:::
