"""Command-line interface for IsabelleBlueprint."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

from isabelle_blueprint import __version__
from isabelle_blueprint.agents.context import (
    DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
    build_agent_context,
    render_agent_context,
    write_agent_context,
)
from isabelle_blueprint.agents.github_sync import sync_github_issues
from isabelle_blueprint.agents.memory import (
    VALID_OUTCOMES,
    load_agent_memory,
    node_input_hash,
    record_memory_attempt,
)
from isabelle_blueprint.agents.tasks import (
    AgentTask,
    generate_tasks,
    render_task_prompt,
    write_tasks,
)
from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.doctor import run_doctor
from isabelle_blueprint.errors import BlueprintError, ValidationError
from isabelle_blueprint.explain import explain_project, render_explanations
from isabelle_blueprint.graph.graphviz_render import write_graph_artifacts
from isabelle_blueprint.isabelle.checker import (
    CheckResult,
    apply_check_report,
    run_check,
    write_report,
)
from isabelle_blueprint.isabelle.compat import check_compatibility, write_compat_report
from isabelle_blueprint.isabelle.dump import (
    apply_dump_report,
    inspect_dump_dir,
    run_dump,
    write_dump_report,
)
from isabelle_blueprint.isabelle.suggestions import (
    suggest_missing_facts,
    write_fact_suggestions,
)
from isabelle_blueprint.isabelle.theory_import import import_theory_file, render_imported_blueprint
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.parser import parse_blueprint, parse_blueprint_file
from isabelle_blueprint.plugins import run_report_renderers, run_status_providers
from isabelle_blueprint.render.site import render_site
from isabelle_blueprint.report.badge import write_badge_endpoint, write_badge_svg
from isabelle_blueprint.report.github_actions import (
    build_summary_markdown,
    emit_step_outputs,
    emit_step_summary,
)
from isabelle_blueprint.report.json_report import write_project_report, write_summary_json
from isabelle_blueprint.report.markdown_report import write_markdown_report
from isabelle_blueprint.report.metrics import build_status_metrics, output_values
from isabelle_blueprint.report.pr_comment import (
    post_or_update_pr_comment,
    write_pr_comment_preview,
)
from isabelle_blueprint.report.roadmap import (
    ROADMAP_STATUSES,
    RoadmapFilters,
    build_roadmap,
    diff_roadmaps,
    load_roadmap_payload,
    render_roadmap,
    roadmap_payload,
    roadmap_strict_failures,
    write_roadmap,
)
from isabelle_blueprint.report.status_overview import build_status_overview, render_status_overview
from isabelle_blueprint.report.trends import append_trend_entry, load_trends
from isabelle_blueprint.schemas import available_schemas, read_schema, write_schemas
from isabelle_blueprint.templates import (
    TEMPLATES,
    blueprint_filename,
    render_template_blueprint,
    render_template_config,
)

if TYPE_CHECKING:
    from isabelle_blueprint.model.project import BlueprintProject


def _load(project_dir: Path) -> tuple[BlueprintConfig, BlueprintProject]:
    config = load_config(project_dir)
    paths = config.blueprint_paths
    missing = [p for p in paths if not p.exists()]
    if missing:
        if len(paths) == 1:
            raise BlueprintError(
                f"blueprint not found at {missing[0]}; run `isabelle-blueprint init` first"
            )
        formatted = ", ".join(str(p) for p in missing)
        raise BlueprintError(f"configured blueprints are missing: {formatted}")
    if len(paths) == 1:
        project = parse_blueprint_file(paths[0], project_name=config.project_name)
    else:
        project = parse_blueprint(paths, project_name=config.project_name)
    return config, project


def _try_apply_check(project: BlueprintProject, config: BlueprintConfig) -> None:
    """Apply a previously stored check report if available - non-fatal."""
    if not config.check_report_path.exists():
        return
    try:
        report_data = json.loads(config.check_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    result = CheckResult.from_dict(report_data)
    apply_check_report(project, result)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _dedupe(values: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values or []))


def _dedupe_int(values: list[int] | None) -> tuple[int, ...]:
    return tuple(dict.fromkeys(values or []))


def _roadmap_filters_from_args(args: argparse.Namespace) -> RoadmapFilters:
    return RoadmapFilters(
        statuses=_dedupe(getattr(args, "status", None)),
        stages=_dedupe_int(getattr(args, "stage", None)),
        kinds=_dedupe(getattr(args, "kind", None)),
    )


def _validate_roadmap_filters(roadmap_stage_count: int, filters: RoadmapFilters) -> None:
    if not filters.stages:
        return
    missing = [stage for stage in filters.stages if stage > roadmap_stage_count]
    if missing:
        requested = ", ".join(str(stage) for stage in missing)
        raise BlueprintError(
            f"roadmap has {roadmap_stage_count} stage(s); requested missing stage(s): {requested}"
        )


def cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    template = TEMPLATES[args.template]
    project_dir.mkdir(parents=True, exist_ok=True)
    blueprint_path = project_dir / blueprint_filename(args.format)
    config_path = project_dir / "isabelle-blueprint.toml"
    if blueprint_path.exists() and not args.force:
        print(f"refusing to overwrite {blueprint_path}; pass --force to replace", file=sys.stderr)
        return 1
    blueprint_path.write_text(render_template_blueprint(template, format=args.format), encoding="utf-8")
    if not config_path.exists() or args.force:
        config_path.write_text(render_template_config(template, format=args.format), encoding="utf-8")
    workflows = project_dir / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    workflow_file = workflows / "blueprint.yml"
    if not workflow_file.exists() or args.force:
        workflow_file.write_text(template.workflow, encoding="utf-8")
    print(f"initialised {args.template} IsabelleBlueprint project at {project_dir}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from isabelle_blueprint.scaffold import render_latex_node_stub, render_node_stub

    fact = "" if args.no_fact else args.fact
    path: Path | None = None
    format = args.format or "markdown"

    if args.append:
        project_dir = Path(args.project_dir).resolve()
        config = load_config(project_dir)
        paths = config.blueprint_paths
        target = getattr(args, "blueprint", None)
        if target is not None:
            resolved = (project_dir / target).resolve()
            if resolved not in [p.resolve() for p in paths]:
                raise BlueprintError(
                    f"--blueprint {target!r} is not one of the configured "
                    f"blueprints: {', '.join(str(p) for p in paths)}"
                )
            path = resolved
        elif len(paths) > 1:
            formatted = ", ".join(str(p) for p in paths)
            raise BlueprintError(
                "project has multiple blueprints; pass --blueprint <path> to "
                f"choose one of: {formatted}"
            )
        else:
            path = paths[0]
        if not path.exists():
            raise BlueprintError(
                f"blueprint not found at {path}; run `isabelle-blueprint init` first"
            )
        target_format = _blueprint_format(path)
        if args.format is not None and args.format != target_format:
            raise BlueprintError(
                f"--format {args.format!r} does not match target blueprint {path.name!r} "
                f"(expected {target_format!r})"
            )
        format = target_format

    renderer = render_latex_node_stub if format == "latex" else render_node_stub
    stub = renderer(
        args.kind,
        args.id,
        title=args.title,
        fact=fact,
        uses=args.uses or [],
        status=args.status,
    )

    if path is not None:
        existing = path.read_text(encoding="utf-8")
        path.write_text(_append_stub(existing, stub, format=format), encoding="utf-8")
        print(f"appended {args.kind} {args.id!r} to {path}")
    else:
        sys.stdout.write(stub)
    return 0


def _blueprint_format(path: Path) -> str:
    return "latex" if path.suffix.lower() == ".tex" else "markdown"


def _append_stub(existing: str, stub: str, *, format: str) -> str:
    if format == "latex":
        marker = r"\end{document}"
        marker_at = existing.rfind(marker)
        if marker_at != -1:
            before = existing[:marker_at].rstrip()
            after = existing[marker_at:].lstrip()
            return f"{before}\n\n{stub.rstrip()}\n\n{after}"
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + separator + stub


def cmd_check(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    try:
        project.validate().raise_if_failed()
    except ValidationError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2

    result = run_check(
        project,
        build_dir=config.build_dir,
        session_name=config.isabelle_session,
        isabelle_executable=args.isabelle or config.isabelle_executable,
        extra_dirs=config.isabelle_dirs,
        project_root=config.project_root,
        timeout=args.timeout if args.timeout is not None else config.isabelle_timeout,
        incremental=bool(getattr(args, "incremental", False)),
        cache_path=config.check_cache_path if getattr(args, "incremental", False) else None,
        jobs=getattr(args, "jobs", None),
    )
    write_report(result, config.check_report_path)
    apply_check_report(project, result)
    write_project_report(project, config.project_json_path)

    print(f"check report -> {config.check_report_path}")
    if not result.isabelle_available:
        print("note: Isabelle binary not found; per-fact existence not verified", file=sys.stderr)
        if args.strict:
            return 3
    elif not result.ran:
        print(f"note: {result.error}", file=sys.stderr)
        if args.strict:
            return 3
    elif result.return_code != 0:
        print(f"isabelle build failed with exit code {result.return_code}", file=sys.stderr)
        return 4
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    written = write_graph_artifacts(project, config.build_dir)
    for name, path in written.items():
        print(f"{name} -> {path}")
    if "svg" not in written:
        print("note: graphviz `dot` not found; install it for SVG output", file=sys.stderr)
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    try:
        project.validate().raise_if_failed()
    except ValidationError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 2

    if args.from_dir:
        result = inspect_dump_dir(project, Path(args.from_dir))
    else:
        result = run_dump(
            project,
            output_dir=config.build_dir / "pide-dump",
            session_name=config.isabelle_session,
            isabelle_executable=args.isabelle or config.isabelle_executable,
            extra_dirs=config.isabelle_dirs,
            project_root=config.project_root,
            timeout=args.timeout if args.timeout is not None else config.isabelle_timeout,
        )
    write_dump_report(result, config.dump_report_path)
    apply_dump_report(project, result)
    write_project_report(project, config.project_json_path)
    print(f"dump report -> {config.dump_report_path}")
    if result.error:
        print(f"note: {result.error}", file=sys.stderr)
        return 3 if args.strict else 0
    return 0


def cmd_compat(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config = load_config(project_dir)
    report = check_compatibility(config, isabelle_executable=args.isabelle or config.isabelle_executable)
    write_compat_report(report, config.compat_report_path)
    print(f"compat report -> {config.compat_report_path}")
    for issue in report.issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(f"{issue.severity}: {issue.code}: {issue.message}", file=stream)
    return 0 if report.ok or not args.strict else 5


def cmd_web(args: argparse.Namespace) -> int:
    if args.watch or args.serve:
        return _watch_web(args)
    project_dir = Path(args.project_dir).resolve()
    index = _render_web_once(project_dir)
    print(f"site -> {index}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    args.watch = True
    args.serve = True
    return _watch_web(args)


def cmd_tasks(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    written = write_tasks(
        project,
        config.build_dir,
        fact_suggestions=fact_suggestions,
        memory=memory,
        github_issues=args.github_issues,
        github_issues_name=args.github_issues_file,
    )
    if args.github_sync:
        from isabelle_blueprint.agents.tasks import generate_tasks, github_issue_drafts

        tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
        drafts = github_issue_drafts(tasks)
        actions = sync_github_issues(
            drafts,
            repo=args.repo or os.environ.get("GITHUB_REPOSITORY"),
            state_path=Path(args.github_sync_state).resolve()
            if args.github_sync_state
            else config.github_sync_state_path,
            token_env=args.token_env,
            confirm=args.github_sync_confirm,
        )
        sync_path = config.build_dir / "github-sync-plan.json"
        sync_path.write_text(
            json.dumps({"actions": [action.to_dict() for action in actions]}, indent=2),
            encoding="utf-8",
        )
        written["github_sync"] = sync_path
    for name, path in written.items():
        print(f"{name} -> {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    json_path = write_project_report(project, config.project_json_path)
    md_path = write_markdown_report(project, config.build_dir / "report.md")
    summary_path = write_summary_json(project, config.build_dir / "summary.json")
    badge_json_path = write_badge_endpoint(project, config.build_dir / "badge.json")
    badge_svg_path = write_badge_svg(project, config.build_dir / "badge.svg")
    trend_entry = append_trend_entry(project, config.trends_path)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    if fact_suggestions:
        suggestions_path = write_fact_suggestions(fact_suggestions, config.build_dir / "fact-suggestions.json")
        print(f"fact suggestions -> {suggestions_path}")
    plugin_annotations = run_status_providers(project)
    if plugin_annotations:
        plugin_path = config.build_dir / "plugin-annotations.json"
        plugin_path.write_text(json.dumps({"annotations": plugin_annotations}, indent=2), encoding="utf-8")
        print(f"plugin annotations -> {plugin_path}")
    for artifact in run_report_renderers(project, config.build_dir):
        if "path" in artifact:
            print(f"plugin renderer {artifact['plugin']} -> {artifact['path']}")
        else:
            print(f"plugin renderer {artifact.get('plugin', 'unknown')} -> {artifact}")
    print(f"project json -> {json_path}")
    print(f"markdown report -> {md_path}")
    print(f"summary -> {summary_path}")
    print(f"badge json -> {badge_json_path}")
    print(f"badge svg -> {badge_svg_path}")
    print(f"trends -> {config.trends_path} (entry @ {trend_entry['timestamp']})")

    # Compute metrics once and reuse for both the GH outputs and the step
    # summary so the two surfaces can never drift apart.
    metrics = build_status_metrics(project)
    outputs = output_values(metrics)
    if emit_step_outputs(outputs):
        print("github outputs -> $GITHUB_OUTPUT")
    summary_md = build_summary_markdown(project.name, metrics.to_dict())
    if emit_step_summary(summary_md):
        print("github summary -> $GITHUB_STEP_SUMMARY")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    overview = build_status_overview(project, ready_tasks)
    if args.json:
        print(json.dumps(overview.to_dict(), indent=2))
    else:
        print(render_status_overview(overview), end="")
    return 0


def cmd_roadmap(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    roadmap = build_roadmap(project, ready_tasks)
    filters = _roadmap_filters_from_args(args)
    _validate_roadmap_filters(roadmap.summary.stage_count, filters)
    diff = (
        diff_roadmaps(load_roadmap_payload(Path(args.since).resolve()), roadmap)
        if args.since
        else None
    )
    written: dict[str, Path] = {}
    if args.write:
        output_dir = Path(args.out).resolve() if args.out else config.build_dir
        written = write_roadmap(roadmap, output_dir)
    if args.json:
        print(json.dumps(roadmap_payload(roadmap, filters=filters, diff=diff), indent=2))
        stream = sys.stderr
    else:
        print(render_roadmap(roadmap, filters=filters, diff=diff), end="")
        stream = sys.stdout
    for name, path in written.items():
        print(f"roadmap {name} -> {path}", file=stream)
    failures = roadmap_strict_failures(roadmap) if args.strict else []
    for failure in failures:
        print(f"roadmap strict: {failure}", file=sys.stderr)
    return 9 if failures else 0


def cmd_agent_context(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    status = build_status_overview(project, ready_tasks)
    roadmap = build_roadmap(project, ready_tasks)
    context = build_agent_context(
        config,
        status,
        roadmap,
        ready_tasks,
        max_tasks=args.max_tasks,
    )
    written: dict[str, Path] = {}
    if args.write:
        project_path = write_project_report(project, config.project_json_path)
        written["project json"] = project_path
        for name, path in write_tasks(
            project,
            config.build_dir,
            fact_suggestions=fact_suggestions,
            memory=memory,
        ).items():
            written[f"tasks {name}"] = path
        for name, path in write_roadmap(roadmap, config.build_dir).items():
            written[f"roadmap {name}"] = path
        for name, path in write_agent_context(context, config.build_dir).items():
            written[f"agent-context {name}"] = path
    if args.json:
        print(json.dumps(context.to_dict(), indent=2))
        stream = sys.stderr
    else:
        print(render_agent_context(context), end="")
        stream = sys.stdout
    for name, path in written.items():
        print(f"{name} -> {path}", file=stream)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    task = _select_ready_task(ready_tasks, args.node, project)
    if task is None:
        message = "No ready tasks are currently available."
        if args.json:
            print(
                json.dumps(
                    {
                        "task": None,
                        "prompt": None,
                        "prompt_path": None,
                        "message": message,
                    },
                    indent=2,
                )
            )
        else:
            print(message)
        return 0

    prompt = render_task_prompt(task)
    prompt_path = _write_next_prompt(prompt, args.output)
    if args.json:
        print(
            json.dumps(
                {
                    "task": task.to_dict(),
                    "prompt": prompt,
                    "prompt_path": str(prompt_path) if prompt_path is not None else None,
                    "message": f"Selected {task.id}.",
                },
                indent=2,
            )
        )
    else:
        print(prompt, end="")
        if prompt_path is not None:
            print(f"next prompt -> {prompt_path}", file=sys.stderr)
    return 0


def _write_next_prompt(prompt: str, output: str | None) -> Path | None:
    if output is None:
        return None
    path = Path(output).resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")
    except OSError as exc:
        raise BlueprintError(f"could not write next prompt to {path}: {exc}") from exc
    return path


def _select_ready_task(
    ready_tasks: list[AgentTask],
    selector: str | None,
    project: BlueprintProject,
) -> AgentTask | None:
    if selector is None:
        # Keep `next`, `roadmap`, and `agent-context` aligned on the same ordering.
        return ready_tasks[0] if ready_tasks else None

    for task in ready_tasks:
        if task.id == selector:
            return task
    for task in ready_tasks:
        if task.node_id == selector:
            return task

    by_id = project.by_id()
    candidate_node_id = selector.removeprefix("task-") if selector.startswith("task-") else selector
    if selector in by_id:
        node = by_id[selector]
        raise BlueprintError(
            f"node {selector!r} is not currently ready for a task "
            f"(formal status: {node.status.formal.value})"
        )
    if candidate_node_id in by_id:
        node = by_id[candidate_node_id]
        raise BlueprintError(
            f"node {candidate_node_id!r} is not currently ready for a task "
            f"(formal status: {node.status.formal.value})"
        )
    raise BlueprintError(f"unknown ready task or node {selector!r}")


def cmd_comment(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    if args.preview:
        preview_path = write_pr_comment_preview(project, config.build_dir / "pr-comment.md")
        print(f"pr comment preview -> {preview_path}")
        return 0
    result = post_or_update_pr_comment(project)
    if result.status == "skipped":
        print(f"pr comment skipped: {result.reason}")
        return 0 if not args.strict else 6
    if result.url:
        print(f"pr comment {result.status} -> {result.url}")
    else:
        print(f"pr comment {result.status}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        Path(args.project_dir),
        isabelle_executable=args.isabelle,
    )
    if args.json:
        output = report.to_json()
        if args.output:
            path = Path(args.output).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output, encoding="utf-8")
            print(f"doctor json -> {path}")
        else:
            print(output)
    else:
        for check in report.checks:
            print(f"[{check.status}] {check.name}: {check.message}")
    return 7 if args.strict and report.has_errors else 0


def cmd_schema(args: argparse.Namespace) -> int:
    if args.out:
        names = [args.name] if args.name else None
        written = write_schemas(Path(args.out).resolve(), names=names)
        for name, path in written.items():
            print(f"{name} -> {path}")
        return 0
    if args.name:
        print(read_schema(args.name))
        return 0
    for name in available_schemas():
        print(name)
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    memory_path = Path(args.memory_file).resolve() if args.memory_file else config.agent_memory_path
    by_id = project.by_id()
    if args.record:
        if not args.node:
            raise BlueprintError("--node is required when recording memory")
        node = by_id.get(args.node)
        if node is None:
            raise BlueprintError(f"unknown node id {args.node!r}")
        attempt = record_memory_attempt(
            memory_path,
            args.node,
            outcome=args.outcome,
            summary=args.summary,
            actor=args.actor,
            tool=args.tool,
            details=args.details or "",
            next_step=args.next_step,
            input_hash=node_input_hash(node),
            max_attempts=args.max_attempts,
        )
        print(f"memory recorded -> {memory_path} ({args.node} @ {attempt.timestamp})")
        return 0

    memory = load_agent_memory(memory_path, strict=True)
    selected = [args.node] if args.node else sorted(memory.nodes)
    rows = []
    for node_id in selected:
        attempts = memory.nodes.get(node_id)
        if attempts is None:
            continue
        for attempt in attempts.attempts:
            rows.append({"node_id": node_id, **attempt.to_dict()})
    if args.json:
        print(json.dumps({"memory_file": str(memory_path), "attempts": rows}, indent=2))
    elif not rows:
        print("No agent memory recorded yet.")
    else:
        for row in rows:
            print(
                f"{row['node_id']} {row['timestamp']} {row['outcome']}: "
                f"{row['summary']}"
            )
            if row.get("next_step"):
                print(f"  next: {row['next_step']}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    explanations = explain_project(project, node_id=args.node, fact_suggestions=fact_suggestions)
    if args.json:
        print(json.dumps({"explanations": [item.to_dict() for item in explanations]}, indent=2))
    else:
        print(render_explanations(explanations), end="")
    return 0


def cmd_import_theory(args: argparse.Namespace) -> int:
    facts = []
    for theory_path in args.theory:
        facts.extend(import_theory_file(Path(theory_path).resolve()))
    blueprint = render_imported_blueprint(facts, project_name=args.project_name)
    if args.output:
        output = Path(args.output).resolve()
        if output.exists() and not args.force:
            raise BlueprintError(f"refusing to overwrite {output}; pass --force")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(blueprint, encoding="utf-8")
        print(f"imported {len(facts)} declaration(s) -> {output}")
    else:
        sys.stdout.write(blueprint)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="isabelle-blueprint", description="Isabelle-aware blueprint tooling.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a fresh blueprint project")
    p_init.add_argument("project_dir", nargs="?", default=".", help="target directory (default: cwd)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.add_argument(
        "--format",
        choices=("markdown", "latex"),
        default="markdown",
        help="blueprint authoring format to scaffold (default: markdown)",
    )
    p_init.add_argument(
        "--template",
        choices=sorted(TEMPLATES),
        default="minimal",
        help="starter template to write (default: minimal)",
    )
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="validate blueprint and run Isabelle existence check")
    p_check.add_argument("project_dir", nargs="?", default=".")
    p_check.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_check.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="max seconds to wait for `isabelle build` before aborting (overrides [isabelle].timeout)",
    )
    p_check.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if Isabelle is unavailable or the build did not run",
    )
    p_check.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "skip facts whose blueprint inputs and context match a previously-proved "
            "cache entry (cache file: build/check-cache.json)"
        ),
    )
    p_check.add_argument(
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="forward `-j N` to `isabelle build` to parallelise upstream session builds",
    )
    p_check.set_defaults(func=cmd_check)

    p_graph = sub.add_parser("graph", help="emit DOT/JSON/SVG dependency graph")
    p_graph.add_argument("project_dir", nargs="?", default=".")
    p_graph.set_defaults(func=cmd_graph)

    p_dump = sub.add_parser("dump", help="run or inspect Isabelle PIDE dump output")
    p_dump.add_argument("project_dir", nargs="?", default=".")
    p_dump.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_dump.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="max seconds to wait for `isabelle dump` before aborting (overrides [isabelle].timeout)",
    )
    p_dump.add_argument("--from", dest="from_dir", default=None, help="inspect an existing dump directory")
    p_dump.add_argument("--strict", action="store_true", help="exit non-zero if dump execution/inspection fails")
    p_dump.set_defaults(func=cmd_dump)

    p_compat = sub.add_parser("compat", help="check Isabelle/AFP version pins and session visibility")
    p_compat.add_argument("project_dir", nargs="?", default=".")
    p_compat.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_compat.add_argument("--strict", action="store_true", help="exit non-zero on compatibility errors")
    p_compat.set_defaults(func=cmd_compat)

    p_web = sub.add_parser("web", help="render the static HTML site")
    p_web.add_argument("project_dir", nargs="?", default=".")
    p_web.add_argument("--watch", action="store_true", help="re-render when blueprint inputs change")
    p_web.add_argument("--serve", action="store_true", help="serve the rendered site while watching")
    p_web.add_argument("--host", default="127.0.0.1", help="host for --serve (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="port for --serve (default: 8000)")
    p_web.add_argument("--interval", type=float, default=1.0, help="watch polling interval in seconds")
    p_web.add_argument("--allow-ci", action="store_true", help="allow --serve when CI=true")
    p_web.set_defaults(func=cmd_web)

    p_serve = sub.add_parser("serve", help="serve and live-rebuild the static HTML site")
    p_serve.add_argument("project_dir", nargs="?", default=".")
    p_serve.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="port to bind (default: 8000)")
    p_serve.add_argument("--interval", type=float, default=1.0, help="watch polling interval in seconds")
    p_serve.add_argument("--allow-ci", action="store_true", help="allow serving when CI=true")
    p_serve.set_defaults(func=cmd_serve)

    p_tasks = sub.add_parser("tasks", help="generate agent-ready tasks and per-task prompts")
    p_tasks.add_argument("project_dir", nargs="?", default=".")
    p_tasks.add_argument(
        "--github-issues",
        action="store_true",
        help="also write build/github-issues.json with issue drafts; does not call GitHub",
    )
    p_tasks.add_argument(
        "--github-issues-file",
        default="github-issues.json",
        help="filename under build_dir for --github-issues output",
    )
    p_tasks.add_argument(
        "--github-sync",
        action="store_true",
        help="write a GitHub issue sync plan; dry-run unless --github-sync-confirm is passed",
    )
    p_tasks.add_argument(
        "--github-sync-confirm",
        action="store_true",
        help="actually create/update GitHub issues for --github-sync",
    )
    p_tasks.add_argument("--repo", default=None, help="GitHub repo for sync, e.g. owner/repo")
    p_tasks.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable containing the GitHub token for confirmed sync",
    )
    p_tasks.add_argument(
        "--github-sync-state",
        default=None,
        help="path to persistent node-to-issue mapping (default: .isabelle-blueprint/github-sync.json)",
    )
    p_tasks.set_defaults(func=cmd_tasks)

    p_next = sub.add_parser("next", help="print the next ready task prompt")
    p_next.add_argument("project_dir", nargs="?", default=".")
    p_next.add_argument(
        "--node",
        default=None,
        metavar="NODE_OR_TASK",
        help="print the ready prompt for this node id or task id instead of the suggested next task",
    )
    p_next.add_argument("--json", action="store_true", help="emit task metadata and prompt JSON")
    p_next.add_argument("--output", default=None, metavar="PATH", help="also write the selected prompt to PATH")
    p_next.set_defaults(func=cmd_next)

    p_report = sub.add_parser("report", help="write JSON and Markdown status reports")
    p_report.add_argument("project_dir", nargs="?", default=".")
    p_report.set_defaults(func=cmd_report)

    p_status = sub.add_parser("status", help="print a concise project health summary")
    p_status.add_argument("project_dir", nargs="?", default=".")
    p_status.add_argument("--json", action="store_true", help="emit machine-readable status JSON")
    p_status.set_defaults(func=cmd_status)

    p_roadmap = sub.add_parser("roadmap", help="plan proof-work stages and suggested path")
    p_roadmap.add_argument("project_dir", nargs="?", default=".")
    p_roadmap.add_argument("--json", action="store_true", help="emit machine-readable roadmap JSON")
    p_roadmap.add_argument(
        "--strict",
        action="store_true",
        help="exit 9 when cycles, problem nodes, stale nodes, or missing dependencies exist",
    )
    p_roadmap.add_argument(
        "--status",
        action="append",
        choices=ROADMAP_STATUSES,
        help="show only roadmap items with this status; repeat to include more statuses",
    )
    p_roadmap.add_argument(
        "--stage",
        action="append",
        type=_positive_int,
        help="show only this topological stage; repeat to include more stages",
    )
    p_roadmap.add_argument(
        "--kind",
        action="append",
        choices=tuple(kind.value for kind in NodeKind),
        help="show only roadmap items of this node kind; repeat to include more kinds",
    )
    p_roadmap.add_argument(
        "--since",
        default=None,
        help="compare against a previous roadmap JSON file or directory containing roadmap.json",
    )
    p_roadmap.add_argument(
        "--write",
        action="store_true",
        help="write build/roadmap.json and build/roadmap.md artifacts",
    )
    p_roadmap.add_argument(
        "--out",
        default=None,
        help="directory for --write artifacts (default: configured build_dir)",
    )
    p_roadmap.set_defaults(func=cmd_roadmap)

    p_agent_context = sub.add_parser(
        "agent-context",
        help="emit an AI-agent handoff bundle with status, roadmap, tasks, and commands",
    )
    p_agent_context.add_argument("project_dir", nargs="?", default=".")
    p_agent_context.add_argument("--json", action="store_true", help="emit machine-readable context JSON")
    p_agent_context.add_argument(
        "--write",
        action="store_true",
        help="write build/agent-context.*, tasks, prompts, roadmap, and project JSON artifacts",
    )
    p_agent_context.add_argument(
        "--max-tasks",
        type=_positive_int,
        default=DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
        help=f"maximum ready tasks to embed in the context (default: {DEFAULT_AGENT_CONTEXT_TASK_LIMIT})",
    )
    p_agent_context.set_defaults(func=cmd_agent_context)

    p_comment = sub.add_parser(
        "comment",
        help="post or update a GitHub PR status comment (or preview the body locally)",
    )
    p_comment.add_argument("project_dir", nargs="?", default=".")
    p_comment.add_argument(
        "--preview",
        action="store_true",
        help="write the comment body to build/pr-comment.md instead of posting",
    )
    p_comment.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when the PR context (token, repo, PR number) cannot be resolved",
    )
    p_comment.set_defaults(func=cmd_comment)

    p_doctor = sub.add_parser("doctor", help="diagnose local IsabelleBlueprint setup")
    p_doctor.add_argument("project_dir", nargs="?", default=".")
    p_doctor.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_doctor.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    p_doctor.add_argument("--output", default=None, help="write --json output to a file")
    p_doctor.add_argument("--strict", action="store_true", help="exit non-zero when an error is found")
    p_doctor.set_defaults(func=cmd_doctor)

    p_schema = sub.add_parser("schema", help="print or export packaged JSON Schemas")
    p_schema.add_argument("name", nargs="?", choices=available_schemas())
    p_schema.add_argument("--out", default=None, help="write selected/all schemas to a directory")
    p_schema.set_defaults(func=cmd_schema)

    p_memory = sub.add_parser("memory", help="record or list per-node proof attempt memory")
    p_memory.add_argument("project_dir", nargs="?", default=".")
    p_memory.add_argument("--node", default=None, help="node id to record/list")
    p_memory.add_argument("--memory-file", default=None, help="override agent memory JSON path")
    p_memory.add_argument("--record", action="store_true", help="record a new memory attempt")
    p_memory.add_argument("--outcome", choices=sorted(VALID_OUTCOMES), default="note")
    p_memory.add_argument("--summary", default="", help="short attempt summary (required with --record)")
    p_memory.add_argument("--details", default="", help="longer notes for the attempt")
    p_memory.add_argument("--next-step", default=None, help="recommended next action")
    p_memory.add_argument("--actor", default=None, help="person or agent that made the attempt")
    p_memory.add_argument("--tool", default=None, help="tool/model used for the attempt")
    p_memory.add_argument("--max-attempts", type=int, default=20, help="attempts to keep per node")
    p_memory.add_argument("--json", action="store_true", help="list memory as JSON")
    p_memory.set_defaults(func=cmd_memory)

    p_explain = sub.add_parser("explain", help="explain status and dependency problems for blueprint nodes")
    p_explain.add_argument("project_dir", nargs="?", default=".")
    p_explain.add_argument("--node", default=None, help="only explain one node id")
    p_explain.add_argument("--json", action="store_true", help="emit machine-readable explanations")
    p_explain.set_defaults(func=cmd_explain)

    p_import = sub.add_parser("import-theory", help="bootstrap a blueprint from Isabelle .thy declarations")
    p_import.add_argument("theory", nargs="+", help="Isabelle theory file(s) to scan")
    p_import.add_argument("--project-name", default=None, help="title for the generated blueprint")
    p_import.add_argument("--output", default=None, help="write generated blueprint to this file")
    p_import.add_argument("--force", action="store_true", help="overwrite --output if it exists")
    p_import.set_defaults(func=cmd_import_theory)

    p_new = sub.add_parser("new", help="print (or append) a ready-to-edit node stub")
    p_new.add_argument("kind", help="node kind, e.g. definition, lemma, theorem")
    p_new.add_argument("id", help="node id, e.g. add-zero-right or thm:pythagoras")
    p_new.add_argument("project_dir", nargs="?", default=".", help="project dir (used with --append)")
    p_new.add_argument("--title", default=None, help="explicit title (default: humanised from id)")
    p_new.add_argument("--fact", default=None, help="Isabelle fact name (default: suggested from id)")
    p_new.add_argument("--no-fact", action="store_true", help="omit the isabelle: line entirely")
    p_new.add_argument("--uses", nargs="*", default=None, metavar="ID", help="dependency node ids")
    p_new.add_argument("--status", default="stub", help="initial blueprint status (default: stub)")
    p_new.add_argument(
        "--format",
        choices=("markdown", "latex"),
        default=None,
        help="stub format (default: target suffix with --append, otherwise markdown)",
    )
    p_new.add_argument(
        "--append",
        action="store_true",
        help="append the stub to the project blueprint instead of printing to stdout",
    )
    p_new.add_argument(
        "--blueprint",
        default=None,
        help="target blueprint file (required with --append when the project has multiple blueprints)",
    )
    p_new.set_defaults(func=cmd_new)

    return parser


def _render_web_once(project_dir: Path) -> Path:
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    trends = load_trends(config.trends_path)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    return render_site(
        project,
        config.site_dir,
        trends=trends,
        fact_suggestions=fact_suggestions,
        memory=memory,
    )


def _watch_web(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    if args.serve and os.environ.get("CI", "").lower() == "true" and not args.allow_ci:
        print("refusing to serve in CI; pass --allow-ci to override", file=sys.stderr)
        return 8
    index = _render_web_once(project_dir)
    print(f"site -> {index}")
    server = _start_site_server(index.parent, args.host, args.port) if args.serve else None
    if server is not None:
        print(f"serving -> http://{args.host}:{args.port}/")
    snapshot = _snapshot(_watch_paths(project_dir))
    try:
        while True:
            time.sleep(max(args.interval, 0.1))
            paths = _watch_paths(project_dir)
            current = _snapshot(paths)
            if current != snapshot:
                index = _render_web_once(project_dir)
                print(f"updated -> {index}")
                snapshot = current
    except KeyboardInterrupt:
        print("stopped")
        return 0
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


def _start_site_server(site_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    import threading

    thread = threading.Thread(target=server.serve_forever, name="isabelle-blueprint-serve", daemon=True)
    thread.start()
    return server


def _watch_paths(project_dir: Path) -> list[Path]:
    paths = [project_dir / "isabelle-blueprint.toml"]
    try:
        config = load_config(project_dir)
    except (OSError, ValueError):
        return paths
    paths.extend(config.blueprint_paths)
    paths.extend(
        [
            config.check_report_path,
            config.dump_report_path,
            config.trends_path,
            config.project_json_path,
        ]
    )
    return paths


def _snapshot(paths: list[Path]) -> dict[str, int | None]:
    snapshot: dict[str, int | None] = {}
    for path in paths:
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except OSError:
            snapshot[str(path)] = None
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BlueprintError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
