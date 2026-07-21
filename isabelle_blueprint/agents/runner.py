"""Execution harness for the ``agent-run`` command.

This module turns a selected ready task into an actual solver invocation: it
substitutes placeholders into a user-supplied command, runs it with a robust
cross-platform subprocess wrapper, and classifies the result into an agent-memory
outcome. The harness is deliberately solver-agnostic -- it never hardcodes an LLM
-- so the pure helpers here stay deterministic and unit-testable by injecting a
fake command runner.

Security notes:

* The command is split into an argv list (via ``--exec``/``--arg`` or a
  ``shlex``-tokenised ``--command`` string) and run **without a shell**, so
  substituted placeholder values cannot inject extra arguments.
* Only the fixed placeholders in :data:`RUN_PLACEHOLDERS` are recognised; an
  unknown ``{name}`` token is rejected rather than silently passed through.
* Combined stdout/stderr is size-capped while the command runs to avoid a
  runaway solver flooding the disk, and only bounded tails are surfaced/recorded.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field

from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.isabelle._run import OutputLimitExceeded, RunResult, run_capture

#: Placeholders substituted into each command token before execution.
RUN_PLACEHOLDERS = ("prompt_file", "node_id", "task_id", "project_dir")

PROMPT_PLACEHOLDER = "{prompt_file}"

#: Default cap on combined stdout+stderr captured from a solver (10 MiB).
DEFAULT_MAX_OUTPUT_BYTES = 10 * 1024 * 1024

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SLUG_RE = re.compile(r"[^0-9A-Za-z._-]+")


CommandRunner = Callable[..., RunResult]


@dataclass(frozen=True)
class CommandResult:
    """Normalised result of attempting to run a solver command."""

    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    spawn_error: bool = False
    output_limit_exceeded: bool = False
    duration_seconds: float | None = None
    error: str | None = None

    @property
    def ran(self) -> bool:
        """True when the command actually started (no spawn error)."""

        return not self.spawn_error


@dataclass
class AgentRunResult:
    """Full outcome of one ``agent-run`` invocation."""

    task_id: str
    node_id: str
    command: list[str]
    ran: bool
    return_code: int | None
    outcome: str
    summary: str
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    output_limit_exceeded: bool = False
    error: str | None = None
    duration_seconds: float | None = None
    recorded: bool = False
    memory: dict[str, object] | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        return data


def split_command_string(command: str) -> list[str]:
    """Tokenise a ``--command`` string into an argv list.

    Uses POSIX ``shlex`` semantics on every platform for predictable quoting.
    Windows users with backslash paths should prefer ``--exec``/``--arg`` which
    avoid tokenisation entirely.
    """

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        raise BlueprintError(f"could not parse --command {command!r}: {exc}") from exc
    if not tokens:
        raise BlueprintError("--command did not contain an executable")
    return tokens


def validate_command_tokens(tokens: Sequence[str], *, require_prompt: bool = True) -> None:
    """Reject empty commands and unknown ``{placeholder}`` tokens."""

    if not tokens:
        raise BlueprintError("agent-run requires a command to execute")
    unknown: list[str] = []
    has_prompt = False
    for token in tokens:
        for name in _PLACEHOLDER_RE.findall(token):
            if name not in RUN_PLACEHOLDERS:
                unknown.append(name)
            elif name == "prompt_file":
                has_prompt = True
    if unknown:
        known = ", ".join(f"{{{name}}}" for name in RUN_PLACEHOLDERS)
        joined = ", ".join(f"{{{name}}}" for name in sorted(set(unknown)))
        raise BlueprintError(
            f"unknown command placeholder(s): {joined}; supported placeholders are {known}"
        )
    if require_prompt and not has_prompt:
        raise BlueprintError(
            "command does not reference {prompt_file}; the solver cannot see the prompt "
            "(pass --allow-missing-prompt to override)"
        )


def substitute_command(tokens: Sequence[str], substitutions: Mapping[str, str]) -> list[str]:
    """Replace ``{placeholder}`` occurrences in each token after splitting.

    Substitution happens per-token, so a value containing spaces stays a single
    argv element and no shell is involved -- there is no argument-injection path.
    """

    def _replace(token: str) -> str:
        def _sub(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in substitutions:
                return substitutions[name]
            return match.group(0)

        return _PLACEHOLDER_RE.sub(_sub, token)

    return [_replace(token) for token in tokens]


def safe_prompt_filename(task_id: str, *, suffix: str = ".md") -> str:
    """Return a filesystem-safe prompt filename derived from ``task_id``.

    Node/task ids are author-controlled and may contain path separators or
    characters that are invalid on Windows. We slugify and append a short hash of
    the original id so distinct ids never collide after slugification.
    """

    slug = _SLUG_RE.sub("-", task_id).strip("-._")
    digest = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:8]
    if not slug:
        slug = "task"
    return f"{slug}-{digest}{suffix}"


def prompt_filename(task_id: str, *, suffix: str = ".md") -> str:
    """Return a prompt filename for ``task_id``, stable for filesystem-safe ids.

    Ids that are already safe (no path separators or Windows-illegal characters)
    are used verbatim -- ``task-main`` -> ``task-main.md`` -- matching the
    documented ``build/prompts/<task-id>.md`` layout. Only ids containing unsafe
    characters are slugified and hash-suffixed (via :func:`safe_prompt_filename`)
    so they cannot escape the prompts directory or collide on Windows.
    """

    if _SLUG_RE.search(task_id) or task_id != task_id.strip("-._") or not task_id:
        return safe_prompt_filename(task_id, suffix=suffix)
    return f"{task_id}{suffix}"


def classify_run_outcome(
    result: CommandResult,
    *,
    success_outcome: str = "succeeded",
    failure_outcome: str = "failed",
) -> str:
    """Map a :class:`CommandResult` to an agent-memory outcome value."""

    if result.spawn_error:
        return "blocked"
    if result.timed_out or result.output_limit_exceeded:
        return failure_outcome
    if result.return_code == 0:
        return success_outcome
    return failure_outcome


def execute_agent_command(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    timeout: float | None = None,
    max_output_bytes: int | None = DEFAULT_MAX_OUTPUT_BYTES,
    runner: CommandRunner = run_capture,
) -> CommandResult:
    """Run ``argv`` and normalise success/timeout/spawn errors into a result."""

    args = list(argv)
    started = time.monotonic()
    try:
        result = runner(args, cwd=cwd, timeout=timeout, max_output_bytes=max_output_bytes)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            return_code=None,
            stdout=_as_text(exc.output),
            stderr=_as_text(exc.stderr),
            timed_out=True,
            duration_seconds=time.monotonic() - started,
            error=f"command timed out after {timeout}s",
        )
    except OutputLimitExceeded as exc:
        return CommandResult(
            return_code=None,
            stdout=exc.output,
            stderr=exc.stderr,
            output_limit_exceeded=True,
            duration_seconds=time.monotonic() - started,
            error=str(exc),
        )
    except FileNotFoundError as exc:
        return CommandResult(
            return_code=None,
            stdout="",
            stderr="",
            spawn_error=True,
            duration_seconds=time.monotonic() - started,
            error=f"command not found: {args[0] if args else ''} ({exc})",
        )
    except OSError as exc:
        return CommandResult(
            return_code=None,
            stdout="",
            stderr="",
            spawn_error=True,
            duration_seconds=time.monotonic() - started,
            error=f"could not start command: {exc}",
        )
    return CommandResult(
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=time.monotonic() - started,
    )


def tail(text: str, *, max_lines: int = 20, max_chars: int = 2000) -> str:
    """Return a bounded tail of ``text`` for display and memory recording."""

    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    trimmed = "\n".join(lines).strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[-max_chars:]
    return trimmed


def default_run_summary(command: Sequence[str], result: CommandResult, outcome: str) -> str:
    """Build a concise, deterministic memory summary for a run."""

    program = command[0] if command else "agent-run"
    if result.spawn_error:
        return f"agent-run could not start {program!r}"
    if result.timed_out:
        return f"agent-run {program!r} timed out ({outcome})"
    if result.output_limit_exceeded:
        return f"agent-run {program!r} exceeded output limit ({outcome})"
    return f"agent-run {program!r} exited {result.return_code} ({outcome})"


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
