r"""Parse Lean Blueprint-style LaTeX sources into blueprint nodes.

The parser is intentionally conservative: it recognises theorem-like LaTeX
environments and the metadata commands commonly used by Lean Blueprint sources
(``\label{...}``, ``\lean{...}``, ``\uses{...}``, ``\leanok``). Isabelle
projects can use the same shape with ``\isabelle{...}`` and ``\isabelleok``.
LaTeX-specific macros such as ``\blueprintstatus{...}``,
``\formalstatus{...}``, and ``\agentstatus{...}`` expose the same status axes
as Markdown metadata without requiring a LaTeX toolchain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.errors import ParseError
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import (
    AgentStatus,
    BlueprintStatus,
    FormalStatus,
    coerce_status,
)

_ENV_KINDS = [
    "definition",
    "lemma",
    "theorem",
    "proposition",
    "corollary",
    "construction",
    "remark",
    "example",
    "note",
    "other",
]

_ENV_RE = re.compile(
    r"""\\begin\{(?P<kind>"""
    + "|".join(_ENV_KINDS)
    + r""")\}
        (?:\[(?P<title>[^\]]*)\])?
        (?P<body>.*?)
        \\end\{(?P=kind)\}
    """,
    re.DOTALL | re.VERBOSE,
)

_LABEL_RE = re.compile(r"\\label\{(?P<value>[^{}]+)\}")
_LEAN_RE = re.compile(r"\\lean\{(?P<value>[^{}]+)\}")
_ISABELLE_RE = re.compile(r"\\isabelle\{(?P<value>[^{}]+)\}")
_ISABELLE_THEORY_RE = re.compile(r"\\isabelletheory\{(?P<value>[^{}]+)\}")
_ISABELLE_SESSION_RE = re.compile(r"\\isabellesession\{(?P<value>[^{}]+)\}")
_USES_RE = re.compile(r"\\uses\{(?P<value>[^{}]*)\}")
_TAGS_RE = re.compile(r"\\tags\{(?P<value>[^{}]*)\}")
_STATUS_RE = re.compile(r"\\status\{(?P<value>[^{}]+)\}")
_BLUEPRINT_STATUS_RE = re.compile(r"\\blueprintstatus\{(?P<value>[^{}]+)\}")
_FORMAL_STATUS_RE = re.compile(r"\\formalstatus\{(?P<value>[^{}]+)\}")
_AGENT_STATUS_RE = re.compile(r"\\agentstatus\{(?P<value>[^{}]+)\}")
_PROOF_RE = re.compile(r"\\begin\{proof\}(?P<body>.*?)\\end\{proof\}", re.DOTALL)
_COMMAND_LINE_RE = re.compile(
    r"^\s*\\(?:label|lean|isabelle|isabelletheory|isabellesession|uses|tags|status|blueprintstatus|formalstatus|agentstatus)\{[^{}]*\}\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class _LatexBlock:
    kind: str
    title: str | None
    body: str
    source_file: str
    source_line: int


def parse_latex_file(path: Path | str, *, project_name: str | None = None) -> BlueprintProject:
    """Parse a single LaTeX blueprint file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    name = project_name or p.stem
    return parse_latex_text(text, source=str(p), project_name=name)


def parse_latex_text(
    text: str, *, source: str = "<text>", project_name: str = "blueprint"
) -> BlueprintProject:
    """Parse LaTeX theorem-like environments into a :class:`BlueprintProject`."""
    blocks = _scan_latex_blocks(text, source=source)
    nodes = [_block_to_node(block) for block in blocks]
    return BlueprintProject.from_nodes(project_name, nodes, sources=[source])


def render_markdown_blueprint(project: BlueprintProject) -> str:
    """Render parsed nodes back to the Markdown blueprint interchange format."""
    parts: list[str] = [f"# {project.name}", ""]
    for node in project.nodes:
        parts.append(f"::: {node.kind.value} {{#{node.id}}}")
        parts.append(f"title: {node.title}")
        if node.isabelle.fact:
            parts.append(f"isabelle: {node.isabelle.fact}")
        if node.uses:
            parts.append("uses:")
            parts.extend(f"  - {dep}" for dep in node.uses)
        if node.tags:
            parts.append("tags:")
            parts.extend(f"  - {tag}" for tag in node.tags)
        parts.append("status:")
        parts.append(f"  blueprint: {node.status.blueprint.value}")
        parts.append(f"  formal: {node.status.formal.value}")
        parts.append(f"  agent: {node.status.agent.value}")
        parts.append(":::")
        parts.append("")
        if node.statement.strip():
            parts.append(node.statement.strip())
            parts.append("")
        if node.informal_proof.strip():
            parts.append("## Proof")
            parts.append(node.informal_proof.strip())
            parts.append("")
        parts.append(":::")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_latex_blueprint(project: BlueprintProject) -> str:
    """Render parsed nodes to a standalone LaTeX blueprint document."""
    parts: list[str] = [
        r"\documentclass{article}",
        "",
        r"\usepackage{amsthm}",
        r"\newtheorem{definition}{Definition}",
        r"\newtheorem{lemma}{Lemma}",
        r"\newtheorem{theorem}{Theorem}",
        r"\newtheorem{proposition}{Proposition}",
        r"\newtheorem{corollary}{Corollary}",
        r"\newtheorem{construction}{Construction}",
        r"\newtheorem{remark}{Remark}",
        r"\newtheorem{example}{Example}",
        r"\newtheorem{note}{Note}",
        r"\newtheorem{other}{Other}",
        "",
        r"\newcommand{\isabelle}[1]{}",
        r"\newcommand{\isabelletheory}[1]{}",
        r"\newcommand{\isabellesession}[1]{}",
        r"\newcommand{\uses}[1]{}",
        r"\newcommand{\tags}[1]{}",
        r"\newcommand{\status}[1]{}",
        r"\newcommand{\blueprintstatus}[1]{}",
        r"\newcommand{\formalstatus}[1]{}",
        r"\newcommand{\agentstatus}[1]{}",
        "",
        r"\begin{document}",
        "",
        rf"\title{{{project.name}}}",
        r"\maketitle",
        "",
    ]
    for node in project.nodes:
        title = f"[{node.title}]" if node.title else ""
        parts.append(rf"\begin{{{node.kind.value}}}{title}")
        parts.append(rf"\label{{{node.id}}}")
        if node.isabelle.fact:
            parts.append(rf"\isabelle{{{node.isabelle.fact}}}")
            if node.isabelle.theory and not node.isabelle.fact.startswith(
                f"{node.isabelle.theory}."
            ):
                parts.append(rf"\isabelletheory{{{node.isabelle.theory}}}")
        elif node.isabelle.theory:
            parts.append(rf"\isabelletheory{{{node.isabelle.theory}}}")
        if node.isabelle.session:
            parts.append(rf"\isabellesession{{{node.isabelle.session}}}")
        if node.uses:
            parts.append(rf"\uses{{{', '.join(node.uses)}}}")
        if node.tags:
            parts.append(rf"\tags{{{', '.join(node.tags)}}}")
        parts.append(rf"\blueprintstatus{{{node.status.blueprint.value}}}")
        parts.append(rf"\formalstatus{{{node.status.formal.value}}}")
        parts.append(rf"\agentstatus{{{node.status.agent.value}}}")
        parts.append("")
        if node.statement.strip():
            parts.append(node.statement.strip())
            parts.append("")
        if node.informal_proof.strip():
            parts.append(r"\begin{proof}")
            parts.append(node.informal_proof.strip())
            parts.append(r"\end{proof}")
        parts.append(rf"\end{{{node.kind.value}}}")
        parts.append("")
    parts.append(r"\end{document}")
    return "\n".join(parts).rstrip() + "\n"


def _scan_latex_blocks(text: str, *, source: str) -> list[_LatexBlock]:
    blocks: list[_LatexBlock] = []
    for match in _ENV_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        blocks.append(
            _LatexBlock(
                kind=match.group("kind"),
                title=_clean_text(match.group("title")) if match.group("title") else None,
                body=match.group("body"),
                source_file=source,
                source_line=line,
            )
        )
    return blocks


def _block_to_node(block: _LatexBlock) -> BlueprintNode:
    label = _first(_LABEL_RE, block.body)
    if not label:
        raise ParseError(
            "LaTeX blueprint node is missing a \\label{...}",
            source=block.source_file,
            line=block.source_line,
        )

    fact = _first(_ISABELLE_RE, block.body) or _first(_LEAN_RE, block.body)
    theory = _first(_ISABELLE_THEORY_RE, block.body)
    session = _first(_ISABELLE_SESSION_RE, block.body)
    uses = _split_csv(_first(_USES_RE, block.body) or "")
    tags = _split_csv(_first(_TAGS_RE, block.body) or "")
    proof_match = _PROOF_RE.search(block.body)
    proof = _clean_body(proof_match.group("body")) if proof_match else ""
    statement_source = _PROOF_RE.sub("", block.body)
    statement = _clean_body(_COMMAND_LINE_RE.sub("", statement_source))

    status, explicit = _parse_latex_status(block.body)
    if not explicit["blueprint"] and statement:
        status.blueprint = BlueprintStatus.WRITTEN
    if not explicit["formal"]:
        status.formal = FormalStatus.NAMED if fact else FormalStatus.MISSING
        if fact and ("\\leanok" in block.body or "\\isabelleok" in block.body):
            status.formal = FormalStatus.FOUND

    return BlueprintNode(
        id=label,
        kind=NodeKind.parse(block.kind),
        title=block.title or _title_from_label(label),
        statement=statement,
        informal_proof=proof,
        uses=uses,
        isabelle=IsabelleRef(
            fact=fact.strip() if fact else None,
            theory=theory.strip() if theory else None,
            session=session.strip() if session else None,
        ),
        status=status,
        tags=tags,
        source_file=block.source_file,
        source_line=block.source_line,
        raw_metadata={"latex_label": label},
    )


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group("value").strip() if match else None


def _split_csv(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[, \n]+", text) if part.strip()]


def _parse_latex_status(text: str) -> tuple[NodeStatus, dict[str, bool]]:
    status = NodeStatus()
    explicit = {"blueprint": False, "formal": False, "agent": False}
    shorthand = _first(_STATUS_RE, text)
    if shorthand:
        axis = _apply_status_token(status, shorthand)
        if axis:
            explicit[axis] = True

    blueprint = _first(_BLUEPRINT_STATUS_RE, text)
    formal = _first(_FORMAL_STATUS_RE, text)
    agent = _first(_AGENT_STATUS_RE, text)
    try:
        if blueprint:
            status.blueprint = coerce_status(BlueprintStatus, blueprint)
            explicit["blueprint"] = True
        if formal:
            status.formal = coerce_status(FormalStatus, formal)
            explicit["formal"] = True
        if agent:
            status.agent = coerce_status(AgentStatus, agent)
            explicit["agent"] = True
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
    return status, explicit


def _apply_status_token(status: NodeStatus, raw: str) -> str | None:
    token = raw.strip().lower()
    if token in {"stub", "written", "reviewed"}:
        status.blueprint = BlueprintStatus(token)
        return "blueprint"
    if token == "planned":
        status.blueprint = BlueprintStatus.WRITTEN
        return "blueprint"
    if token in {
        "proved",
        "found",
        "missing",
        "not_found",
        "tainted",
        "stale",
        "broken",
        "failed_check",
    }:
        status.formal = FormalStatus(token)
        return "formal"
    if token in {"ready", "blocked", "solved", "attempted", "needs_human", "in_progress"}:
        status.agent = AgentStatus(token)
        return "agent"
    return None


def _title_from_label(label: str) -> str:
    tail = label.split(":")[-1].replace("-", " ").replace("_", " ")
    return tail[:1].upper() + tail[1:]


def _clean_body(text: str) -> str:
    text = re.sub(r"\\leanok\b|\\isabelleok\b", "", text)
    return _clean_text(text)


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in text.strip().splitlines()]
    return "\n".join(lines).strip()


__all__ = [
    "parse_latex_file",
    "parse_latex_text",
    "render_latex_blueprint",
    "render_markdown_blueprint",
]
