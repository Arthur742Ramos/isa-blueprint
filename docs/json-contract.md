# JSON contract

This document is the **frozen public surface** of the JSON files
`isabelle-blueprint` writes under `build/` plus JSON stdout payloads as of
v1.7.1. Keys, value types, and value semantics listed here will not change
without a major version bump. New keys may be added in backward-compatible
releases; consumers should ignore unknown keys.

Report files are always UTF-8, indent-2 pretty-printed JSON. Packaged JSON
Schemas for the public payloads are available via `isabelle-blueprint schema`.

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
        "blueprint": "written",
        "formal": "found",
        "agent": "ready",
        "last_checked": "2026-05-31T12:00:00Z",
        "check_error": null
      },
      "tags": [],
      "source": { "file": "blueprint.md", "line": 12 }
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
| `tags` | array of strings | Free-form tags from the blueprint block. Always present; may be empty. |
| `source` | object | `{ "file": string\|null, "line": integer\|null }` pointing at the blueprint block this node was parsed from. Both subkeys may be `null` for synthesised nodes. |

The `status` object:

| Key | Type | Notes |
| --- | --- | --- |
| `blueprint` | string | One of `stub`, `written`, `reviewed`. |
| `formal` | string | One of `missing`, `named`, `not_found`, `found`, `proved`, `tainted`, `stale`, `broken`, `failed_check`. |
| `agent` | string | One of `blocked`, `ready`, `in_progress`, `attempted`, `solved`, `needs_human`. |
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

Bounded coverage / problem-count history. Added in v0.8. The top-level value
is an object containing an `entries` array; entries are appended in
chronological order (oldest first, newest last).

```json
{
  "schema_version": 1,
  "entries": [
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
}
```

Top-level keys:

| Key | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | Always `1` in the v1 line. |
| `entries` | array of entry objects | Oldest entry first, newest last. May be empty. |

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

Writers in the v1 line always emit the object form
`{ "schema_version": 1, "entries": [...] }`. Readers also tolerate the
legacy bare-array form (a top-level JSON array of entry objects, used by
pre-1.0 builds) for backward compatibility.

---

## `build/tasks.json`

Agent-ready tasks written by `isabelle-blueprint tasks` and mirrored into the
static site by `isabelle-blueprint web`.

```json
{
  "tasks": [
    {
      "id": "task-main-theorem",
      "node_id": "main-theorem",
      "title": "Main theorem",
      "kind": "theorem",
      "target_fact": "Demo.main_theorem",
      "target_theory": "Demo",
      "informal_statement": "...",
      "informal_proof": "...",
      "dependencies": [
        {
          "id": "technical-lemma",
          "title": "Technical lemma",
          "fact": "Demo.technical_lemma",
          "theory": "Demo"
        }
      ],
      "acceptance_criteria": ["..."],
      "metadata": {
        "priority": "high",
        "difficulty": "medium",
        "dependency_depth": 2,
        "blocking_count": 0,
        "suggested_order": 1,
        "suggested_facts": []
      }
    }
  ],
  "suggested_next_task": "task-main-theorem",
  "filters": {
    "kind": ["theorem"],
    "priority": ["high"],
    "difficulty": [],
    "memory_state": ["fresh"],
    "last_outcome": [],
    "exclude_node": []
  },
  "ready_task_count": 3,
  "filtered_ready_task_count": 1
}
```

v1.1 adds the optional `metadata` object and top-level
`suggested_next_task`. v1.2 adds the optional `memory` object:

```json
{
  "attempt_count": 2,
  "last_outcome": "failed",
  "last_summary": "simp looped on the induction hypothesis",
  "last_timestamp": "2026-06-01T12:00:00Z",
  "next_step": "try induction on n",
  "stale": false
}
```

`stale` is `true` when the latest attempt was recorded against older task
inputs. Existing task keys remain unchanged.

When `isabelle-blueprint tasks` is run with ready-task filters, `tasks` contains
only the filtered ready tasks and `suggested_next_task` is the first task in that
filtered view. Filtered payloads also include `filters`, `ready_task_count`, and
`filtered_ready_task_count`, using the same shapes as `next --json`. Without
filters, those top-level metadata keys may be omitted.

---

## `next --json`

A read-only ready-task prompt payload printed to stdout by
`isabelle-blueprint next --json`. It is generated directly from the current
blueprint and any available check, dump, suggestion, or memory artifacts; prompt
files do not need to exist first.

```json
{
  "task": {
    "id": "task-main-theorem",
    "node_id": "main-theorem",
    "title": "Main theorem"
  },
  "prompt": "# Task: Main theorem\n...",
  "prompt_path": "/absolute/path/to/next.md",
  "filters": {
    "kind": ["theorem"],
    "priority": ["high"],
    "difficulty": [],
    "memory_state": ["fresh"],
    "last_outcome": [],
    "exclude_node": ["task-old-attempt"]
  },
  "ready_task_count": 3,
  "filtered_ready_task_count": 1,
  "message": "Selected task-main-theorem."
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `task` | object or null | Full task object using the same shape as entries in `build/tasks.json`, or `null` when no ready task exists. |
| `prompt` | string or null | Rendered Markdown prompt for the selected task, or `null` when no ready task exists. |
| `prompt_path` | string or null | Absolute path written by `next --output PATH`, or `null` when `--output` was omitted or no prompt was selected. Added in v1.5.2. |
| `filters` | object | Selected `kind`, `priority`, `difficulty`, `memory_state`, `last_outcome`, and `exclude_node` filter values. Added in v1.7 with `memory_state`, `last_outcome`, and `exclude_node` in v1.7.1. |
| `ready_task_count` | integer | Number of currently ready tasks before filters. Added in v1.7. |
| `filtered_ready_task_count` | integer | Number of ready tasks after applying selection filters. Added in v1.7. |
| `message` | string | Human-readable selection or no-task summary. |

Selecting an unknown, blocked, complete, or otherwise not-ready node exits 1
with a CLI error instead of emitting a JSON payload. When filters exclude all
ready tasks, the command exits 0 with `task`, `prompt`, and `prompt_path` set to
`null`, `ready_task_count` greater than zero, and a `message` that says existing
ready tasks were filtered out.

---

## `attempt --json`

Proof-attempt handoff payload printed by `isabelle-blueprint attempt --json`.

```json
{
  "task": { "id": "task-main-theorem", "node_id": "main-theorem" },
  "prompt_path": "/absolute/path/to/build/attempts/task-main-theorem.md",
  "check": {
    "report_path": "/absolute/path/to/build/check-report.json",
    "project_json_path": "/absolute/path/to/build/project.json",
    "isabelle_available": true,
    "ran": true,
    "return_code": 0,
    "error": null
  },
  "memory": {
    "timestamp": "2026-06-01T12:00:00Z",
    "outcome": "failed",
    "summary": "simp looped",
    "actor": null,
    "tool": null,
    "details": "",
    "next_step": "try induction",
    "input_hash": "..."
  },
  "filters": {
    "kind": ["theorem"],
    "priority": [],
    "difficulty": [],
    "memory_state": ["attempted"],
    "last_outcome": ["failed"],
    "exclude_node": []
  },
  "ready_task_count": 3,
  "filtered_ready_task_count": 1,
  "message": "Prepared task-main-theorem."
}
```

`task` uses the same shape as `build/tasks.json`; `check` is `null` unless
`--check` was passed; `memory` is `null` unless `--record-outcome` was passed.
`filters`, `ready_task_count`, and `filtered_ready_task_count` mirror
`next --json` and were added in v1.7. The `memory_state`, `last_outcome`, and
`exclude_node` filter keys were added in v1.7.1. When no ready task exists, `task`,
`prompt_path`, `check`, and `memory` are `null` and `message` explains the empty
state or filter exclusion.

---

## `status --json`

A read-only project health overview printed to stdout by
`isabelle-blueprint status --json`.

```json
{
  "project": "Group theory demo",
  "health": "ready",
  "metrics": {
    "node_count": 10,
    "formal_target_count": 4,
    "proved_count": 2,
    "found_count": 2,
    "problem_count": 0,
    "stale_count": 0,
    "has_cycles": false,
    "coverage_percent": 50
  },
  "ready_task_count": 1,
  "next_task": {
    "id": "task-main-theorem",
    "node_id": "main-theorem",
    "title": "Main theorem",
    "kind": "theorem",
    "target_fact": "Demo.main_theorem",
    "priority": "high",
    "difficulty": "high",
    "blocking_count": 3,
    "suggested_order": 1
  }
}
```

| Key | Type | Notes |
| --- | --- | --- |
| `project` | string | Project name from `[project].name`. |
| `health` | string | One of `complete`, `ready`, `blocked`, `problem`, `stale`, or `unstarted`. |
| `metrics` | object | Same scalar status metrics used by badges and GitHub Actions outputs. `coverage_percent` is `null` when no formal targets exist. |
| `ready_task_count` | integer | Number of currently actionable proof tasks. |
| `next_task` | object or null | Summary of the first suggested task, or `null` when no task is ready. |
| `top_ready_tasks` | array, optional | Present only when `status --top-tasks N --json` is used. Contains the first `N` ready-task summaries in stable task order; when non-empty, `top_ready_tasks[0]` is the same summary as `next_task`. |

---

## `roadmap --json` / `build/roadmap.json`

Roadmap payloads are printed by `isabelle-blueprint roadmap --json` and written
to `build/roadmap.json` by `isabelle-blueprint roadmap --write`.

```json
{
  "schema_version": 1,
  "project": "Group theory demo",
  "summary": {
    "node_count": 10,
    "complete_count": 5,
    "ready_count": 2,
    "blocked_count": 2,
    "problem_count": 1,
    "stale_count": 0,
    "stage_count": 4
  },
  "metrics": {
    "node_count": 10,
    "formal_target_count": 7,
    "proved_count": 3,
    "found_count": 2,
    "problem_count": 1,
    "stale_count": 0,
    "has_cycles": false,
    "coverage_percent": 43
  },
  "suggested_next_task": "task-main-theorem",
  "suggested_path": ["main-theorem", "final-corollary"],
  "cycles": [],
  "stages": [
    {
      "index": 1,
      "items": [
        {
          "node_id": "group",
          "title": "Group",
          "kind": "definition",
          "stage": 1,
          "status": "complete",
          "formal_status": "proved",
          "agent_status": "solved",
          "target_fact": "Group.group_def",
          "blocked_by": [],
          "blocks": 3,
          "task_id": null,
          "priority": null,
          "difficulty": null,
          "suggested_order": null
        }
      ]
    }
  ]
}
```

Top-level keys:

| Key | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | Always `1` for the v1 roadmap shape. |
| `project` | string | Project name from `[project].name`. |
| `summary` | object | Roadmap classification counts: `node_count`, `complete_count`, `ready_count`, `blocked_count`, `problem_count`, `stale_count`, and `stage_count`. |
| `metrics` | object | Same scalar status metrics used by badges and GitHub Actions outputs. |
| `suggested_next_task` | string or null | The first ready task from the same stable ordering used by `tasks`, or `null`. |
| `suggested_path` | array of strings | A deterministic heuristic path through incomplete downstream work. It starts from `suggested_next_task` when available, otherwise from the first incomplete node by stage and id; ties choose the longest path, then the most downstream blocked nodes, then lexicographic node id. |
| `cycles` | array of string arrays | Dependency cycles reported by validation. Nodes in cycles are classified as `problem`. |
| `stages` | array | Topological dependency stages. Nodes that participate in cycles are placed in the final stage. |
| `filters` | object, optional | Present only for filtered `roadmap --json` output. Contains the requested `status`, `stage`, and `kind` filter arrays. Top-level summary, metrics, cycles, and suggestions still describe the full roadmap; only `stages` is filtered. |
| `diff` | object, optional | Present only for `roadmap --json --since PATH`. Contains status changes computed from the full current roadmap before display filters are applied. |

Roadmap item statuses:

| Status | Meaning |
| --- | --- |
| `complete` | The node's formal status is `found` or `proved`. |
| `ready` | The node is not complete and every dependency is `found` or `proved`; it has a matching generated task. |
| `blocked` | The node is incomplete and at least one dependency is incomplete or missing. |
| `problem` | The node is in a dependency cycle or has formal status `not_found`, `broken`, `failed_check`, or `tainted`. |
| `stale` | The node's formal status is exactly `stale`. |

Each `blocked_by` entry includes `id`, nullable `title`, the dependency's
roadmap `status` (or `missing` for an undefined dependency), nullable
`formal_status`, and a `reason` such as
`missing_dependency`, `incomplete_dependency`, `problem_dependency`,
`stale_dependency`, or `cycle_dependency`.

`diff` contains:

| Key | Type | Notes |
| --- | --- | --- |
| `previous_project` | string or null | Project name from the baseline roadmap. |
| `current_project` | string | Project name from the current roadmap. |
| `counts` | object | Counts for each diff bucket. |
| `added` / `removed` | arrays | Nodes added to or removed from the roadmap. |
| `newly_complete` / `newly_ready` / `newly_blocked` / `newly_problem` / `newly_stale` | arrays | Nodes whose roadmap status changed into that state. |
| `status_changed` | array | Status changes that do not fit one of the named buckets. |

Each diff entry includes `node_id`, nullable `title`, nullable `kind`, nullable
`previous_status`, nullable `current_status`, nullable `previous_stage`, and
nullable `current_stage`.

---

## `agent-context --json` / `build/agent-context.json`

The agent-context payload is printed by
`isabelle-blueprint agent-context --json` and written to
`build/agent-context.json` by `isabelle-blueprint agent-context --write`. It is
the recommended first payload for AI agents because it points at the fuller
status, roadmap, task, prompt, and memory artifacts without forcing agents to
discover them one by one.

```json
{
  "schema_version": 1,
  "tool_version": "1.7.1",
  "generated_at": "2026-06-01T12:00:00Z",
  "project": {
    "name": "Group theory demo",
    "root": ".",
    "blueprints": ["blueprint.md"]
  },
  "health": "ready",
  "metrics": {
    "node_count": 10,
    "formal_target_count": 4,
    "proved_count": 2,
    "found_count": 2,
    "problem_count": 0,
    "stale_count": 0,
    "has_cycles": false,
    "coverage_percent": 50
  },
  "ready_task_count": 2,
  "ready_tasks_truncated": false,
  "suggested_next_task": "task-main-theorem",
  "suggested_path": ["main-theorem", "final-corollary"],
  "warnings": [],
  "artifacts": {
    "agent_context_json": "build/agent-context.json",
    "agent_context_md": "build/agent-context.md",
    "project_json": "build/project.json",
    "tasks_json": "build/tasks.json",
    "tasks_md": "build/tasks.md",
    "prompts_dir": "build/prompts",
    "roadmap_json": "build/roadmap.json",
    "roadmap_md": "build/roadmap.md",
    "agent_memory": ".isabelle-blueprint/agent-memory.json",
    "check_report": "build/check_report.json"
  },
  "commands": [
    {
      "intent": "refresh_context",
      "description": "Refresh the machine-readable handoff without writing artifacts.",
      "argv": ["isabelle-blueprint", "agent-context", ".", "--json"],
      "writes": false
    }
  ],
  "ready_tasks": [
    {
      "id": "task-main-theorem",
      "node_id": "main-theorem",
      "title": "Main theorem",
      "kind": "theorem",
      "target_fact": "Demo.main_theorem",
      "target_theory": "Demo",
      "prompt_path": "build/prompts/task-main-theorem.md",
      "priority": "high",
      "difficulty": "medium",
      "blocking_count": 3,
      "suggested_order": 1,
      "memory": null
    }
  ]
}
```

Top-level keys:

| Key | Type | Notes |
| --- | --- | --- |
| `schema_version` | integer | Always `1` for the v1 agent-context shape. |
| `tool_version` | string | IsabelleBlueprint package version that generated the payload. |
| `generated_at` | string | ISO-8601 UTC timestamp. Honors `SOURCE_DATE_EPOCH` when set. |
| `project` | object | Project name, root marker (`"."`), and blueprint paths. |
| `health` | string | Same values and semantics as `status --json`. |
| `metrics` | object | Same scalar status metrics used by `status`, `roadmap`, badges, and GitHub Actions outputs. |
| `ready_task_count` | integer | Full count of currently actionable tasks. |
| `ready_tasks_truncated` | boolean | `true` when the embedded `ready_tasks` list is capped by `--max-tasks`; read `artifacts.tasks_json` for the full queue. |
| `suggested_next_task` | string or null | Same stable ordering as `tasks` and `roadmap`. |
| `suggested_path` | array of strings | Same path heuristic as `roadmap`. |
| `warnings` | array | Machine-branchable warnings with `code`, `message`, `severity`, and `related_nodes`. Codes include `cycles_detected`, `problem_nodes`, `stale_nodes`, `missing_dependencies`, `stale_memory`, and `no_ready_tasks`. |
| `artifacts` | object | Conventional artifact paths. Paths are project-root-relative POSIX strings when under the project root; unusual external output directories may be absolute platform paths. |
| `commands` | array | Advisory follow-up commands. Each entry has an `intent`, human description, `argv` array, and `writes` flag. |
| `ready_tasks` | array | Bounded summaries of the first ready tasks plus their prompt paths and latest memory summary. |

`agent-context` reuses existing status, roadmap, and task builders. Consumers that
need full prompt bodies, dependencies, or acceptance criteria should follow
`prompt_path` or read `artifacts.tasks_json`; the context payload intentionally
keeps each ready-task entry compact.

---

## `build/fact-suggestions.json`

Written by `report` when unresolved formal targets have nearby known fact
names.

```json
{
  "suggestions": [
    {
      "node_id": "main-theorem",
      "target_fact": "Demo.main_theorm",
      "suggestions": ["Demo.main_theorem"]
    }
  ]
}
```

---

## `.isabelle-blueprint/agent-memory.json`

Persistent per-node proof-attempt memory. This file is intentionally outside
`build/` so teams can commit it or share it across agent runs.

```json
{
  "schema_version": 1,
  "nodes": {
    "main-theorem": {
      "attempts": [
        {
          "timestamp": "2026-06-01T12:00:00Z",
          "outcome": "failed",
          "summary": "simp loops after unfolding the definition",
          "actor": "alice",
          "tool": "sledgehammer",
          "details": "",
          "next_step": "prove the monotonicity helper first",
          "input_hash": "..."
        }
      ]
    }
  }
}
```

Attempts are capped by the `memory --max-attempts` value when recording
(default 20 per node). Readers should ignore unknown keys.

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
