"""Export a blueprint plan into an Isabelle ``.thy`` scaffold.

This is the reverse of :mod:`isabelle_blueprint.isabelle.theory_import`. Where the
importer derives a blueprint from existing Isabelle declarations, the exporter
turns a blueprint *plan* into a single, buildable theory skeleton so a human or
agent can start formalizing without facing a blank page.

The generator is deterministic (no timestamps or nonces) so its output can be
pinned with golden-string tests and round-tripped. It emits one ``theory`` that
imports only ``Main`` -- keeping the scaffold buildable before the real
session theories exist -- with the nodes laid out in dependency order (a node's
dependencies always precede it).
"""
from __future__ import annotations

import re

from isabelle_blueprint.graph.dependency_graph import dependency_levels
from isabelle_blueprint.isabelle.theory_gen import _thy_inner_string
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.project import BlueprintProject


def sanitize_theory_name(name: str) -> str:
    """Coerce *name* into a valid Isabelle theory identifier.

    Isabelle theory names (and their long-ident lemma names) match
    ``[A-Za-z][A-Za-z0-9_']*``. Runs of other characters collapse to a single
    underscore; a leading digit/underscore is prefixed with ``T`` so the result
    always starts with a letter. Empty input yields ``Blueprint``.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_']+", "_", name).strip("_")
    if not cleaned:
        return "Blueprint"
    if not cleaned[0].isalpha():
        cleaned = f"T_{cleaned}"
    return cleaned


def _lemma_name(node: BlueprintNode) -> str:
    """Short, valid Isabelle lemma identifier for *node*.

    Prefers the short name from the node's Isabelle ``fact`` (the segment after
    the final ``.``); otherwise falls back to a sanitized form of the node id.
    """
    fact = node.isabelle.fact
    if fact:
        short = fact.rsplit(".", 1)[-1].strip()
        if short:
            return sanitize_theory_name(short)
    return sanitize_theory_name(node.id)


def _topological_node_ids(project: BlueprintProject) -> list[str]:
    """Node ids in dependency order: a node's ``uses`` appear before it.

    Reuses :func:`dependency_levels` (leaves first, stable within a level by id).
    Any ids that the layering omits -- it only sees nodes reachable in the
    dependency graph -- are appended afterwards in declaration order so no node
    is silently dropped.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for level in dependency_levels(project):
        for node_id in level:
            if node_id not in seen:
                ordered.append(node_id)
                seen.add(node_id)
    for node in project.nodes:
        if node.id not in seen:
            ordered.append(node.id)
            seen.add(node.id)
    return ordered


def _safe_comment(text: str) -> str:
    """Make *text* safe to embed inside an Isabelle ``(* ... *)`` comment.

    Nested ``(*``/``*)`` tokens would prematurely open/close the comment, so a
    space is inserted to break the token while preserving readability.
    """
    return text.replace("*)", "* )").replace("(*", "( *")


def _uses_label(node: BlueprintNode, by_id: dict[str, BlueprintNode]) -> list[str]:
    """Render a dependency reference per ``uses`` entry: fact name, else id."""
    labels: list[str] = []
    for dep_id in node.uses:
        dep = by_id.get(dep_id)
        if dep is not None and dep.isabelle.fact:
            labels.append(dep.isabelle.fact)
        else:
            labels.append(dep_id)
    return labels


def _render_node(node: BlueprintNode, by_id: dict[str, BlueprintNode]) -> list[str]:
    """Render one node: a comment block followed by a stub lemma or a TODO."""
    title = node.title.strip() or node.id
    lines = [f"(* {node.kind.value}: {_safe_comment(title)} [{node.id}] *)"]

    uses = _uses_label(node, by_id)
    if uses:
        lines.append(f"(*   uses: {_safe_comment(', '.join(uses))} *)")

    statement = node.statement.strip()
    if statement:
        for raw in statement.splitlines():
            lines.append(f"(*   {_safe_comment(raw.rstrip())} *)")

    goal = (node.goal or "").strip()
    if goal:
        name = _lemma_name(node)
        lines.append(f'lemma {name}: "{_thy_inner_string(goal)}"')
        lines.append("  sorry")
    else:
        lines.append(f"(* TODO: formalize {node.kind.value} {node.id}: {_safe_comment(title)} *)")
    return lines


def generate_theory_scaffold(
    project: BlueprintProject, *, theory_name: str | None = None
) -> str:
    """Return the source of a buildable ``.thy`` scaffold for *project*.

    The theory imports only ``Main`` and lays out every node in dependency order.
    Goal-bearing nodes become ``lemma ... sorry`` stubs; goalless nodes become a
    ``TODO`` comment so the file still builds.
    """
    name = sanitize_theory_name(theory_name) if theory_name else sanitize_theory_name(project.name)
    by_id = project.by_id()

    lines = [f"theory {name}", "  imports Main", "begin", ""]
    for node_id in _topological_node_ids(project):
        node = by_id.get(node_id)
        if node is None:
            continue
        lines.extend(_render_node(node, by_id))
        lines.append("")
    lines.append("end")
    return "\n".join(lines) + "\n"
