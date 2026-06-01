"""Emit data into the GitHub Actions ``$GITHUB_OUTPUT`` and ``$GITHUB_STEP_SUMMARY`` files.

The CLI calls these unconditionally; both functions are no-ops when the
corresponding environment variable is unset (i.e. when running locally), and
they swallow ``OSError`` so a misconfigured runner cannot turn a successful
report into a failed CLI exit. Returning ``bool`` lets the caller log
whether anything was written, but exit codes are never affected.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

GITHUB_OUTPUT_ENV = "GITHUB_OUTPUT"
GITHUB_STEP_SUMMARY_ENV = "GITHUB_STEP_SUMMARY"


def emit_step_outputs(
    values: Mapping[str, object],
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Append ``key=value`` lines to ``$GITHUB_OUTPUT``.

    Multi-line values use the documented ``<<DELIM`` heredoc form with a
    delimiter derived from :func:`uuid.uuid4`, so a value that happens to
    contain ``EOF`` (or any other guessable token) cannot terminate the block
    early. See: https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-an-output-parameter
    """
    env_map = os.environ if env is None else env
    path_str = env_map.get(GITHUB_OUTPUT_ENV)
    if not path_str:
        return False
    try:
        path = Path(path_str)
        with path.open("a", encoding="utf-8") as handle:
            for key, raw in values.items():
                rendered = _render_value(raw)
                if "\n" in rendered:
                    delim = f"ghadelim_{uuid.uuid4().hex}"
                    handle.write(f"{key}<<{delim}\n{rendered}\n{delim}\n")
                else:
                    handle.write(f"{key}={rendered}\n")
    except OSError:
        return False
    return True


def emit_step_summary(
    markdown: str,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Append ``markdown`` (plus a trailing newline) to ``$GITHUB_STEP_SUMMARY``."""
    env_map = os.environ if env is None else env
    path_str = env_map.get(GITHUB_STEP_SUMMARY_ENV)
    if not path_str:
        return False
    try:
        path = Path(path_str)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip("\n") + "\n")
    except OSError:
        return False
    return True


def build_summary_markdown(
    project_name: str,
    metrics_dict: Mapping[str, object],
    *,
    extra_lines: Iterable[str] = (),
) -> str:
    """Render a short Markdown summary suitable for ``$GITHUB_STEP_SUMMARY``.

    Kept deliberately compact - just the headline coverage line plus a small
    counts table - so it slots in next to summaries from other steps without
    dominating the run page.
    """
    coverage = metrics_dict.get("coverage_percent")
    proved = metrics_dict.get("proved_count", 0)
    target = metrics_dict.get("formal_target_count", 0)
    if coverage in ("", None):
        coverage_line = "Coverage: _no formal targets yet_"
    else:
        coverage_line = f"Coverage: **{coverage}%** ({proved}/{target} proved)"

    lines: list[str] = [
        f"## IsabelleBlueprint - {project_name}",
        "",
        coverage_line,
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Nodes | {metrics_dict.get('node_count', 0)} |",
        f"| Formal targets | {metrics_dict.get('formal_target_count', 0)} |",
        f"| Proved | {metrics_dict.get('proved_count', 0)} |",
        f"| Found | {metrics_dict.get('found_count', 0)} |",
        f"| Problems | {metrics_dict.get('problem_count', 0)} |",
        f"| Has cycles | {'yes' if metrics_dict.get('has_cycles') in (True, 'true') else 'no'} |",
    ]
    for extra in extra_lines:
        lines.append(str(extra))
    return "\n".join(lines)


def _render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
