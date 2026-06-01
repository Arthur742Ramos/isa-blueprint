"""Project model: a collection of nodes plus validation."""
from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.errors import ValidationError
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.status import AgentStatus, FormalStatus


@dataclass
class ValidationReport:
    """The output of :meth:`BlueprintProject.validate`."""

    duplicate_ids: list[str] = field(default_factory=list)
    missing_dependencies: list[tuple[str, str]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    # missing-dependency id -> ranked list of similar known ids ("did you mean?")
    suggestions: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.duplicate_ids or self.missing_dependencies or self.cycles)

    def issues(self) -> list[str]:
        msgs: list[str] = []
        for dup in self.duplicate_ids:
            msgs.append(f"duplicate node id: {dup!r}")
        for node_id, missing in self.missing_dependencies:
            msg = f"node {node_id!r} depends on undefined node {missing!r}"
            hints = self.suggestions.get(missing)
            if hints:
                quoted = " or ".join(repr(h) for h in hints)
                msg += f" (did you mean {quoted}?)"
            msgs.append(msg)
        for cycle in self.cycles:
            msgs.append("dependency cycle: " + " -> ".join(cycle))
        return msgs

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise ValidationError("blueprint validation failed", issues=self.issues())

    def to_dict(self) -> dict:
        return {
            "duplicate_ids": list(self.duplicate_ids),
            "missing_dependencies": [
                {"node": node, "missing": missing}
                for node, missing in self.missing_dependencies
            ],
            "cycles": [list(cycle) for cycle in self.cycles],
            "suggestions": {k: list(v) for k, v in self.suggestions.items()},
            "ok": self.ok,
        }


@dataclass
class BlueprintProject:
    """A parsed blueprint.

    Iterating yields nodes in the order they were declared in the source.
    """

    name: str
    nodes: list[BlueprintNode] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    # ---- collection helpers ------------------------------------------------

    def __iter__(self) -> Iterator[BlueprintNode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def by_id(self) -> dict[str, BlueprintNode]:
        return {node.id: node for node in self.nodes}

    def get(self, node_id: str) -> BlueprintNode | None:
        return self.by_id().get(node_id)

    # ---- validation --------------------------------------------------------

    def validate(self) -> ValidationReport:
        report = ValidationReport()

        # duplicate ids
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                report.duplicate_ids.append(node.id)
            seen.add(node.id)

        # missing dependencies (with "did you mean?" suggestions)
        all_ids = {node.id for node in self.nodes}
        sorted_ids = sorted(all_ids)
        for node in self.nodes:
            for dep in node.uses:
                if dep not in all_ids:
                    report.missing_dependencies.append((node.id, dep))
                    if dep not in report.suggestions:
                        close = difflib.get_close_matches(dep, sorted_ids, n=3, cutoff=0.6)
                        if close:
                            report.suggestions[dep] = close

        # cycle detection (DFS)
        adjacency: dict[str, list[str]] = {n.id: [d for d in n.uses if d in all_ids] for n in self.nodes}
        visited: set[str] = set()
        path: list[str] = []
        on_stack: set[str] = set()
        cycles_seen: set[tuple[str, ...]] = set()

        def dfs(current: str) -> None:
            visited.add(current)
            on_stack.add(current)
            path.append(current)
            for neighbour in adjacency.get(current, []):
                if neighbour in on_stack:
                    start = path.index(neighbour)
                    cycle = tuple(path[start:] + [neighbour])
                    # canonical form so we don't record both rotations
                    canonical = _canonical_cycle(cycle)
                    if canonical not in cycles_seen:
                        cycles_seen.add(canonical)
                        report.cycles.append(list(cycle))
                elif neighbour not in visited:
                    dfs(neighbour)
            path.pop()
            on_stack.discard(current)

        for node_id in adjacency:
            if node_id not in visited:
                dfs(node_id)

        return report

    # ---- status helpers ----------------------------------------------------

    def recompute_agent_status(self) -> None:
        """Update ``status.agent`` based on dependency completeness.

        A node becomes READY when:
          * its formal status is not yet PROVED, and
          * all dependencies have formal status FOUND or PROVED.

        Otherwise the node is BLOCKED, unless it is already PROVED (then SOLVED).
        ``IN_PROGRESS``/``ATTEMPTED``/``NEEDS_HUMAN`` set by humans are preserved.
        """
        by_id = self.by_id()
        manual = {AgentStatus.IN_PROGRESS, AgentStatus.ATTEMPTED, AgentStatus.NEEDS_HUMAN}
        for node in self.nodes:
            if node.status.agent in manual:
                continue
            if node.status.formal == FormalStatus.PROVED:
                node.status.agent = AgentStatus.SOLVED
                continue
            deps_ok = all(
                (dep := by_id.get(dep_id))
                and dep.status.formal in {FormalStatus.FOUND, FormalStatus.PROVED}
                for dep_id in node.uses
            )
            node.status.agent = AgentStatus.READY if deps_ok else AgentStatus.BLOCKED

    # ---- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source_files": list(self.source_files),
            "nodes": [n.to_dict() for n in self.nodes],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_nodes(cls, name: str, nodes: Iterable[BlueprintNode], sources: Iterable[str] = ()) -> BlueprintProject:
        return cls(name=name, nodes=list(nodes), source_files=list(sources))


def _canonical_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Return a rotation-invariant form of ``cycle`` (excluding the duplicate tail)."""
    if len(cycle) <= 1:
        return cycle
    # Drop the duplicated last element if it matches the start of the cycle.
    body = cycle[:-1] if cycle[-1] == cycle[0] else cycle
    rotations = [body[i:] + body[:i] for i in range(len(body))]
    return min(rotations)
