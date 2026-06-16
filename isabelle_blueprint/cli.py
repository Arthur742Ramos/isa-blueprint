"""Command-line interface for IsabelleBlueprint."""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

from isabelle_blueprint import __version__, console
from isabelle_blueprint.agents.assignments import (
    clear_assignment,
    load_assignments,
    set_assignment,
    write_assignments,
)
from isabelle_blueprint.agents.blame import (
    blame_payload,
    build_blame,
    render_blame,
    render_blame_markdown,
    render_blame_table,
)
from isabelle_blueprint.agents.context import (
    DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
    build_agent_context,
    render_agent_context,
    write_agent_context,
)
from isabelle_blueprint.agents.github_sync import pull_github_issue_states, sync_github_issues
from isabelle_blueprint.agents.memory import (
    VALID_OUTCOMES,
    load_agent_memory,
    node_input_hash,
    record_memory_attempt,
)
from isabelle_blueprint.agents.runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    AgentRunResult,
    classify_run_outcome,
    default_run_summary,
    execute_agent_command,
    prompt_filename,
    safe_prompt_filename,
    split_command_string,
    substitute_command,
    tail,
    validate_command_tokens,
)
from isabelle_blueprint.agents.selection import (
    READY_TASK_DIFFICULTIES,
    READY_TASK_LAST_OUTCOMES,
    READY_TASK_MEMORY_STATES,
    READY_TASK_PRIORITIES,
)
from isabelle_blueprint.agents.selection import (
    filter_ready_tasks as _filter_ready_tasks,
)
from isabelle_blueprint.agents.selection import (
    no_ready_task_message as _no_ready_task_message,
)
from isabelle_blueprint.agents.selection import (
    ready_task_filters_from_args as _ready_task_filters_from_args,
)
from isabelle_blueprint.agents.selection import (
    ready_task_filters_to_argv as _ready_task_filters_to_argv,
)
from isabelle_blueprint.agents.selection import (
    select_ready_task as _select_ready_task,
)
from isabelle_blueprint.agents.selection import (
    selection_metadata as _selection_metadata,
)
from isabelle_blueprint.agents.tasks import (
    generate_tasks,
    render_sledgehammer_appendix,
    render_task_prompt,
    write_tasks,
)
from isabelle_blueprint.agents.tracker_export import (
    SUPPORTED_TRACKERS as TRACKER_EXPORTS,
)
from isabelle_blueprint.agents.tracker_export import (
    render_tracker_csv,
)
from isabelle_blueprint.completion import (
    SUPPORTED_SHELLS,
    install_completion,
    render_completion,
)
from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.doctor import run_doctor
from isabelle_blueprint.errors import BlueprintError, ValidationError
from isabelle_blueprint.explain import (
    explain_project,
    render_explanations,
    render_explanations_markdown,
)
from isabelle_blueprint.graph.dependency_graph import (
    UnknownNodeError as GraphUnknownNodeError,
)
from isabelle_blueprint.graph.dependency_graph import (
    focus_subproject,
    roots_subproject,
)
from isabelle_blueprint.graph.graphviz_render import write_graph_artifacts
from isabelle_blueprint.isabelle.checker import (
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
from isabelle_blueprint.isabelle.fact_search import (
    match_missing_facts,
    render_hits,
    render_hits_markdown,
    render_matches,
    render_matches_markdown,
    search_index,
)
from isabelle_blueprint.isabelle.root import default_session_dir
from isabelle_blueprint.isabelle.source_index import (
    SourceIndex,
    build_index,
    render_theory_index_mermaid,
    session_theory_files,
)
from isabelle_blueprint.isabelle.suggestions import (
    suggest_missing_facts,
    write_fact_suggestions,
)
from isabelle_blueprint.isabelle.theory_import import (
    import_theory_file,
    imported_theory_review,
    render_imported_blueprint,
)
from isabelle_blueprint.model.node import NodeKind
from isabelle_blueprint.model.status import AgentStatus, FormalStatus
from isabelle_blueprint.plugins import run_report_renderers, run_status_providers
from isabelle_blueprint.project_io import (
    apply_stored_check_report,
    load_config_checked,
    load_project,
)
from isabelle_blueprint.refactor import rename_node
from isabelle_blueprint.refactor.format import format_blueprint_paths
from isabelle_blueprint.refactor.hooks import (
    PRECOMMIT_CONFIG_FILENAME,
    render_precommit_config,
)
from isabelle_blueprint.refactor.lintfix import (
    apply_lint_fixes,
    render_lint_fix_summary,
)
from isabelle_blueprint.render.site import render_site
from isabelle_blueprint.report.badge import write_badge_endpoint, write_badge_svg
from isabelle_blueprint.report.burndown import (
    build_burndown_report,
    burndown_payload,
    render_burndown_markdown,
    render_burndown_report,
)
from isabelle_blueprint.report.critical_path import (
    build_critical_path,
    critical_path_payload,
    critical_path_strict_failures,
    render_critical_path,
    render_critical_path_mermaid,
    write_critical_path,
)
from isabelle_blueprint.report.diff import (
    build_diff,
    load_baseline,
    render_diff,
    render_diff_markdown,
)
from isabelle_blueprint.report.effort import (
    build_effort_gate,
    build_effort_report,
    render_effort_markdown,
    render_effort_report,
)
from isabelle_blueprint.report.gate import (
    build_gate_report,
    render_gate_markdown,
    render_gate_report,
)
from isabelle_blueprint.report.github_actions import (
    build_summary_markdown,
    emit_step_outputs,
    emit_step_summary,
)
from isabelle_blueprint.report.history import (
    render_trend_csv,
    render_trend_markdown,
    render_trend_summary,
    summarize_trends,
)
from isabelle_blueprint.report.impact import (
    UnknownNodeError,
    build_impact_overview,
    build_impact_report,
    impact_overview_payload,
    impact_report_payload,
    render_impact_dot,
    render_impact_mermaid,
    render_impact_overview,
    render_impact_overview_csv,
    render_impact_report,
    render_impact_report_csv,
)
from isabelle_blueprint.report.json_report import write_project_report, write_summary_json
from isabelle_blueprint.report.lint import (
    build_lint_report,
    render_lint_markdown,
    render_lint_report,
)
from isabelle_blueprint.report.markdown_report import write_markdown_report
from isabelle_blueprint.report.metrics import (
    PROBLEM_FORMAL_STATUSES,
    build_status_metrics,
    output_values,
)
from isabelle_blueprint.report.notify import (
    SUPPORTED_FORMATS as NOTIFY_FORMATS,
)
from isabelle_blueprint.report.notify import (
    build_notification,
    post_notification,
    render_payload,
)
from isabelle_blueprint.report.path import (
    UnknownNodeError as PathUnknownNodeError,
)
from isabelle_blueprint.report.path import (
    build_path_report,
    render_path_markdown,
    render_path_report,
)
from isabelle_blueprint.report.portfolio import (
    build_portfolio,
    coverage_gate_failures,
    portfolio_payload,
    render_portfolio_csv,
    render_portfolio_markdown,
    render_portfolio_report,
)
from isabelle_blueprint.report.pr_comment import (
    post_or_update_pr_comment,
    write_pr_comment_preview,
)
from isabelle_blueprint.report.prometheus import render_prometheus
from isabelle_blueprint.report.roadmap import (
    COMPLETE_FORMAL_STATUSES,
    ROADMAP_STATUSES,
    RoadmapFilters,
    build_roadmap,
    diff_roadmaps,
    load_roadmap_payload,
    render_roadmap,
    render_roadmap_csv,
    render_roadmap_mermaid,
    roadmap_payload,
    roadmap_strict_failures,
    write_roadmap,
)
from isabelle_blueprint.report.sarif import render_sarif
from isabelle_blueprint.report.scorecard import (
    ALL_GRADES,
    SCORE_COMPONENTS,
    build_scorecard,
    grade_threshold,
    render_scorecard,
    write_scorecard_markdown,
)
from isabelle_blueprint.report.staleness import (
    build_staleness_report,
    render_staleness_csv,
    render_staleness_markdown,
    render_staleness_report,
    staleness_payload,
)
from isabelle_blueprint.report.stats import (
    build_stats_report,
    render_stats_markdown,
    render_stats_report,
)
from isabelle_blueprint.report.status_overview import (
    build_status_overview,
    render_status_markdown,
    render_status_overview,
)
from isabelle_blueprint.report.tags import (
    build_tag_gate,
    build_tag_report,
    render_tag_report,
    render_tags_csv,
    render_tags_markdown,
)
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
    return load_project(project_dir)


def _try_apply_check(project: BlueprintProject, config: BlueprintConfig) -> None:
    """Apply a previously stored check report if available - non-fatal."""
    apply_stored_check_report(project, config)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _percent(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


# Formal statuses selectable by the shared ``--fail-on`` policy gate.
FAIL_ON_STATUSES = tuple(status.value for status in FormalStatus)

# A convenient alias expanding to every "problem" formal status.
FAIL_ON_PROBLEM_ALIAS = "problem"


def _resolve_fail_on(statuses: list[str] | None) -> set[str]:
    """Expand a ``--fail-on`` selection (including the ``problem`` alias)."""
    if not statuses:
        return set()
    resolved: set[str] = set()
    for status in statuses:
        if status == FAIL_ON_PROBLEM_ALIAS:
            resolved.update(PROBLEM_FORMAL_STATUSES)
        else:
            resolved.add(status)
    return resolved


def _fail_on_failures(project: BlueprintProject, statuses: set[str]) -> list[str]:
    """Return ids of nodes whose formal status is in ``statuses`` (sorted)."""
    if not statuses:
        return []
    return sorted(
        node.id for node in project.nodes if node.status.formal.value in statuses
    )


def _report_fail_on(project: BlueprintProject, raw_statuses: list[str] | None) -> int:
    """Print and return exit 5 when any node matches the ``--fail-on`` policy.

    Returns 0 when the policy is satisfied (or not requested) so callers can
    ``return _report_fail_on(...)`` as their final step.
    """
    statuses = _resolve_fail_on(raw_statuses)
    failures = _fail_on_failures(project, statuses)
    if failures:
        selected = ", ".join(sorted(statuses))
        print(
            f"fail-on policy triggered ({selected}): "
            + ", ".join(failures),
            file=sys.stderr,
        )
        return 5
    return 0


def _add_fail_on_argument(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--fail-on`` policy flag to a subparser."""
    parser.add_argument(
        "--fail-on",
        action="append",
        choices=(*FAIL_ON_STATUSES, FAIL_ON_PROBLEM_ALIAS),
        metavar="STATUS",
        help=(
            "exit non-zero (5) if any node has the given formal status; "
            "repeatable; 'problem' expands to all problem statuses"
        ),
    )


def _grade_arg(value: str) -> str:
    """argparse ``type`` that accepts a letter grade case-insensitively."""
    normalized = value.strip().upper()
    if grade_threshold(normalized) is None:
        raise argparse.ArgumentTypeError(
            f"invalid grade {value!r}; choose one of {', '.join(ALL_GRADES)}"
        )
    return normalized


def _score_arg(value: str) -> int:
    """argparse ``type`` that accepts an integer score in ``[0, 100]``."""
    try:
        score = int(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"invalid score {value!r}; choose an integer from 0 to 100"
        ) from err
    if not 0 <= score <= 100:
        raise argparse.ArgumentTypeError(
            f"invalid score {value!r}; choose an integer from 0 to 100"
        )
    return score


def _min_component_arg(value: str) -> tuple[str, int]:
    """argparse ``type`` parsing a ``NAME=PCT`` per-component scorecard gate.

    ``NAME`` must be one of the known scorecard components and ``PCT`` an integer
    percentage in ``[0, 100]``. Returns the ``(name, pct)`` pair.
    """
    name, sep, pct_text = value.partition("=")
    name = name.strip().lower()
    if not sep:
        raise argparse.ArgumentTypeError(
            f"invalid component gate {value!r}; expected NAME=PCT"
        )
    if name not in SCORE_COMPONENTS:
        raise argparse.ArgumentTypeError(
            f"invalid component {name!r}; choose one of {', '.join(SCORE_COMPONENTS)}"
        )
    try:
        pct = int(pct_text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            f"invalid percentage {pct_text!r}; choose an integer from 0 to 100"
        ) from err
    if not 0 <= pct <= 100:
        raise argparse.ArgumentTypeError(
            f"invalid percentage {pct_text!r}; choose an integer from 0 to 100"
        )
    return name, pct


def _label_arg(value: str) -> tuple[str, str]:
    """argparse ``type`` parsing a ``key=value`` static Prometheus label.

    The key must be a valid Prometheus label name
    (``[a-zA-Z_][a-zA-Z0-9_]*``); the value may be any string. Names beginning
    with ``__`` are reserved by Prometheus for internal use and are rejected.
    """
    key, sep, label_value = value.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(
            f"invalid label {value!r}; expected key=value"
        )
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", key):
        raise argparse.ArgumentTypeError(
            f"invalid label name {key!r}; must match [a-zA-Z_][a-zA-Z0-9_]*"
        )
    if key.startswith("__"):
        raise argparse.ArgumentTypeError(
            f"invalid label name {key!r}; names beginning with '__' are reserved by Prometheus"
        )
    return key, label_value



def _add_watch_arguments(parser: argparse.ArgumentParser, *, action: str) -> None:
    """Attach shared ``--watch``/``--interval`` flags to a subparser.

    ``action`` is a short verb phrase used in the help text (e.g. "report").
    """
    parser.add_argument(
        "--watch",
        action="store_true",
        help=f"re-run the {action} whenever the blueprint sources change (Ctrl-C to stop)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="polling interval for --watch (default: 1.0)",
    )


def _dedupe(values: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values or []))


def _dedupe_int(values: list[int] | None) -> tuple[int, ...]:
    return tuple(dict.fromkeys(values or []))


def _render_template_catalog() -> str:
    width = max(len(name) for name in TEMPLATES)
    lines = ["Available templates:"]
    for name in sorted(TEMPLATES):
        template = TEMPLATES[name]
        lines.append(f"  {name.ljust(width)}  {template.description}")
    return "\n".join(lines) + "\n"


def _roadmap_filters_from_args(args: argparse.Namespace) -> RoadmapFilters:
    return RoadmapFilters(
        statuses=_dedupe(getattr(args, "status", None)),
        stages=_dedupe_int(getattr(args, "stage", None)),
        kinds=_dedupe(getattr(args, "kind", None)),
    )


def _add_ready_task_filter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--kind",
        action="append",
        choices=tuple(kind.value for kind in NodeKind),
        help="only consider ready tasks of this node kind; repeat to include multiple kinds",
    )
    parser.add_argument(
        "--priority",
        action="append",
        choices=READY_TASK_PRIORITIES,
        help="only consider ready tasks with this priority; repeat to include multiple priorities",
    )
    parser.add_argument(
        "--difficulty",
        action="append",
        choices=READY_TASK_DIFFICULTIES,
        help=(
            "only consider ready tasks with this difficulty; repeat to include "
            "multiple difficulties"
        ),
    )
    parser.add_argument(
        "--memory-state",
        action="append",
        choices=READY_TASK_MEMORY_STATES,
        help=(
            "only consider ready tasks with this memory state: fresh (no attempts), "
            "attempted (has memory), or stale (last attempt input is outdated); repeat "
            "to include multiple states"
        ),
    )
    parser.add_argument(
        "--last-outcome",
        action="append",
        choices=READY_TASK_LAST_OUTCOMES,
        help=(
            "only consider ready tasks whose latest recorded attempt has this outcome; "
            "repeat to include multiple outcomes"
        ),
    )
    parser.add_argument(
        "--exclude-node",
        action="append",
        default=None,
        metavar="NODE_OR_TASK",
        help="omit this ready node id or task id; repeat to omit multiple tasks",
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
    if args.list_templates:
        print(_render_template_catalog(), end="")
        return 0

    project_dir = Path(args.project_dir).resolve()
    template = TEMPLATES[args.template]
    if project_dir.exists() and not project_dir.is_dir():
        raise BlueprintError(f"{project_dir} exists and is not a directory")
    project_dir.mkdir(parents=True, exist_ok=True)
    blueprint_path = project_dir / blueprint_filename(args.format)
    config_path = project_dir / "isabelle-blueprint.toml"
    if blueprint_path.exists() and not args.force:
        print(f"refusing to overwrite {blueprint_path}; pass --force to replace", file=sys.stderr)
        return 1
    blueprint_path.write_text(
        render_template_blueprint(template, format=args.format), encoding="utf-8"
    )
    if not config_path.exists() or args.force:
        config_path.write_text(
            render_template_config(template, format=args.format), encoding="utf-8"
        )
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
    if getattr(args, "watch", False):
        return _watch_check(args)
    return _run_check_once(args)


def _run_check_once(args: argparse.Namespace) -> int:
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
    # The policy gate runs last so genuine infrastructure failures (3/4) are
    # surfaced before a "node still in a bad state" gate.
    return _report_fail_on(project, getattr(args, "fail_on", None))


def _watch_check(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    exit_code = _run_check_once(args)
    print(f"watching for changes (exit code {exit_code}); press Ctrl-C to stop", file=sys.stderr)
    snapshot = _snapshot(_check_watch_paths(project_dir))
    try:
        while True:
            time.sleep(max(getattr(args, "interval", 1.0), 0.1))
            current = _snapshot(_check_watch_paths(project_dir))
            if current != snapshot:
                snapshot = current
                try:
                    exit_code = _run_check_once(args)
                except BlueprintError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    exit_code = 1
                print(f"re-checked (exit code {exit_code})", file=sys.stderr)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return exit_code


def _run_watch(args: argparse.Namespace, run_once) -> int:
    """Re-run ``run_once(args)`` whenever an input source changes.

    Shared by ``report``/``status``/``tasks``; like ``check --watch`` it only
    watches input sources (config + blueprint files) via ``_check_watch_paths``
    so regenerating outputs never re-triggers the loop.
    """

    project_dir = Path(args.project_dir).resolve()
    exit_code = run_once(args)
    print(f"watching for changes (exit code {exit_code}); press Ctrl-C to stop", file=sys.stderr)
    snapshot = _snapshot(_check_watch_paths(project_dir))
    try:
        while True:
            time.sleep(max(getattr(args, "interval", 1.0), 0.1))
            current = _snapshot(_check_watch_paths(project_dir))
            if current != snapshot:
                snapshot = current
                try:
                    exit_code = run_once(args)
                except BlueprintError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    exit_code = 1
                print(f"re-ran (exit code {exit_code})", file=sys.stderr)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return exit_code


def cmd_graph(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    focus = getattr(args, "focus", None)
    if focus:
        depth = getattr(args, "depth", None)
        if depth is not None and depth < 0:
            raise BlueprintError("depth must be non-negative")
        try:
            project = focus_subproject(project, focus, depth)
        except GraphUnknownNodeError:
            known = ", ".join(sorted(n.id for n in project.nodes)) or "(none)"
            raise BlueprintError(
                f"unknown node {focus!r}; known node ids: {known}"
            ) from None
    if getattr(args, "roots_only", False):
        project = roots_subproject(project)
    fmt = getattr(args, "format", "all")
    formats = ("dot", "json", "svg", "mermaid", "graphml") if fmt == "all" else (fmt,)
    written = write_graph_artifacts(project, config.build_dir, formats=formats)
    for name, path in written.items():
        print(f"{name} -> {path}")
    if ("svg" in formats) and "svg" not in written:
        print("note: graphviz `dot` not found; install it for SVG output", file=sys.stderr)
    return 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    card = build_scorecard(project)

    if getattr(args, "markdown", False):
        md_path = write_scorecard_markdown(card, config.build_dir / "scorecard.md")
        print(f"scorecard markdown -> {md_path}", file=sys.stderr)

    exit_code = 0
    gate: dict[str, object] = {}
    min_grade = getattr(args, "min_grade", None)
    min_score = getattr(args, "min_score", None)

    meets_grade: bool | None = None
    if min_grade is not None:
        # Validated at parse time, so the threshold is always defined.
        threshold = grade_threshold(min_grade)
        if card.score is None:
            meets_grade = None  # nothing gradeable; do not fail the gate
        else:
            meets_grade = card.score >= (threshold or 0)
            if not meets_grade:
                exit_code = 5
        gate["min_grade"] = min_grade
        gate["score"] = card.score
        gate["grade"] = card.grade
        gate["meets_min_grade"] = meets_grade

    meets_score: bool | None = None
    if min_score is not None:
        if card.score is None:
            meets_score = None  # nothing gradeable; do not fail the gate
        else:
            meets_score = card.score >= min_score
            if not meets_score:
                exit_code = 5
        if "score" not in gate:
            gate["score"] = card.score
            gate["grade"] = card.grade
        gate["min_score"] = min_score
        gate["meets_min_score"] = meets_score

    min_components: list[tuple[str, int]] = getattr(args, "min_component", []) or []
    component_gates: list[dict[str, object]] = []
    failed_components: list[tuple[str, int, int]] = []
    if min_components:
        scores_by_name = {c.name: c.score for c in card.components}
        for name, threshold in min_components:
            raw = scores_by_name.get(name)
            if raw is None:
                pct: int | None = None
                meets_component: bool | None = None  # undefined; never fails
            else:
                pct = round(raw * 100)  # display value only
                # Compare the RAW ratio (unrounded) so e.g. 79.7% fails an =80
                # gate even though it rounds up to 80 for display.
                meets_component = raw * 100 >= threshold
                if not meets_component:
                    exit_code = 5
                    failed_components.append((name, threshold, pct))
            component_gates.append(
                {
                    "component": name,
                    "threshold": threshold,
                    "score": pct,
                    "meets": meets_component,
                }
            )

    if args.json:
        payload = card.to_dict()
        if gate:
            payload["gate"] = gate
        if component_gates:
            payload["component_gates"] = component_gates
        print(json.dumps(payload, indent=2))
    else:
        print(render_scorecard(card), end="")
        if min_grade is not None:
            if meets_grade is None:
                print(
                    f"min-grade {min_grade} not enforced: project has no gradeable "
                    "components yet.",
                    file=sys.stderr,
                )
            elif not meets_grade:
                print(
                    f"min-grade policy triggered: {card.grade} "
                    f"({card.score}/100) is below {min_grade}.",
                    file=sys.stderr,
                )
        if min_score is not None:
            if meets_score is None:
                print(
                    f"min-score {min_score} not enforced: project has no gradeable "
                    "components yet.",
                    file=sys.stderr,
                )
            elif not meets_score:
                print(
                    f"min-score policy triggered: {card.score}/100 "
                    f"is below {min_score}.",
                    file=sys.stderr,
                )
        for name, threshold, pct in failed_components:
            print(
                f"min-component policy triggered: {name} {pct}% "
                f"is below {threshold}%.",
                file=sys.stderr,
            )
    return exit_code


def cmd_tags(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    report = build_tag_report(project, only=args.tag or None)

    exit_code = 0
    gate = None
    fail_under = getattr(args, "fail_under", None)
    if fail_under is not None:
        gate = build_tag_gate(report, fail_under)
        if not gate.ok:
            exit_code = 5

    if args.json:
        payload = report.to_dict()
        if gate is not None:
            payload["gate"] = gate.to_dict()
        print(json.dumps(payload, indent=2))
    elif getattr(args, "markdown", False):
        print(render_tags_markdown(report), end="")
        if gate is not None and not gate.ok:
            print(
                f"fail-under {fail_under}% policy triggered: "
                f"{', '.join(gate.failing_tags)} below threshold.",
                file=sys.stderr,
            )
    elif getattr(args, "csv", False):
        print(render_tags_csv(report), end="")
        if gate is not None and not gate.ok:
            print(
                f"fail-under {fail_under}% policy triggered: "
                f"{', '.join(gate.failing_tags)} below threshold.",
                file=sys.stderr,
            )
    else:
        print(render_tag_report(report), end="")
        if gate is not None and not gate.ok:
            print(
                f"fail-under {fail_under}% policy triggered: "
                f"{', '.join(gate.failing_tags)} below threshold.",
                file=sys.stderr,
            )
    return exit_code


def cmd_path(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    try:
        report = build_path_report(
            project,
            args.source,
            args.target,
            all_paths=getattr(args, "all_paths", False),
        )
    except PathUnknownNodeError as exc:
        unknown = exc.args[0] if exc.args else "?"
        known = ", ".join(sorted(n.id for n in project.nodes)) or "(none)"
        raise BlueprintError(
            f"unknown node {unknown!r}; known node ids: {known}"
        ) from None
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif getattr(args, "markdown", False):
        print(render_path_markdown(report), end="")
    else:
        print(render_path_report(report), end="")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)

    fix_result = None
    if getattr(args, "fix", False):
        paths = [p for p in config.blueprint_paths if p.exists()]
        fix_result = apply_lint_fixes(
            project,
            paths,
            project_name=config.project_name,
            check_only=args.fix_dry_run,
        )
        if fix_result.refused:
            if _resolve_lint_format(args) == "json":
                print(json.dumps(fix_result.to_dict(), indent=2))
            else:
                print(render_lint_fix_summary(fix_result), end="", file=sys.stderr)
            return 2
        if _resolve_lint_format(args) != "json":
            print(render_lint_fix_summary(fix_result), end="", file=sys.stderr)

    report = build_lint_report(project)
    fmt = _resolve_lint_format(args)
    if fmt == "json":
        payload = report.to_dict()
        if fix_result is not None:
            payload["fix"] = fix_result.to_dict()
        print(json.dumps(payload, indent=2))
    elif fmt == "sarif":
        print(render_sarif(report, project), end="")
    elif fmt == "markdown":
        print(render_lint_markdown(report), end="")
    else:
        print(render_lint_report(report), end="")
    if args.strict and not report.ok:
        return 2
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fail_on = _resolve_fail_on(getattr(args, "fail_on", None))
    report = build_gate_report(
        project,
        min_coverage=args.min_coverage,
        fail_on=fail_on,
        min_grade=getattr(args, "min_grade", None),
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif args.markdown:
        print(render_gate_markdown(report), end="")
    else:
        print(render_gate_report(report), end="")
    return 0 if report.ok else 5


def cmd_prometheus(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    metrics = build_status_metrics(project)
    eta_days: float | None = None
    if not args.no_burndown:
        entries = load_trends(config.trends_path)
        eta_days = build_burndown_report(entries).eta_days
    labels = dict(args.label) if args.label else None
    text = render_prometheus(metrics, eta_days=eta_days, labels=labels)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"prometheus metrics -> {out}")
    else:
        print(text, end="")
    return 0


def cmd_effort(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    report = build_effort_report(project, include_by_tag=args.by_tag)
    fail_under = getattr(args, "fail_under", None)
    gate = None if fail_under is None else build_effort_gate(report, fail_under)
    if args.json:
        payload = report.to_dict(include_by_tag=args.by_tag)
        if gate is not None:
            payload["gate"] = gate
        print(json.dumps(payload, indent=2))
    else:
        if args.markdown:
            print(render_effort_markdown(report, by_tag=args.by_tag), end="")
        else:
            print(render_effort_report(report, by_tag=args.by_tag), end="")
        if gate is not None and not gate["meets"]:
            actual = (
                "undefined"
                if report.coverage_percent is None
                else f"{report.coverage_percent}%"
            )
            print(
                f"effort-weighted coverage {actual} is below {fail_under}%",
                file=sys.stderr,
            )
    if gate is not None and not gate["meets"]:
        return 5
    return 0


def cmd_hooks(args: argparse.Namespace) -> int:
    text = render_precommit_config()
    if not args.write:
        print(text, end="")
        return 0
    project_dir = Path(args.project_dir).resolve()
    target = project_dir / PRECOMMIT_CONFIG_FILENAME
    if target.exists() and not args.force:
        print(
            f"{target} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 1
    target.write_text(text, encoding="utf-8")
    print(f"pre-commit config -> {target}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    metrics = build_status_metrics(project)
    eta_days: float | None = None
    if not args.no_burndown:
        entries = load_trends(config.trends_path)
        eta_days = build_burndown_report(entries).eta_days
    content = build_notification(project, metrics, eta_days=eta_days)
    payload = render_payload(content, args.format)

    if not args.send:
        print(json.dumps(payload, indent=2))
        print(
            "dry-run: nothing was sent. Re-run with --send --url <webhook> to post.",
            file=sys.stderr,
        )
        return 0

    if not args.url:
        print("error: --send requires --url", file=sys.stderr)
        return 1
    status = post_notification(
        args.url,
        payload,
        allow_http=args.allow_http,
        timeout=args.timeout,
    )
    if 200 <= status < 300:
        print(f"notification sent ({args.format}, HTTP {status})")
        return 0
    print(f"webhook returned HTTP {status}", file=sys.stderr)
    return 1


def cmd_blame(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    memory = load_agent_memory(config.agent_memory_path)
    blames = build_blame(
        project,
        project_dir,
        memory,
        node_id=args.node_id,
    )
    if args.json:
        print(json.dumps(blame_payload(blames), indent=2))
    elif args.table:
        print(render_blame_table(blames), end="")
    elif args.markdown:
        print(render_blame_markdown(blames), end="")
    else:
        print(render_blame(blames), end="")
    return 0


def cmd_critical_path(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    overview = build_critical_path(project)
    goal = getattr(args, "goal", None)
    if args.json:
        print(json.dumps(critical_path_payload(overview, top=args.top), indent=2))
    elif getattr(args, "mermaid", False):
        print(render_critical_path_mermaid(overview, top=args.top, goal=goal), end="")
    elif getattr(args, "markdown", False):
        from isabelle_blueprint import console

        was_enabled = console.is_enabled()
        console.set_enabled(False)
        try:
            markdown = render_critical_path(overview, top=args.top, goal=goal)
        finally:
            console.set_enabled(was_enabled)
        print(markdown, end="")
    else:
        print(render_critical_path(overview, top=args.top, goal=goal), end="")
    if getattr(args, "write", False):
        stream = sys.stderr if args.json else sys.stdout
        written = write_critical_path(overview, config.build_dir, top=args.top, goal=goal)
        for name, path in written.items():
            print(f"critical-path {name} -> {path}", file=stream)
    failures = critical_path_strict_failures(overview) if args.fail_on_cycle else []
    for failure in failures:
        print(f"critical-path: {failure}", file=sys.stderr)
    return 2 if failures else 0


def cmd_impact(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fmt = _resolve_lint_format(args)
    node = getattr(args, "node", None)
    if fmt in ("dot", "mermaid") and not node:
        raise BlueprintError(f"--format {fmt} requires --node NODE")
    if node:
        try:
            report = build_impact_report(project, node)
        except UnknownNodeError:
            known = ", ".join(sorted(n.id for n in project.nodes)) or "(none)"
            raise BlueprintError(
                f"unknown node {node!r}; known node ids: {known}"
            ) from None
        if fmt == "dot":
            print(render_impact_dot(project, node), end="")
        elif fmt == "mermaid":
            print(render_impact_mermaid(project, node), end="")
        elif fmt == "csv":
            print(render_impact_report_csv(report), end="")
        elif fmt == "json":
            print(json.dumps(impact_report_payload(report), indent=2))
        else:
            print(render_impact_report(report, top=args.top), end="")
        return 0
    overview = build_impact_overview(project)
    if fmt == "json":
        print(json.dumps(impact_overview_payload(overview, top=args.top), indent=2))
    elif fmt == "csv":
        print(render_impact_overview_csv(overview, top=args.top), end="")
    else:
        print(render_impact_overview(overview, top=args.top), end="")
    return 0


def _resolve_lint_format(args: argparse.Namespace) -> str:
    """Reconcile the ``--json`` alias with ``--format``.

    ``--json`` predates ``--format`` and is kept as a backward-compatible alias
    for ``--format json``. The two may be combined only when they agree.
    """

    fmt = getattr(args, "format", None)
    if args.json:
        if fmt is not None and fmt != "json":
            raise BlueprintError(
                f"--json conflicts with --format {fmt}; use one or the other"
            )
        return "json"
    return fmt or "text"


PROG_NAME = "isabelle-blueprint"


def _subcommand_names() -> list[str]:
    """Return the sorted list of registered subcommand names."""

    parser = _build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    return []


def _subcommand_options() -> dict[str, list[str]]:
    """Map each registered subcommand to its sorted option strings.

    Generated from the live parser so the completion scripts never drift from
    the actual flags a subcommand accepts.
    """

    parser = _build_parser()
    result: dict[str, list[str]] = {}
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                opts: list[str] = []
                for sub_action in subparser._actions:  # noqa: SLF001
                    opts.extend(sub_action.option_strings)
                result[name] = sorted(dict.fromkeys(opts))
            break
    return result


def cmd_version(args: argparse.Namespace) -> int:
    info = {
        "name": PROG_NAME,
        "version": __version__,
        "python": platform.python_version(),
        "schemas": list(available_schemas()),
    }
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"{PROG_NAME} {__version__}")
        print(f"  python  {info['python']}")
        print(f"  schemas {', '.join(info['schemas'])}")
    return 0


def cmd_completion(args: argparse.Namespace) -> int:
    commands = _subcommand_names()
    options = _subcommand_options()
    if args.install or args.dest:
        target, hint = install_completion(
            args.shell, PROG_NAME, commands, options, dest=args.dest
        )
        print(f"Wrote {args.shell} completion to {target}")
        if hint:
            print(hint)
        return 0
    print(render_completion(args.shell, PROG_NAME, commands, options), end="")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    memory = load_agent_memory(config.agent_memory_path)
    report = build_stats_report(memory, project)

    exit_code = 0
    gate: dict[str, object] = {}
    min_rate = getattr(args, "min_success_rate", None)
    meets: bool | None = None
    # Gate on the RAW rate (succeeded / resolved), not report.success_rate which
    # is rounded to 4 decimals and could flip the verdict near the threshold.
    succeeded = report.outcomes.get("succeeded", 0)
    failed = report.outcomes.get("failed", 0)
    resolved = succeeded + failed
    raw_rate = succeeded / resolved if resolved else None
    if min_rate is not None:
        if raw_rate is None:
            meets = None  # no resolved attempts; do not fail the gate
        else:
            meets = raw_rate * 100 >= min_rate
            if not meets:
                exit_code = 5
        gate["min_success_rate"] = min_rate
        gate["success_rate"] = report.success_rate
        gate["meets"] = meets

    if args.json:
        payload = report.to_dict()
        if gate:
            payload["gate"] = gate
        print(json.dumps(payload, indent=2))
    elif args.markdown:
        print(render_stats_markdown(report), end="")
    else:
        print(render_stats_report(report), end="")

    if min_rate is not None and not args.json:
        if meets is None:
            print(
                f"min-success-rate {min_rate:g} not enforced: project has no "
                "resolved attempts yet.",
                file=sys.stderr,
            )
        elif not meets:
            assert raw_rate is not None
            print(
                f"min-success-rate policy triggered: {raw_rate * 100:.2f}% "
                f"is below {min_rate:g}%.",
                file=sys.stderr,
            )
    return exit_code


def cmd_staleness(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    report = build_staleness_report(project)
    if args.json:
        payload = staleness_payload(
            report, top=args.top, max_causes=args.max_causes
        )
        print(json.dumps(payload, indent=2))
    elif args.markdown:
        print(
            render_staleness_markdown(report, top=args.top, max_causes=args.max_causes),
            end="",
        )
    elif args.csv:
        print(
            render_staleness_csv(report, top=args.top, max_causes=args.max_causes),
            end="",
        )
    else:
        print(
            render_staleness_report(report, top=args.top, max_causes=args.max_causes),
            end="",
        )
    tripped = False
    if args.fail_on_problem and report.problem_count > 0:
        print(
            f"{report.problem_count} trusted node(s) rest on broken/missing "
            "dependencies",
            file=sys.stderr,
        )
        tripped = True
    if args.fail_on_outdated and report.outdated_count > 0:
        print(
            f"{report.outdated_count} trusted node(s) are outdated (rest on a "
            "dependency that is stale or was re-checked more recently than the node)",
            file=sys.stderr,
        )
        tripped = True
    return 5 if tripped else 0


def cmd_diff(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    baseline_path = Path(args.baseline).resolve()
    baseline_nodes = load_baseline(baseline_path)
    diff = build_diff(baseline_nodes, project)
    if args.json:
        print(json.dumps(diff.to_dict(), indent=2))
    elif args.markdown:
        print(render_diff_markdown(diff), end="")
    else:
        print(render_diff(diff), end="")
    # Check --fail-on-regression first: a regression also counts as a change,
    # so this ordering keeps the more specific message when both flags are set.
    if args.fail_on_regression and diff.has_regression:
        print(
            f"regression detected vs baseline "
            f"({len(diff.regressions) + len(diff.removed)} node(s))",
            file=sys.stderr,
        )
        return 5
    if args.fail_on_change and diff.has_changes:
        print(
            f"change detected vs baseline "
            f"({len(diff.added)} added, {len(diff.removed)} removed, "
            f"{len(diff.changes)} changed)",
            file=sys.stderr,
        )
        return 5
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    # history only needs trends.json, so avoid parsing the (possibly broken)
    # blueprint - historical data is most useful exactly when the current
    # blueprint does not load.
    config = load_config(project_dir)
    entries = load_trends(config.trends_path)
    summary = summarize_trends(entries, limit=args.limit)
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    elif args.csv:
        print(render_trend_csv(summary), end="")
    elif args.markdown:
        print(render_trend_markdown(summary), end="")
    else:
        print(render_trend_summary(summary), end="")
    return 0


def cmd_burndown(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    # Like history, burndown reads only trends.json, so it still forecasts when
    # the current blueprint fails to parse.
    config = load_config(project_dir)
    entries = load_trends(config.trends_path)
    report = build_burndown_report(entries, recent_window=args.window)
    if args.json:
        payload = burndown_payload(report, limit=args.limit)
        payload["trends_path"] = str(config.trends_path)
        print(json.dumps(payload, indent=2))
    elif args.markdown:
        print(render_burndown_markdown(report), end="")
    else:
        limit = args.limit if args.limit is not None else 10
        print(render_burndown_report(report, limit=limit), end="")
    if args.fail_when_stalled and report.remaining and report.status in {
        "stalled",
        "regressing",
        "scope_growing",
        "beyond_horizon",
    }:
        return 5
    return 0


def cmd_portfolio(args: argparse.Namespace) -> int:
    root = Path(args.root_dir).resolve()
    report = build_portfolio(root)
    coverage_failures: list[str] = []
    if args.min_coverage is not None:
        coverage_failures = coverage_gate_failures(report, args.min_coverage)
    if args.json:
        payload = portfolio_payload(report)
        if args.min_coverage is not None:
            payload["coverage_gate"] = {
                "min_coverage": args.min_coverage,
                "failing_projects": coverage_failures,
                "ok": not coverage_failures,
            }
        print(json.dumps(payload, indent=2))
    elif args.csv:
        print(render_portfolio_csv(report), end="")
    elif args.markdown:
        print(render_portfolio_markdown(report), end="")
    else:
        print(render_portfolio_report(report), end="")
    exit_code = 0
    if args.fail_on_problem and (
        report.totals.projects_with_problems
        or report.totals.projects_with_cycles
        or report.totals.error_count
    ):
        exit_code = 5
    if coverage_failures:
        if not args.json:
            print(
                f"coverage gate failed: {len(coverage_failures)} project(s) below "
                f"{args.min_coverage}% proved-coverage: "
                f"{', '.join(coverage_failures)}",
                file=sys.stderr,
            )
        exit_code = 5
    return exit_code


def cmd_assign(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)

    node_id = args.node_id
    if node_id is not None and project.by_id().get(node_id) is None:
        raise BlueprintError(f"node id {node_id!r} not found in the blueprint")

    # Mutating flags only take effect for a specific node; reject combinations
    # that would otherwise be silently discarded (a footgun: the user believes
    # the owner/note/clear was applied when it was not).
    if node_id is None and (args.owner is not None or args.note is not None or args.clear):
        raise BlueprintError("--owner/--note/--clear require a node id")
    if args.clear and (args.owner is not None or args.note is not None):
        raise BlueprintError("--clear cannot be combined with --owner/--note")
    # (clear+note is already rejected above, so here a note implies no --clear.)
    if node_id is not None and args.note is not None and args.owner is None:
        raise BlueprintError("--note requires --owner (a note is stored alongside an owner)")

    mutating = node_id is not None and (args.clear or args.owner is not None)
    # When we are about to write the store back, refuse to start from an empty
    # store if the existing file is corrupt (which would clobber real data).
    store = load_assignments(config.assignments_path, strict=mutating)

    mutated = False
    if node_id is not None and args.clear:
        removed = clear_assignment(store, node_id)
        if not removed:
            print(f"no assignment for {node_id!r}", file=sys.stderr)
        mutated = removed
    elif node_id is not None and args.owner is not None:
        set_assignment(store, node_id, args.owner, note=args.note or "")
        mutated = True
    elif node_id is not None:
        # Lookup of a single node's assignment.
        pass

    if mutated:
        write_assignments(store, config.assignments_path)

    payload = _assignments_payload(store, project, node_id)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_render_assignments(payload), end="")
    return 0


def _assignments_payload(store, project, node_id):  # type: ignore[no-untyped-def]
    items = []
    selected = [node_id] if node_id is not None else sorted(store.nodes)
    for nid in selected:
        assignment = store.nodes.get(nid)
        if assignment is None:
            if node_id is not None:
                items.append({"node_id": nid, "owner": None, "note": "", "updated_at": ""})
            continue
        items.append(
            {
                "node_id": nid,
                "owner": assignment.owner,
                "note": assignment.note,
                "updated_at": assignment.updated_at,
            }
        )
    owners = {item["node_id"]: item["owner"] for item in items}
    return {
        "project": project.name,
        "count": len(items),
        "owners": owners,
        "assignments": items,
    }


def _render_assignments(payload: dict) -> str:
    items = payload.get("assignments", [])
    if not items:
        return "No assignments recorded.\n"
    lines = [f"{payload.get('project', 'project')}: {len(items)} assignment(s)"]
    for item in items:
        owner = item.get("owner") or "(unassigned)"
        note = item.get("note") or ""
        suffix = f" - {note}" if note else ""
        lines.append(f"  {item['node_id']}: {owner}{suffix}")
    return "\n".join(lines) + "\n"


def cmd_rename(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config = load_config_checked(project_dir)
    result = rename_node(config, args.old_id, args.new_id, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    verb = "would rename" if result.dry_run else "renamed"
    print(f"{verb} {result.old_id!r} -> {result.new_id!r}")
    for path in result.changed_files:
        print(f"  source: {path}")
    for rekey in result.store_rekeys:
        if rekey.changed:
            action = "would update" if result.dry_run else "updated"
            print(f"  {action} {rekey.name} store: {rekey.path}")
    if not result.changed_files:
        print("  (no source files referenced this id)")
    return 0


def cmd_fmt(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config = load_config_checked(project_dir)
    paths = [p for p in config.blueprint_paths if p.exists()]
    diff = getattr(args, "diff", False)
    result = format_blueprint_paths(
        paths, project_name=config.project_name, check_only=args.check, diff=diff
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif diff:
        for entry in result.files:
            if entry.skipped:
                print(f"  skipped {entry.path} ({entry.reason})")
            elif entry.diff:
                print(entry.diff, end="" if entry.diff.endswith("\n") else "\n")
        if not result.would_change:
            print("All Markdown blueprints are already canonical.")
    else:
        for entry in result.files:
            if entry.skipped:
                print(f"  skipped {entry.path} ({entry.reason})")
            elif entry.changed:
                verb = "needs formatting" if args.check else "formatted"
                print(f"  {verb}: {entry.path}")
        if not result.would_change:
            print("All Markdown blueprints are already canonical.")
    if (args.check or diff) and result.would_change:
        return 10
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    try:
        project.validate().raise_if_failed()
    except ValidationError as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"ran": False, "ok": False, "error": str(exc), "issues": exc.issues},
                    indent=2,
                )
            )
        else:
            print(f"validation failed: {exc}", file=sys.stderr)
        return 2

    if args.from_dir:
        result = inspect_dump_dir(
            project,
            Path(args.from_dir),
            isabelle_executable=args.isabelle or config.isabelle_executable,
        )
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
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"dump report -> {config.dump_report_path}")
        if result.error:
            print(f"note: {result.error}", file=sys.stderr)
    if result.error and args.strict:
        return 3
    return 0


def cmd_compat(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config = load_config(project_dir)
    report = check_compatibility(
        config, isabelle_executable=args.isabelle or config.isabelle_executable
    )
    write_compat_report(report, config.compat_report_path)
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
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
    if getattr(args, "watch", False):
        return _run_watch(args, _run_tasks_once)
    return _run_tasks_once(args)


def _run_tasks_once(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    payload_metadata = (
        _selection_metadata(
            filters,
            ready_task_count=len(all_ready_tasks),
            filtered_ready_task_count=len(ready_tasks),
        )
        if filters.active
        else None
    )
    empty_message = (
        _no_ready_task_message(len(all_ready_tasks), filters) if filters.active else None
    )
    written = write_tasks(
        project,
        config.build_dir,
        fact_suggestions=fact_suggestions,
        memory=memory,
        tasks=ready_tasks,
        prompt_tasks=all_ready_tasks,
        payload_metadata=payload_metadata,
        empty_message=empty_message,
        github_issues=args.github_issues,
        github_issues_name=args.github_issues_file,
        github_issue_labels=args.github_label,
        github_issue_assignees=args.github_assignee,
    )
    tracker = getattr(args, "tracker_export", None)
    if tracker:
        csv_text = render_tracker_csv(ready_tasks, tracker)
        csv_path = config.build_dir / f"tasks-{tracker}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(csv_text, encoding="utf-8")
        written["tracker_export"] = csv_path
    if args.github_sync:
        from isabelle_blueprint.agents.tasks import github_issue_drafts

        drafts = github_issue_drafts(
            all_ready_tasks,
            extra_labels=args.github_label,
            assignees=args.github_assignee,
        )
        actions = sync_github_issues(
            drafts,
            repo=args.repo or os.environ.get("GITHUB_REPOSITORY"),
            state_path=Path(args.github_sync_state).resolve()
            if args.github_sync_state
            else config.github_sync_state_path,
            token_env=args.token_env,
            confirm=args.github_sync_confirm,
            completed_node_ids=_completed_node_ids(project),
        )
        sync_path = config.build_dir / "github-sync-plan.json"
        sync_path.write_text(
            json.dumps({"actions": [action.to_dict() for action in actions]}, indent=2),
            encoding="utf-8",
        )
        written["github_sync"] = sync_path
    if args.github_sync_pull:
        states = pull_github_issue_states(
            state_path=Path(args.github_sync_state).resolve()
            if args.github_sync_state
            else config.github_sync_state_path,
            repo=args.repo or os.environ.get("GITHUB_REPOSITORY"),
            token_env=args.token_env,
        )
        pull_path = config.build_dir / "github-sync-state.json"
        pull_path.parent.mkdir(parents=True, exist_ok=True)
        pull_path.write_text(
            json.dumps({"issues": [s.to_dict() for s in states]}, indent=2),
            encoding="utf-8",
        )
        written["github_sync_state"] = pull_path
        closed = [s.node_id for s in states if s.state == "closed"]
        if closed:
            print(
                f"note: {len(closed)} tracked issue(s) are closed upstream: "
                + ", ".join(sorted(closed)),
                file=sys.stderr,
            )
    for name, path in written.items():
        print(f"{name} -> {path}")
    if filters.active and not ready_tasks:
        print(_no_ready_task_message(len(all_ready_tasks), filters), file=sys.stderr)
    if filters.active and args.github_sync:
        print(
            "note: --github-sync reconciles all ready tasks; filters only narrow "
            "tasks.json, tasks.md, and issue drafts",
            file=sys.stderr,
        )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    if getattr(args, "watch", False):
        return _run_watch(args, _run_report_once)
    return _run_report_once(args)


def _run_report_once(args: argparse.Namespace) -> int:
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
        suggestions_path = write_fact_suggestions(
            fact_suggestions, config.build_dir / "fact-suggestions.json"
        )
        print(f"fact suggestions -> {suggestions_path}")
    plugin_annotations = run_status_providers(project)
    if plugin_annotations:
        plugin_path = config.build_dir / "plugin-annotations.json"
        plugin_path.write_text(
            json.dumps({"annotations": plugin_annotations}, indent=2), encoding="utf-8"
        )
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
    return _report_fail_on(project, getattr(args, "fail_on", None))


def cmd_status(args: argparse.Namespace) -> int:
    if getattr(args, "watch", False):
        return _run_watch(args, _run_status_once)
    return _run_status_once(args)


def _run_status_once(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    selected_ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    overview = build_status_overview(
        project,
        all_ready_tasks,
        top_task_count=args.top_tasks,
        selected_ready_tasks=selected_ready_tasks if filters.active else None,
        filters=filters.to_dict() if filters.active else None,
    )
    if args.json:
        print(json.dumps(overview.to_dict(), indent=2))
    elif getattr(args, "markdown", False):
        was_enabled = console.is_enabled()
        console.set_enabled(False)
        try:
            print(render_status_markdown(overview), end="")
        finally:
            console.set_enabled(was_enabled)
    else:
        print(render_status_overview(overview), end="")
    if filters.active and not selected_ready_tasks and all_ready_tasks:
        print(
            _no_ready_task_message(len(all_ready_tasks), filters),
            file=sys.stderr,
        )
    return _report_fail_on(project, getattr(args, "fail_on", None))


def cmd_roadmap(args: argparse.Namespace) -> int:
    if args.mermaid and args.json:
        # Frozen pre-existing wording; do not change.
        raise BlueprintError("roadmap --mermaid and --json are mutually exclusive")
    output_flags = [name for name in ("mermaid", "json", "csv") if getattr(args, name)]
    if len(output_flags) > 1:
        raise BlueprintError(
            "roadmap --mermaid, --json, and --csv are mutually exclusive"
        )
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
    if args.mermaid:
        print(render_roadmap_mermaid(roadmap, filters=filters), end="")
        stream = sys.stderr
    elif args.csv:
        print(render_roadmap_csv(roadmap, filters=filters), end="")
        stream = sys.stderr
    elif args.json:
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
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    selected_ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    status = build_status_overview(project, all_ready_tasks)
    roadmap = build_roadmap(project, all_ready_tasks)
    context = build_agent_context(
        config,
        status,
        roadmap,
        all_ready_tasks,
        max_tasks=args.max_tasks,
        filtered_ready_tasks=selected_ready_tasks if filters.active else None,
        filters=filters.to_dict() if filters.active else None,
        filter_argv=_ready_task_filters_to_argv(filters) if filters.active else None,
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
    if filters.active and not selected_ready_tasks and all_ready_tasks:
        print(
            _no_ready_task_message(len(all_ready_tasks), filters),
            file=sys.stderr,
        )
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    task = _select_ready_task(
        ready_tasks,
        args.node,
        project,
        filters=filters,
        unfiltered_ready_tasks=all_ready_tasks,
    )
    if task is None:
        message = _no_ready_task_message(len(all_ready_tasks), filters)
        metadata = _selection_metadata(
            filters,
            ready_task_count=len(all_ready_tasks),
            filtered_ready_task_count=len(ready_tasks),
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "task": None,
                        "prompt": None,
                        "prompt_path": None,
                        "message": message,
                        **metadata,
                    },
                    indent=2,
                )
            )
        else:
            print(message)
        return 0

    prompt = render_task_prompt(task)
    prompt_path = _write_next_prompt(prompt, args.output)
    metadata = _selection_metadata(
        filters,
        ready_task_count=len(all_ready_tasks),
        filtered_ready_task_count=len(ready_tasks),
    )
    if args.json:
        print(
            json.dumps(
                {
                    "task": task.to_dict(),
                    "prompt": prompt,
                    "prompt_path": str(prompt_path) if prompt_path is not None else None,
                    "message": f"Selected {task.id}.",
                    **metadata,
                },
                indent=2,
            )
        )
    else:
        print(prompt, end="")
        if prompt_path is not None:
            print(f"next prompt -> {prompt_path}", file=sys.stderr)
    return 0


def cmd_attempt(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    task = _select_ready_task(
        ready_tasks,
        args.node,
        project,
        filters=filters,
        unfiltered_ready_tasks=all_ready_tasks,
    )
    if task is None:
        message = _no_ready_task_message(len(all_ready_tasks), filters)
        no_task_payload: dict[str, object] = {
            "task": None,
            "prompt_path": None,
            "check": None,
            "memory": None,
            "message": message,
            **_selection_metadata(
                filters,
                ready_task_count=len(all_ready_tasks),
                filtered_ready_task_count=len(ready_tasks),
            ),
        }
        if args.json:
            print(json.dumps(no_task_payload, indent=2))
        else:
            print(no_task_payload["message"])
        return 0

    prompt = render_task_prompt(task)
    if getattr(args, "sledgehammer", False):
        prompt = prompt.rstrip("\n") + "\n\n" + render_sledgehammer_appendix(task)
    output = args.output or str(config.build_dir / "attempts" / prompt_filename(task.id))
    prompt_path = _write_next_prompt(prompt, output)
    check_payload = _run_attempt_check(args, config, project) if args.check else None
    memory_payload = None
    if args.record_outcome:
        summary = args.summary.strip() if args.summary else ""
        if not summary:
            raise BlueprintError("--summary is required with --record-outcome")
        attempt = record_memory_attempt(
            config.agent_memory_path,
            task.node_id,
            outcome=args.record_outcome,
            summary=summary,
            actor=args.actor,
            tool=args.tool,
            details=args.details or "",
            next_step=args.next_step,
            input_hash=node_input_hash(project.by_id()[task.node_id]),
            max_attempts=args.max_attempts,
        )
        memory_payload = attempt.to_dict()

    payload: dict[str, object] = {
        "task": task.to_dict(),
        "prompt_path": str(prompt_path),
        "check": check_payload,
        "memory": memory_payload,
        "message": f"Prepared {task.id}.",
        **_selection_metadata(
            filters,
            ready_task_count=len(all_ready_tasks),
            filtered_ready_task_count=len(ready_tasks),
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"attempt prompt -> {prompt_path}")
        if check_payload is not None:
            print(f"check report -> {check_payload['report_path']}")
            if check_payload["return_code"] not in (None, 0):
                print(f"check exited with {check_payload['return_code']}", file=sys.stderr)
        if memory_payload is not None:
            print(f"memory recorded -> {config.agent_memory_path}")
    return 0


def _run_attempt_check(
    args: argparse.Namespace,
    config: BlueprintConfig,
    project: BlueprintProject,
) -> dict[str, object]:
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
    return {
        "report_path": str(config.check_report_path),
        "project_json_path": str(config.project_json_path),
        "isabelle_available": result.isabelle_available,
        "ran": result.ran,
        "return_code": result.return_code,
        "error": result.error,
    }


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


def _agent_run_command_tokens(args: argparse.Namespace) -> list[str]:
    """Resolve the solver command from --exec/--arg or --command."""

    if args.exec_program is not None:
        return [args.exec_program, *(args.arg or [])]
    if args.arg:
        raise BlueprintError("--arg requires --exec")
    if args.command:
        return split_command_string(args.command)
    raise BlueprintError(
        "agent-run requires a solver command: pass --command \"<template>\" or "
        "--exec PROGRAM [--arg ARG ...]"
    )


def _agent_run_prompt_path(args: argparse.Namespace, config: BlueprintConfig,
                           project_dir: Path, task_id: str) -> Path:
    if args.output:
        path = Path(args.output)
        if not path.is_absolute():
            path = project_dir / path
        return path.resolve()
    return (config.build_dir / "agent-run" / safe_prompt_filename(task_id)).resolve()


def _agent_run_details(result: object, stdout_tail: str, stderr_tail: str) -> str:
    parts = [f"exit={getattr(result, 'return_code', None)}"]
    if getattr(result, "timed_out", False):
        parts.append("timed_out")
    if getattr(result, "output_limit_exceeded", False):
        parts.append("output_limit_exceeded")
    duration = getattr(result, "duration_seconds", None)
    if duration is not None:
        parts.append(f"duration={duration:.2f}s")
    detail = " ".join(parts)
    if stdout_tail:
        detail += f"\n[stdout tail]\n{stdout_tail}"
    if stderr_tail:
        detail += f"\n[stderr tail]\n{stderr_tail}"
    return detail


def cmd_agent_run(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    all_ready_tasks = generate_tasks(project, fact_suggestions=fact_suggestions, memory=memory)
    filters = _ready_task_filters_from_args(args)
    ready_tasks = _filter_ready_tasks(all_ready_tasks, filters)
    task = _select_ready_task(
        ready_tasks,
        args.node,
        project,
        filters=filters,
        unfiltered_ready_tasks=all_ready_tasks,
    )
    metadata = _selection_metadata(
        filters,
        ready_task_count=len(all_ready_tasks),
        filtered_ready_task_count=len(ready_tasks),
    )

    # Resolve the solver command early so a misconfigured command fails fast
    # (before selecting/writing anything).
    tokens = _agent_run_command_tokens(args)
    validate_command_tokens(tokens, require_prompt=not args.allow_missing_prompt)

    # If we intend to record the outcome, verify the memory store is readable
    # *before* running the (potentially expensive) solver. Otherwise a corrupt
    # store is only discovered at record time, after the solver has run, and the
    # completed attempt is discarded with a non-zero exit.
    if not args.no_record:
        load_agent_memory(config.agent_memory_path, strict=True)

    if task is None:
        message = _no_ready_task_message(len(all_ready_tasks), filters)
        payload: dict[str, object] = {
            "task": None,
            "command": None,
            "outcome": None,
            "recorded": False,
            "message": message,
            **metadata,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(message)
        return 0

    prompt = render_task_prompt(task)
    prompt_path = _agent_run_prompt_path(args, config, project_dir, task.id)
    substitutions = {
        "prompt_file": str(prompt_path),
        "node_id": task.node_id,
        "task_id": task.id,
        "project_dir": str(project_dir),
    }
    command = substitute_command(tokens, substitutions)

    if args.dry_run:
        dry_payload: dict[str, object] = {
            "task": task.to_dict(),
            "prompt": prompt,
            "prompt_path": str(prompt_path),
            "command": command,
            "dry_run": True,
            "outcome": None,
            "recorded": False,
            "message": f"Would run {task.id}.",
            **metadata,
        }
        if args.json:
            print(json.dumps(dry_payload, indent=2))
        else:
            print(f"agent-run (dry-run) {task.id}")
            print(f"  prompt -> {prompt_path}")
            print(f"  command: {' '.join(command)}")
        return 0

    _write_next_prompt(prompt, str(prompt_path))
    max_output = None if args.max_output_bytes == 0 else args.max_output_bytes
    result = execute_agent_command(
        command,
        cwd=str(project_dir),
        timeout=args.timeout,
        max_output_bytes=max_output,
    )
    outcome = classify_run_outcome(result, failure_outcome=args.failure_outcome)
    summary = (
        args.summary.strip()
        if args.summary
        else default_run_summary(command, result, outcome)
    )
    stdout_tail = tail(result.stdout)
    stderr_tail = tail(result.stderr)

    run_result = AgentRunResult(
        task_id=task.id,
        node_id=task.node_id,
        command=command,
        ran=result.ran,
        return_code=result.return_code,
        outcome=outcome,
        summary=summary,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        timed_out=result.timed_out,
        output_limit_exceeded=result.output_limit_exceeded,
        error=result.error,
        duration_seconds=result.duration_seconds,
    )

    # A spawn error is a harness/config failure, not a proof attempt: never record
    # it against the node and always exit non-zero.
    recorded = False
    if not args.no_record and not result.spawn_error:
        details = args.details or _agent_run_details(result, stdout_tail, stderr_tail)
        attempt = record_memory_attempt(
            config.agent_memory_path,
            task.node_id,
            outcome=outcome,
            summary=summary,
            actor=args.actor or "agent-run",
            tool=args.tool or command[0],
            details=details,
            next_step=args.next_step,
            input_hash=node_input_hash(project.by_id()[task.node_id]),
            max_attempts=args.max_attempts,
        )
        run_result.memory = attempt.to_dict()
        recorded = True
    run_result.recorded = recorded

    out_payload: dict[str, object] = {
        **run_result.to_dict(),
        "prompt_path": str(prompt_path),
        "message": f"Ran {task.id}.",
        **metadata,
    }
    if args.json:
        print(json.dumps(out_payload, indent=2))
    else:
        print(f"agent-run {task.id} -> {outcome}")
        print(f"  prompt -> {prompt_path}")
        if result.error:
            print(f"  {result.error}", file=sys.stderr)
        if recorded:
            print(f"  memory recorded -> {config.agent_memory_path}")

    if result.spawn_error:
        return 1
    if args.fail_on_failure and outcome != "succeeded":
        return 5
    return 0


def _completed_node_ids(project: BlueprintProject) -> set[str]:
    return {
        node.id
        for node in project.nodes
        if node.status.formal in COMPLETE_FORMAL_STATUSES
        or node.status.agent is AgentStatus.SOLVED
    }


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
            print(f"[{_paint_doctor_status(check.status)}] {check.name}: {check.message}")
    return 7 if args.strict and report.has_errors else 0


def _paint_doctor_status(status: str) -> str:
    if status == "error":
        return console.error(status)
    if status == "warning":
        return console.warning(status)
    if status == "ok":
        return console.success(status)
    return status


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
    elif args.markdown:
        print(render_explanations_markdown(explanations, project), end="")
    else:
        print(render_explanations(explanations), end="")
    return 0


def _resolve_index_files(args: argparse.Namespace) -> list[Path]:
    """Resolve the ``.thy`` files for a source-only command from its args.

    Honors explicit positional paths first, then ``--root DIR`` (optionally with
    ``--session NAME``), then falls back to the discovered default session dir.
    """
    explicit = [Path(p).resolve() for p in getattr(args, "theory", []) or []]
    root_dir = getattr(args, "root", None)
    session = getattr(args, "session", None)
    if explicit and root_dir:
        raise BlueprintError("pass either theory paths or --root, not both")
    if explicit:
        missing = [p for p in explicit if not p.is_file()]
        if missing:
            raise BlueprintError(f"theory file not found: {missing[0]}")
        return explicit
    base = Path(root_dir).resolve() if root_dir else default_session_dir()
    if not base.exists():
        raise BlueprintError(f"theory root not found: {base}")
    try:
        files = session_theory_files(base, session)
    except ValueError as exc:
        raise BlueprintError(str(exc)) from exc
    if not files:
        raise BlueprintError(f"no .thy files found under {base}")
    return files


def cmd_import_theory(args: argparse.Namespace) -> int:
    if args.root:
        files = _resolve_index_files(args)
        index = build_index(files)
        if index.has_import_cycle:
            raise BlueprintError(
                "theory import graph contains a cycle; cannot derive an acyclic "
                "blueprint (resolve the cyclic imports or import files individually)"
            )
        facts = index.imported_facts()
    else:
        if not args.theory:
            raise BlueprintError("provide one or more theory paths or use --root DIR")
        facts = []
        for theory_path in args.theory:
            resolved = Path(theory_path).resolve()
            if not resolved.is_file():
                raise BlueprintError(f"theory file not found: {resolved}")
            facts.extend(import_theory_file(resolved))
    blueprint = render_imported_blueprint(facts, project_name=args.project_name)
    if args.review_output:
        review_output = Path(args.review_output).resolve()
        if review_output.exists() and not args.force:
            raise BlueprintError(f"refusing to overwrite {review_output}; pass --force")
        review_output.parent.mkdir(parents=True, exist_ok=True)
        review_output.write_text(
            json.dumps(imported_theory_review(facts), indent=2), encoding="utf-8"
        )
        print(f"import review -> {review_output}", file=sys.stderr)
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


def _theory_index_summary(index: SourceIndex) -> str:
    lines = [
        f"theories: {len(index.theory_order)}",
        f"entries:  {len(index.entries)}",
        f"sorry/oops markers: {len(index.sorries)}",
    ]
    if index.has_import_cycle:
        lines.append("WARNING: theory import graph contains a cycle")
    for theory in index.theory_order:
        deps, _ = index.theory_deps(theory)
        count = sum(1 for entry in index.entries if entry.theory == theory)
        dep_note = f" imports {', '.join(deps)}" if deps else ""
        lines.append(f"  {theory}: {count} entr{'y' if count == 1 else 'ies'}{dep_note}")
    return "\n".join(lines)


def cmd_theory_index(args: argparse.Namespace) -> int:
    if args.mermaid and args.json:
        raise BlueprintError("theory-index --mermaid and --json are mutually exclusive")
    if args.mermaid:
        conflicting = [
            flag
            for flag, active in (
                ("--callers", args.callers is not None),
                ("--callees", args.callees is not None),
                ("--deps", args.deps is not None),
                ("--sorry", args.sorry),
                ("--unreferenced", args.unreferenced),
                ("--counts", args.counts),
            )
            if active
        ]
        if conflicting:
            raise BlueprintError(
                "theory-index --mermaid is a standalone output mode and cannot be "
                f"combined with {', '.join(conflicting)}"
            )
    files = _resolve_index_files(args)
    index = build_index(files)

    if args.callers is not None:
        result = index.callers(args.callers, transitive=args.transitive)
        if args.json:
            print(json.dumps({"callers": result}, indent=2))
        else:
            print("\n".join(result) if result else "(no callers)")
        return 0
    if args.callees is not None:
        result = index.callees(args.callees, transitive=args.transitive)
        if args.json:
            print(json.dumps({"callees": result}, indent=2))
        else:
            print("\n".join(result) if result else "(no callees)")
        return 0
    if args.deps is not None:
        forward, reverse = index.theory_deps(args.deps)
        if args.json:
            print(json.dumps({"imports": forward, "imported_by": reverse}, indent=2))
        else:
            print(f"imports: {', '.join(forward) if forward else '(none)'}")
            print(f"imported_by: {', '.join(reverse) if reverse else '(none)'}")
        return 0
    if args.sorry:
        markers = [
            {"theory": m.theory, "line": m.line, "token": m.token, "entry": m.entry}
            for m in index.sorries
        ]
        if args.json:
            print(json.dumps({"sorries": markers}, indent=2))
        else:
            if not markers:
                print("(no sorry/oops markers)")
            for marker in markers:
                entry = marker["entry"] or "(top level)"
                print(f"{marker['theory']}:{marker['line']} {marker['token']} in {entry}")
        return 0
    if args.unreferenced:
        result = index.unreferenced_entries()
        if args.json:
            print(json.dumps({"unreferenced": result}, indent=2))
        else:
            if not result:
                print("(no unreferenced entries)")
            else:
                print("\n".join(result))
        return 0

    if args.counts:
        counts = index.counts()
        if args.json:
            print(json.dumps({"counts": counts}, indent=2))
        else:
            print(f"theories:    {counts['theories']}")
            print(f"entries:     {counts['entries']}")
            print(f"sorry/oops entries: {counts['sorry_entries']}")
            print(f"unreferenced: {counts['unreferenced']}")
            print(f"import edges: {counts['import_edges']}")
        return 0

    if args.mermaid:
        print(render_theory_index_mermaid(index), end="")
        return 0

    if args.json:
        print(json.dumps(index.to_dict(), indent=2))
    else:
        print(_theory_index_summary(index))
    return 0


def cmd_search_facts(args: argparse.Namespace) -> int:
    files = _resolve_index_files(args)
    index = build_index(files)
    kinds = set(args.kind) if args.kind else None

    if args.query is not None:
        hits = search_index(index, args.query, kinds=kinds, limit=args.limit)
        if args.json:
            print(
                json.dumps(
                    {"query": args.query, "hits": [hit.to_dict() for hit in hits]},
                    indent=2,
                )
            )
        elif args.markdown:
            print(render_hits_markdown(args.query, hits), end="")
        else:
            print(render_hits(args.query, hits), end="")
        return 0

    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    matches = match_missing_facts(project, index, limit=args.limit)
    if args.json:
        print(
            json.dumps(
                {"matches": [match.to_dict() for match in matches]}, indent=2
            )
        )
    elif args.markdown:
        print(render_matches_markdown(matches), end="")
    else:
        print(render_matches(matches), end="")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isabelle-blueprint",
        description="Isabelle-aware blueprint tooling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""common workflows:
  isabelle-blueprint init my-formalization --template agent-ready
  isabelle-blueprint check . --strict
  isabelle-blueprint roadmap . --write
  isabelle-blueprint web . --serve

Run `isabelle-blueprint init --list-templates` to inspect scaffold choices.""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="when to colourise human-facing output (default: auto; honours NO_COLOR)",
    )
    parser.add_argument(
        "--no-color",
        action="store_const",
        const="never",
        dest="color",
        help="disable coloured output (alias for --color never)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a fresh blueprint project")
    p_init.add_argument(
        "project_dir", nargs="?", default=".", help="target directory (default: cwd)"
    )
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.add_argument(
        "--list-templates", action="store_true", help="list starter templates and exit"
    )
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
        help=(
            "max seconds to wait for `isabelle build` before aborting "
            "(overrides [isabelle].timeout)"
        ),
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
        type=_positive_int,
        default=None,
        metavar="N",
        help="forward `-j N` to `isabelle build` to parallelise upstream session builds",
    )
    p_check.add_argument(
        "--watch",
        action="store_true",
        help="re-run the check whenever the blueprint sources change (Ctrl-C to stop)",
    )
    p_check.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="polling interval for --watch (default: 1.0)",
    )
    _add_fail_on_argument(p_check)
    p_check.set_defaults(func=cmd_check)

    p_graph = sub.add_parser("graph", help="emit DOT/JSON/SVG/Mermaid/GraphML/D2 dependency graph")
    p_graph.add_argument("project_dir", nargs="?", default=".")
    p_graph.add_argument(
        "--format",
        choices=("all", "dot", "json", "svg", "mermaid", "graphml", "d2"),
        default="all",
        help="which artifact(s) to write (default: all)",
    )
    p_graph.add_argument(
        "--focus",
        metavar="NODE",
        default=None,
        help="restrict the graph to NODE and its dependency neighbourhood",
    )
    p_graph.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="with --focus, include nodes within N dependency hops (default: unlimited)",
    )
    p_graph.add_argument(
        "--roots-only",
        action="store_true",
        help="prune the graph to root nodes (those nothing else uses); "
        "composes with --focus/--depth",
    )
    p_graph.set_defaults(func=cmd_graph)

    p_scorecard = sub.add_parser(
        "scorecard",
        help="grade overall project health as one weighted 0-100 score (A+...F)",
    )
    p_scorecard.add_argument("project_dir", nargs="?", default=".")
    p_scorecard.add_argument(
        "--json", action="store_true", help="emit the scorecard as JSON"
    )
    p_scorecard.add_argument(
        "--markdown",
        action="store_true",
        help=(
            "also write the rendered Markdown scorecard to "
            "build/scorecard.md under the configured build_dir (composes with "
            "the gates and --json; does not change stdout or the exit code)"
        ),
    )
    p_scorecard.add_argument(
        "--min-grade",
        type=_grade_arg,
        metavar="GRADE",
        help=(
            "exit non-zero (5) if the overall grade is below GRADE "
            f"(one of {', '.join(ALL_GRADES)}; case-insensitive). An ungradeable "
            "(empty) project never fails the gate."
        ),
    )
    p_scorecard.add_argument(
        "--min-score",
        type=_score_arg,
        metavar="N",
        help=(
            "exit non-zero (5) if the overall score is below N (an integer 0-100). "
            "Composes with --min-grade (fails if either threshold is unmet). An "
            "ungradeable (empty) project never fails the gate."
        ),
    )
    p_scorecard.add_argument(
        "--min-component",
        action="append",
        type=_min_component_arg,
        default=[],
        metavar="NAME=PCT",
        help=(
            "exit non-zero (5) if the named component score is below PCT percent "
            f"(NAME one of {', '.join(SCORE_COMPONENTS)}; PCT an integer 0-100). "
            "Repeatable; composes with --min-grade/--min-score (fails if any "
            "threshold is unmet). A component with no defined score never fails "
            "the gate."
        ),
    )
    p_scorecard.set_defaults(func=cmd_scorecard)

    p_tags = sub.add_parser(
        "tags",
        help="roll up node counts and coverage per blueprint tag",
    )
    p_tags.add_argument("project_dir", nargs="?", default=".")
    p_tags_format = p_tags.add_mutually_exclusive_group()
    p_tags_format.add_argument(
        "--json", action="store_true", help="emit the tag roll-up as JSON"
    )
    p_tags_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the tag roll-up as a Markdown table",
    )
    p_tags_format.add_argument(
        "--csv",
        action="store_true",
        help="emit the tag roll-up as CSV (one row per tag plus an untagged row)",
    )
    p_tags.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="NAME",
        help="restrict the roll-up to the named tag (repeatable)",
    )
    p_tags.add_argument(
        "--fail-under",
        type=_score_arg,
        metavar="PCT",
        help=(
            "exit non-zero (5) if any gated tag's proved-coverage is below PCT "
            "(an integer 0-100). Honours --tag; tags with no formal targets never "
            "fail the gate."
        ),
    )
    p_tags.set_defaults(func=cmd_tags)

    p_path = sub.add_parser(
        "path",
        help="find the shortest dependency path between two node ids",
    )
    p_path.add_argument("source", help="source node id")
    p_path.add_argument("target", help="target node id")
    p_path.add_argument("project_dir", nargs="?", default=".")
    p_path_format = p_path.add_mutually_exclusive_group()
    p_path_format.add_argument(
        "--json", action="store_true", help="emit the path report as JSON"
    )
    p_path_format.add_argument(
        "--markdown",
        action="store_true",
        help="render the path report as a Markdown document",
    )
    p_path.add_argument(
        "--all",
        action="store_true",
        dest="all_paths",
        help="enumerate all shortest paths of equal minimal length",
    )
    p_path.set_defaults(func=cmd_path)

    p_lint = sub.add_parser("lint", help="run structural and quality checks on the blueprint")
    p_lint.add_argument("project_dir", nargs="?", default=".")
    p_lint.add_argument(
        "--json",
        action="store_true",
        help="emit findings as JSON (alias for --format json)",
    )
    p_lint.add_argument(
        "--format",
        choices=("text", "json", "sarif", "markdown"),
        default=None,
        help=(
            "output format: text (default), json, sarif (SARIF 2.1.0 for code "
            "scanning), or markdown"
        ),
    )
    p_lint.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero (2) when any error-severity finding is present",
    )
    p_lint.add_argument(
        "--fix",
        action="store_true",
        help="drop dangling 'uses' references and rewrite affected Markdown sources",
    )
    p_lint.add_argument(
        "--fix-dry-run",
        action="store_true",
        help="with --fix, report what would change without writing any files",
    )
    p_lint.set_defaults(func=cmd_lint)

    p_gate = sub.add_parser(
        "gate",
        help="run a single pass/fail CI gate (lint errors + coverage + status policy)",
    )
    p_gate.add_argument("project_dir", nargs="?", default=".")
    p_gate_format = p_gate.add_mutually_exclusive_group()
    p_gate_format.add_argument(
        "--json", action="store_true", help="emit the gate result as JSON"
    )
    p_gate_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the gate result as a Markdown report (heading, verdict, check table)",
    )
    p_gate.add_argument(
        "--min-coverage",
        type=int,
        default=None,
        metavar="PCT",
        help="fail (exit 5) when proved coverage is below PCT percent, or undefined",
    )
    p_gate.add_argument(
        "--fail-on",
        action="append",
        choices=(*FAIL_ON_STATUSES, FAIL_ON_PROBLEM_ALIAS),
        metavar="STATUS",
        help="fail when any node has this formal status (repeatable; "
        f"'{FAIL_ON_PROBLEM_ALIAS}' expands to all problem statuses)",
    )
    p_gate.add_argument(
        "--min-grade",
        type=_grade_arg,
        default=None,
        metavar="GRADE",
        help=(
            "fail (exit 5) when the project scorecard grade is below GRADE "
            f"(one of {', '.join(ALL_GRADES)}; case-insensitive)"
        ),
    )
    p_gate.set_defaults(func=cmd_gate)

    p_prom = sub.add_parser(
        "prometheus",
        help="emit blueprint status as a Prometheus text-exposition payload",
    )
    p_prom.add_argument("project_dir", nargs="?", default=".")
    p_prom.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="PATH",
        help="write the metrics to PATH (e.g. a node-exporter textfile) instead of stdout",
    )
    p_prom.add_argument(
        "--no-burndown",
        action="store_true",
        help="skip the burndown ETA gauge (do not read trends.json)",
    )
    p_prom.add_argument(
        "--label",
        action="append",
        type=_label_arg,
        metavar="KEY=VALUE",
        help=(
            "inject an extra static label onto every metric line; "
            "repeatable (e.g. --label env=ci --label team=hol)"
        ),
    )
    p_prom.set_defaults(func=cmd_prometheus)

    p_effort = sub.add_parser(
        "effort",
        help="report effort-weighted formalization progress (uses optional node 'effort')",
    )
    p_effort.add_argument("project_dir", nargs="?", default=".")
    p_effort_format = p_effort.add_mutually_exclusive_group()
    p_effort_format.add_argument(
        "--json", action="store_true", help="emit the effort report as JSON"
    )
    p_effort_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the effort report as a Markdown document with summary tables",
    )
    p_effort.add_argument(
        "--by-tag",
        action="store_true",
        help="additionally group effort-weighted progress per tag",
    )
    p_effort.add_argument(
        "--fail-under",
        type=_percent,
        default=None,
        metavar="PCT",
        help=(
            "fail (exit 5) when effort-weighted coverage is below PCT percent "
            "(0-100), or undefined"
        ),
    )
    p_effort.set_defaults(func=cmd_effort)

    p_hooks = sub.add_parser(
        "hooks",
        help="print or write a .pre-commit-config.yaml wiring fmt --check and lint --strict",
    )
    p_hooks.add_argument("project_dir", nargs="?", default=".")
    p_hooks.add_argument(
        "--write",
        action="store_true",
        help="write .pre-commit-config.yaml into the project (default: print to stdout)",
    )
    p_hooks.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing .pre-commit-config.yaml when used with --write",
    )
    p_hooks.set_defaults(func=cmd_hooks)

    p_notify = sub.add_parser(
        "notify",
        help="build (and optionally POST) a status notification for a chat webhook",
    )
    p_notify.add_argument("project_dir", nargs="?", default=".")
    p_notify.add_argument(
        "--format",
        choices=NOTIFY_FORMATS,
        default="slack",
        help="webhook payload format (default: slack)",
    )
    p_notify.add_argument(
        "--url",
        default=None,
        metavar="WEBHOOK",
        help="webhook URL to POST to (required with --send)",
    )
    p_notify.add_argument(
        "--send",
        action="store_true",
        help="actually POST the payload (default: dry-run, just print it)",
    )
    p_notify.add_argument(
        "--allow-http",
        action="store_true",
        help="permit POSTing to a plaintext http:// URL (default: https only)",
    )
    p_notify.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="network timeout in seconds when sending (default: 10)",
    )
    p_notify.add_argument(
        "--no-burndown",
        action="store_true",
        help="skip the burndown ETA line (do not read trends.json)",
    )
    p_notify.set_defaults(func=cmd_notify)

    p_blame = sub.add_parser(
        "blame",
        help="show per-node provenance from git history and agent memory",
    )
    p_blame.add_argument("project_dir", nargs="?", default=".")
    p_blame.add_argument(
        "--node-id",
        "--node",
        dest="node_id",
        default=None,
        metavar="ID",
        help="restrict output to a single node id (default: all nodes)",
    )
    p_blame_format = p_blame.add_mutually_exclusive_group()
    p_blame_format.add_argument(
        "--json", action="store_true", help="emit provenance as JSON"
    )
    p_blame_format.add_argument(
        "--table",
        action="store_true",
        help="compact one-row-per-node table instead of the default detailed view",
    )
    p_blame_format.add_argument(
        "--markdown",
        action="store_true",
        help="render provenance as a Markdown table",
    )
    p_blame.set_defaults(func=cmd_blame)

    p_critical = sub.add_parser(
        "critical-path",
        help="show the longest remaining incomplete dependency chain and bottlenecks",
    )
    p_critical.add_argument("project_dir", nargs="?", default=".")
    p_critical_fmt = p_critical.add_mutually_exclusive_group()
    p_critical_fmt.add_argument("--json", action="store_true", help="emit the analysis as JSON")
    p_critical_fmt.add_argument(
        "--markdown",
        action="store_true",
        help="print the report as plain Markdown (no colour) to stdout",
    )
    p_critical_fmt.add_argument(
        "--mermaid",
        action="store_true",
        help="emit the critical chain as a Mermaid flowchart (bottlenecks highlighted)",
    )
    p_critical.add_argument(
        "--top",
        type=_positive_int,
        default=5,
        metavar="N",
        help="number of bottleneck nodes to display (default: 5)",
    )
    p_critical.add_argument(
        "--goal",
        default=None,
        metavar="NODE",
        help="focus the output on a single goal node's critical chain",
    )
    p_critical.add_argument(
        "--fail-on-cycle",
        action="store_true",
        help="exit non-zero (2) when a dependency cycle is present",
    )
    p_critical.add_argument(
        "--write",
        action="store_true",
        help="write critical-path.json and critical-path.md into the build dir "
        "in addition to printing",
    )
    p_critical.set_defaults(func=cmd_critical_path)

    p_impact = sub.add_parser(
        "impact",
        help="show the downstream blast radius of a node (what depends on it)",
    )
    p_impact.add_argument("project_dir", nargs="?", default=".")
    p_impact.add_argument(
        "--node",
        default=None,
        metavar="NODE",
        help="focus on a single node's blast radius (omit for a project-wide ranking)",
    )
    p_impact.add_argument("--json", action="store_true", help="emit the analysis as JSON")
    p_impact.add_argument(
        "--format",
        choices=("text", "json", "dot", "mermaid", "csv"),
        default=None,
        help=(
            "output format (default: text); `dot` emits a Graphviz subgraph of the "
            "node's blast radius and requires --node. `mermaid` emits the same blast "
            "radius as a Mermaid flowchart and likewise requires --node. `csv` emits "
            "one row per node ranked by blast radius, or per dependent when --node is "
            "given. `--json` is an alias for `--format json`."
        ),
    )
    p_impact.add_argument(
        "--top",
        type=_positive_int,
        default=10,
        metavar="N",
        help="maximum rows to display, and ranking entries to keep in --json (default: 10)",
    )
    p_impact.set_defaults(func=cmd_impact)

    p_stats = sub.add_parser(
        "stats", help="aggregate agent-memory analytics (outcomes, success rate, per-node)"
    )
    p_stats.add_argument("project_dir", nargs="?", default=".")
    p_stats_format = p_stats.add_mutually_exclusive_group()
    p_stats_format.add_argument("--json", action="store_true", help="emit stats as JSON")
    p_stats_format.add_argument(
        "--markdown", action="store_true", help="emit stats as a Markdown document"
    )
    p_stats.add_argument(
        "--min-success-rate",
        type=_percent,
        default=None,
        metavar="PCT",
        help=(
            "fail (exit 5) when the overall proof-attempt success rate is below "
            "PCT percent (0-100); not enforced when there are no resolved attempts"
        ),
    )
    p_stats.set_defaults(func=cmd_stats)

    p_staleness = sub.add_parser(
        "staleness",
        help="audit trusted nodes whose found/proved status rests on shaky dependencies",
    )
    p_staleness.add_argument("project_dir", nargs="?", default=".")
    p_staleness_format = p_staleness.add_mutually_exclusive_group()
    p_staleness_format.add_argument(
        "--json", action="store_true", help="emit the analysis as JSON"
    )
    p_staleness_format.add_argument(
        "--markdown",
        action="store_true",
        help="render the trust audit as a Markdown table (no colour)",
    )
    p_staleness_format.add_argument(
        "--csv",
        action="store_true",
        help=(
            "emit one CSV row per flagged trusted node "
            "(columns: node_id, severity, cause_count, first_cause)"
        ),
    )
    p_staleness.add_argument(
        "--top",
        type=_positive_int,
        default=10,
        metavar="N",
        help="maximum stale nodes to display / keep in --json (default: 10)",
    )
    p_staleness.add_argument(
        "--max-causes",
        type=_positive_int,
        default=5,
        metavar="N",
        help="maximum causes to show per stale node (default: 5)",
    )
    p_staleness.add_argument(
        "--fail-on-problem",
        action="store_true",
        help="exit non-zero (5) when any trusted node rests on broken/missing deps",
    )
    p_staleness.add_argument(
        "--fail-on-outdated",
        action="store_true",
        help=(
            "exit non-zero (5) when any trusted node is outdated (rests on a "
            "dependency that is stale or was re-checked more recently than the node)"
        ),
    )
    p_staleness.set_defaults(func=cmd_staleness)

    p_version = sub.add_parser("version", help="print version, Python, and schema information")
    p_version.add_argument("--json", action="store_true", help="emit version info as JSON")
    p_version.set_defaults(func=cmd_version)

    p_completion = sub.add_parser(
        "completion", help="print a shell completion script (bash, zsh, fish, or powershell)"
    )
    p_completion.add_argument("shell", choices=SUPPORTED_SHELLS)
    p_completion.add_argument(
        "--install",
        action="store_true",
        help="write the script to a per-user completion path instead of stdout",
    )
    p_completion.add_argument(
        "--dest",
        help="install destination path (implies --install; parent dirs are created)",
    )
    p_completion.set_defaults(func=cmd_completion)

    p_diff = sub.add_parser(
        "diff", help="compare the current blueprint against a saved project.json"
    )
    p_diff.add_argument("baseline", help="path to a baseline project.json")
    p_diff.add_argument("project_dir", nargs="?", default=".")
    p_diff_format = p_diff.add_mutually_exclusive_group()
    p_diff_format.add_argument("--json", action="store_true", help="emit the diff as JSON")
    p_diff_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the diff as a Markdown summary",
    )
    p_diff.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit non-zero (5) when a node regresses or is removed vs the baseline",
    )
    p_diff.add_argument(
        "--fail-on-change",
        action="store_true",
        help="exit non-zero (5) when there is any difference vs the baseline "
        "(added, removed, or changed node), not just regressions",
    )
    p_diff.set_defaults(func=cmd_diff)

    p_history = sub.add_parser("history", help="summarize trends.json coverage history")
    p_history.add_argument("project_dir", nargs="?", default=".")
    p_history_format = p_history.add_mutually_exclusive_group()
    p_history_format.add_argument(
        "--json", action="store_true", help="emit the summary as JSON"
    )
    p_history_format.add_argument(
        "--csv", action="store_true", help="emit the trend snapshots as CSV"
    )
    p_history_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the trend snapshots as a Markdown table",
    )
    p_history.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        metavar="N",
        help="only consider the most recent N entries",
    )
    p_history.set_defaults(func=cmd_history)

    p_burndown = sub.add_parser(
        "burndown",
        help="forecast an ETA to full proved coverage from trends.json",
    )
    p_burndown.add_argument("project_dir", nargs="?", default=".")
    p_burndown_format = p_burndown.add_mutually_exclusive_group()
    p_burndown_format.add_argument(
        "--json", action="store_true", help="emit the forecast as JSON"
    )
    p_burndown_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the forecast as a Markdown summary",
    )
    p_burndown.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        metavar="N",
        help="only display the most recent N snapshots (velocity always uses all)",
    )
    p_burndown.add_argument(
        "--window",
        type=_positive_int,
        default=5,
        metavar="N",
        help="number of most-recent snapshots used for the recent velocity (default: 5)",
    )
    p_burndown.add_argument(
        "--fail-when-stalled",
        action="store_true",
        help="exit non-zero (5) when work remains but is stalled/regressing/scope-growing",
    )
    p_burndown.set_defaults(func=cmd_burndown)

    p_portfolio = sub.add_parser(
        "portfolio",
        help="aggregate status across every blueprint project under a directory",
    )
    p_portfolio.add_argument(
        "root_dir",
        nargs="?",
        default=".",
        help="directory tree to scan for blueprint projects (default: .)",
    )
    p_portfolio_format = p_portfolio.add_mutually_exclusive_group()
    p_portfolio_format.add_argument(
        "--json", action="store_true", help="emit the roll-up as JSON"
    )
    p_portfolio_format.add_argument(
        "--csv",
        action="store_true",
        help="emit one CSV row per project (header + name, path, counts, status)",
    )
    p_portfolio_format.add_argument(
        "--markdown",
        action="store_true",
        help="emit the roll-up as Markdown (heading, totals line, project table)",
    )
    p_portfolio.add_argument(
        "--fail-on-problem",
        action="store_true",
        help=(
            "exit non-zero (5) when any project has problems, dependency "
            "cycles, or fails to load"
        ),
    )
    p_portfolio.add_argument(
        "--min-coverage",
        type=_score_arg,
        metavar="PCT",
        default=None,
        help=(
            "exit non-zero (5) when any project's proved-coverage is below PCT "
            "(an integer from 0 to 100; a cross-project coverage floor); projects "
            "with undefined coverage (no formal targets, or load errors) are "
            "excluded from failures; composes with --fail-on-problem"
        ),
    )
    p_portfolio.set_defaults(func=cmd_portfolio)

    p_assign = sub.add_parser("assign", help="record or list per-node ownership")
    p_assign.add_argument(
        "node_id",
        nargs="?",
        default=None,
        help="node id (omit to list all assignments)",
    )
    p_assign.add_argument("--project-dir", dest="project_dir", default=".")
    p_assign.add_argument("--owner", default=None, help="owner to assign to the node")
    p_assign.add_argument("--note", default=None, help="optional note stored with the assignment")
    p_assign.add_argument("--clear", action="store_true", help="remove the assignment for the node")
    p_assign.add_argument("--json", action="store_true", help="emit assignments as JSON")
    p_assign.set_defaults(func=cmd_assign)

    p_rename = sub.add_parser("rename", help="rename a node id across blueprint sources and stores")
    p_rename.add_argument("old_id", help="existing node id")
    p_rename.add_argument("new_id", help="new node id")
    p_rename.add_argument("--project-dir", dest="project_dir", default=".")
    p_rename.add_argument(
        "--dry-run", action="store_true", help="show changes without writing files"
    )
    p_rename.add_argument("--json", action="store_true", help="emit the rename result as JSON")
    p_rename.set_defaults(func=cmd_rename)

    p_fmt = sub.add_parser(
        "fmt", help="rewrite Markdown blueprints into canonical interchange form"
    )
    p_fmt.add_argument("project_dir", nargs="?", default=".")
    p_fmt.add_argument(
        "--check",
        action="store_true",
        help="report non-canonical files and exit non-zero (10) without writing",
    )
    p_fmt.add_argument(
        "--diff",
        action="store_true",
        help="print a unified diff of canonicalisation without writing; exits 10 on drift",
    )
    p_fmt.add_argument("--json", action="store_true", help="emit the format result as JSON")
    p_fmt.set_defaults(func=cmd_fmt)

    p_dump = sub.add_parser("dump", help="run or inspect Isabelle PIDE dump output")
    p_dump.add_argument("project_dir", nargs="?", default=".")
    p_dump.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_dump.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "max seconds to wait for `isabelle dump` before aborting "
            "(overrides [isabelle].timeout)"
        ),
    )
    p_dump.add_argument(
        "--from", dest="from_dir", default=None, help="inspect an existing dump directory"
    )
    p_dump.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if dump execution/inspection fails",
    )
    p_dump.add_argument(
        "--json",
        action="store_true",
        help="emit the dump report as JSON (the same report written to disk)",
    )
    p_dump.set_defaults(func=cmd_dump)

    p_compat = sub.add_parser(
        "compat", help="check Isabelle/AFP version pins and session visibility"
    )
    p_compat.add_argument("project_dir", nargs="?", default=".")
    p_compat.add_argument("--isabelle", default=None, help="path to the `isabelle` binary")
    p_compat.add_argument(
        "--strict", action="store_true", help="exit non-zero on compatibility errors"
    )
    p_compat.add_argument(
        "--json",
        action="store_true",
        help="emit the compatibility report as JSON (the same report written to disk)",
    )
    p_compat.set_defaults(func=cmd_compat)

    p_web = sub.add_parser("web", help="render the static HTML site")
    p_web.add_argument("project_dir", nargs="?", default=".")
    p_web.add_argument(
        "--watch", action="store_true", help="re-render when blueprint inputs change"
    )
    p_web.add_argument(
        "--serve", action="store_true", help="serve the rendered site while watching"
    )
    p_web.add_argument(
        "--host", default="127.0.0.1", help="host for --serve (default: 127.0.0.1)"
    )
    p_web.add_argument(
        "--port", type=int, default=8000, help="port for --serve (default: 8000)"
    )
    p_web.add_argument(
        "--interval", type=float, default=1.0, help="watch polling interval in seconds"
    )
    p_web.add_argument("--allow-ci", action="store_true", help="allow --serve when CI=true")
    p_web.set_defaults(func=cmd_web)

    p_serve = sub.add_parser("serve", help="serve and live-rebuild the static HTML site")
    p_serve.add_argument("project_dir", nargs="?", default=".")
    p_serve.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="port to bind (default: 8000)")
    p_serve.add_argument(
        "--interval", type=float, default=1.0, help="watch polling interval in seconds"
    )
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
    p_tasks.add_argument(
        "--github-sync-pull",
        action="store_true",
        help="read-only: fetch tracked issues' open/closed state into build/github-sync-state.json",
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
        help=(
            "path to persistent node-to-issue mapping "
            "(default: .isabelle-blueprint/github-sync.json)"
        ),
    )
    p_tasks.add_argument(
        "--github-label",
        action="append",
        default=None,
        help="extra label to add to generated GitHub issue drafts; repeat to add multiple labels",
    )
    p_tasks.add_argument(
        "--github-assignee",
        action="append",
        default=None,
        help=(
            "GitHub username to assign to generated issue drafts; repeat to add "
            "multiple assignees"
        ),
    )
    p_tasks.add_argument(
        "--tracker-export",
        choices=TRACKER_EXPORTS,
        default=None,
        metavar="TRACKER",
        help="also write build/tasks-<tracker>.csv for import into jira or linear",
    )
    _add_ready_task_filter_arguments(p_tasks)
    _add_watch_arguments(p_tasks, action="task generation")
    p_tasks.set_defaults(func=cmd_tasks)

    p_next = sub.add_parser("next", help="print the next ready task prompt")
    p_next.add_argument("project_dir", nargs="?", default=".")
    p_next.add_argument(
        "--node",
        default=None,
        metavar="NODE_OR_TASK",
        help=(
            "print the ready prompt for this node id or task id instead of the "
            "suggested next task"
        ),
    )
    p_next.add_argument("--json", action="store_true", help="emit task metadata and prompt JSON")
    p_next.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="also write the selected prompt to PATH",
    )
    _add_ready_task_filter_arguments(p_next)
    p_next.set_defaults(func=cmd_next)

    p_attempt = sub.add_parser(
        "attempt", help="prepare a proof-attempt handoff and optional check/memory update"
    )
    p_attempt.add_argument("project_dir", nargs="?", default=".")
    p_attempt.add_argument(
        "--node",
        default=None,
        metavar="NODE_OR_TASK",
        help="prepare this ready node/task instead of the suggested next task",
    )
    p_attempt.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="write the prompt to PATH (default: build/attempts/<task-id>.md)",
    )
    p_attempt.add_argument("--json", action="store_true", help="emit machine-readable attempt JSON")
    p_attempt.add_argument(
        "--sledgehammer",
        action="store_true",
        help="append a Sledgehammer-first strategy block to the handoff prompt",
    )
    p_attempt.add_argument(
        "--check", action="store_true", help="run `check` after writing the handoff prompt"
    )
    p_attempt.add_argument(
        "--isabelle", default=None, help="path to the `isabelle` binary for --check"
    )
    p_attempt.add_argument("--timeout", type=float, default=None, help="timeout for --check")
    p_attempt.add_argument(
        "--incremental", action="store_true", help="use check-cache.json during --check"
    )
    p_attempt.add_argument(
        "--jobs",
        type=_positive_int,
        default=None,
        metavar="N",
        help="forward `-j N` during --check",
    )
    _add_ready_task_filter_arguments(p_attempt)
    p_attempt.add_argument(
        "--record-outcome",
        choices=sorted(VALID_OUTCOMES),
        default=None,
        help="record post-attempt memory for the selected node",
    )
    p_attempt.add_argument(
        "--summary", default="", help="memory summary required with --record-outcome"
    )
    p_attempt.add_argument("--details", default="", help="longer memory notes for --record-outcome")
    p_attempt.add_argument("--next-step", default=None, help="recommended next action for memory")
    p_attempt.add_argument("--actor", default=None, help="person or agent that made the attempt")
    p_attempt.add_argument("--tool", default=None, help="tool/model used for the attempt")
    p_attempt.add_argument(
        "--max-attempts", type=int, default=20, help="attempts to keep per node"
    )
    p_attempt.set_defaults(func=cmd_attempt)

    p_agent_run = sub.add_parser(
        "agent-run",
        help="run an external solver against the next ready task and record the outcome",
    )
    p_agent_run.add_argument("project_dir", nargs="?", default=".")
    p_agent_run.add_argument(
        "--node",
        default=None,
        metavar="NODE_OR_TASK",
        help="run this ready node/task instead of the suggested next task",
    )
    agent_run_command = p_agent_run.add_mutually_exclusive_group()
    agent_run_command.add_argument(
        "--command",
        default=None,
        metavar="TEMPLATE",
        help=(
            "solver command template, shlex-split (POSIX quoting); supports the "
            "placeholders {prompt_file} {node_id} {task_id} {project_dir}"
        ),
    )
    agent_run_command.add_argument(
        "--exec",
        dest="exec_program",
        default=None,
        metavar="PROGRAM",
        help="solver executable; combine with repeated --arg (argv-native, avoids shell quoting)",
    )
    p_agent_run.add_argument(
        "--arg",
        dest="arg",
        action="append",
        metavar="ARG",
        help="argument for --exec (repeatable; supports the same placeholders)",
    )
    p_agent_run.add_argument(
        "--allow-missing-prompt",
        action="store_true",
        help="permit a command that does not reference {prompt_file}",
    )
    p_agent_run.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        metavar="SECONDS",
        help="kill the solver (and its children) after SECONDS (default: 900)",
    )
    p_agent_run.add_argument(
        "--max-output-bytes",
        type=int,
        default=DEFAULT_MAX_OUTPUT_BYTES,
        metavar="N",
        help="cap captured stdout+stderr; 0 disables the cap (default: 10 MiB)",
    )
    p_agent_run.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=(
            "write the prompt to PATH (default: build/agent-run/<task>.md; "
            "relative paths resolve against the project dir)"
        ),
    )
    p_agent_run.add_argument(
        "--dry-run",
        action="store_true",
        help="select and render the task and resolve the command without running or recording",
    )
    p_agent_run.add_argument("--json", action="store_true", help="emit machine-readable run JSON")
    _add_ready_task_filter_arguments(p_agent_run)
    p_agent_run.add_argument(
        "--failure-outcome",
        choices=("failed", "blocked", "needs_human"),
        default="failed",
        help="memory outcome recorded when the solver fails (default: failed)",
    )
    p_agent_run.add_argument(
        "--no-record", action="store_true", help="do not write an agent-memory attempt"
    )
    p_agent_run.add_argument("--summary", default="", help="override the recorded memory summary")
    p_agent_run.add_argument("--details", default="", help="override the recorded memory details")
    p_agent_run.add_argument("--next-step", default=None, help="recommended next action for memory")
    p_agent_run.add_argument(
        "--actor", default=None, help="person or agent that ran the solver (default: agent-run)"
    )
    p_agent_run.add_argument(
        "--tool", default=None, help="tool/model label for memory (default: the executable)"
    )
    p_agent_run.add_argument(
        "--max-attempts", type=int, default=20, help="attempts to keep per node"
    )
    p_agent_run.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="exit 5 when the recorded outcome is not 'succeeded'",
    )
    p_agent_run.set_defaults(func=cmd_agent_run)

    p_report = sub.add_parser("report", help="write JSON and Markdown status reports")
    p_report.add_argument("project_dir", nargs="?", default=".")
    _add_fail_on_argument(p_report)
    _add_watch_arguments(p_report, action="report")
    p_report.set_defaults(func=cmd_report)

    p_status = sub.add_parser("status", help="print a concise project health summary")
    p_status.add_argument("project_dir", nargs="?", default=".")
    p_status_format = p_status.add_mutually_exclusive_group()
    p_status_format.add_argument(
        "--json", action="store_true", help="emit machine-readable status JSON"
    )
    p_status_format.add_argument(
        "--markdown",
        action="store_true",
        help="render the health overview as a Markdown table (mutually exclusive with --json)",
    )
    p_status.add_argument(
        "--top-tasks",
        type=_positive_int,
        default=None,
        metavar="N",
        help="include the first N ready-task summaries in output",
    )
    _add_ready_task_filter_arguments(p_status)
    _add_fail_on_argument(p_status)
    _add_watch_arguments(p_status, action="status summary")
    p_status.set_defaults(func=cmd_status)

    p_roadmap = sub.add_parser("roadmap", help="plan proof-work stages and suggested path")
    p_roadmap.add_argument("project_dir", nargs="?", default=".")
    p_roadmap.add_argument("--json", action="store_true", help="emit machine-readable roadmap JSON")
    p_roadmap.add_argument(
        "--mermaid",
        action="store_true",
        help=(
            "emit a Mermaid flowchart of the staged plan "
            "(mutually exclusive with --json/--mermaid/--csv)"
        ),
    )
    p_roadmap.add_argument(
        "--csv",
        action="store_true",
        help=(
            "emit one CSV row per node in the staged plan "
            "(mutually exclusive with --json/--mermaid/--csv)"
        ),
    )
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
    p_agent_context.add_argument(
        "--json", action="store_true", help="emit machine-readable context JSON"
    )
    p_agent_context.add_argument(
        "--write",
        action="store_true",
        help="write build/agent-context.*, tasks, prompts, roadmap, and project JSON artifacts",
    )
    p_agent_context.add_argument(
        "--max-tasks",
        type=_positive_int,
        default=DEFAULT_AGENT_CONTEXT_TASK_LIMIT,
        help=(
            "maximum ready tasks to embed in the context "
            f"(default: {DEFAULT_AGENT_CONTEXT_TASK_LIMIT})"
        ),
    )
    _add_ready_task_filter_arguments(p_agent_context)
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
    p_doctor.add_argument(
        "--strict", action="store_true", help="exit non-zero when an error is found"
    )
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
    p_memory.add_argument(
        "--summary", default="", help="short attempt summary (required with --record)"
    )
    p_memory.add_argument("--details", default="", help="longer notes for the attempt")
    p_memory.add_argument("--next-step", default=None, help="recommended next action")
    p_memory.add_argument("--actor", default=None, help="person or agent that made the attempt")
    p_memory.add_argument("--tool", default=None, help="tool/model used for the attempt")
    p_memory.add_argument("--max-attempts", type=int, default=20, help="attempts to keep per node")
    p_memory.add_argument("--json", action="store_true", help="list memory as JSON")
    p_memory.set_defaults(func=cmd_memory)

    p_explain = sub.add_parser(
        "explain", help="explain status and dependency problems for blueprint nodes"
    )
    p_explain.add_argument("project_dir", nargs="?", default=".")
    p_explain.add_argument("--node", default=None, help="only explain one node id")
    p_explain_format = p_explain.add_mutually_exclusive_group()
    p_explain_format.add_argument(
        "--json", action="store_true", help="emit machine-readable explanations"
    )
    p_explain_format.add_argument(
        "--markdown", action="store_true", help="render explanations as a Markdown document"
    )
    p_explain.set_defaults(func=cmd_explain)

    p_import = sub.add_parser(
        "import-theory", help="bootstrap a blueprint from Isabelle .thy declarations"
    )
    p_import.add_argument(
        "theory",
        nargs="*",
        help="Isabelle theory file(s) to scan (omit when using --root)",
    )
    p_import.add_argument(
        "--root",
        default=None,
        metavar="DIR",
        help=(
            "import every theory a session ROOT declares under DIR, inferring "
            "cross-theory dependencies from the source reference graph"
        ),
    )
    p_import.add_argument(
        "--session",
        default=None,
        metavar="NAME",
        help="select one session when the ROOT under --root declares several",
    )
    p_import.add_argument("--project-name", default=None, help="title for the generated blueprint")
    p_import.add_argument("--output", default=None, help="write generated blueprint to this file")
    p_import.add_argument(
        "--review-output", default=None, help="write dependency-inference review JSON"
    )
    p_import.add_argument("--force", action="store_true", help="overwrite --output if it exists")
    p_import.set_defaults(func=cmd_import_theory)

    p_tindex = sub.add_parser(
        "theory-index",
        help="source-only analysis of Isabelle .thy files (no Isabelle needed)",
    )
    p_tindex.add_argument(
        "theory",
        nargs="*",
        help="theory file(s) to index (omit to use --root or the discovered session)",
    )
    p_tindex.add_argument(
        "--root",
        default=None,
        metavar="DIR",
        help="index every theory a session ROOT declares under DIR",
    )
    p_tindex.add_argument(
        "--session",
        default=None,
        metavar="NAME",
        help="select one session when the ROOT under --root declares several",
    )
    p_tindex.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_tindex.add_argument(
        "--callers", default=None, metavar="NAME", help="list entries that reference NAME"
    )
    p_tindex.add_argument(
        "--callees", default=None, metavar="NAME", help="list entries that NAME references"
    )
    p_tindex.add_argument(
        "--transitive",
        action="store_true",
        help="follow the reference graph transitively for --callers/--callees",
    )
    p_tindex.add_argument(
        "--deps", default=None, metavar="THEORY", help="show THEORY's imports and importers"
    )
    p_tindex.add_argument(
        "--sorry", action="store_true", help="list sorry/oops markers with their enclosing entry"
    )
    p_tindex.add_argument(
        "--unreferenced",
        action="store_true",
        help="list entries not referenced by any other indexed entry (not dead-code analysis)",
    )
    p_tindex.add_argument(
        "--counts",
        action="store_true",
        help=(
            "print a compact numeric summary (theories, entries, sorry/oops "
            "entries, unreferenced count, import-edge count)"
        ),
    )
    p_tindex.add_argument(
        "--mermaid",
        action="store_true",
        help="emit a Mermaid flowchart of the theory import graph (mutually exclusive with --json)",
    )
    p_tindex.set_defaults(func=cmd_theory_index)

    p_search = sub.add_parser(
        "search-facts",
        help="search .thy sources for fact/lemma/theorem names (no Isabelle needed)",
    )
    p_search.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        help="blueprint dir, used to resolve unresolved targets when --query is omitted",
    )
    p_search.add_argument(
        "--theory",
        nargs="*",
        default=None,
        metavar="FILE",
        help="theory file(s) to search (omit to use --root or the discovered session)",
    )
    p_search.add_argument(
        "--root",
        default=None,
        metavar="DIR",
        help="search every theory a session ROOT declares under DIR",
    )
    p_search.add_argument(
        "--session",
        default=None,
        metavar="NAME",
        help="select one session when the ROOT under --root declares several",
    )
    p_search.add_argument(
        "--query",
        default=None,
        metavar="TEXT",
        help="free-text search; when omitted, match the project's unresolved targets",
    )
    p_search.add_argument(
        "--kind",
        action="append",
        default=None,
        metavar="KIND",
        help="restrict to a declaration kind, e.g. lemma/theorem/definition (repeatable)",
    )
    p_search.add_argument(
        "--limit",
        type=_positive_int,
        default=10,
        metavar="N",
        help="maximum matches to show (per node in target mode; default: 10)",
    )
    p_search_fmt = p_search.add_mutually_exclusive_group()
    p_search_fmt.add_argument("--json", action="store_true", help="emit results as JSON")
    p_search_fmt.add_argument(
        "--markdown",
        action="store_true",
        help="render results as a Markdown table (mutually exclusive with --json)",
    )
    p_search.set_defaults(func=cmd_search_facts)

    p_new = sub.add_parser("new", help="print (or append) a ready-to-edit node stub")
    p_new.add_argument("kind", help="node kind, e.g. definition, lemma, theorem")
    p_new.add_argument("id", help="node id, e.g. add-zero-right or thm:pythagoras")
    p_new.add_argument(
        "project_dir", nargs="?", default=".", help="project dir (used with --append)"
    )
    p_new.add_argument(
        "--title", default=None, help="explicit title (default: humanised from id)"
    )
    p_new.add_argument(
        "--fact", default=None, help="Isabelle fact name (default: suggested from id)"
    )
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
        help=(
            "target blueprint file (required with --append when the project has "
            "multiple blueprints)"
        ),
    )
    p_new.set_defaults(func=cmd_new)

    # Accept `--color`/`--no-color` after the subcommand too (e.g. `lint --color
    # never`). SUPPRESS defaults mean an omitted sub-command flag never clobbers
    # the value parsed from the top-level parser.
    for subparser in sub.choices.values():
        subparser.add_argument(
            "--color",
            choices=("auto", "always", "never"),
            default=argparse.SUPPRESS,
            help="when to colourise human-facing output (default: auto; honours NO_COLOR)",
        )
        subparser.add_argument(
            "--no-color",
            action="store_const",
            const="never",
            dest="color",
            default=argparse.SUPPRESS,
            help="disable coloured output (alias for --color never)",
        )

    return parser


def _render_web_once(project_dir: Path) -> Path:
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    trends = load_trends(config.trends_path)
    fact_suggestions = suggest_missing_facts(project, dump_report_path=config.dump_report_path)
    memory = load_agent_memory(config.agent_memory_path)
    assignments = load_assignments(config.assignments_path)
    return render_site(
        project,
        config.site_dir,
        trends=trends,
        fact_suggestions=fact_suggestions,
        memory=memory,
        assignments=assignments,
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

    thread = threading.Thread(
        target=server.serve_forever, name="isabelle-blueprint-serve", daemon=True
    )
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
            config.assignments_path,
        ]
    )
    return paths


def _check_watch_paths(project_dir: Path) -> list[Path]:
    """Input-only watch list so `check --watch` never re-triggers on its own output."""
    paths = [project_dir / "isabelle-blueprint.toml"]
    try:
        config = load_config(project_dir)
    except (OSError, ValueError):
        return paths
    paths.extend(config.blueprint_paths)
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
    console.configure(getattr(args, "color", "auto"), stream=sys.stdout)
    try:
        return args.func(args)
    except BlueprintError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
