"""Generate ready-to-edit blueprint node stubs in the lighter Markdown grammar.

This powers the ``isabelle-blueprint new`` command. The goal is to remove the
"blank page" problem: a single command emits a node skeleton with a humanised
title, a suggested Isabelle fact name, and (for proof-carrying kinds) a
``## Proof`` section, so the author only has to fill in the prose.
"""
from __future__ import annotations

import re

from isabelle_blueprint.parser.markdown import _humanize_id

# Kinds that get a `## Proof` section in the generated stub.
_PROOF_KINDS = {"lemma", "theorem", "proposition", "corollary"}


def suggest_fact(node_id: str) -> str:
    """Suggest an Isabelle fact name from a node id.

    ``add-zero-right`` -> ``add_zero_right``; ``thm:pythagoras`` -> ``pythagoras``.
    Hyphens become underscores so the result is a valid Isabelle identifier.
    """
    tail = node_id.split(":")[-1]
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", tail).strip("_")
    return cleaned or node_id


def render_node_stub(
    kind: str,
    node_id: str,
    *,
    title: str | None = None,
    fact: str | None = None,
    uses: list[str] | None = None,
    status: str | None = "stub",
) -> str:
    """Return a blueprint node stub as a Markdown string.

    The stub uses the lighter grammar: inline ``key: value`` metadata, a blank
    line separating metadata from the body, and a single closing ``:::``.
    Passing ``fact=""`` suppresses the ``isabelle:`` line; leaving it ``None``
    fills in :func:`suggest_fact`.
    """
    title = title if title is not None else _humanize_id(node_id)
    fact = fact if fact is not None else suggest_fact(node_id)

    lines = [f"::: {kind} {{#{node_id}}}", f"title: {title}"]
    if fact:
        lines.append(f"isabelle: {fact}")
    if uses:
        lines.append("uses:")
        lines.extend(f"  - {dep}" for dep in uses)
    if status:
        lines.append(f"status: {status}")

    lines.append("")  # blank line: ends inline metadata, starts the body
    lines.append(f"<!-- TODO: state the {kind} here. -->")
    if kind in _PROOF_KINDS:
        lines.append("")
        lines.append("## Proof")
        lines.append("")
        lines.append("<!-- TODO: sketch the proof. -->")
    lines.append(":::")
    return "\n".join(lines) + "\n"
