# JSON contract

This document is the **frozen public surface** of the JSON files
`isabelle-blueprint` writes under `build/` as of v1.0.0. Keys, value types,
and value semantics listed here will not change without a major version bump.
New keys may be added in minor releases; consumers should ignore unknown
keys.

All four files are written by `isabelle-blueprint report`. They are always
UTF-8, indent-2 pretty-printed JSON.

---

## `build/project.json`

The full node graph in machine-readable form.

```json
{
  "name": "Group theory demo",
  "source_files": ["blueprint.md"],
  "nodes": [
    {
      "id": "group",
      "kind": "definition",
      "title": "Group",
      "statement": "A set with an associative binary operation, identity, and inverses.",
      "informal_proof": "",
      "uses": [],
      "isabelle": {
        "fact": "Group.group_def",
        "theory": "Group",
        "session": "HOL-Algebra"
      },
      "status": {
        "blueprint": "drafted",
        "formal": "found",
        "agent": "idle",
        "last_checked": "2026-05-31T12:00:00Z",
        "check_error": null
      }
    }
  ]
}
```

Top-level keys:

| Key | Type | Notes |
| --- | --- | --- |
| `name` | string | Project name from `[project].name`. |
| `source_files` | array of strings | Blueprint files this project was loaded from, in declaration order. Always at least one entry. Added in v0.7. |
| `nodes` | array of node objects | Order follows declaration order across the listed source files. |

Each node object:

| Key | Type | Notes |
| --- | --- | --- |
| `id` | string | Unique within the project. |
| `kind` | string | `definition`, `lemma`, `theorem`, `proposition`, `corollary`, `axiom`, `notation`, or `note`. |
| `title` | string | Human-friendly title. |
| `statement` | string | Body of the blueprint block. May be empty. |
| `informal_proof` | string | Optional `## Proof` section. May be empty. |
| `uses` | array of strings | Node ids this one depends on. |
| `isabelle` | object | `{ "fact": string\|null, "theory": string\|null, "session": string\|null }`. |
| `status` | object | See below. |

The `status` object:

| Key | Type | Notes |
| --- | --- | --- |
| `blueprint` | string | One of `stub`, `drafted`, `complete`. |
| `formal` | string | One of `missing`, `named`, `found`, `proved`, `tainted`, `failed_check`, `broken`, `not_found`. |
| `agent` | string | One of `idle`, `claimed`, `working`, `done`. |
| `last_checked` | string or null | ISO-8601 UTC timestamp of the most recent `check` / `dump`. |
| `check_error` | string or null | Human-readable diagnostic when the most recent check failed. |

---

## `build/summary.json`

A compact aggregation of the project, used by the badge endpoint and by
external dashboards.

```json
{
  "name": "Group theory demo",
  "node_count": 10,
  "formal_status_counts": {
    "missing": 3,
    "named": 2,
    "found": 3,
    "proved": 2
  }
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `name` | string | Project name. |
| `node_count` | integer | Total number of nodes. |
| `formal_status_counts` | object | Map from formal-status value (see above) to count. Only statuses that occur at least once are listed. |

---

## `build/badge.json`

A [shields.io endpoint](https://shields.io/endpoint) payload you can point a
shields URL at.

```json
{
  "schemaVersion": 1,
  "label": "blueprint",
  "message": "50% formal (2/4 proved)",
  "color": "yellow"
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `schemaVersion` | integer | Always `1`. |
| `label` | string | Always `"blueprint"`. |
| `message` | string | Coverage summary or `"no formal targets"`. Format may evolve within the v1 line; the field is always present and always a non-empty string. |
| `color` | string | One of `lightgrey`, `red`, `orange`, `yellow`, `green`, `brightgreen`. Forced to `red` if any node has a `not_found`, `broken`, `failed_check`, or `tainted` formal status. |

---

## `build/trends.json`

Bounded coverage / problem-count history. Added in v0.8. Newest entry first.

```json
[
  {
    "timestamp": "2026-05-31T12:00:00Z",
    "commit_sha": "abc12345...",
    "branch": "main",
    "coverage_percent": 50.0,
    "node_count": 10,
    "formal_target_count": 4,
    "proved_count": 2,
    "found_count": 2,
    "problem_count": 0,
    "stale_count": 0,
    "has_cycles": false
  }
]
```

Per-entry keys:

| Key | Type | Notes |
| --- | --- | --- |
| `timestamp` | string | ISO-8601 UTC. |
| `commit_sha` | string or null | Auto-detected from `$GITHUB_SHA`; null for local runs. |
| `branch` | string or null | Auto-detected from `$GITHUB_REF_NAME`; null for local runs. |
| `coverage_percent` | number or null | `proved / formal_target_count * 100`; null when there are no formal targets. |
| `node_count` | integer | |
| `formal_target_count` | integer | Count of nodes whose formal status is not `missing`. |
| `proved_count` | integer | |
| `found_count` | integer | |
| `problem_count` | integer | Nodes with `not_found`, `broken`, `failed_check`, or `tainted`. |
| `stale_count` | integer | Nodes whose declared facts no longer match upstream. |
| `has_cycles` | boolean | |

Storage rules:

- Capped at **500 entries**; older entries are dropped on insert.
- Deduped by `(commit_sha, branch)`: a re-run of the same commit replaces
  rather than duplicates its entry.
- On a corrupted or older-format file, `report` silently re-initialises the
  history; this is intentional and consumers should not rely on entries
  surviving forever.

The top-level shape is either a JSON array (the canonical form, used since
v0.8) or an object with an `entries` array (tolerated by readers for forward
compatibility); writers always emit the array form in the v1 line.

---

## Compatibility rules

For the v1.x line:

1. **No documented key will be removed or renamed.** Adding new keys to any
   object is allowed and is not a breaking change; consumers should ignore
   unknown keys.
2. **Value types of documented keys will not change.** A field documented as
   `string or null` may produce either; a field documented as `integer` will
   not start producing strings.
3. **Enum value sets** (`kind`, `blueprint`, `formal`, `agent`, badge
   `color`) may be **extended** with new values in minor releases. Consumers
   should treat unknown values defensively (e.g. as "unknown / other").
4. The `build/check-cache.json` file is **not** part of this contract — it is
   an internal cache. Do not parse it from outside the tool.
