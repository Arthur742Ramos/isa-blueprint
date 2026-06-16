"""Tag co-occurrence analysis: which tags appear together on the same nodes.

``tag-cooccurrence`` looks at every node's declared ``tags`` and, for each
unordered pair of distinct tags, counts how many nodes carry *both*. The result
is a ranking of tag pairs by descending shared-node count, which surfaces tag
clusters (tags that travel together) and potential redundancy (two tags that
are almost always used in tandem).

A node contributes a pair only when it carries at least two distinct tags;
nodes with fewer than two tags add nothing. Repeated tags within a single node
are de-duplicated so a pair is never double-counted from one node. No Isabelle
invocation is required.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from isabelle_blueprint.model.project import BlueprintProject

TAG_COOCCURRENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TagPair:
    """One unordered pair of tags and the nodes carrying both.

    ``tags`` is the pair as a sorted 2-tuple. ``node_ids`` lists the ids of the
    nodes that carry both tags, in the project's node order.
    """

    tags: tuple[str, str]
    node_ids: tuple[str, ...]

    @property
    def shared_count(self) -> int:
        return len(self.node_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "tags": list(self.tags),
            "shared_count": self.shared_count,
            "node_ids": list(self.node_ids),
        }


@dataclass(frozen=True)
class TagCooccurrenceReport:
    """Ranked tag co-occurrence across a :class:`BlueprintProject`."""

    project: str
    min_shared: int
    pairs: tuple[TagPair, ...]
    schema_version: int = TAG_COOCCURRENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "min_shared": self.min_shared,
            "pair_count": len(self.pairs),
            "pairs": [pair.to_dict() for pair in self.pairs],
        }


def build_tag_cooccurrence_report(
    project: BlueprintProject, min_shared: int = 1
) -> TagCooccurrenceReport:
    """Compute tag co-occurrence counts for ``project``.

    For every unordered pair of distinct tags, count the nodes carrying both.
    Only pairs whose shared-node count is at least ``max(min_shared, 1)`` are
    kept (a pair with no shared node is never represented). Pairs are sorted by
    descending shared count, then alphabetically by the pair for stable output.
    """

    threshold = max(min_shared, 1)

    members: dict[tuple[str, str], list[str]] = {}
    for node in project.nodes:
        # De-duplicate tags within a node so a repeated tag is not double-counted,
        # then sort so each unordered pair has a single canonical key.
        node_tags = sorted(dict.fromkeys(node.tags))
        if len(node_tags) < 2:
            continue
        for pair in combinations(node_tags, 2):
            members.setdefault(pair, []).append(node.id)

    pairs = tuple(
        TagPair(tags=pair, node_ids=tuple(node_ids))
        for pair, node_ids in members.items()
        if len(node_ids) >= threshold
    )
    pairs = tuple(
        sorted(pairs, key=lambda p: (-p.shared_count, p.tags))
    )

    return TagCooccurrenceReport(
        project=project.name,
        min_shared=threshold,
        pairs=pairs,
    )


def render_tag_cooccurrence_report(report: TagCooccurrenceReport) -> str:
    """Render the ranking as a compact Markdown table for the terminal."""

    lines = [
        f"# {report.project} tag co-occurrence",
        "",
        (
            f"{len(report.pairs)} tag pair(s) sharing at least "
            f"{report.min_shared} node(s)."
        ),
        "",
    ]
    if not report.pairs:
        lines.append("_(no co-occurring tags)_")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Tag A | Tag B | Shared nodes |",
            "| --- | --- | --- |",
        ]
    )
    for pair in report.pairs:
        a, b = pair.tags
        lines.append(f"| {a} | {b} | {pair.shared_count} |")
    return "\n".join(lines) + "\n"
