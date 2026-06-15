"""Per-node provenance: who last touched each blueprint node, and when.

``blame`` answers "where did this node come from?" by combining two independent
sources of history:

* **git** - the last commit that touched the Markdown/LaTeX file the node was
  parsed from (short hash, author, ISO date, subject).
* **agent memory** - the most recent recorded attempt for the node (outcome,
  actor, timestamp) from ``.isabelle-blueprint/agent-memory.json``.

Both sources degrade gracefully: a project that is not a git repository, has an
untracked source file, or has no agent memory simply reports ``None`` for that
half rather than failing. Git is invoked with ``shell=False`` and a ``--``
path separator, and results are cached per file so a large blueprint only shells
out once per source file.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.agents.memory import AgentMemory
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.model.project import BlueprintProject

_GIT_TIMEOUT_SECONDS = 10.0
_GIT_LOG_FORMAT = "%h%x1f%an%x1f%aI%x1f%s"


@dataclass(frozen=True)
class GitProvenance:
    """The last git commit that touched a node's source file."""

    commit: str
    author: str
    date: str
    subject: str

    def to_dict(self) -> dict[str, str]:
        return {
            "commit": self.commit,
            "author": self.author,
            "date": self.date,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class MemoryProvenance:
    """A condensed view of the latest agent-memory attempt for a node."""

    attempts: int
    last_outcome: str | None
    last_actor: str | None
    last_timestamp: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "last_outcome": self.last_outcome,
            "last_actor": self.last_actor,
            "last_timestamp": self.last_timestamp,
        }


@dataclass(frozen=True)
class NodeBlame:
    """Combined provenance for a single blueprint node."""

    node_id: str
    title: str
    source_file: str | None
    source_line: int | None
    git: GitProvenance | None
    memory: MemoryProvenance | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.node_id,
            "title": self.title,
            "source": {"file": self.source_file, "line": self.source_line},
            "git": self.git.to_dict() if self.git else None,
            "memory": self.memory.to_dict() if self.memory else None,
        }


def git_file_provenance(
    project_dir: Path,
    rel_path: str,
    *,
    cache: dict[str, GitProvenance | None],
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> GitProvenance | None:
    """Return the last commit that touched ``rel_path``, or ``None``.

    ``None`` is returned for any of: git not installed, ``project_dir`` not a
    git work tree, or ``rel_path`` untracked/never committed. Results are cached
    in ``cache`` keyed by ``rel_path`` so repeated nodes share one git call.
    """
    if rel_path in cache:
        return cache[rel_path]

    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                "-1",
                f"--format={_GIT_LOG_FORMAT}",
                "--",
                rel_path,
            ],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        cache[rel_path] = None
        return None

    provenance: GitProvenance | None = None
    if proc.returncode == 0:
        line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        parts = line.split("\x1f")
        if len(parts) == 4:
            provenance = GitProvenance(
                commit=parts[0],
                author=parts[1],
                date=parts[2],
                subject=parts[3],
            )
    cache[rel_path] = provenance
    return provenance


def _memory_provenance(memory: AgentMemory, node_id: str) -> MemoryProvenance | None:
    node_memory = memory.nodes.get(node_id)
    if node_memory is None or not node_memory.attempts:
        return None
    last = node_memory.attempts[-1]
    return MemoryProvenance(
        attempts=len(node_memory.attempts),
        last_outcome=last.outcome or None,
        last_actor=last.actor,
        last_timestamp=last.timestamp or None,
    )


def build_blame(
    project: BlueprintProject,
    project_dir: Path,
    memory: AgentMemory,
    *,
    node_id: str | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> list[NodeBlame]:
    """Build provenance for every node (or just ``node_id`` when given)."""
    if node_id is not None:
        node = project.get(node_id)
        if node is None:
            raise BlueprintError(f"unknown node id {node_id!r}")
        nodes = [node]
    else:
        nodes = list(project.nodes)

    cache: dict[str, GitProvenance | None] = {}
    blames: list[NodeBlame] = []
    for node in nodes:
        git_info: GitProvenance | None = None
        if node.source_file:
            git_info = git_file_provenance(
                project_dir, node.source_file, cache=cache, timeout=timeout
            )
        blames.append(
            NodeBlame(
                node_id=node.id,
                title=node.title,
                source_file=node.source_file,
                source_line=node.source_line,
                git=git_info,
                memory=_memory_provenance(memory, node.id),
            )
        )
    return blames


def render_blame(blames: list[NodeBlame]) -> str:
    """Render ``blames`` as human-readable text (trailing newline)."""
    if not blames:
        return "no nodes to blame\n"
    lines: list[str] = []
    for blame in blames:
        location = blame.source_file or "(no source)"
        if blame.source_line is not None:
            location = f"{location}:{blame.source_line}"
        lines.append(f"{blame.node_id}  ({blame.title})")
        lines.append(f"  source: {location}")
        if blame.git is not None:
            lines.append(
                f"  git:    {blame.git.commit} {blame.git.author} "
                f"{blame.git.date} - {blame.git.subject}"
            )
        else:
            lines.append("  git:    (no commit history)")
        if blame.memory is not None:
            actor = blame.memory.last_actor or "?"
            outcome = blame.memory.last_outcome or "?"
            stamp = blame.memory.last_timestamp or "?"
            lines.append(
                f"  agent:  {blame.memory.attempts} attempt(s); "
                f"last {outcome} by {actor} at {stamp}"
            )
        else:
            lines.append("  agent:  (no recorded attempts)")
    return "\n".join(lines) + "\n"


def render_blame_table(blames: list[NodeBlame]) -> str:
    """Render ``blames`` as a compact one-row-per-node table (trailing newline)."""
    if not blames:
        return "no nodes to blame\n"
    rows: list[tuple[str, str, str, str]] = []
    for blame in blames:
        location = blame.source_file or "(no source)"
        if blame.source_line is not None:
            location = f"{location}:{blame.source_line}"
        if blame.git is not None:
            git_cell = f"{blame.git.commit} {blame.git.author}"
        else:
            git_cell = "-"
        if blame.memory is not None:
            outcome = blame.memory.last_outcome or "?"
            agent_cell = f"{blame.memory.attempts}x {outcome}"
        else:
            agent_cell = "-"
        rows.append((blame.node_id, location, git_cell, agent_cell))

    headers = ("NODE", "SOURCE", "GIT", "AGENT")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt(cols: tuple[str, str, str, str]) -> str:
        return "  ".join(
            cols[i].ljust(widths[i]) if i < len(cols) - 1 else cols[i]
            for i in range(len(cols))
        ).rstrip()

    lines = [_fmt(headers)]
    lines.extend(_fmt(row) for row in rows)
    return "\n".join(lines) + "\n"


def blame_payload(blames: list[NodeBlame]) -> dict[str, object]:
    """Render ``blames`` as a JSON-serialisable payload."""
    return {"nodes": [blame.to_dict() for blame in blames]}
