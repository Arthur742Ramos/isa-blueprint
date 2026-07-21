"""Fuzzy suggestions for missing Isabelle fact names."""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import COMPLETE_FORMAL_STATUSES, FormalStatus
from isabelle_blueprint.scaffold import suggest_fact


@dataclass(frozen=True)
class FactSuggestion:
    """Suggested replacements for one missing formal target."""

    node_id: str
    target_fact: str
    suggestions: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_SUGGEST_FOR = {
    FormalStatus.NOT_FOUND,
    FormalStatus.FAILED_CHECK,
    FormalStatus.BROKEN,
    FormalStatus.NAMED,
}


def suggest_missing_facts(
    project: BlueprintProject,
    *,
    dump_report_path: Path | None = None,
    limit: int = 5,
) -> list[FactSuggestion]:
    """Suggest nearby fact names for unresolved formal targets."""

    candidates = _candidate_facts(project, dump_report_path=dump_report_path)
    suggestions: list[FactSuggestion] = []
    for node in project.nodes:
        target = node.isabelle.fact
        if not target or node.status.formal not in _SUGGEST_FOR:
            continue
        pool = sorted(candidate for candidate in candidates if candidate != target)
        close = _ranked_matches(target, pool, limit=limit)
        if close:
            suggestions.append(FactSuggestion(node.id, target, close))
    return suggestions


def suggestions_by_node(suggestions: list[FactSuggestion]) -> dict[str, FactSuggestion]:
    """Index suggestions by blueprint node id."""

    return {suggestion.node_id: suggestion for suggestion in suggestions}


def write_fact_suggestions(suggestions: list[FactSuggestion], path: Path) -> Path:
    """Write suggestions to JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"suggestions": [suggestion.to_dict() for suggestion in suggestions]}, indent=2),
        encoding="utf-8",
    )
    return path


def _candidate_facts(
    project: BlueprintProject,
    *,
    dump_report_path: Path | None,
) -> set[str]:
    candidates = {
        node.isabelle.fact
        for node in project.nodes
        if node.isabelle.fact and node.status.formal in COMPLETE_FORMAL_STATUSES
    }
    candidates.update(node.isabelle.fact for node in project.nodes if node.isabelle.fact)
    for node in project.nodes:
        inferred = suggest_fact(node.id)
        if node.isabelle.theory:
            candidates.add(f"{node.isabelle.theory}.{inferred}")
        candidates.add(inferred)
    if dump_report_path is not None:
        candidates.update(_dump_report_candidates(dump_report_path))
    return {candidate for candidate in candidates if candidate}


def _dump_report_candidates(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return set()
    candidates: set[str] = set()
    for item in facts:
        if not isinstance(item, dict):
            continue
        fact = item.get("fact")
        if isinstance(fact, str) and fact:
            candidates.add(fact)
    return candidates


def _ranked_matches(target: str, candidates: list[str], *, limit: int) -> list[str]:
    direct = difflib.get_close_matches(target, candidates, n=limit, cutoff=0.45)
    if len(direct) >= limit:
        return direct[:limit]
    target_tail = target.rsplit(".", 1)[-1]
    by_tail = {
        candidate.rsplit(".", 1)[-1]: candidate for candidate in candidates if "." in candidate
    }
    tail_matches = difflib.get_close_matches(
        target_tail,
        sorted(by_tail),
        n=limit,
        cutoff=0.5,
    )
    merged = list(direct)
    for tail in tail_matches:
        candidate = by_tail[tail]
        if candidate not in merged:
            merged.append(candidate)
        if len(merged) == limit:
            break
    return merged
