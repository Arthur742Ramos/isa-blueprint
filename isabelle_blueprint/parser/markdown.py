"""Parse a Markdown blueprint document into a :class:`BlueprintProject`.

Supported block syntax
----------------------

::

    ::: theorem {#thm-id}
    title: Pythagoras' theorem
    isabelle: Pythagoras.pythagoras_thm
    uses:
      - def-triangle
      - lem-right-angle
    status:
      blueprint: written
      formal: missing
    tags: [geometry, classic]
    :::

    The statement is ...

    ## Proof

    The proof goes ...

    :::

Two ``:::`` markers per node: the first closes the YAML metadata header, and the
trailing one closes the whole node. Code fences (``` ``` `` and ``~~~``) inside the
body are respected so that ``:::`` lines appearing inside example code are not
treated as directives.

Body parsing is intentionally lightweight: a Markdown heading of the form
``## Proof`` (or ``### Proof``) splits the body into ``statement`` and
``informal_proof``. Otherwise the entire body is stored as ``statement``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Opening directive:
#   ::: theorem {#thm-id}
#   ::: {.theorem #thm-id}
#   ::: lemma{#lem-id}
_DIRECTIVE_OPEN = re.compile(
    r"""^
    :::                              # fence
    \s*
    (?:
        (?P<kind1>[A-Za-z][\w-]*)    # kind directly after :::
        \s*
        (?:\{\s*\#(?P<id1>[\w.\-/:]+)\s*\})?
    |
        \{\s*
        (?:\.(?P<kind2>[A-Za-z][\w-]*)\s*)?
        (?:\#(?P<id2>[\w.\-/:]+)\s*)?
        \}
    )
    \s*$
    """,
    re.VERBOSE,
)

_DIRECTIVE_CLOSE = re.compile(r"^:::\s*$")

_FENCE_RE = re.compile(r"^(?P<marker>```+|~~~+)")
_PROOF_HEADING_RE = re.compile(r"^(#{2,4})\s+(?:proof|formal proof|isabelle proof)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal representation while scanning
# ---------------------------------------------------------------------------


@dataclass
class _RawBlock:
    kind_hint: str | None  # kind from the opening line, if given
    id_hint: str | None
    metadata_lines: list[str]
    body_lines: list[str]
    source_file: str
    source_line: int  # 1-based line of the opening directive


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_blueprint_file(path: Path | str, *, project_name: str | None = None) -> BlueprintProject:
    """Parse a single blueprint Markdown file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    name = project_name or p.stem
    return parse_blueprint_text(text, source=str(p), project_name=name)


def parse_blueprint(paths: Iterable[Path | str], *, project_name: str = "blueprint") -> BlueprintProject:
    """Parse one or more Markdown files into a single project."""
    nodes: list[BlueprintNode] = []
    sources: list[str] = []
    for path in paths:
        sub = parse_blueprint_file(path, project_name=project_name)
        nodes.extend(sub.nodes)
        sources.extend(sub.source_files)
    return BlueprintProject.from_nodes(project_name, nodes, sources)


def parse_blueprint_text(text: str, *, source: str = "<text>", project_name: str = "blueprint") -> BlueprintProject:
    """Parse a blueprint Markdown string."""
    blocks = _scan_blocks(text, source=source)
    nodes = [_block_to_node(b) for b in blocks]
    return BlueprintProject.from_nodes(project_name, nodes, sources=[source])


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _scan_blocks(text: str, *, source: str) -> list[_RawBlock]:
    """Scan ``text`` for ``:::`` blocks.

    State machine:
      OUTSIDE  -- looking for an opening directive line.
      META     -- collecting YAML metadata; ends at the first ``:::``.
      BODY     -- collecting body; ends at the next ``:::`` (respecting code fences).
    """
    blocks: list[_RawBlock] = []
    current: _RawBlock | None = None
    state = "OUTSIDE"
    fence_marker: str | None = None  # the current code-fence marker, if any

    lines = text.splitlines()
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")

        if state == "OUTSIDE":
            opener = _DIRECTIVE_OPEN.match(line)
            if opener:
                kind = opener.group("kind1") or opener.group("kind2")
                node_id = opener.group("id1") or opener.group("id2")
                current = _RawBlock(
                    kind_hint=kind,
                    id_hint=node_id,
                    metadata_lines=[],
                    body_lines=[],
                    source_file=source,
                    source_line=idx,
                )
                state = "META"
            # else: ignore preamble lines.
            continue

        if state == "META":
            if _DIRECTIVE_CLOSE.match(line):
                state = "BODY"
                continue
            # Reject the (rare) attempt to nest another block while in metadata.
            if _DIRECTIVE_OPEN.match(line):
                raise ParseError(
                    "encountered new ':::' directive before metadata was closed",
                    source=source,
                    line=idx,
                )
            assert current is not None
            current.metadata_lines.append(line)
            continue

        if state == "BODY":
            assert current is not None
            fence_match = _FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group("marker")
                if fence_marker is None:
                    fence_marker = marker[0]  # `` or ~
                elif line.lstrip().startswith(fence_marker):
                    fence_marker = None
                current.body_lines.append(line)
                continue

            if fence_marker is None and _DIRECTIVE_CLOSE.match(line):
                blocks.append(current)
                current = None
                state = "OUTSIDE"
                continue

            current.body_lines.append(line)
            continue

    if state != "OUTSIDE":
        assert current is not None
        raise ParseError(
            "unterminated ':::' block (missing closing ':::')",
            source=source,
            line=current.source_line,
        )

    return blocks


# ---------------------------------------------------------------------------
# Block -> Node
# ---------------------------------------------------------------------------


def _block_to_node(block: _RawBlock) -> BlueprintNode:
    metadata = _parse_metadata("\n".join(block.metadata_lines), block.source_file, block.source_line)
    node_id = metadata.pop("id", None) or block.id_hint
    if not node_id:
        raise ParseError(
            "blueprint node is missing an id (use '::: kind {#id}' or 'id: ...')",
            source=block.source_file,
            line=block.source_line,
        )
    kind_value = metadata.pop("kind", None) or block.kind_hint or "other"
    kind = NodeKind.parse(str(kind_value))

    title = str(metadata.pop("title", node_id))
    uses_raw = metadata.pop("uses", []) or []
    if isinstance(uses_raw, str):
        uses = [u.strip() for u in re.split(r"[,\s]+", uses_raw) if u.strip()]
    else:
        uses = [str(u).strip() for u in uses_raw if str(u).strip()]

    tags_raw = metadata.pop("tags", []) or []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in re.split(r"[,]+", tags_raw) if t.strip()]
    else:
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]

    isabelle_ref = _parse_isabelle_ref(metadata)
    status = _parse_status(metadata)

    statement, informal_proof = _split_body(block.body_lines)

    return BlueprintNode(
        id=str(node_id),
        kind=kind,
        title=title,
        statement=statement,
        informal_proof=informal_proof,
        uses=uses,
        isabelle=isabelle_ref,
        status=status,
        tags=tags,
        source_file=block.source_file,
        source_line=block.source_line,
        raw_metadata=metadata,
    )


def _parse_metadata(text: str, source: str, line: int) -> dict:
    if not text.strip():
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML metadata: {exc}", source=source, line=line) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ParseError(
            f"expected YAML mapping in metadata, got {type(data).__name__}",
            source=source,
            line=line,
        )
    return data


def _parse_isabelle_ref(metadata: dict) -> IsabelleRef:
    raw = metadata.pop("isabelle", None)
    if raw is None:
        return IsabelleRef()
    if isinstance(raw, str):
        return IsabelleRef(fact=raw.strip())
    if isinstance(raw, dict):
        return IsabelleRef(
            fact=raw.get("fact"),
            theory=raw.get("theory"),
            session=raw.get("session"),
        )
    raise ParseError(f"unsupported 'isabelle:' value of type {type(raw).__name__}")


def _parse_status(metadata: dict) -> NodeStatus:
    raw = metadata.pop("status", None)
    status = NodeStatus()
    if raw is None:
        return status
    if isinstance(raw, str):
        # Legacy single-string status: map to the closest enum.
        token = raw.strip().lower()
        if token in {"stub", "written", "reviewed"}:
            status.blueprint = BlueprintStatus(token)
        elif token in {"planned"}:
            status.blueprint = BlueprintStatus.WRITTEN
        elif token in {"proved", "found", "missing", "not_found", "tainted", "stale", "broken"}:
            status.formal = FormalStatus(token)
        elif token in {"ready", "blocked", "solved", "attempted", "needs_human", "in_progress"}:
            status.agent = AgentStatus(token)
        return status
    if not isinstance(raw, dict):
        raise ParseError(f"unsupported 'status:' value of type {type(raw).__name__}")
    if "blueprint" in raw:
        status.blueprint = BlueprintStatus(str(raw["blueprint"]).strip().lower())
    if "formal" in raw:
        status.formal = FormalStatus(str(raw["formal"]).strip().lower())
    if "agent" in raw:
        status.agent = AgentStatus(str(raw["agent"]).strip().lower())
    return status


def _split_body(body_lines: list[str]) -> tuple[str, str]:
    """Return ``(statement, informal_proof)`` from the body lines.

    Splits on a markdown heading like ``## Proof`` if present, otherwise the
    entire body is treated as the statement.
    """
    proof_idx: int | None = None
    in_fence = False
    fence_marker: str | None = None
    for i, line in enumerate(body_lines):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group("marker")
            if fence_marker is None:
                fence_marker = marker[0]
                in_fence = True
            elif line.lstrip().startswith(fence_marker):
                fence_marker = None
                in_fence = False
            continue
        if in_fence:
            continue
        if _PROOF_HEADING_RE.match(line.strip()):
            proof_idx = i
            break

    if proof_idx is None:
        return _trim("\n".join(body_lines)), ""
    statement = _trim("\n".join(body_lines[:proof_idx]))
    proof_body = body_lines[proof_idx + 1 :]
    informal_proof = _trim("\n".join(proof_body))
    return statement, informal_proof


def _trim(s: str) -> str:
    return s.strip("\n").rstrip()
