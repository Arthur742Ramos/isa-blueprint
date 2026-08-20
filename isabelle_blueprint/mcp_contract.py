"""Typed result contracts used by the optional MCP integration."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

GraphFormatValue = Literal["json", "dot", "mermaid", "graphml", "d2"]


class MCPVersionPayload(TypedDict):
    """Machine-readable server metadata."""

    name: str
    version: str
    project_dir: str
    workspace_dir: str
    default_project: str | None
    project_count: int
    writes_enabled: bool
    schemas: list[str]
    mcp_api_version: NotRequired[str]
    mcp_sdk_version: NotRequired[str | None]
    transport: NotRequired[str]
    http_host: NotRequired[str]
    http_path: NotRequired[str]
    max_result_bytes: NotRequired[int | None]
    catalog_generation: NotRequired[int]
    catalog_refreshed_at: NotRequired[str]


class MCPProjectEntry(TypedDict):
    """One project in the workspace catalog."""

    id: str
    name: str
    path: str
    project_dir: str
    default: bool
    metadata_error: NotRequired[str]


class MCPProjectCatalog(TypedDict):
    """Workspace project discovery payload."""

    workspace_dir: str
    default_project: str | None
    project_count: int
    projects: list[MCPProjectEntry]
    generation: NotRequired[int]
    refreshed_at: NotRequired[str]


class MCPStatusMetrics(TypedDict):
    """Stable status counters."""

    node_count: int
    formal_target_count: int
    proved_count: int
    found_count: int
    problem_count: int
    stale_count: int
    has_cycles: bool
    coverage_percent: int | None


class MCPNextTaskOverview(TypedDict):
    """Compact task metadata embedded in status responses."""

    id: str
    node_id: str
    title: str
    kind: str
    target_fact: str | None
    priority: str | None
    difficulty: str | None
    blocking_count: int | None
    suggested_order: int | None


class MCPStatusPayload(TypedDict):
    """Structured output for the status tool."""

    project: str
    health: str
    metrics: MCPStatusMetrics
    ready_task_count: int
    next_task: MCPNextTaskOverview | None
    top_ready_tasks: NotRequired[list[MCPNextTaskOverview]]
    filters: NotRequired[dict[str, list[str]]]
    filtered_ready_task_count: NotRequired[int]
    message: NotRequired[str]
    snapshot: NotRequired[dict[str, Any]]


class MCPTaskDependency(TypedDict):
    """A dependency attached to a ready task."""

    id: str
    title: str
    fact: str | None
    theory: str | None


class MCPTaskMetadata(TypedDict):
    """Scheduling metadata attached to a ready task."""

    priority: str
    difficulty: str
    dependency_depth: int
    blocking_count: int
    suggested_order: int
    suggested_facts: list[str]


class MCPTask(TypedDict):
    """Full ready-task payload."""

    id: str
    node_id: str
    title: str
    kind: str
    target_fact: str | None
    target_theory: str | None
    informal_statement: str
    informal_proof: str
    dependencies: list[MCPTaskDependency]
    acceptance_criteria: list[str]
    metadata: MCPTaskMetadata | None
    memory: dict[str, Any] | None


class MCPSelectionMetadata(TypedDict):
    """Common selection metadata returned by task tools."""

    filters: dict[str, list[str]]
    ready_task_count: int
    filtered_ready_task_count: int


class MCPListTasksPayload(MCPSelectionMetadata):
    """Structured output for list_tasks."""

    tasks: list[MCPTask]
    suggested_next_task: str | None
    returned_task_count: NotRequired[int]
    tasks_truncated: NotRequired[bool]
    snapshot: NotRequired[dict[str, Any]]
    message: NotRequired[str]


class MCPNextTaskPayload(MCPSelectionMetadata):
    """Structured output for next_task and prove_task planning."""

    task: MCPTask | None
    prompt: str | None
    message: str
    snapshot: NotRequired[dict[str, Any]]


class MCPAgentContextPayload(TypedDict):
    """Structured output for the compact agent handoff bundle."""

    schema_version: int
    tool_version: str
    generated_at: str
    project: dict[str, Any]
    health: str
    metrics: dict[str, Any]
    ready_task_count: int
    ready_tasks_truncated: bool
    suggested_next_task: str | None
    suggested_path: list[str]
    warnings: list[dict[str, Any]]
    artifacts: dict[str, str]
    commands: list[dict[str, Any]]
    ready_tasks: list[dict[str, Any]]
    filters: NotRequired[dict[str, list[str]]]
    filtered_ready_task_count: NotRequired[int]
    snapshot: NotRequired[dict[str, Any]]


class MCPGraphPayload(TypedDict):
    """Structured output for graph rendering."""

    format: GraphFormatValue
    graph: dict[str, Any] | str


class MCPTheoryIndexPayload(TypedDict):
    """Structured output for source-only theory indexing."""

    schema_version: int
    theories: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    sorries: list[dict[str, Any]]
    unreferenced: list[str]
    has_import_cycle: bool
    session: str | None
    source_roots: list[str]
    theory_files: list[str]
    warnings: list[str]


class MCPSchemaPayload(TypedDict):
    """Structured output for the schema discovery tool."""

    schemas: NotRequired[list[str]]
    name: NotRequired[str]
    schema: NotRequired[dict[str, Any]]
