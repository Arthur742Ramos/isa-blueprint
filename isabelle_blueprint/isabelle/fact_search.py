"""Search Isabelle ``.thy`` sources for declared fact/lemma/theorem names.

This is the source-only counterpart to the blueprint-internal fact suggester:
where :mod:`isabelle_blueprint.isabelle.suggestions` proposes names from the
blueprint itself, ``search-facts`` looks at the *actual* declarations in the
theory files (via :class:`SourceIndex`) so you can find the real name to drop
into a node's ``isabelle:`` line - no running Isabelle required.

Two modes are supported:

* **free text** - rank every indexed declaration against a query string
  (exact > prefix > substring > fuzzy), optionally filtered by kind.
* **missing targets** - for each blueprint node whose formal target is
  unresolved (``not_found``/``failed_check``/``broken``/``named``), fuzzy-match
  its referenced fact's short name against the real declarations.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from isabelle_blueprint.isabelle.source_index import SourceEntry, SourceIndex
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus

# Formal statuses that signal a node's fact reference still needs resolving.
_UNRESOLVED_FOR = {
    FormalStatus.NOT_FOUND,
    FormalStatus.FAILED_CHECK,
    FormalStatus.BROKEN,
    FormalStatus.NAMED,
}

_FUZZY_CUTOFF = 0.4


@dataclass(frozen=True)
class FactHit:
    """One ranked declaration matched from the theory sources."""

    key: str
    name: str
    kind: str
    theory: str
    line: int
    path: str
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "theory": self.theory,
            "line": self.line,
            "path": self.path,
            "score": round(self.score, 3),
        }


@dataclass(frozen=True)
class NodeFactMatch:
    """Candidate real declarations for one node's unresolved fact target."""

    node_id: str
    target_fact: str
    hits: list[FactHit]

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "target_fact": self.target_fact,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def _score(query: str, entry: SourceEntry) -> float:
    name = entry.name.lower()
    key = entry.key.lower()
    if query == name or query == key:
        return 1.0
    if name.startswith(query) or key.endswith("." + query):
        return 0.9
    if query in name or query in key:
        return 0.75
    return max(
        difflib.SequenceMatcher(None, query, name).ratio(),
        difflib.SequenceMatcher(None, query, key).ratio(),
    )


def search_index(
    index: SourceIndex,
    query: str,
    *,
    kinds: set[str] | None = None,
    limit: int = 10,
) -> list[FactHit]:
    """Return up to ``limit`` declarations ranked against ``query``.

    A non-positive ``limit`` yields no hits. A negative ``limit`` previously fell
    through to ``hits[:limit]`` and silently dropped the *lowest*-ranked match
    instead of returning nothing, which is a confusing footgun for callers that
    forward an unvalidated CLI value.
    """
    needle = query.strip().lower()
    if not needle or limit <= 0:
        return []
    hits: list[FactHit] = []
    for entry in index.entries:
        if kinds is not None and entry.kind not in kinds:
            continue
        score = _score(needle, entry)
        if score < _FUZZY_CUTOFF:
            continue
        hits.append(
            FactHit(
                key=entry.key,
                name=entry.name,
                kind=entry.kind,
                theory=entry.theory,
                line=entry.line,
                path=entry.path,
                score=score,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.key))
    return hits[:limit]


def match_missing_facts(
    project: BlueprintProject,
    index: SourceIndex,
    *,
    limit: int = 5,
) -> list[NodeFactMatch]:
    """Suggest real declarations for each node with an unresolved fact target."""
    matches: list[NodeFactMatch] = []
    for node in project.nodes:
        fact = node.isabelle.fact
        if not fact or node.status.formal not in _UNRESOLVED_FOR:
            continue
        short = fact.rsplit(".", 1)[-1]
        hits = search_index(index, short, limit=limit)
        if hits:
            matches.append(NodeFactMatch(node.id, fact, hits))
    return matches


def render_hits(query: str, hits: list[FactHit]) -> str:
    """Render free-text search ``hits`` as text (trailing newline)."""
    if not hits:
        return f"no declarations match {query!r}\n"
    lines = [f"matches for {query!r}:"]
    for hit in hits:
        lines.append(
            f"  {hit.key}  [{hit.kind}]  {hit.path}:{hit.line}  (score {hit.score:.2f})"
        )
    return "\n".join(lines) + "\n"


def _md_cell(text: str) -> str:
    """Escape ``|`` so a value never breaks the surrounding Markdown table."""
    return text.replace("|", "\\|")


def render_hits_markdown(query: str, hits: list[FactHit]) -> str:
    """Render free-text search ``hits`` as a Markdown table (trailing newline)."""
    lines = [f"# Fact search: {query}", ""]
    if not hits:
        lines.append(f"No declarations match {query!r}.")
        return "\n".join(lines) + "\n"
    lines.append("| Fact | Score | Theory |")
    lines.append("| --- | --- | --- |")
    for hit in hits:
        lines.append(
            f"| `{_md_cell(hit.key)}` | {hit.score:.2f} | {_md_cell(hit.theory)} |"
        )
    return "\n".join(lines) + "\n"


def render_matches_markdown(matches: list[NodeFactMatch]) -> str:
    """Render missing-target ``matches`` as Markdown (trailing newline)."""
    lines = ["# Fact search: unresolved targets", ""]
    if not matches:
        lines.append("No unresolved fact targets with source matches.")
        return "\n".join(lines) + "\n"
    for match in matches:
        lines.append(f"## `{match.node_id}` (target `{match.target_fact}`)")
        lines.append("")
        lines.append("| Fact | Score | Theory |")
        lines.append("| --- | --- | --- |")
        for hit in match.hits:
            lines.append(
                f"| `{_md_cell(hit.key)}` | {hit.score:.2f} | {_md_cell(hit.theory)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_matches(matches: list[NodeFactMatch]) -> str:
    """Render missing-target ``matches`` as text (trailing newline)."""
    if not matches:
        return "no unresolved fact targets with source matches\n"
    lines: list[str] = []
    for match in matches:
        lines.append(f"{match.node_id}  (target {match.target_fact})")
        for hit in match.hits:
            lines.append(
                f"  -> {hit.key}  [{hit.kind}]  {hit.path}:{hit.line}  "
                f"(score {hit.score:.2f})"
            )
    return "\n".join(lines) + "\n"
