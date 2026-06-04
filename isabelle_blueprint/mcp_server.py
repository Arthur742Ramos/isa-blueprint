"""Model Context Protocol server for IsabelleBlueprint projects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from isabelle_blueprint import __version__
from isabelle_blueprint.agents.assignments import (
    clear_assignment,
    load_assignments,
    set_assignment,
    write_assignments,
)
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
from isabelle_blueprint.graph.graphviz_render import render_dot, render_json, render_mermaid
from isabelle_blueprint.isabelle.suggestions import suggest_missing_facts
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.project_io import load_project, load_project_with_check
from isabelle_blueprint.refactor import rename_node
from isabelle_blueprint.report.lint import build_lint_report
from isabelle_blueprint.report.roadmap import (
    ROADMAP_STATUSES,
    RoadmapFilters,
    build_roadmap,
    roadmap_payload,
)
from isabelle_blueprint.report.status_overview import build_status_overview
from isabelle_blueprint.schemas import available_schemas, read_schema

GraphFormat = Literal["json", "dot", "mermaid"]


def build_server(
    project_dir: Path,
    *,
    allow_writes: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
) -> Any:
    """Build a FastMCP server bound to one or more IsabelleBlueprint projects."""

    FastMCP = _require_fastmcp()
    launch_root = Path(project_dir).resolve()
    catalog = _ProjectCatalog.discover(launch_root)
    http_path = path if path.startswith("/") else f"/{path}"
    write_lock = threading.Lock()
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

    @server.tool(name="version")
    def version() -> dict[str, object]:
        """Return MCP server and IsabelleBlueprint package metadata."""

        default_project = catalog.default_project
        return {
            "name": "isabelle-blueprint",
            "version": __version__,
            "project_dir": str(default_project.root if default_project is not None else launch_root),
            "workspace_dir": str(launch_root),
            "default_project": default_project.id if default_project is not None else None,
            "project_count": len(catalog.projects),
            "writes_enabled": allow_writes,
            "schemas": list(available_schemas()),
        }

    @server.tool(name="list_projects")
    def list_projects() -> dict[str, object]:
        """List IsabelleBlueprint projects discovered under the launch directory."""

        return catalog.to_dict()

    @server.tool(name="status")
    def status(
        top_tasks: int | None = None,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return the same project health payload as `isabelle-blueprint status --json`."""

        snapshot = _snapshot(catalog.resolve(project).root)
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
        if filters.active and not selected and snapshot.ready_tasks:
            payload["message"] = no_ready_task_message(len(snapshot.ready_tasks), filters)
        return payload

    @server.tool(name="roadmap")
    def roadmap(
        status: list[str] | None = None,
        stage: list[int] | None = None,
        kind: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return staged proof-work planning data."""

        snapshot = _snapshot(catalog.resolve(project).root)
        overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        filters = _roadmap_filters(status=status, stage=stage, kind=kind)
        _validate_roadmap_filters(overview.summary.stage_count, filters)
        return roadmap_payload(overview, filters=filters)

    @server.tool(name="list_tasks")
    def list_tasks(
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """List currently ready proof tasks, optionally filtered."""

        snapshot = _snapshot(catalog.resolve(project).root)
        filters = _ready_filters(
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )
        tasks = filter_ready_tasks(snapshot.ready_tasks, filters)
        payload: dict[str, object] = {
            "tasks": [task.to_dict() for task in tasks],
            "suggested_next_task": tasks[0].id if tasks else None,
        }
        if filters.active:
            payload.update(
                selection_metadata(
                    filters,
                    ready_task_count=len(snapshot.ready_tasks),
                    filtered_ready_task_count=len(tasks),
                )
            )
            if not tasks:
                payload["message"] = no_ready_task_message(len(snapshot.ready_tasks), filters)
        return payload

    @server.tool(name="next_task")
    def next_task(
        node: str | None = None,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return the selected ready task plus its rendered proof prompt."""

        return _next_task_payload(
            catalog.resolve(project).root,
            node=node,
            kind=kind,
            priority=priority,
            difficulty=difficulty,
            memory_state=memory_state,
            last_outcome=last_outcome,
            exclude_node=exclude_node,
        )

    @server.tool(name="agent_context")
    def agent_context(
        max_tasks: int = DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
        kind: list[str] | None = None,
        priority: list[str] | None = None,
        difficulty: list[str] | None = None,
        memory_state: list[str] | None = None,
        last_outcome: list[str] | None = None,
        exclude_node: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Return the compact handoff bundle for proof agents."""

        snapshot = _snapshot(catalog.resolve(project).root)
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
        return context.to_dict()

    @server.tool(name="explain_node")
    def explain_node(
        node_id: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Explain status, blockers, and next steps for one node or all nodes."""

        snapshot = _snapshot(catalog.resolve(project).root)
        explanations = explain_project(
            snapshot.project,
            node_id=node_id,
            fact_suggestions=snapshot.fact_suggestions,
        )
        return {"explanations": [item.to_dict() for item in explanations]}

    @server.tool(name="lint")
    def lint(project: str | None = None) -> dict[str, object]:
        """Run structural and quality lint checks without invoking Isabelle."""

        snapshot = _snapshot(catalog.resolve(project).root)
        return build_lint_report(snapshot.project).to_dict()

    @server.tool(name="graph")
    def graph(
        format: GraphFormat = "json",
        project: str | None = None,
    ) -> dict[str, object]:
        """Return the dependency graph as JSON, DOT, or Mermaid without writing files."""

        snapshot = _snapshot(catalog.resolve(project).root)
        if format == "json":
            return {"format": "json", "graph": json.loads(render_json(snapshot.project))}
        if format == "dot":
            return {"format": "dot", "graph": render_dot(snapshot.project)}
        if format == "mermaid":
            return {"format": "mermaid", "graph": render_mermaid(snapshot.project)}
        raise BlueprintError("graph format must be one of: json, dot, mermaid")

    @server.tool(name="schema")
    def schema(name: str | None = None) -> dict[str, object]:
        """List packaged schemas or return one schema by name."""

        if name is None:
            return {"schemas": list(available_schemas())}
        return {"name": name, "schema": json.loads(read_schema(name))}

    @server.tool(name="doctor")
    def doctor(
        isabelle: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:
        """Run local environment diagnostics."""

        return run_doctor(catalog.resolve(project).root, isabelle_executable=isabelle).to_dict()

    @server.tool(name="preview_rename_node")
    def preview_rename_node(
        old_id: str,
        new_id: str,
        project: str | None = None,
    ) -> dict[str, object]:
        """Preview a node rename without writing files."""

        config, _project = load_project(catalog.resolve(project).root)
        return rename_node(config, old_id, new_id, dry_run=True).to_dict()

    @server.resource("blueprint://projects", mime_type="application/json")
    def projects_resource() -> str:
        """Discovered IsabelleBlueprint project catalog."""

        return _json_resource(catalog.to_dict())

    @server.resource("blueprint://project", mime_type="application/json")
    def project_resource() -> str:
        """Parsed project graph as JSON."""

        return _json_resource(_snapshot(catalog.resolve(None).root).project.to_dict())

    @server.resource("blueprint://nodes/{node_id}", mime_type="application/json")
    def node_resource(node_id: str) -> str:
        """One blueprint node by id."""

        project = _snapshot(catalog.resolve(None).root).project
        node = project.by_id().get(node_id)
        if node is None:
            raise BlueprintError(f"unknown node id {node_id!r}")
        return _json_resource(node.to_dict())

    @server.resource("blueprint://tasks", mime_type="application/json")
    def tasks_resource() -> str:
        """Ready proof task catalog."""

        snapshot = _snapshot(catalog.resolve(None).root)
        return _json_resource(
            {
                "tasks": [task.to_dict() for task in snapshot.ready_tasks],
                "suggested_next_task": snapshot.ready_tasks[0].id if snapshot.ready_tasks else None,
            }
        )

    @server.resource("blueprint://roadmap", mime_type="application/json")
    def roadmap_resource() -> str:
        """Staged proof-work roadmap."""

        snapshot = _snapshot(catalog.resolve(None).root)
        return _json_resource(build_roadmap(snapshot.project, snapshot.ready_tasks).to_dict())

    @server.resource("blueprint://agent-context", mime_type="application/json")
    def agent_context_resource() -> str:
        """Default AI-agent handoff bundle."""

        snapshot = _snapshot(catalog.resolve(None).root)
        status_overview = build_status_overview(snapshot.project, snapshot.ready_tasks)
        roadmap_overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        context = build_agent_context(
            snapshot.config,
            status_overview,
            roadmap_overview,
            snapshot.ready_tasks,
        )
        return _json_resource(context.to_dict())

    @server.resource("blueprint://projects/{project}/project", mime_type="application/json")
    def project_scoped_project_resource(project: str) -> str:
        """Parsed project graph for a selected project id."""

        return _json_resource(_snapshot(catalog.resolve(project).root).project.to_dict())

    @server.resource("blueprint://projects/{project}/nodes/{node_id}", mime_type="application/json")
    def project_scoped_node_resource(project: str, node_id: str) -> str:
        """One blueprint node by id for a selected project id."""

        selected_project = _snapshot(catalog.resolve(project).root).project
        node = selected_project.by_id().get(node_id)
        if node is None:
            raise BlueprintError(f"unknown node id {node_id!r}")
        return _json_resource(node.to_dict())

    @server.resource("blueprint://projects/{project}/tasks", mime_type="application/json")
    def project_scoped_tasks_resource(project: str) -> str:
        """Ready proof task catalog for a selected project id."""

        snapshot = _snapshot(catalog.resolve(project).root)
        return _json_resource(
            {
                "tasks": [task.to_dict() for task in snapshot.ready_tasks],
                "suggested_next_task": snapshot.ready_tasks[0].id if snapshot.ready_tasks else None,
            }
        )

    @server.resource("blueprint://projects/{project}/roadmap", mime_type="application/json")
    def project_scoped_roadmap_resource(project: str) -> str:
        """Staged proof-work roadmap for a selected project id."""

        snapshot = _snapshot(catalog.resolve(project).root)
        return _json_resource(build_roadmap(snapshot.project, snapshot.ready_tasks).to_dict())

    @server.resource("blueprint://projects/{project}/agent-context", mime_type="application/json")
    def project_scoped_agent_context_resource(project: str) -> str:
        """Default AI-agent handoff bundle for a selected project id."""

        snapshot = _snapshot(catalog.resolve(project).root)
        status_overview = build_status_overview(snapshot.project, snapshot.ready_tasks)
        roadmap_overview = build_roadmap(snapshot.project, snapshot.ready_tasks)
        context = build_agent_context(
            snapshot.config,
            status_overview,
            roadmap_overview,
            snapshot.ready_tasks,
        )
        return _json_resource(context.to_dict())

    @server.resource("blueprint://schemas/{name}", mime_type="application/json")
    def schema_resource(name: str) -> str:
        """Packaged JSON Schema by short name."""

        return read_schema(name)

    @server.prompt(name="prove_task")
    def prove_task(
        node: str | None = None,
        project: str | None = None,
    ) -> str:
        """Return a proof-focused prompt for the suggested or selected ready task."""

        payload = _next_task_payload(catalog.resolve(project).root, node=node)
        prompt = payload.get("prompt")
        if isinstance(prompt, str):
            return prompt
        return str(payload.get("message") or "No ready task is currently available.")

    if allow_writes:
        _register_write_tools(server, catalog, write_lock)

    return server


def _register_write_tools(server: Any, catalog: _ProjectCatalog, write_lock: threading.Lock) -> None:
    @server.tool(name="record_attempt")
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
        with write_lock:
            snapshot = _snapshot(catalog.resolve(project).root)
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

    @server.tool(name="assign_node")
    def assign_node(
        node_id: str,
        owner: str | None = None,
        note: str = "",
        clear: bool = False,
        project: str | None = None,
    ) -> dict[str, object]:
        """Set or clear task ownership. Registered only with --allow-writes."""

        with write_lock:
            snapshot = _snapshot(catalog.resolve(project).root)
            if node_id not in snapshot.project.by_id():
                raise BlueprintError(f"unknown node id {node_id!r}")
            store = load_assignments(snapshot.config.assignments_path, strict=True)
            changed = False
            if clear:
                changed = clear_assignment(store, node_id)
            else:
                if not owner:
                    raise BlueprintError("owner is required unless clear=true")
                set_assignment(store, node_id, owner, note=note)
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
    ) -> None:
        self.launch_root = launch_root
        self.projects = projects
        self.default_project_id = default_project_id
        self._by_id = {project.id: project for project in projects}

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
        return cls(launch_root, entries, default_project_id)

    def resolve(self, selector: str | None) -> _ProjectEntry:
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
            dirname
            for dirname in dirnames
            if _should_descend_into(current / dirname)
        )
        if current == launch_root:
            continue
        if _filenames_have_project_marker(filenames):
            roots.append(current.resolve())
            dirnames[:] = []

    return sorted(dict.fromkeys(roots), key=lambda path: _relative_path_for_project(launch_root, path))


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


def _snapshot(project_dir: Path) -> _ProjectSnapshot:
    return _ProjectSnapshot(project_dir)


def _next_task_payload(
    project_root: Path,
    *,
    node: str | None = None,
    kind: list[str] | None = None,
    priority: list[str] | None = None,
    difficulty: list[str] | None = None,
    memory_state: list[str] | None = None,
    last_outcome: list[str] | None = None,
    exclude_node: list[str] | None = None,
) -> dict[str, object]:
    snapshot = _snapshot(project_root)
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
            **metadata,
        }
    return {
        "task": task.to_dict(),
        "prompt": render_task_prompt(task),
        "message": f"Selected {task.id}.",
        **metadata,
    }


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
            f"unknown roadmap kind {unknown_kinds[0]!r}; choose one of: "
            f"{', '.join(valid_kinds)}"
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


def _positive_or_none(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise BlueprintError("top_tasks must be at least 1")
    return value


def _json_resource(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2)


def _require_fastmcp() -> type[Any]:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "MCP support requires the optional dependency group. "
            "Install it with `pip install 'isabelle-blueprint[mcp]'`."
        ) from exc
    return FastMCP


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
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
