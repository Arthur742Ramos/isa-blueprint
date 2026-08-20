"""Model Context Protocol server for IsabelleBlueprint projects."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import threading
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal, cast, get_type_hints

from isabelle_blueprint import __version__
from isabelle_blueprint.agents.assignments import (
    AssignmentStore,
    clear_assignment,
    load_assignments,
    set_assignment,
    write_assignments,
)
from isabelle_blueprint.agents.blame import blame_payload, build_blame
from isabelle_blueprint.agents.context import (
    DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
    build_agent_context,
)
from isabelle_blueprint.agents.memory import (
    VALID_OUTCOMES,
    load_agent_memory,
    node_input_hash,
    record_memory_attempt,
)
from isabelle_blueprint.agents.runner import (
    PROMPT_PLACEHOLDER,
    RUN_PLACEHOLDERS,
    safe_prompt_filename,
    split_command_string,
    substitute_command,
    validate_command_tokens,
)
from isabelle_blueprint.agents.selection import (
    filter_ready_tasks,
    no_ready_task_message,
    ready_task_filters_from_values,
    ready_task_filters_to_argv,
    select_ready_task,
    selection_metadata,
)
from isabelle_blueprint.agents.tasks import generate_tasks, render_task_prompt
from isabelle_blueprint.config import DEFAULT_BLUEPRINT_NAME, DEFAULT_CONFIG_NAME
from isabelle_blueprint.doctor import run_doctor
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.explain import explain_project
from isabelle_blueprint.graph.dependency_graph import (
    UnknownNodeError as GraphUnknownNodeError,
)
from isabelle_blueprint.graph.dependency_graph import (
    focus_subproject,
)
from isabelle_blueprint.graph.graphviz_render import (
    render_d2,
    render_dot,
    render_graphml,
    render_json,
    render_mermaid,
)
from isabelle_blueprint.isabelle.compat import check_compatibility
from isabelle_blueprint.isabelle.reconcile import dependency_audit_payload
from isabelle_blueprint.isabelle.source_index import build_index, session_theory_files
from isabelle_blueprint.isabelle.suggestions import suggest_missing_facts
from isabelle_blueprint.mcp_contract import (
    MCPAgentContextPayload,
    MCPGraphPayload,
    MCPListTasksPayload,
    MCPNextTaskPayload,
    MCPProjectCatalog,
    MCPSchemaPayload,
    MCPStatusPayload,
    MCPTheoryIndexPayload,
    MCPVersionPayload,
)
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.project_io import (
    load_config_checked,
    load_project,
    load_project_with_check,
)
from isabelle_blueprint.refactor import rename_node
from isabelle_blueprint.report.burndown import build_burndown_report, burndown_payload
from isabelle_blueprint.report.critical_path import (
    build_critical_path,
    critical_path_payload,
)
from isabelle_blueprint.report.depends import (
    UnknownNodeError as DependsUnknownNodeError,
)
from isabelle_blueprint.report.depends import (
    build_depends_report,
)
from isabelle_blueprint.report.diff import build_diff, load_baseline
from isabelle_blueprint.report.effort import build_effort_gate, build_effort_report
from isabelle_blueprint.report.fact_coverage import build_fact_coverage_report
from isabelle_blueprint.report.gate import build_gate_report
from isabelle_blueprint.report.history import summarize_trends
from isabelle_blueprint.report.impact import (
    UnknownNodeError,
    build_impact_overview,
    build_impact_report,
    impact_overview_payload,
    impact_report_payload,
)
from isabelle_blueprint.report.kinds import build_kind_report
from isabelle_blueprint.report.levels import build_levels_report
from isabelle_blueprint.report.lint import build_lint_report
from isabelle_blueprint.report.matrix import build_matrix_report
from isabelle_blueprint.report.metrics import PROBLEM_FORMAL_STATUSES
from isabelle_blueprint.report.orphans import build_orphan_report
from isabelle_blueprint.report.path import (
    UnknownNodeError as PathUnknownNodeError,
)
from isabelle_blueprint.report.path import (
    build_path_report,
)
from isabelle_blueprint.report.portfolio import build_portfolio, portfolio_payload
from isabelle_blueprint.report.proof_debt import build_proof_debt_report
from isabelle_blueprint.report.roadmap import (
    ROADMAP_STATUSES,
    RoadmapFilters,
    build_roadmap,
    roadmap_payload,
)
from isabelle_blueprint.report.scorecard import build_scorecard
from isabelle_blueprint.report.staleness import build_staleness_report, staleness_payload
from isabelle_blueprint.report.stats import build_stats_report
from isabelle_blueprint.report.status_overview import build_status_overview
from isabelle_blueprint.report.tag_cooccurrence import build_tag_cooccurrence_report
from isabelle_blueprint.report.tags import build_tag_report
from isabelle_blueprint.report.trends import load_trends
from isabelle_blueprint.schemas import available_schemas, read_schema

GraphFormat = Literal["json", "dot", "mermaid", "graphml", "d2"]
MCP_API_VERSION = "1.18"
GateGrade = Literal["A", "B", "C", "D", "F"]
GateStatus = Literal[
    "missing",
    "named",
    "not_found",
    "found",
    "proved",
    "tainted",
    "stale",
    "broken",
    "failed_check",
    "problem",
]


def build_server(
    project_dir: Path,
    *,
    allow_writes: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    transport: str = "stdio",
    allow_insecure_http: bool = False,
    max_result_bytes: int | None = None,
) -> Any:
    """Build a FastMCP server bound to one or more IsabelleBlueprint projects."""

    FastMCP = _require_fastmcp()
    if transport not in {"stdio", "streamable-http"}:
        raise BlueprintError("transport must be 'stdio' or 'streamable-http'")
    if max_result_bytes is not None and max_result_bytes < 1:
        raise BlueprintError("max_result_bytes must be at least 1")
    if transport == "streamable-http" and not _is_loopback_host(host) and not allow_insecure_http:
        raise BlueprintError(
            "streamable HTTP is restricted to loopback hosts by default; "
            "use --allow-insecure-http only behind a separately authenticated boundary"
        )
    launch_root = Path(project_dir).resolve()
    catalog = _ProjectCatalog.discover(launch_root)
    http_path = path if path.startswith("/") else f"/{path}"
    write_lock = threading.Lock()
    snapshot_cache = _SnapshotCache()
    project_word = "project" if len(catalog.projects) == 1 else "projects"
    server = FastMCP(
        "IsabelleBlueprint",
        instructions=(
            "Inspect IsabelleBlueprint formalization plans, dependency status, "
            f"ready proof tasks, and agent handoff context for Isabelle {project_word}. "
            "Use list_projects first when this server exposes multiple projects."
        ),
        host=host,
        port=port,
        streamable_http_path=http_path,
        json_response=True,
    )

    def mcp_tool(
        *,
        name: str,
        title: str | None = None,
        read_only: bool = True,
        idempotent: bool = True,
        destructive: bool = False,
        open_world: bool = False,
    ) -> Any:
        return _tool_decorator(
            server,
            name=name,
            title=title,
            read_only=read_only,
            idempotent=idempotent,
            destructive=destructive,
            open_world=open_world,
            max_result_bytes=max_result_bytes,
        )

    def mcp_resource(
        uri: str,
        *,
        title: str | None = None,
        priority: float = 0.5,
    ) -> Any:
        return _resource_decorator(
            server,
            uri,
            title=title,
            priority=priority,
            max_result_bytes=max_result_bytes,
        )

    def snapshot_for(project: str | None) -> _ProjectSnapshot:
        try:
            selected = catalog.resolve(project)
        except BlueprintError:
            # A long-lived server may receive a selector for a project created
            # after startup. Refresh only on a failed lookup to keep ordinary
            # reads cheap while making the catalog self-healing.
            catalog.refresh()
            selected = catalog.resolve(project)
        return snapshot_cache.get(selected.root)

    @mcp_tool(name="version", title="IsabelleBlueprint server information")
    def version() -> MCPVersionPayload:
        """Return MCP server and IsabelleBlueprint package metadata."""

        catalog.refresh()
        default_project = catalog.default_project
        return {
            "name": "isabelle-blueprint",
            "version": __version__,
            "project_dir": str(
                default_project.root if default_project is not None else launch_root
            ),
            "workspace_dir": str(launch_root),
            "default_project": default_project.id if default_project is not None else None,
            "project_count": len(catalog.projects),
            "writes_enabled": allow_writes,
            "schemas": list(available_schemas()),
            "mcp_api_version": MCP_API_VERSION,
            "mcp_sdk_version": _mcp_sdk_version(),
            "transport": transport,
            "http_host": host,
            "http_path": http_path,
            "max_result_bytes": max_result_bytes,
            "catalog_generation": catalog.generation,
            "catalog_refreshed_at": catalog.refreshed_at,
        }

    @mcp_tool(name="list_projects", title="List IsabelleBlueprint projects")
    def list_projects(refresh: bool = True) -> MCPProjectCatalog:
        """List IsabelleBlueprint projects discovered under the launch directory."""

        if refresh:
            catalog.refresh()
        return cast(MCPProjectCatalog, catalog.to_dict())

    @mcp_tool(name="status", title="Inspect project health")
    def status(
        top_tasks: int | None = None,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> MCPStatusPayload:
        """Return the same project health payload as `isabelle-blueprint status --json`."""

        snapshot = snapshot_for(project)
        filters = _ready_filters(
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )
        selected = filter_ready_tasks(snapshot.ready_tasks, filters)
        overview = build_status_overview(
            snapshot.project,
            snapshot.ready_tasks,
            top_task_count=_positive_or_none(top_tasks),
            selected_ready_tasks=selected if filters.active else None,
            filters=filters.to_dict() if filters.active else None,
        )
        payload = overview.to_dict()
        payload["snapshot"] = snapshot.metadata()
        payload.setdefault("top_ready_tasks", [])
        payload.setdefault("filters", filters.to_dict())
        payload.setdefault("filtered_ready_task_count", len(selected))
        payload.setdefault("message", "")
        if filters.active and not selected and snapshot.ready_tasks:
            payload["message"] = no_ready_task_message(len(snapshot.ready_tasks), filters)
        return cast(MCPStatusPayload, payload)

    @mcp_tool(name="roadmap", title="Plan staged proof work")
    def roadmap(
        status: list[str] | None = None,
        stage: list[int] | None = None,
        kind: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return staged proof-work planning data."""

        snapshot = snapshot_for(project)
        overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        filters = _roadmap_filters(status=status, stage=stage, kind=kind)
        _validate_roadmap_filters(overview.summary.stage_count, filters)
        return roadmap_payload(overview, filters=filters)

    @mcp_tool(name="list_tasks", title="List ready proof tasks")
    def list_tasks(
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        limit: int | None = None,
        project: str | None = None,
    ) -> MCPListTasksPayload:
        """List currently ready proof tasks, optionally filtered."""

        limit = _positive_or_none(limit, label="limit")
        snapshot = snapshot_for(project)
        filters = _ready_filters(
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )
        all_tasks = filter_ready_tasks(snapshot.ready_tasks, filters)
        tasks = all_tasks if limit is None else all_tasks[:limit]
        payload: dict[str, object] = {
            "tasks": [task.to_dict() for task in tasks],
            "suggested_next_task": all_tasks[0].id if all_tasks else None,
            "snapshot": snapshot.metadata(),
            "returned_task_count": len(tasks),
            "tasks_truncated": len(tasks) < len(all_tasks),
        }
        payload.update(
            selection_metadata(
                filters,
                ready_task_count=len(snapshot.ready_tasks),
                filtered_ready_task_count=len(all_tasks),
            )
        )
        payload["message"] = (
            no_ready_task_message(len(snapshot.ready_tasks), filters) if not all_tasks else ""
        )
        return cast(MCPListTasksPayload, payload)

    @mcp_tool(name="next_task", title="Select the next proof task")
    def next_task(
        node: str | None = None,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> MCPNextTaskPayload:
        """Return the selected ready task plus its rendered proof prompt."""

        snapshot = snapshot_for(project)
        return cast(
            MCPNextTaskPayload,
            _next_task_payload(
                snapshot.project_root,
                snapshot=snapshot,
                node=node,
                kind=kind,
                priority=priority,
                difficulty=difficulty,
                memory_state=memory_state,
                last_outcome=last_outcome,
                exclude_node=exclude_node,
            ),
        )

    @mcp_tool(name="agent_run_plan", title="Plan an agent proof run")
    def agent_run_plan(
        command: str | None = None,
        node: str | None = None,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Plan an ``agent-run`` invocation WITHOUT executing anything.

        Returns the selected task, its prompt, where the CLI would write the
        prompt, the outcome mapping, and a suggested local ``isabelle-blueprint
        agent-run`` invocation. If a ``command`` template is supplied its resolved
        argv is echoed as a read-only preview. Executing solver commands is
        intentionally CLI-only -- this tool never spawns a process.
        """

        snapshot = snapshot_for(project)
        return _agent_run_plan_payload(
            snapshot.project_root,
            snapshot=snapshot,
            command=command,
            node=node,
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )

    @mcp_tool(name="agent_context", title="Build agent handoff context")
    def agent_context(
        max_tasks: int = DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> MCPAgentContextPayload:
        """Return the compact handoff bundle for proof agents."""

        max_tasks = _positive_or_none(max_tasks, label="max_tasks") or 1
        snapshot = snapshot_for(project)
        filters = _ready_filters(
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )
        selected = filter_ready_tasks(snapshot.ready_tasks, filters)
        status_overview = build_status_overview(snapshot.project, snapshot.ready_tasks)
        roadmap_overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        context = build_agent_context(
            snapshot.config,
            status_overview,
            roadmap_overview,
            snapshot.ready_tasks,
            max_tasks=max_tasks,
            filtered_ready_tasks=selected if filters.active else None,
            filters=filters.to_dict() if filters.active else None,
            filter_argv=ready_task_filters_to_argv(filters) if filters.active else None,
        )
        payload = context.to_dict()
        payload.setdefault("filters", filters.to_dict())
        payload.setdefault("filtered_ready_task_count", len(selected))
        payload["snapshot"] = snapshot.metadata()
        return cast(MCPAgentContextPayload, payload)

    @mcp_tool(name="explain_node", title="Explain node status and blockers")
    def explain_node(
        node_id: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Explain status, blockers, and next steps for one node or all nodes."""

        snapshot = snapshot_for(project)
        explanations = explain_project(
            snapshot.project,
            node_id=node_id,
            fact_suggestions=snapshot.fact_suggestions,
        )
        return {"explanations": [item.to_dict() for item in explanations]}

    @mcp_tool(name="lint", title="Lint the blueprint")
    def lint(project: str | None = None) -> dict[str, object]:
        """Run structural and quality lint checks without invoking Isabelle."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_lint_report(parsed).to_dict()

    @mcp_tool(name="gate", title="Evaluate the project gate")
    def gate(
        min_coverage: int | None = None,
        fail_on: list[GateStatus] | None = None,
        min_grade: GateGrade | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Evaluate the explainable lint, coverage, status, and scorecard gate."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        coverage = _percentage_or_none(min_coverage, label="min_coverage")
        report = build_gate_report(
            parsed,
            min_coverage=int(coverage) if coverage is not None else None,
            fail_on=_gate_fail_on(fail_on),
            min_grade=min_grade,
        )
        return report.to_dict()

    @mcp_tool(name="blame", title="Inspect node provenance")
    def blame(
        node: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return source, Git, and agent-memory provenance for blueprint nodes."""

        selected = catalog.resolve(project).root
        config, parsed = load_project_with_check(selected)
        memory = load_agent_memory(config.agent_memory_path)
        return blame_payload(build_blame(parsed, selected, memory, node_id=node))

    @mcp_tool(name="effort", title="Measure effort-weighted progress")
    def effort(
        by_tag: bool = False,
        nodes: bool = False,
        fail_under: float | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return effort-weighted proof progress and an optional threshold gate."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        report = build_effort_report(parsed, include_by_tag=by_tag, include_nodes=nodes)
        payload = report.to_dict(include_by_tag=by_tag, include_nodes=nodes)
        threshold = _percentage_or_none(fail_under, label="fail_under")
        if threshold is not None:
            payload["gate"] = build_effort_gate(report, threshold)
        return payload

    @mcp_tool(name="diff", title="Compare against a project baseline")
    def diff(
        baseline: str,
        project: str | None = None,
    ) -> dict[str, object]:
        """Compare the current project with a project-report baseline under its root."""

        selected = catalog.resolve(project).root
        _config, parsed = load_project_with_check(selected)
        baseline_path = _project_file(selected, baseline, label="baseline")
        return build_diff(load_baseline(baseline_path), parsed).to_dict()

    @mcp_tool(name="deps_audit", title="Audit declared dependencies")
    def deps_audit(
        actual_dependencies: dict[str, list[str]],
        project: str | None = None,
    ) -> dict[str, object]:
        """Compare supplied Isabelle fact dependencies with declared blueprint edges.

        This is the read-only comparison phase of ``reconcile``. It does not
        generate theories, invoke Isabelle, or write artifacts.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        known = set(parsed.by_id())
        unknown = sorted(set(actual_dependencies) - known)
        if unknown:
            raise BlueprintError(
                "actual_dependencies contains unknown node ids: "
                + ", ".join(unknown)
                + "; known node ids: "
                + (", ".join(sorted(known)) or "(none)")
            )
        normalized = {
            node_id: sorted(set(dependencies))
            for node_id, dependencies in sorted(actual_dependencies.items())
        }
        return dependency_audit_payload(parsed, normalized)

    @mcp_tool(name="critical_path", title="Find the critical proof path")
    def critical_path(
        top: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return longest-pole proof-dependency analysis (bottlenecks and goal chains)."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        overview = build_critical_path(parsed)
        return critical_path_payload(overview, top=_positive_or_none(top, label="top"))

    @mcp_tool(name="impact", title="Rank dependency impact")
    def impact(
        node: str | None = None,
        top: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return downstream blast-radius analysis.

        With ``node`` set, return that node's full impact report (``top`` is
        ignored). Without ``node``, return every node ranked by blast radius,
        limited to ``top`` rankings when provided.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        top_value = _positive_or_none(top, label="top")
        if node:
            try:
                report = build_impact_report(parsed, node)
            except UnknownNodeError:
                known = ", ".join(sorted(item.id for item in parsed.nodes)) or "(none)"
                raise BlueprintError(f"unknown node {node!r}; known node ids: {known}") from None
            return impact_report_payload(report)
        overview = build_impact_overview(parsed)
        return impact_overview_payload(overview, top=top_value)

    @mcp_tool(name="stats", title="Summarize agent memory")
    def stats(project: str | None = None) -> dict[str, object]:
        """Return agent-memory analytics (attempts, outcomes, and success rates)."""

        config, parsed = load_project(catalog.resolve(project).root)
        memory = load_agent_memory(config.agent_memory_path)
        return build_stats_report(memory, parsed).to_dict()

    @mcp_tool(name="staleness", title="Audit proof staleness")
    def staleness(
        top: int | None = None,
        max_causes: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Audit trusted (found/proved) nodes resting on shaky dependencies.

        Scans every trusted node and walks its dependencies to flag ones whose
        status is not justified: a ``problem`` dependency (broken/tainted/
        missing/cyclic), an ``incomplete`` one (unproven), or an ``outdated`` one
        (a dependency re-checked more recently than this node). ``top`` limits the
        number of stale nodes returned; ``max_causes`` limits causes per node.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        report = build_staleness_report(parsed)
        return staleness_payload(
            report,
            top=_positive_or_none(top, label="top"),
            max_causes=_positive_or_none(max_causes, label="max_causes"),
        )

    @mcp_tool(name="history", title="Summarize coverage history")
    def history(
        limit: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Summarize the ``trends.json`` coverage history.

        Returns the same ``entry_count``/``entries``/``deltas`` summary as
        ``history --json``, plus two convenience keys not in the CLI output:
        ``latest`` (the newest entry, or ``null`` when there is no history) and
        ``trends_path`` (the resolved store location).

        Reads only the recorded trend store, so it still works when the current
        blueprint fails to parse — historical movement is most useful exactly
        then. ``limit`` keeps only the most recent N entries in the view; the
        latest delta is always computed from the two newest entries.
        """

        return _history_payload(
            catalog.resolve(project).root,
            limit=_positive_or_none(limit, label="limit"),
        )

    @mcp_tool(name="burndown", title="Forecast proof burndown")
    def burndown(
        window: int | None = None,
        limit: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Forecast an ETA to full proved coverage (mirrors ``burndown --json``).

        Reads only the recorded ``trends.json`` series, so it still forecasts
        when the current blueprint fails to parse. The ETA is derived from the
        slope of *remaining* work over time (so a growing target is reflected),
        with proved/target velocities reported for context. ``window`` sets how
        many recent snapshots feed the recent velocity; ``limit`` only trims the
        displayed points.
        """

        return _burndown_payload(
            catalog.resolve(project).root,
            window=_positive_or_none(window, label="window"),
            limit=_positive_or_none(limit, label="limit"),
        )

    @mcp_tool(name="portfolio", title="Summarize the project portfolio")
    def portfolio() -> dict[str, object]:
        """Aggregate status across every blueprint project in the workspace.

        Scans the launch root for blueprint projects (mirrors ``portfolio
        --json``) and rolls up coverage, health, ready-task counts, and
        problem/cycle flags. This view is workspace-wide and takes no
        ``project`` argument; unparseable projects are reported as errors
        without failing the roll-up.
        """

        return _portfolio_payload(catalog.launch_root)

    @mcp_tool(name="compat", title="Check Isabelle compatibility")
    def compat(
        isabelle: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Check Isabelle/AFP version pins and session visibility (read-only).

        Mirrors the ``compat`` JSON payload, including the per-issue severity
        list and the overall ``ok`` flag. Unlike the CLI command, this does not
        write the report file to disk.
        """

        config = load_config_checked(catalog.resolve(project).root)
        report = check_compatibility(config, isabelle_executable=isabelle)
        return report.to_dict()

    @mcp_tool(name="suggest_facts", title="Suggest Isabelle facts")
    def suggest_facts(project: str | None = None) -> dict[str, object]:
        """Return fuzzy fact-name suggestions for unresolved formal targets."""

        snapshot = snapshot_for(project)
        suggestions = [item.to_dict() for item in snapshot.fact_suggestions]
        return {"suggestions": suggestions, "count": len(suggestions)}

    @mcp_tool(name="theory_index", title="Index Isabelle theory sources")
    def theory_index(
        session: str | None = None,
        project: str | None = None,
    ) -> MCPTheoryIndexPayload:
        """Source-only index of Isabelle ``.thy`` files (mirrors ``theory-index --json``).

        Needs no ``isabelle`` binary and never parses ``blueprint.md``, so it
        works in CI, on partial checkouts, and even when the blueprint itself
        fails to load. Theory sources are resolved from ``[isabelle].dirs`` and
        ``[isabelle].session`` in the project config (falling back to a ``ROOT``
        or ``.thy`` files at the project root); ``session`` overrides the
        configured session name. Returns the cross-theory reference (call)
        graph, theory import dependencies (both directions), ``sorry``/``oops``
        markers, and entries no other indexed entry references, all in one
        payload. ``source_roots``/``theory_files`` report what was indexed and
        ``warnings`` lists configured roots that resolved no theories.
        """

        return cast(
            MCPTheoryIndexPayload,
            _theory_index_payload(catalog.resolve(project).root, session=session),
        )

    @mcp_tool(name="graph", title="Render the dependency graph")
    def graph(
        format: GraphFormat = "json",
        focus: str | None = None,
        depth: int | None = None,
        project: str | None = None,
    ) -> MCPGraphPayload:
        """Return the dependency graph as JSON, DOT, Mermaid, GraphML, or D2 without writing files.

        With ``focus`` set, the graph is restricted to that node and its
        dependency neighbourhood (ancestors and descendants); ``depth`` limits
        the neighbourhood to that many hops (``None`` = unlimited). GraphML is
        suitable for Gephi/Cytoscape/yEd/NetworkX import.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        if focus:
            if depth is not None and depth < 0:
                raise BlueprintError("depth must be non-negative")
            try:
                parsed = focus_subproject(parsed, focus, depth)
            except GraphUnknownNodeError:
                known = ", ".join(sorted(item.id for item in parsed.nodes)) or "(none)"
                raise BlueprintError(f"unknown node {focus!r}; known node ids: {known}") from None
        if format == "json":
            return {"format": "json", "graph": json.loads(render_json(parsed))}
        if format == "dot":
            return {"format": "dot", "graph": render_dot(parsed)}
        if format == "mermaid":
            return {"format": "mermaid", "graph": render_mermaid(parsed)}
        if format == "graphml":
            return {"format": "graphml", "graph": render_graphml(parsed)}
        if format == "d2":
            return {"format": "d2", "graph": render_d2(parsed)}
        raise BlueprintError("graph format must be one of: json, dot, mermaid, graphml, d2")

    @mcp_tool(name="scorecard", title="Score project quality")
    def scorecard(project: str | None = None) -> dict[str, object]:
        """Return the composite project quality scorecard (mirrors ``scorecard --json``).

        Distils coverage, integrity, structure, freshness, documentation, and
        readiness into one weighted 0-100 score plus a letter grade and a
        per-component breakdown. Computed without invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_scorecard(parsed).to_dict()

    @mcp_tool(name="tags", title="Summarize tag coverage")
    def tags(project: str | None = None) -> dict[str, object]:
        """Return the per-tag coverage roll-up (mirrors ``tags --json``).

        Groups nodes by their declared ``tags`` and reports node counts, formal
        targets, proved/found/problem counts, and per-tag coverage, plus how
        many nodes carry no tag. A multi-tag node is counted under each tag.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_tag_report(parsed).to_dict()

    @mcp_tool(name="kinds", title="Summarize node-kind coverage")
    def kinds(project: str | None = None) -> dict[str, object]:
        """Return the per-kind coverage roll-up (mirrors ``kinds --json``).

        Groups nodes by their declared ``kind`` (definition/lemma/theorem/...)
        and reports, per kind, the node count, formal targets, proved/found/
        problem counts, and a per-kind coverage percentage. Computed without
        invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_kind_report(parsed).to_dict()

    @mcp_tool(name="proof_debt", title="Measure proof debt")
    def proof_debt(project: str | None = None) -> dict[str, object]:
        """Return the effort-weighted remaining proof work (mirrors ``proof-debt --json``).

        Sums the ``effort`` weight of every formal-target node that is not yet
        proved into a single debt figure, attributed to status buckets (named/
        found/problem, plus an informational missing). Computed without invoking
        Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_proof_debt_report(parsed).to_dict()

    @mcp_tool(name="fact_coverage", title="Measure fact coverage")
    def fact_coverage(project: str | None = None) -> dict[str, object]:
        """Return per-theory Isabelle fact coverage (mirrors ``fact-coverage --json``).

        Reports, per referenced theory, how many of the project's formal-target
        facts resolve to known facts versus remain unresolved. Computed without
        invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_fact_coverage_report(parsed).to_dict()

    @mcp_tool(name="levels", title="Inspect dependency levels")
    def levels(project: str | None = None) -> dict[str, object]:
        """Return the dependency-depth layering (mirrors ``levels --json``).

        Groups nodes into topological levels by how deep they sit in the
        ``uses`` dependency graph, so bottom-up proof work can be sequenced.
        Computed without invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_levels_report(parsed).to_dict()

    @mcp_tool(name="orphans", title="Find orphaned nodes")
    def orphans(project: str | None = None) -> dict[str, object]:
        """Return nodes unreachable from any project goal (mirrors ``orphans --json``).

        Walks the ``uses`` graph from the root goals and lists every node it
        never reaches (dead planning weight), flagging fully isolated nodes.
        Computed without invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_orphan_report(parsed).to_dict()

    @mcp_tool(name="tag_cooccurrence", title="Rank tag co-occurrence")
    def tag_cooccurrence(
        min_shared: int | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return ranked co-occurring tag pairs (mirrors ``tag-cooccurrence --json``).

        Reports tag pairs that share at least ``min_shared`` nodes (default 1),
        ranked by shared-node count, with a sample of the shared nodes. Computed
        without invoking Isabelle.
        """

        shared = _positive_or_none(min_shared, label="min_shared")
        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return build_tag_cooccurrence_report(parsed, min_shared=shared or 1).to_dict()

    @mcp_tool(name="matrix", title="Build a project matrix")
    def matrix(
        rows: str = "formal",
        cols: str = "kind",
        project: str | None = None,
    ) -> dict[str, object]:
        """Return a 2D node-count cross-tabulation (mirrors ``matrix --json``).

        Cross-tabulates node counts across two categorical dimensions, each one
        of ``formal``/``blueprint``/``agent``/``kind`` (default ``formal`` rows x
        ``kind`` cols). The two dimensions must differ. Computed without invoking
        Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        try:
            return build_matrix_report(parsed, rows, cols).to_dict()
        except ValueError as exc:
            raise BlueprintError(str(exc)) from None

    @mcp_tool(name="depends", title="Inspect direct dependencies")
    def depends(node: str, project: str | None = None) -> dict[str, object]:
        """Return a node's direct dependency neighbourhood (mirrors ``depends --json``).

        Reports the nodes ``node`` directly ``uses`` (its dependencies) and the
        nodes that directly ``use`` it (its dependents), each with id, kind, and
        formal status. Computed without invoking Isabelle.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        try:
            return build_depends_report(parsed, node).to_dict()
        except DependsUnknownNodeError as exc:
            unknown = exc.args[0] if exc.args else "?"
            known = ", ".join(sorted(item.id for item in parsed.nodes)) or "(none)"
            raise BlueprintError(f"unknown node {unknown!r}; known node ids: {known}") from None

    @mcp_tool(name="path", title="Find a dependency path")
    def path_tool(
        source: str,
        target: str,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return the shortest dependency path between two nodes (mirrors ``path --json``).

        Searches ``uses`` edges from ``source`` to ``target`` first (``source``
        depends on ``target``); if there is no such path it searches the other
        direction and reports which way it found. Reports reachability, the
        direction, and the node chain.
        """

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        try:
            report = build_path_report(parsed, source, target)
        except PathUnknownNodeError as exc:
            unknown = exc.args[0] if exc.args else "?"
            known = ", ".join(sorted(item.id for item in parsed.nodes)) or "(none)"
            raise BlueprintError(f"unknown node {unknown!r}; known node ids: {known}") from None
        return report.to_dict()

    @mcp_tool(name="schema", title="Inspect packaged JSON schemas")
    def schema(name: str | None = None) -> MCPSchemaPayload:
        """List packaged schemas or return one schema by name."""

        if name is None:
            return cast(
                MCPSchemaPayload,
                {"schemas": list(available_schemas()), "name": "", "schema": {}},
            )
        return cast(
            MCPSchemaPayload,
            {
                "schemas": list(available_schemas()),
                "name": name,
                "schema": json.loads(read_schema(name)),
            },
        )

    @mcp_tool(name="doctor", title="Diagnose local setup")
    def doctor(
        isabelle: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Run local environment diagnostics."""

        return run_doctor(catalog.resolve(project).root, isabelle_executable=isabelle).to_dict()

    @mcp_tool(name="preview_rename_node", title="Preview a node rename")
    def preview_rename_node(
        old_id: str,
        new_id: str,
        project: str | None = None,
    ) -> dict[str, object]:
        """Preview a node rename without writing files."""

        # Mirror the CLI's cmd_rename: rename_node only needs the config, so
        # avoid re-parsing the whole blueprint. Use the checked loader so a
        # malformed config surfaces as a BlueprintError (consistent with the
        # other entrypoints) instead of leaking a raw ValueError/OSError.
        config = load_config_checked(catalog.resolve(project).root)
        return rename_node(config, old_id, new_id, dry_run=True).to_dict()

    @mcp_tool(name="list_assignments", title="List node assignments")
    def list_assignments(project: str | None = None) -> dict[str, object]:
        """List node ownership (owner/note/updated_at) recorded for the project.

        This is the read-only counterpart to the ``assign_node`` write tool: it
        mirrors CLI ``assign`` list mode, so an agent can discover who owns a node
        before starting work without needing ``--allow-writes``. A missing or
        corrupt assignments store is tolerated (returns an empty list).
        """

        return _assignments_resource_payload(catalog.resolve(project).root)

    @mcp_resource("blueprint://projects", title="Project catalog", priority=1.0)
    def projects_resource() -> str:
        """Discovered IsabelleBlueprint project catalog."""

        catalog.refresh()
        return _json_resource(catalog.to_dict())

    @mcp_resource("blueprint://project", title="Project graph", priority=1.0)
    def project_resource() -> str:
        """Parsed project graph as JSON."""

        return _json_resource(snapshot_for(None).project.to_dict())

    @mcp_resource("blueprint://nodes/{node_id}", title="Blueprint node")
    def node_resource(node_id: str) -> str:
        """One blueprint node by id."""

        project = snapshot_for(None).project
        node = project.by_id().get(node_id)
        if node is None:
            raise BlueprintError(f"unknown node id {node_id!r}")
        return _json_resource(node.to_dict())

    @mcp_resource("blueprint://tasks", title="Ready proof tasks", priority=1.0)
    def tasks_resource() -> str:
        """Ready proof task catalog."""

        snapshot = snapshot_for(None)
        return _json_resource(
            {
                "tasks": [task.to_dict() for task in snapshot.ready_tasks],
                "suggested_next_task": snapshot.ready_tasks[0].id if snapshot.ready_tasks else None,
            }
        )

    @mcp_resource("blueprint://roadmap", title="Proof-work roadmap", priority=0.9)
    def roadmap_resource() -> str:
        """Staged proof-work roadmap."""

        snapshot = snapshot_for(None)
        return _json_resource(build_roadmap(snapshot.project, snapshot.ready_tasks).to_dict())

    @mcp_resource("blueprint://agent-context", title="Agent handoff context", priority=1.0)
    def agent_context_resource() -> str:
        """Default AI-agent handoff bundle."""

        snapshot = snapshot_for(None)
        status_overview = build_status_overview(snapshot.project, snapshot.ready_tasks)
        roadmap_overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        context = build_agent_context(
            snapshot.config,
            status_overview,
            roadmap_overview,
            snapshot.ready_tasks,
        )
        return _json_resource(context.to_dict())

    @mcp_resource("blueprint://history", title="Coverage history")
    def history_resource() -> str:
        """Coverage trend history summary for the default project."""

        return _json_resource(_history_payload(catalog.resolve(None).root))

    @mcp_resource("blueprint://burndown", title="Proof burndown forecast")
    def burndown_resource() -> str:
        """Velocity / ETA-to-full-coverage forecast for the default project."""

        return _json_resource(_burndown_payload(catalog.resolve(None).root))

    @mcp_resource("blueprint://portfolio", title="Project portfolio", priority=0.9)
    def portfolio_resource() -> str:
        """Workspace-wide roll-up across every discovered blueprint project."""

        return _json_resource(_portfolio_payload(catalog.launch_root))

    @mcp_resource("blueprint://fact-suggestions", title="Fact suggestions")
    def fact_suggestions_resource() -> str:
        """Fuzzy fact-name suggestions for the default project."""

        snapshot = snapshot_for(None)
        suggestions = [item.to_dict() for item in snapshot.fact_suggestions]
        return _json_resource({"suggestions": suggestions, "count": len(suggestions)})

    @mcp_resource("blueprint://theory-index", title="Theory source index")
    def theory_index_resource() -> str:
        """Source-only Isabelle ``.thy`` index for the default project."""

        return _json_resource(_theory_index_payload(catalog.resolve(None).root))

    @mcp_resource("blueprint://staleness", title="Proof staleness audit")
    def staleness_resource() -> str:
        """Trusted-node staleness audit for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(staleness_payload(build_staleness_report(parsed)))

    @mcp_resource("blueprint://critical-path", title="Critical proof path")
    def critical_path_resource() -> str:
        """Longest remaining incomplete dependency chain for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(critical_path_payload(build_critical_path(parsed)))

    @mcp_resource("blueprint://kinds", title="Node-kind coverage")
    def kinds_resource() -> str:
        """Per-kind coverage roll-up for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_kind_report(parsed).to_dict())

    @mcp_resource("blueprint://proof-debt", title="Proof debt")
    def proof_debt_resource() -> str:
        """Effort-weighted remaining proof work for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_proof_debt_report(parsed).to_dict())

    @mcp_resource("blueprint://fact-coverage", title="Fact coverage")
    def fact_coverage_resource() -> str:
        """Per-theory Isabelle fact coverage for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_fact_coverage_report(parsed).to_dict())

    @mcp_resource("blueprint://levels", title="Dependency levels")
    def levels_resource() -> str:
        """Dependency-depth layering for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_levels_report(parsed).to_dict())

    @mcp_resource("blueprint://orphans", title="Orphaned nodes")
    def orphans_resource() -> str:
        """Nodes unreachable from any goal for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_orphan_report(parsed).to_dict())

    @mcp_resource("blueprint://tag-cooccurrence", title="Tag co-occurrence")
    def tag_cooccurrence_resource() -> str:
        """Ranked co-occurring tag pairs for the default project."""

        _config, parsed = load_project_with_check(catalog.resolve(None).root)
        return _json_resource(build_tag_cooccurrence_report(parsed).to_dict())

    @mcp_resource("blueprint://assignments", title="Node assignments")
    def assignments_resource() -> str:
        """Recorded node ownership for the default project."""

        return _json_resource(_assignments_resource_payload(catalog.resolve(None).root))

    @mcp_resource("blueprint://projects/{project}/project", title="Selected project graph")
    def project_scoped_project_resource(project: str) -> str:
        """Parsed project graph for a selected project id."""

        return _json_resource(snapshot_for(project).project.to_dict())

    @mcp_resource("blueprint://projects/{project}/nodes/{node_id}", title="Selected blueprint node")
    def project_scoped_node_resource(project: str, node_id: str) -> str:
        """One blueprint node by id for a selected project id."""

        selected_project = snapshot_for(project).project
        node = selected_project.by_id().get(node_id)
        if node is None:
            raise BlueprintError(f"unknown node id {node_id!r}")
        return _json_resource(node.to_dict())

    @mcp_resource("blueprint://projects/{project}/tasks", title="Selected ready tasks")
    def project_scoped_tasks_resource(project: str) -> str:
        """Ready proof task catalog for a selected project id."""

        snapshot = snapshot_for(project)
        return _json_resource(
            {
                "tasks": [task.to_dict() for task in snapshot.ready_tasks],
                "suggested_next_task": snapshot.ready_tasks[0].id if snapshot.ready_tasks else None,
            }
        )

    @mcp_resource("blueprint://projects/{project}/roadmap", title="Selected proof roadmap")
    def project_scoped_roadmap_resource(project: str) -> str:
        """Staged proof-work roadmap for a selected project id."""

        snapshot = snapshot_for(project)
        return _json_resource(build_roadmap(snapshot.project, snapshot.ready_tasks).to_dict())

    @mcp_resource("blueprint://projects/{project}/agent-context", title="Selected agent context")
    def project_scoped_agent_context_resource(project: str) -> str:
        """Default AI-agent handoff bundle for a selected project id."""

        snapshot = snapshot_for(project)
        status_overview = build_status_overview(snapshot.project, snapshot.ready_tasks)
        roadmap_overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        context = build_agent_context(
            snapshot.config,
            status_overview,
            roadmap_overview,
            snapshot.ready_tasks,
        )
        return _json_resource(context.to_dict())

    @mcp_resource("blueprint://projects/{project}/history", title="Selected coverage history")
    def project_scoped_history_resource(project: str) -> str:
        """Coverage trend history summary for a selected project id."""

        return _json_resource(_history_payload(catalog.resolve(project).root))

    @mcp_resource("blueprint://projects/{project}/burndown", title="Selected burndown forecast")
    def project_scoped_burndown_resource(project: str) -> str:
        """Velocity / ETA-to-full-coverage forecast for a selected project id."""

        return _json_resource(_burndown_payload(catalog.resolve(project).root))

    @mcp_resource(
        "blueprint://projects/{project}/fact-suggestions", title="Selected fact suggestions"
    )
    def project_scoped_fact_suggestions_resource(project: str) -> str:
        """Fuzzy fact-name suggestions for a selected project id."""

        snapshot = snapshot_for(project)
        suggestions = [item.to_dict() for item in snapshot.fact_suggestions]
        return _json_resource({"suggestions": suggestions, "count": len(suggestions)})

    @mcp_resource("blueprint://projects/{project}/theory-index", title="Selected theory index")
    def project_scoped_theory_index_resource(project: str) -> str:
        """Source-only Isabelle ``.thy`` index for a selected project id."""

        return _json_resource(_theory_index_payload(catalog.resolve(project).root))

    @mcp_resource("blueprint://projects/{project}/staleness", title="Selected staleness audit")
    def project_scoped_staleness_resource(project: str) -> str:
        """Trusted-node staleness audit for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(staleness_payload(build_staleness_report(parsed)))

    @mcp_resource("blueprint://projects/{project}/critical-path", title="Selected critical path")
    def project_scoped_critical_path_resource(project: str) -> str:
        """Longest remaining incomplete dependency chain for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(critical_path_payload(build_critical_path(parsed)))

    @mcp_resource("blueprint://projects/{project}/kinds", title="Selected kind coverage")
    def project_scoped_kinds_resource(project: str) -> str:
        """Per-kind coverage roll-up for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_kind_report(parsed).to_dict())

    @mcp_resource("blueprint://projects/{project}/proof-debt", title="Selected proof debt")
    def project_scoped_proof_debt_resource(project: str) -> str:
        """Effort-weighted remaining proof work for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_proof_debt_report(parsed).to_dict())

    @mcp_resource("blueprint://projects/{project}/fact-coverage", title="Selected fact coverage")
    def project_scoped_fact_coverage_resource(project: str) -> str:
        """Per-theory Isabelle fact coverage for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_fact_coverage_report(parsed).to_dict())

    @mcp_resource("blueprint://projects/{project}/levels", title="Selected dependency levels")
    def project_scoped_levels_resource(project: str) -> str:
        """Dependency-depth layering for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_levels_report(parsed).to_dict())

    @mcp_resource("blueprint://projects/{project}/orphans", title="Selected orphaned nodes")
    def project_scoped_orphans_resource(project: str) -> str:
        """Nodes unreachable from any goal for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_orphan_report(parsed).to_dict())

    @mcp_resource(
        "blueprint://projects/{project}/tag-cooccurrence", title="Selected tag co-occurrence"
    )
    def project_scoped_tag_cooccurrence_resource(project: str) -> str:
        """Ranked co-occurring tag pairs for a selected project id."""

        _config, parsed = load_project_with_check(catalog.resolve(project).root)
        return _json_resource(build_tag_cooccurrence_report(parsed).to_dict())

    @mcp_resource("blueprint://projects/{project}/assignments", title="Selected node assignments")
    def project_scoped_assignments_resource(project: str) -> str:
        """Recorded node ownership for a selected project id."""

        return _json_resource(_assignments_resource_payload(catalog.resolve(project).root))

    @mcp_resource("blueprint://schemas/{name}", title="Packaged JSON schema")
    def schema_resource(name: str) -> str:
        """Packaged JSON Schema by short name."""

        return read_schema(name)

    @_prompt_decorator(
        server,
        name="prove_task",
        title="Prove a ready Isabelle task",
    )
    def prove_task(
        node: str | None = None,
        kind: str | None = None,
        priority: str | None = None,
        difficulty: str | None = None,
        memory_state: str | None = None,
        last_outcome: str | None = None,
        exclude_node: str | None = None,
        project: str | None = None,
    ) -> str:
        """Return a proof-focused prompt for the suggested or selected ready task."""

        snapshot = snapshot_for(project)
        payload = _next_task_payload(
            snapshot.project_root,
            snapshot=snapshot,
            node=node,
            kind=_split_prompt_filter(kind),
            priority=_split_prompt_filter(priority),
            difficulty=_split_prompt_filter(difficulty),
            memory_state=_split_prompt_filter(memory_state),
            last_outcome=_split_prompt_filter(last_outcome),
            exclude_node=_split_prompt_filter(exclude_node),
        )
        prompt = payload.get("prompt")
        if isinstance(prompt, str):
            return prompt
        return str(payload.get("message") or "No ready task is currently available.")

    _register_completion(server, catalog, snapshot_for)

    if allow_writes:
        _register_write_tools(server, catalog, write_lock, snapshot_for, mcp_tool)

    return server


def _register_write_tools(
    server: Any,
    catalog: _ProjectCatalog,
    write_lock: threading.Lock,
    snapshot_for: Any,
    mcp_tool: Any,
) -> None:
    @mcp_tool(
        name="record_attempt",
        title="Record a proof attempt",
        read_only=False,
        idempotent=False,
    )
    def record_attempt(
        node_id: str,
        outcome: str,
        summary: str,
        details: str = "",
        next_step: str | None = None,
        actor: str | None = None,
        tool: str | None = None,
        max_attempts: int = 20,
        project: str | None = None,
    ) -> dict[str, object]:
        """Record proof-attempt memory for a node. Registered only with --allow-writes."""

        if outcome not in VALID_OUTCOMES:
            raise BlueprintError(
                f"unknown memory outcome {outcome!r}; choose one of: "
                f"{', '.join(sorted(VALID_OUTCOMES))}"
            )
        max_attempts = _positive_or_none(max_attempts, label="max_attempts") or 1
        with write_lock:
            snapshot = snapshot_for(project)
            node = snapshot.project.by_id().get(node_id)
            if node is None:
                raise BlueprintError(f"unknown node id {node_id!r}")
            attempt = record_memory_attempt(
                snapshot.config.agent_memory_path,
                node_id,
                outcome=outcome,
                summary=summary,
                actor=actor,
                tool=tool,
                details=details,
                next_step=next_step,
                input_hash=node_input_hash(node),
                max_attempts=max_attempts,
            )
            return {
                "memory_file": str(snapshot.config.agent_memory_path),
                "node_id": node_id,
                "attempt": attempt.to_dict(),
            }

    @mcp_tool(
        name="assign_node",
        title="Assign a proof node",
        read_only=False,
        idempotent=True,
    )
    def assign_node(
        node_id: str,
        owner: str | None = None,
        note: str = "",
        clear: bool = False,
        project: str | None = None,
    ) -> dict[str, object]:
        """Set or clear task ownership. Registered only with --allow-writes."""

        with write_lock:
            snapshot = snapshot_for(project)
            if node_id not in snapshot.project.by_id():
                raise BlueprintError(f"unknown node id {node_id!r}")
            store = load_assignments(snapshot.config.assignments_path, strict=True)
            changed = False
            if clear:
                changed = clear_assignment(store, node_id)
            else:
                if not owner or not owner.strip():
                    raise BlueprintError("owner is required unless clear=true")
                set_assignment(store, node_id, owner.strip(), note=note)
                changed = True
            if changed:
                write_assignments(store, snapshot.config.assignments_path)
            assignment = store.nodes.get(node_id)
            return {
                "assignments_file": str(snapshot.config.assignments_path),
                "node_id": node_id,
                "changed": changed,
                "assignment": assignment.to_dict() if assignment is not None else None,
            }


@dataclass(frozen=True)
class _ProjectEntry:
    id: str
    root: Path
    relative_path: str
    name: str
    metadata_error: str | None = None

    def to_dict(self, *, is_default: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "path": self.relative_path,
            "project_dir": str(self.root),
            "default": is_default,
        }
        if self.metadata_error is not None:
            payload["metadata_error"] = self.metadata_error
        return payload


class _ProjectCatalog:
    def __init__(
        self,
        launch_root: Path,
        projects: list[_ProjectEntry],
        default_project_id: str | None,
        *,
        generation: int = 1,
        refreshed_at: str | None = None,
    ) -> None:
        self.launch_root = launch_root
        self.projects = projects
        self.default_project_id = default_project_id
        self._by_id = {project.id: project for project in projects}
        self.generation = generation
        self.refreshed_at = refreshed_at or _utc_now()

    @property
    def default_project(self) -> _ProjectEntry | None:
        if self.default_project_id is None:
            return None
        return self._by_id[self.default_project_id]

    @classmethod
    def discover(cls, launch_root: Path) -> _ProjectCatalog:
        launch_root = launch_root.resolve()
        roots = _discover_project_roots(launch_root)
        entries = _project_entries(launch_root, roots)
        root_entry = next((entry for entry in entries if entry.root == launch_root), None)
        if root_entry is not None:
            default_project_id = root_entry.id
        elif len(entries) == 1:
            default_project_id = entries[0].id
        else:
            default_project_id = None
        return cls(launch_root, entries, default_project_id, refreshed_at=_utc_now())

    def refresh(self) -> None:
        """Refresh discovered projects while preserving stable ids for existing roots."""

        roots = _discover_project_roots(self.launch_root)
        old_by_root = {project.root: project for project in self.projects}
        used_ids: set[str] = set()
        refreshed: list[_ProjectEntry] = []
        for root in roots:
            relative_path = _relative_path_for_project(self.launch_root, root)
            previous = old_by_root.get(root)
            if previous is not None and previous.id not in used_ids:
                project_id = previous.id
            else:
                project_id = _project_id(relative_path, used_ids)
            used_ids.add(project_id)
            name, metadata_error = _read_project_metadata(root)
            refreshed.append(
                _ProjectEntry(
                    id=project_id,
                    root=root,
                    relative_path=relative_path,
                    name=name,
                    metadata_error=metadata_error,
                )
            )

        root_entry = next((entry for entry in refreshed if entry.root == self.launch_root), None)
        if root_entry is not None:
            default_project_id = root_entry.id
        elif len(refreshed) == 1:
            default_project_id = refreshed[0].id
        else:
            default_project_id = None

        previous_state = (
            tuple(self.projects),
            self.default_project_id,
        )
        next_state = (tuple(refreshed), default_project_id)
        if previous_state != next_state:
            self.generation += 1
        self.projects = refreshed
        self.default_project_id = default_project_id
        self._by_id = {project.id: project for project in refreshed}
        self.refreshed_at = _utc_now()

    def resolve(self, selector: str | None) -> _ProjectEntry:
        """Resolve a selector, refreshing a long-lived catalog after a miss."""

        try:
            return self._resolve_current(selector)
        except BlueprintError:
            previous_state = (tuple(self.projects), self.default_project_id)
            self.refresh()
            current_state = (tuple(self.projects), self.default_project_id)
            if current_state != previous_state:
                return self._resolve_current(selector)
            raise

    def _resolve_current(self, selector: str | None) -> _ProjectEntry:
        if selector is None or not selector.strip():
            default_project = self.default_project
            if default_project is not None:
                return default_project
            if not self.projects:
                raise BlueprintError(
                    f"no IsabelleBlueprint projects found under {self.launch_root}; "
                    f"pass --project-dir to a directory containing {DEFAULT_CONFIG_NAME} "
                    f"or {DEFAULT_BLUEPRINT_NAME}, or run `isabelle-blueprint init` first"
                )
            raise BlueprintError(
                "project is required because this MCP server exposes multiple "
                f"IsabelleBlueprint projects: {self._format_options()}"
            )

        text = selector.strip()
        if text in self._by_id:
            return self._by_id[text]

        path_matches = self._matching_path_projects(text)
        if path_matches:
            return self._only_project_match(text, path_matches)

        name_matches = [project for project in self.projects if project.name == text]
        if name_matches:
            return self._only_project_match(text, name_matches)

        raise BlueprintError(f"unknown project {text!r}; choose one of: {self._format_options()}")

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_dir": str(self.launch_root),
            "default_project": self.default_project_id,
            "project_count": len(self.projects),
            "generation": self.generation,
            "refreshed_at": self.refreshed_at,
            "projects": [
                project.to_dict(is_default=project.id == self.default_project_id)
                for project in self.projects
            ],
        }

    def _matching_path_projects(self, selector: str) -> list[_ProjectEntry]:
        resolved = _resolve_project_selector_path(self.launch_root, selector)
        if resolved is None or not _is_relative_to(resolved, self.launch_root):
            return []
        return [project for project in self.projects if project.root == resolved]

    def _only_project_match(self, selector: str, matches: list[_ProjectEntry]) -> _ProjectEntry:
        if len(matches) == 1:
            return matches[0]
        choices = ", ".join(project.id for project in matches)
        raise BlueprintError(
            f"project selector {selector!r} is ambiguous; use one of these ids: {choices}"
        )

    def _format_options(self) -> str:
        return ", ".join(
            f"{project.id} ({project.relative_path}, {project.name})" for project in self.projects
        )


def _discover_project_roots(launch_root: Path) -> list[Path]:
    roots: list[Path] = []
    if _has_project_marker(launch_root):
        roots.append(launch_root)

    for current_raw, dirnames, filenames in os.walk(launch_root, followlinks=False):
        current = Path(current_raw)
        dirnames[:] = sorted(
            dirname for dirname in dirnames if _should_descend_into(current / dirname)
        )
        if current == launch_root:
            continue
        if _filenames_have_project_marker(filenames):
            roots.append(current.resolve())
            dirnames[:] = []

    return sorted(
        dict.fromkeys(roots), key=lambda path: _relative_path_for_project(launch_root, path)
    )


def _project_entries(launch_root: Path, roots: list[Path]) -> list[_ProjectEntry]:
    used_ids: set[str] = set()
    entries: list[_ProjectEntry] = []
    for root in roots:
        relative_path = _relative_path_for_project(launch_root, root)
        project_id = _project_id(relative_path, used_ids)
        used_ids.add(project_id)
        name, metadata_error = _read_project_metadata(root)
        entries.append(
            _ProjectEntry(
                id=project_id,
                root=root,
                relative_path=relative_path,
                name=name,
                metadata_error=metadata_error,
            )
        )
    return entries


def _has_project_marker(path: Path) -> bool:
    return (path / DEFAULT_CONFIG_NAME).is_file() or (path / DEFAULT_BLUEPRINT_NAME).is_file()


def _filenames_have_project_marker(filenames: list[str]) -> bool:
    return DEFAULT_CONFIG_NAME in filenames or DEFAULT_BLUEPRINT_NAME in filenames


def _should_descend_into(path: Path) -> bool:
    name = path.name
    if path.is_symlink():
        return False
    if name.startswith("."):
        return False
    return name not in {
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "site",
        "venv",
    }


def _relative_path_for_project(launch_root: Path, project_root: Path) -> str:
    if project_root == launch_root:
        return "."
    return project_root.relative_to(launch_root).as_posix()


def _project_id(relative_path: str, used_ids: set[str]) -> str:
    if relative_path == ".":
        base = "root"
    else:
        base = re.sub(r"[^A-Za-z0-9]+", "-", relative_path).strip("-").lower()
        if not base:
            base = "project"
    if base not in used_ids:
        return base
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}-{digest}"
    counter = 2
    while candidate in used_ids:
        candidate = f"{base}-{digest}-{counter}"
        counter += 1
    return candidate


def _read_project_metadata(project_root: Path) -> tuple[str, str | None]:
    config_path = project_root / DEFAULT_CONFIG_NAME
    if not config_path.exists():
        return "Untitled IsabelleBlueprint project", None
    try:
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return "Untitled IsabelleBlueprint project", str(exc)
    project_section = raw.get("project", {})
    if not isinstance(project_section, dict):
        return "Untitled IsabelleBlueprint project", "[project] must be a table"
    name = project_section.get("name")
    if isinstance(name, str) and name.strip():
        return name, None
    return "Untitled IsabelleBlueprint project", None


def _resolve_project_selector_path(launch_root: Path, selector: str) -> Path | None:
    normalized = selector.replace("\\", "/")
    try:
        selector_path = Path(normalized)
        if selector_path.is_absolute():
            return selector_path.resolve()
        parts = [part for part in normalized.split("/") if part and part != "."]
        if not parts:
            return launch_root
        return launch_root.joinpath(*parts).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class _ProjectSnapshot:
    def __init__(self, project_dir: Path) -> None:
        self.config, self.project = load_project_with_check(project_dir)
        self.project_root = self.config.project_root
        self.generated_at = _utc_now()
        self.input_signature = _project_input_signature(self.config)
        self.fact_suggestions = suggest_missing_facts(
            self.project,
            dump_report_path=self.config.dump_report_path,
        )
        self.memory = load_agent_memory(self.config.agent_memory_path)
        self.ready_tasks = generate_tasks(
            self.project,
            fact_suggestions=self.fact_suggestions,
            memory=self.memory,
        )

    def metadata(self) -> dict[str, object]:
        """Return provenance for the snapshot used to produce an MCP result."""

        return {
            "project_root": str(self.project_root),
            "generated_at": self.generated_at,
            "input_signature": self.input_signature,
            "check_report": str(self.config.check_report_path),
            "check_report_exists": self.config.check_report_path.is_file(),
        }


class _SnapshotCache:
    """Reuse project analysis until one of its source inputs changes."""

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[str, _ProjectSnapshot]] = {}
        self._lock = threading.RLock()

    def get(self, project_dir: Path) -> _ProjectSnapshot:
        with self._lock:
            config = load_config_checked(project_dir)
            signature = _project_input_signature(config)
            cached = self._entries.get(config.project_root)
            if cached is not None and cached[0] == signature:
                return cached[1]
            snapshot = _ProjectSnapshot(config.project_root)
            self._entries[config.project_root] = (signature, snapshot)
            return snapshot


def _snapshot(project_dir: Path) -> _ProjectSnapshot:
    return _ProjectSnapshot(project_dir)


def _project_input_signature(config: Any) -> str:
    """Fingerprint files whose changes can alter project status or ready tasks."""

    paths = [
        config.project_root / DEFAULT_CONFIG_NAME,
        *config.blueprint_paths,
        config.check_report_path,
        config.dump_report_path,
        config.agent_memory_path,
    ]
    digest = hashlib.sha256()
    for path in sorted(dict.fromkeys(paths), key=str):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        try:
            stat = path.stat()
        except OSError:
            digest.update(b"<missing>\0")
        else:
            digest.update(f"{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}".encode("ascii"))
            digest.update(b"\0")
    return digest.hexdigest()


def _assignments_payload(
    project_name: str, store: AssignmentStore, assignments_path: Path
) -> dict[str, object]:
    """Shape an assignment store for MCP clients.

    The ``project`` + ``assignments`` list mirrors CLI ``assign`` list mode; an
    extra ``assignments_file`` key (not in the CLI output) records the resolved
    store path so an agent can locate it.
    """

    items = [
        {
            "node_id": nid,
            "owner": assignment.owner,
            "note": assignment.note,
            "updated_at": assignment.updated_at,
        }
        for nid, assignment in sorted(store.nodes.items())
    ]
    return {
        "project": project_name,
        "assignments_file": str(assignments_path),
        "assignments": items,
    }


def _assignments_resource_payload(project_dir: Path) -> dict[str, object]:
    """Load + shape node ownership for the ``list_assignments`` tool and resource."""

    config, parsed = load_project(project_dir)
    store = load_assignments(config.assignments_path)
    return _assignments_payload(parsed.name, store, config.assignments_path)


def _history_payload(project_dir: Path, *, limit: int | None = None) -> dict[str, object]:
    # History only needs trends.json, so avoid parsing the (possibly broken)
    # blueprint: historical data is most useful exactly when the current
    # blueprint does not load.
    config = load_config_checked(project_dir)
    entries = load_trends(config.trends_path)
    summary = summarize_trends(entries, limit=limit)
    payload = summary.to_dict()
    payload["latest"] = summary.latest
    payload["trends_path"] = str(config.trends_path)
    return payload


def _burndown_payload(
    project_dir: Path,
    *,
    window: int | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    # Like history, burndown reads only trends.json, so it still forecasts when
    # the current blueprint fails to parse.
    config = load_config_checked(project_dir)
    entries = load_trends(config.trends_path)
    report = build_burndown_report(entries, recent_window=window or 5)
    payload = burndown_payload(report, limit=limit)
    payload["trends_path"] = str(config.trends_path)
    return payload


def _portfolio_payload(root: Path) -> dict[str, object]:
    # Portfolio is workspace-wide: it scans the launch root for every blueprint
    # project and rolls them up, so it takes the launch root rather than a
    # single resolved project directory.
    return portfolio_payload(build_portfolio(root))


def _mcp_session_hint(message: str) -> str:
    # session_theory_files() raises CLI-flavored guidance ("pass --session NAME").
    # This payload is surfaced over MCP, where callers pass a `session` argument
    # rather than a command-line flag, so translate the advice before exposing it.
    return message.replace("pass --session NAME", "pass the `session` argument")


def _theory_index_payload(
    project_dir: Path,
    *,
    session: str | None = None,
) -> dict[str, object]:
    # Source-only analysis: read .thy files directly and never parse the
    # (possibly broken) blueprint, so it works on partial checkouts and CI.
    config = load_config_checked(project_dir)
    selected_session = session if session is not None else config.isabelle_session
    roots = config.isabelle_dirs or [config.project_root]
    # Per-root warnings about missing/empty roots are only meaningful when several
    # roots are configured; for a single root the friendly "no .thy files" error
    # below already names what was searched.
    report_root_gaps = len(roots) > 1
    files: list[Path] = []
    seen: set[Path] = set()
    used_roots: list[Path] = []
    warnings: list[str] = []
    for root in roots:
        if not root.exists():
            # A configured root that is absent on disk would otherwise silently
            # shrink the index; surface it so the gap is never invisible.
            if report_root_gaps:
                warnings.append(f"configured source root {root} does not exist")
            continue
        try:
            resolved = session_theory_files(root, selected_session)
        except ValueError as exc:
            # A single configured root that lacks the session must not abort the
            # whole index when other roots still resolve theories; remember it.
            warnings.append(_mcp_session_hint(str(exc)))
            continue
        if resolved:
            used_roots.append(root)
        elif report_root_gaps:
            # Present but contributes nothing (e.g. no session declaration and no
            # loose .thy files); record it so a partial index stays transparent.
            warnings.append(f"configured source root {root} resolved no theory files")
        for path in resolved:
            if path not in seen:
                seen.add(path)
                files.append(path)
    if not files:
        if warnings:
            raise BlueprintError("; ".join(warnings))
        searched = ", ".join(str(root) for root in roots) or str(config.project_root)
        raise BlueprintError(
            f"no .thy files found for project {config.project_root} (searched: {searched}); "
            f"set [isabelle].dirs in {DEFAULT_CONFIG_NAME} or add a ROOT/theory sources"
        )
    payload = build_index(files).to_dict()
    payload["session"] = selected_session
    payload["source_roots"] = [str(root) for root in used_roots]
    payload["theory_files"] = [str(path) for path in files]
    payload["warnings"] = warnings
    return payload


def _next_task_payload(
    project_root: Path,
    *,
    snapshot: _ProjectSnapshot | None = None,
    node: str | None = None,
    kind: list[str] | None = None,
    priority: list[str] | None = None,
    difficulty: list[str] | None = None,
    memory_state: list[str] | None = None,
    last_outcome: list[str] | None = None,
    exclude_node: list[str] | None = None,
) -> dict[str, object]:
    snapshot = snapshot or _snapshot(project_root)
    filters = _ready_filters(
        kind=kind,
        priority=priority,
        difficulty=difficulty,
        memory_state=memory_state,
        last_outcome=last_outcome,
        exclude_node=exclude_node,
    )
    ready_tasks = filter_ready_tasks(snapshot.ready_tasks, filters)
    task = select_ready_task(
        ready_tasks,
        node,
        snapshot.project,
        filters=filters,
        unfiltered_ready_tasks=snapshot.ready_tasks,
    )
    metadata = selection_metadata(
        filters,
        ready_task_count=len(snapshot.ready_tasks),
        filtered_ready_task_count=len(ready_tasks),
    )
    if task is None:
        return {
            "task": None,
            "prompt": None,
            "message": no_ready_task_message(len(snapshot.ready_tasks), filters),
            "snapshot": snapshot.metadata(),
            **metadata,
        }
    return {
        "task": task.to_dict(),
        "prompt": render_task_prompt(task),
        "message": f"Selected {task.id}.",
        "snapshot": snapshot.metadata(),
        **metadata,
    }


_AGENT_RUN_OUTCOME_MAPPING = {
    "exit_zero": "succeeded",
    "nonzero": "failed",
    "timeout": "failed",
    "output_limit_exceeded": "failed",
    "spawn_error": "blocked",
}


def _agent_run_plan_payload(
    project_root: Path,
    *,
    snapshot: _ProjectSnapshot | None = None,
    command: str | None = None,
    node: str | None = None,
    kind: list[str] | None = None,
    priority: list[str] | None = None,
    difficulty: list[str] | None = None,
    memory_state: list[str] | None = None,
    last_outcome: list[str] | None = None,
    exclude_node: list[str] | None = None,
) -> dict[str, object]:
    base = _next_task_payload(
        project_root,
        snapshot=snapshot,
        node=node,
        kind=kind,
        priority=priority,
        difficulty=difficulty,
        memory_state=memory_state,
        last_outcome=last_outcome,
        exclude_node=exclude_node,
    )
    plan: dict[str, object] = {
        **base,
        "command_template": command,
        "command_argv_preview": None,
        "command_error": None,
        "prompt_path": None,
        "cli_argv": None,
        "outcome_mapping": dict(_AGENT_RUN_OUTCOME_MAPPING),
        "placeholders": list(RUN_PLACEHOLDERS),
        "execution_note": (
            "Execution is intentionally CLI-only; this tool never runs commands. "
            "Run the suggested cli_argv locally with `isabelle-blueprint agent-run`."
        ),
    }
    task = base.get("task")
    if not isinstance(task, dict):
        return plan
    task_id = str(task["id"])
    node_id = str(task["node_id"])
    config = load_config_checked(project_root)
    prompt_path = config.build_dir / "agent-run" / safe_prompt_filename(task_id)
    plan["prompt_path"] = str(prompt_path)
    cli_argv = ["isabelle-blueprint", "agent-run", str(project_root), "--node", task_id]
    if command:
        prompt_in_command = PROMPT_PLACEHOLDER in command
        try:
            tokens = split_command_string(command)
            validate_command_tokens(tokens, require_prompt=False)
        except BlueprintError as exc:
            plan["command_error"] = str(exc)
        else:
            substitutions = {
                "prompt_file": str(prompt_path),
                "node_id": node_id,
                "task_id": task_id,
                "project_dir": str(project_root),
            }
            plan["command_argv_preview"] = substitute_command(tokens, substitutions)
        cli_argv += ["--command", command]
        # Keep the suggested CLI runnable: agent-run requires {prompt_file} unless
        # --allow-missing-prompt is passed, so mirror that here when the planned
        # command omits the placeholder.
        if not prompt_in_command:
            cli_argv.append("--allow-missing-prompt")
    else:
        cli_argv += ["--command", "<solver> {prompt_file}"]
    plan["cli_argv"] = cli_argv
    return plan


def _ready_filters(
    *,
    kind: list[str] | None = None,
    priority: list[str] | None = None,
    difficulty: list[str] | None = None,
    memory_state: list[str] | None = None,
    last_outcome: list[str] | None = None,
    exclude_node: list[str] | None = None,
):
    return ready_task_filters_from_values(
        kinds=kind,
        priorities=priority,
        difficulties=difficulty,
        memory_states=memory_state,
        last_outcomes=last_outcome,
        excluded_nodes=exclude_node,
    )


def _roadmap_filters(
    *,
    status: list[str] | None = None,
    stage: list[int] | None = None,
    kind: list[str] | None = None,
) -> RoadmapFilters:
    statuses = _dedupe(status)
    unknown_statuses = [value for value in statuses if value not in ROADMAP_STATUSES]
    if unknown_statuses:
        raise BlueprintError(
            f"unknown roadmap status {unknown_statuses[0]!r}; choose one of: "
            f"{', '.join(ROADMAP_STATUSES)}"
        )
    kinds = _dedupe(kind)
    valid_kinds = tuple(item.value for item in NodeKind)
    unknown_kinds = [value for value in kinds if value not in valid_kinds]
    if unknown_kinds:
        raise BlueprintError(
            f"unknown roadmap kind {unknown_kinds[0]!r}; choose one of: {', '.join(valid_kinds)}"
        )
    stages = tuple(dict.fromkeys(stage or ()))
    for value in stages:
        if value < 1:
            raise BlueprintError("roadmap stage filters must be positive integers")
    return RoadmapFilters(
        statuses=statuses,
        stages=stages,
        kinds=kinds,
    )


def _validate_roadmap_filters(roadmap_stage_count: int, filters: RoadmapFilters) -> None:
    missing = [stage for stage in filters.stages if stage > roadmap_stage_count]
    if missing:
        requested = ", ".join(str(stage) for stage in missing)
        raise BlueprintError(
            f"roadmap has {roadmap_stage_count} stage(s); requested missing stage(s): {requested}"
        )


def _dedupe(values: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values or ()))


def _positive_or_none(value: int | None, *, label: str = "top_tasks") -> int | None:
    if value is None:
        return None
    if value < 1:
        raise BlueprintError(f"{label} must be at least 1")
    return value


def _percentage_or_none(
    value: int | float | None,
    *,
    label: str,
) -> int | float | None:
    if value is None:
        return None
    if not 0 <= value <= 100:
        raise BlueprintError(f"{label} must be between 0 and 100")
    return value


def _gate_fail_on(values: Sequence[str] | None) -> set[str]:
    selected = set(values or ())
    valid = {status.value for status in FormalStatus} | {"problem"}
    unknown = sorted(selected - valid)
    if unknown:
        raise BlueprintError(
            "unknown gate status "
            + ", ".join(repr(item) for item in unknown)
            + "; expected one of: "
            + ", ".join(sorted(valid))
        )
    if "problem" in selected:
        selected.remove("problem")
        selected.update(PROBLEM_FORMAL_STATUSES)
    return selected


def _project_file(project_dir: Path, value: str, *, label: str) -> Path:
    if not value.strip():
        raise BlueprintError(f"{label} must not be empty")
    root = project_dir.resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise BlueprintError(f"{label} must resolve within project root {root}") from None
    return candidate


def _json_resource(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2)


def _tool_decorator(
    server: Any,
    *,
    name: str,
    title: str | None,
    read_only: bool,
    idempotent: bool,
    destructive: bool,
    open_world: bool,
    max_result_bytes: int | None,
) -> Any:
    """Build a FastMCP tool decorator with portable annotations and size bounds."""

    kwargs: dict[str, object] = {"name": name}
    if title is not None:
        kwargs["title"] = title
    annotations = _tool_annotations(
        title=title,
        read_only=read_only,
        idempotent=idempotent,
        destructive=destructive,
        open_world=open_world,
    )
    if annotations is not None:
        kwargs["annotations"] = annotations
    decorator = _fastmcp_decorator(server.tool, kwargs)

    def decorate(function: Any) -> Any:
        function = _resolved_annotations(function)
        bounded = _bounded_callable(function, name=name, max_result_bytes=max_result_bytes)
        return decorator(bounded)

    return decorate


def _resource_decorator(
    server: Any,
    uri: str,
    *,
    title: str | None,
    priority: float,
    max_result_bytes: int | None,
) -> Any:
    """Build a FastMCP resource decorator with portable annotations and size bounds."""

    kwargs: dict[str, object] = {
        "name": _resource_name(uri),
        "mime_type": "application/json",
    }
    if title is not None:
        kwargs["title"] = title
    annotations = _resource_annotations(priority)
    if annotations is not None:
        kwargs["annotations"] = annotations
    decorator = _fastmcp_decorator(lambda **values: server.resource(uri, **values), kwargs)

    def decorate(function: Any) -> Any:
        function = _resolved_annotations(function)
        bounded = _bounded_callable(function, name=uri, max_result_bytes=max_result_bytes)
        return decorator(bounded)

    return decorate


def _fastmcp_decorator(factory: Any, kwargs: dict[str, object]) -> Any:
    """Call a FastMCP decorator factory across supported SDK minor versions."""

    candidates: list[dict[str, object]] = [kwargs]
    without_annotations = {key: value for key, value in kwargs.items() if key != "annotations"}
    if without_annotations != kwargs:
        candidates.append(without_annotations)
    minimal: dict[str, object] = {
        key: kwargs[key] for key in ("name", "mime_type") if key in kwargs
    }
    if minimal not in candidates:
        candidates.append(minimal)
    if "mime_type" in kwargs:
        candidates.append({"mime_type": kwargs["mime_type"]})
    candidates.append({})
    last_error: TypeError | None = None
    for candidate in candidates:
        try:
            return factory(**candidate)
        except TypeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("FastMCP did not provide a decorator factory")


def _tool_annotations(
    *,
    title: str | None,
    read_only: bool,
    idempotent: bool,
    destructive: bool,
    open_world: bool,
) -> Any | None:
    try:
        from mcp.types import ToolAnnotations
    except ImportError:
        return None
    for names in (
        {
            "title": title,
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": idempotent,
            "openWorldHint": open_world,
        },
        {
            "title": title,
            "read_only_hint": read_only,
            "destructive_hint": destructive,
            "idempotent_hint": idempotent,
            "open_world_hint": open_world,
        },
    ):
        try:
            return ToolAnnotations(**cast(dict[str, Any], names))
        except TypeError:
            continue
    return None


def _resource_annotations(priority: float) -> Any | None:
    try:
        from mcp.types import Annotations
    except ImportError:
        return None
    try:
        return Annotations(audience=["assistant"], priority=priority)
    except TypeError:
        return None


def _bounded_callable(function: Any, *, name: str, max_result_bytes: int | None) -> Any:
    if max_result_bytes is None:
        return function

    @wraps(function)
    def bounded(*args: Any, **kwargs: Any) -> Any:
        result = function(*args, **kwargs)
        return _enforce_result_size(result, name=name, max_result_bytes=max_result_bytes)

    return bounded


def _enforce_result_size(result: Any, *, name: str, max_result_bytes: int | None) -> Any:
    if max_result_bytes is None:
        return result
    if isinstance(result, str):
        size = len(result.encode("utf-8"))
    else:
        size = len(json.dumps(result, default=str, separators=(",", ":")).encode("utf-8"))
    if size > max_result_bytes:
        raise BlueprintError(
            f"MCP result for {name!r} is {size} bytes, exceeding max_result_bytes="
            f"{max_result_bytes}; request a narrower result or raise the server limit"
        )
    return result


def _resource_name(uri: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", uri).strip("-").lower() or "resource"


def _prompt_decorator(server: Any, *, name: str, title: str) -> Any:
    """Build a prompt decorator across FastMCP versions with and without titles."""

    factory = server.prompt
    try:
        factory_decorator = factory(name=name, title=title)
    except TypeError:
        factory_decorator = factory(name=name)

    def decorate(function: Any) -> Any:
        return factory_decorator(_resolved_annotations(function))

    return decorate


def _resolved_annotations(function: Any) -> Any:
    """Evaluate postponed annotations for FastMCP releases predating PEP 563 support."""

    try:
        hints = get_type_hints(function)
    except (NameError, TypeError, ValueError):
        return function
    function.__annotations__ = hints
    return function


def _mcp_sdk_version() -> str | None:
    try:
        return package_version("mcp")
    except PackageNotFoundError:
        return None


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _split_prompt_filter(value: str | None) -> list[str] | None:
    if value is None:
        return None
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None


def _register_completion(server: Any, catalog: _ProjectCatalog, snapshot_for: Any) -> None:
    """Register prompt/resource completions when the installed MCP SDK supports them."""

    completion_factory = getattr(server, "completion", None)
    if not callable(completion_factory):
        return
    try:
        decorator = completion_factory()
    except (AttributeError, TypeError):
        return

    @decorator
    async def complete(ref: Any, argument: Any, context: Any) -> Any:
        from mcp.types import Completion

        name = str(getattr(argument, "name", ""))
        partial = str(getattr(argument, "value", ""))
        context_arguments = getattr(context, "arguments", None) or {}
        values: list[str] = []
        if name == "project":
            catalog.refresh()
            for entry in catalog.projects:
                values.extend((entry.id, entry.name, entry.relative_path))
        elif name == "name" and "schemas" in str(getattr(ref, "uri", "")):
            values = list(available_schemas())
        elif name in {"node", "node_id"}:
            context_project = context_arguments.get("project")
            try:
                snapshot = snapshot_for(context_project)
            except BlueprintError:
                snapshot = None
            if snapshot is not None:
                values = [node.id for node in snapshot.project.nodes]
                if name == "node":
                    values.extend(task.id for task in snapshot.ready_tasks)
        prefix = partial.casefold()
        candidates = sorted({value for value in values if value.casefold().startswith(prefix)})
        limited = candidates[:100]
        try:
            return Completion(values=limited, total=len(candidates), hasMore=len(candidates) > 100)
        except TypeError:
            completion_type = cast(Any, Completion)
            return completion_type(
                values=limited,
                total=len(candidates),
                has_more=len(candidates) > 100,
            )


def _require_fastmcp() -> type[Any]:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "MCP support requires the optional dependency group. "
            "Install it with `pip install 'isabelle-blueprint[mcp]'`."
        ) from exc
    return cast(type[Any], FastMCP)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isabelle-blueprint-mcp",
        description="Serve an IsabelleBlueprint project over MCP.",
    )
    parser.add_argument("--project-dir", default=".", help="blueprint project directory")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to serve (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (streamable-http only)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (streamable-http only)")
    parser.add_argument("--path", default="/mcp", help="HTTP MCP path (default: /mcp)")
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="allow non-loopback HTTP binding; put authentication at a trusted proxy",
    )
    parser.add_argument(
        "--max-result-bytes",
        type=int,
        help="reject oversized tool/resource results at this UTF-8 byte limit",
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="register low-risk write tools for memory and assignments",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        server = build_server(
            Path(args.project_dir),
            allow_writes=args.allow_writes,
            host=args.host,
            port=args.port,
            path=args.path,
            transport=args.transport,
            allow_insecure_http=args.allow_insecure_http,
            max_result_bytes=args.max_result_bytes,
        )
    except (BlueprintError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
