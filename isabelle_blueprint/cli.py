"""Command-line interface for IsabelleBlueprint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from isabelle_blueprint import __version__
from isabelle_blueprint.agents.tasks import write_tasks
from isabelle_blueprint.config import BlueprintConfig, load_config
from isabelle_blueprint.errors import BlueprintError, ValidationError
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
from isabelle_blueprint.parser import parse_blueprint, parse_blueprint_file
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
from isabelle_blueprint.report.trends import append_trend_entry, load_trends

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


def cmd_init(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    blueprint_path = project_dir / "blueprint.md"
    config_path = project_dir / "isabelle-blueprint.toml"
    if blueprint_path.exists() and not args.force:
        print(f"refusing to overwrite {blueprint_path}; pass --force to replace", file=sys.stderr)
        return 1
    blueprint_path.write_text(_DEFAULT_BLUEPRINT, encoding="utf-8")
    if not config_path.exists() or args.force:
        config_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    workflows = project_dir / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    workflow_file = workflows / "blueprint.yml"
    if not workflow_file.exists() or args.force:
        workflow_file.write_text(_DEFAULT_WORKFLOW, encoding="utf-8")
    print(f"initialised IsabelleBlueprint project at {project_dir}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from isabelle_blueprint.scaffold import render_node_stub

    fact = "" if args.no_fact else args.fact
    stub = render_node_stub(
        args.kind,
        args.id,
        title=args.title,
        fact=fact,
        uses=args.uses or [],
        status=args.status,
    )

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
        existing = path.read_text(encoding="utf-8")
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        path.write_text(existing + separator + stub, encoding="utf-8")
        print(f"appended {args.kind} {args.id!r} to {path}")
    else:
        sys.stdout.write(stub)
    return 0


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
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    trends = load_trends(config.trends_path)
    index = render_site(project, config.site_dir, trends=trends)
    print(f"site -> {index}")
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    config, project = _load(project_dir)
    _try_apply_check(project, config)
    written = write_tasks(project, config.build_dir)
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="isabelle-blueprint", description="Isabelle-aware blueprint tooling.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a fresh blueprint project")
    p_init.add_argument("project_dir", nargs="?", default=".", help="target directory (default: cwd)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
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
    p_web.set_defaults(func=cmd_web)

    p_tasks = sub.add_parser("tasks", help="generate agent-ready tasks and per-task prompts")
    p_tasks.add_argument("project_dir", nargs="?", default=".")
    p_tasks.set_defaults(func=cmd_tasks)

    p_report = sub.add_parser("report", help="write JSON and Markdown status reports")
    p_report.add_argument("project_dir", nargs="?", default=".")
    p_report.set_defaults(func=cmd_report)

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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BlueprintError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


_DEFAULT_BLUEPRINT = """# My blueprint

Welcome! Edit this file and replace the placeholder nodes below.
Tip: run `isabelle-blueprint new theorem my-id` to scaffold more nodes.

::: definition {#example-def}
title: Example definition
isabelle: Main.True
status: stub

Describe what is being defined.
:::

::: theorem {#example-thm}
title: Example theorem
isabelle: My_Theory.example_lemma
uses:
  - example-def
status: stub

State the result.

## Proof

Sketch the proof.
:::
"""

_DEFAULT_CONFIG = """[project]
name = "My blueprint"
blueprint = "blueprint.md"

[isabelle]
# session = "My_Session"
# executable = "isabelle"
# version = "Isabelle2025-2"
# timeout = 600  # max seconds for `isabelle build`/`dump`; omit to wait indefinitely

[afp]
# root = "/path/to/afp"
# entry = "My_AFP_Entry"
# required = false

[output]
build_dir = "build"
site_dir = "site"
"""

_DEFAULT_WORKFLOW = """name: blueprint
on:
  push:
  pull_request:
jobs:
  blueprint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install isabelle-blueprint
      - run: isabelle-blueprint check .
      - run: isabelle-blueprint compat .
      - run: isabelle-blueprint graph .
      - run: isabelle-blueprint web .
      - run: isabelle-blueprint report .
      - uses: actions/upload-artifact@v4
        with:
          name: blueprint-site
          path: site
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
