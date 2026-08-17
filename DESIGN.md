---
name: IsabelleBlueprint
description: A calm, evidence-first proof cockpit for Isabelle/HOL formalizations.
colors:
  ink: "#1f2937"
  canvas: "#f8fafc"
  surface: "#ffffff"
  surface-muted: "#f1f5f9"
  muted: "#6b7280"
  accent: "#2563eb"
  success: "#16a34a"
  warning: "#f59e0b"
  danger: "#dc2626"
  ready: "#8b5cf6"
  border: "#e5e7eb"
  dark-ink: "#e5e7eb"
  dark-canvas: "#0f172a"
  dark-surface: "#111827"
  dark-surface-muted: "#1f2937"
  dark-muted: "#9ca3af"
  dark-accent: "#60a5fa"
  dark-border: "#374151"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Helvetica, Arial, sans-serif"
    fontSize: "1.8rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Helvetica, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Helvetica, Arial, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.3
  mono:
    fontFamily: "SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.9em"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  pill: "999px"
spacing:
  xs: "0.35rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.5rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "0.5rem 0.75rem"
  filter-pill:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.2rem 0.7rem"
  surface-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "1rem"
---

# Design System: IsabelleBlueprint

## 1. Overview

**Creative North Star: “The Proof Cockpit”**

The interface is a calm, evidence-first workspace for navigating formal proof
work. It combines the density of a developer tool with the legibility of a
well-kept lab notebook: neutral surfaces carry the information, one blue
accent marks action and navigation, and semantic colors explain proof state.

The system favors familiar product patterns over visual novelty. It should not
feel like a generic SaaS analytics dashboard, a noisy AI command center, or a
decorative graph demo. Progress is only meaningful when its trust status and
freshness are visible.

**Key Characteristics:**

- Evidence-first hierarchy with a clear next action.
- Restrained neutral surfaces and semantic status colors.
- Dense, scannable data with progressive disclosure for detail.
- Keyboard-friendly, responsive, and honest in degraded/offline states.

## 2. Colors

The palette is restrained: cool neutral surfaces create a quiet workspace, the
blue accent marks interaction, and green/amber/red/purple carry formalization
semantics. Status colors must always be paired with text or shape, never used
as the only signal.

### Primary

- **Blueprint blue** (#2563eb): links, focused actions, current navigation, and
  primary affordances. Use sparingly so an actionable link remains obvious.
- **Ready violet** (#8b5cf6): work that is unblocked and ready for a proof
  attempt.

### Semantic

- **Proved green** (#16a34a): trusted completed formal work.
- **Warning amber** (#f59e0b): stale or attention-needed work.
- **Problem red** (#dc2626): broken, failed, tainted, or structurally invalid
  work.

### Neutral

- **Canvas** (#f8fafc): page background.
- **Surface** (#ffffff): primary content surfaces and controls.
- **Muted surface** (#f1f5f9): filter controls, secondary panels, and code
  context.
- **Ink** (#1f2937): primary text.
- **Muted ink** (#6b7280): supporting labels and secondary explanations.
- **Border** (#e5e7eb): quiet separation, never decoration.

### Named Rules

**The Evidence Rule.** Every semantic color is accompanied by a text label,
icon, pattern, or shape. Color is a fast channel, not the source of truth.

## 3. Typography

**Display Font:** System UI sans stack

**Body Font:** System UI sans stack

**Label/Mono Font:** SFMono-Regular, Menlo, Consolas, monospace for node ids,
Isabelle facts, commands, and machine-facing values.

**Character:** Familiar, compact, and highly legible. The type scale is tighter
than a marketing site because users scan tables, dependencies, and statuses.
Prose stays within roughly 65–75 characters per line where possible.

### Hierarchy

- **Display** (700, 1.8rem, 1.2): page title and project identity.
- **Headline** (600, 1.25rem, 1.3): major page sections and dashboard groups.
- **Title** (600, 1rem, 1.4): cards, task titles, and node headings.
- **Body** (400, 1rem, 1.5): explanations, statements, and instructions.
- **Label** (600, 0.85rem, 1.3): filters, metadata, status summaries, and compact
  controls.

### Named Rules

**The One Voice Rule.** Use the system sans for interface language and the mono
stack only when the value is actually a code, fact, node id, or command.

## 4. Elevation

The system uses tonal layering first and quiet ambient shadows second. Surfaces
should feel organized, not floating. Borders establish structure; shadows are
reserved for dense cards and small elevation changes.

### Shadow Vocabulary

- **Low surface** (`0 1px 2px rgba(0, 0, 0, 0.05)`): status cards and tables.
- **Dark low surface** (`0 1px 2px rgba(0, 0, 0, 0.35)`): the dark theme
  equivalent.

### Named Rules

**The Quiet Surface Rule.** No decorative glow, glass, or heavy shadow. Depth
comes from spacing, border, and surface tone before elevation.

## 5. Components

### Buttons

- **Shape:** 6px radius; compact, tactile, and consistent.
- **Primary:** blueprint blue with white text for the main action.
- **Secondary:** neutral surface with a border for reset, copy, and supporting
  actions.
- **Hover / Focus:** darken or accent the border; always show a visible
  `:focus-visible` ring.
- **Feedback:** copy and run actions must announce success or failure and never
  silently do nothing.

### Chips

- **Style:** pill shape, muted surface at rest, semantic accent when selected.
- **State:** selected state uses `aria-pressed="true"` and visible text; counts
  remain readable in both themes.

### Cards / Containers

- **Corner Style:** 6–8px radius.
- **Background:** surface white/light or dark surface in dark mode.
- **Shadow Strategy:** low ambient shadow only where scanning benefits from a
  boundary.
- **Border:** 1px neutral border; do not use thick colored side stripes.
- **Internal Padding:** 0.75–1rem, with larger rhythm around page sections.

### Inputs / Fields

- **Style:** surface background, 1px border, 6px radius, system font.
- **Focus:** accent border plus a clear, non-color-only focus ring.
- **Error / Disabled:** explain the state inline; preserve readable contrast.

### Navigation

- **Style:** compact top navigation with a clear active state and project logo.
- **Mobile treatment:** wrap or scroll predictably, keep labels available, and
  provide a skip link to the main content.
- **Context:** breadcrumbs on node pages and a persistent current project/check
  context reduce lost context in deep links.

### Signature Component: Proof Status

Status presentation combines a semantic label, a compact color treatment, and
an optional icon or shape. The text must remain meaningful in grayscale and
screen-reader output.

## 6. Do's and Don'ts

### Do:

- **Do** foreground the next safe proof action and its blockers.
- **Do** show source, freshness, and trust evidence near progress metrics.
- **Do** use familiar product patterns and preserve keyboard access.
- **Do** make empty, offline, and degraded Isabelle states instructive.
- **Do** keep the accent rare enough that links and actions are easy to spot.

### Don't:

- **Don't** make the product feel like a generic SaaS analytics dashboard.
- **Don't** make it a noisy AI command center or decorative graph demo.
- **Don't** use gradients as decoration or status communicated by color alone.
- **Don't** hide the difference between a fact existing and a proof being
  trusted.
- **Don't** use thick colored side stripes, glassmorphism, or unexplained
  automation as a substitute for hierarchy.
