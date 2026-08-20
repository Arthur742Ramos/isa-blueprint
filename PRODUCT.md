# Product

## Register

product

## Users

Isabelle/HOL formalization authors, research collaborators, maintainers of AFP
entries, and Isabelle-aware coding agents use IsabelleBlueprint while planning,
checking, reviewing, and handing off proof work. They work across a terminal, a
static progress site, CI, MCP clients, and VS Code; the interface must remain
useful when Isabelle is unavailable and become more authoritative when a real
session check is available.

## Product Purpose

IsabelleBlueprint turns an informal Markdown or LaTeX formalization plan into a
dependency-aware proof cockpit. It answers four questions quickly: what is
planned, what is actually connected to Isabelle, what is trusted, and what can
be attempted next. Success means a collaborator can understand project health
in seconds, an agent can receive a safe bounded task, and every status claim is
traceable to source, dependency, and check evidence.

## Brand Personality

Rigorous, calm, collaborative. The product should feel like a well-kept lab
notebook with the navigational confidence of a professional developer tool:
quietly precise, transparent about uncertainty, and generous with the next
useful action.

## Anti-references

Do not make the product feel like a generic SaaS analytics dashboard, a noisy
AI command center, or a decorative graph demo. Avoid metric theater, gradients
used as decoration, status communicated by color alone, unexplained automation,
and interfaces that hide the difference between a fact existing and a proof
being trusted.

## Design Principles

- **Evidence before celebration.** Every progress signal should expose its
  source, freshness, and trust meaning.
- **One proof cockpit, many surfaces.** CLI, static site, VS Code, MCP, and CI
  should share vocabulary, ordering, and next-action logic.
- **Make the next safe move obvious.** Ready work, blockers, dependencies, and
  copyable handoffs deserve priority over exhaustive secondary detail.
- **Dense when useful, humane when complex.** Formalization data can be dense,
  but hierarchy, progressive disclosure, and good empty states should prevent
  cognitive overload.
- **Graceful degradation is a feature.** Offline rendering, missing Isabelle,
  partial history, and failed checks must produce honest, actionable states.

## Accessibility & Inclusion

Target WCAG 2.2 AA for the generated site and VS Code surfaces. Never rely on
color alone for formal, blueprint, or agent status. Preserve keyboard access to
navigation, filtering, graph actions, and copy controls; provide visible focus,
screen-reader labels, useful empty/error states, reduced-motion behavior, and
responsive layouts for narrow screens. Respect system light/dark preferences
and keep the evidence readable at increased text size.
