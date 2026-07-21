"""Project model: a collection of nodes plus validation."""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import SupportsIndex

from isabelle_blueprint.errors import ValidationError
from isabelle_blueprint.model.node import BlueprintNode
from isabelle_blueprint.model.status import COMPLETE_FORMAL_STATUSES, AgentStatus, FormalStatus


class _TrackedNodeList(list[BlueprintNode]):
    """A ``list[BlueprintNode]`` that counts every mutation it undergoes.

    ``BlueprintProject.nodes`` is transparently wrapped in this subclass
    (see ``BlueprintProject.__setattr__``) purely so ``by_id()``'s cache can
    tell *whether* the list changed since the index was built -- not just
    "was it replaced" or "did its length change" (which misses same-length
    in-place edits), but every mutating operation: ``append``, ``extend``,
    ``insert``, ``remove``, ``pop``, ``clear``, ``sort``, ``reverse``,
    ``+=``/``*=``, single-index assignment (``nodes[i] = other``), and slice
    assignment/deletion. Reads are completely unaffected -- this is a plain
    list to every other consumer, just with a monotonically increasing
    ``_version`` counter bumped after each mutation.
    """

    def __init__(self, *args: Iterable[BlueprintNode]) -> None:
        super().__init__(*args)
        self._version = 0

    def _bump(self) -> None:
        self._version += 1

    def append(self, obj: BlueprintNode) -> None:
        super().append(obj)
        self._bump()

    def extend(self, iterable: Iterable[BlueprintNode]) -> None:
        super().extend(iterable)
        self._bump()

    def insert(self, index: SupportsIndex, obj: BlueprintNode) -> None:
        super().insert(index, obj)
        self._bump()

    def remove(self, value: BlueprintNode) -> None:
        super().remove(value)
        self._bump()

    def pop(self, index: SupportsIndex = -1) -> BlueprintNode:
        value = super().pop(index)
        self._bump()
        return value

    def clear(self) -> None:
        super().clear()
        self._bump()

    def sort(self, *args: object, **kwargs: object) -> None:
        super().sort(*args, **kwargs)  # type: ignore[call-overload]
        self._bump()

    def reverse(self) -> None:
        super().reverse()
        self._bump()

    def __setitem__(self, index: object, value: object) -> None:
        super().__setitem__(index, value)  # type: ignore[call-overload]
        self._bump()

    def __delitem__(self, index: object) -> None:
        super().__delitem__(index)  # type: ignore[arg-type]
        self._bump()

    def __iadd__(self, other: Iterable[BlueprintNode]) -> _TrackedNodeList:  # type: ignore[override, misc]
        result = super().__iadd__(other)
        self._bump()
        return result  # type: ignore[return-value]

    def __imul__(self, n: SupportsIndex) -> _TrackedNodeList:
        result = super().__imul__(n)
        self._bump()
        return result  # type: ignore[return-value]


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
                {"node": node, "missing": missing} for node, missing in self.missing_dependencies
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

    # Cache for by_id(): (identity of the `nodes` list, its `_version` at
    # build time, index). `self.nodes` is transparently wrapped in
    # `_TrackedNodeList` (see `__setattr__` below), which bumps a private
    # `_version` counter on *every* mutating operation -- append, extend,
    # insert, remove, pop, clear, sort, reverse, `+=`/`*=`, single-index
    # assignment (`nodes[i] = other_node`), and slice assignment/deletion.
    # The cache is valid iff the list object is still the same one *and* its
    # version hasn't advanced, so same-length in-place edits (which a plain
    # `(identity, len)` check would miss) are also caught, at O(1) cost.
    # In-place attribute mutation on an already-present node (e.g. updating
    # `status`) never needs invalidation: the cached index stores references
    # to the same node objects, so such mutations are visible automatically.
    # The one residual, deliberately out-of-scope gap is mutating
    # `node.id` directly in place (`node.id = "new"`) without going through
    # any list operation -- nothing in this codebase does that; the
    # supported way to rename a node's id is index replacement
    # (`project.nodes[i] = dataclasses.replace(node, id="new")`), which the
    # `_TrackedNodeList.__setitem__` override already invalidates correctly.
    _id_index_cache: tuple[list[BlueprintNode], int, dict[str, BlueprintNode]] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name == "nodes" and not isinstance(value, _TrackedNodeList):
            value = _TrackedNodeList(value)  # type: ignore[arg-type]
        super().__setattr__(name, value)

    # ---- collection helpers ------------------------------------------------

    def __iter__(self) -> Iterator[BlueprintNode]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def _by_id_index(self) -> dict[str, BlueprintNode]:
        """Return the *live*, cached node-id index -- for internal use only.

        This is the zero-copy counterpart to :meth:`by_id`: it returns the
        cached ``dict`` object directly rather than a defensive copy, so
        repeated internal lookups (task generation, dependency-depth and
        blocking-count calculations, ...) don't each pay an O(n) rebuild or
        an O(n) copy. Callers **must never mutate** the returned mapping --
        it is shared and reused across calls until ``self.nodes`` changes.
        Public/external code should call :meth:`by_id` instead, which
        returns an independent copy.
        """
        version = getattr(self.nodes, "_version", 0)
        cache = self._id_index_cache
        if cache is not None and cache[0] is self.nodes and cache[1] == version:
            return cache[2]
        index = {node.id: node for node in self.nodes}
        self._id_index_cache = (self.nodes, version, index)
        return index

    def by_id(self) -> dict[str, BlueprintNode]:
        """Return a mapping of node id -> node.

        The underlying index is cached and reused across calls as long as
        ``self.nodes`` hasn't changed since it was built (see
        ``_id_index_cache`` / :meth:`_by_id_index`), so hot paths that call
        ``by_id()`` repeatedly (task generation, dependency-depth/blocking-
        count calculations, report generators, ...) don't each pay a full
        O(n) rebuild. A fresh ``dict`` is still returned on every call --
        callers get an independent object, exactly as before -- so
        accidental mutation of the result can never corrupt the cache.
        """
        return dict(self._by_id_index())

    def get(self, node_id: str) -> BlueprintNode | None:
        return self._by_id_index().get(node_id)

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

        # cycle detection (DFS), run iteratively via an explicit stack so
        # deep or reversed dependency chains (beyond
        # ``sys.getrecursionlimit()``) don't raise ``RecursionError``. The
        # traversal order, cycle-capture logic, and output ordering are kept
        # identical to the previous recursive implementation.
        adjacency: dict[str, list[str]] = {
            n.id: [d for d in n.uses if d in all_ids] for n in self.nodes
        }
        visited: set[str] = set()
        path: list[str] = []
        on_stack: set[str] = set()
        cycles_seen: set[tuple[str, ...]] = set()

        for start in adjacency:
            if start in visited:
                continue
            # Parallel stacks mirror the recursive call stack: `stack_ids[i]`
            # is the node at depth `i`, and `stack_idx[i]` is the index of the
            # next neighbour of that node still to be examined.
            stack_ids: list[str] = [start]
            stack_idx: list[int] = [0]
            visited.add(start)
            on_stack.add(start)
            path.append(start)
            while stack_ids:
                current = stack_ids[-1]
                idx = stack_idx[-1]
                neighbours = adjacency.get(current, [])
                if idx >= len(neighbours):
                    # equivalent to falling off the end of dfs(current)
                    path.pop()
                    on_stack.discard(current)
                    stack_ids.pop()
                    stack_idx.pop()
                    continue
                stack_idx[-1] = idx + 1
                neighbour = neighbours[idx]
                if neighbour in on_stack:
                    cycle_start = path.index(neighbour)
                    cycle = tuple(path[cycle_start:] + [neighbour])
                    # canonical form so we don't record both rotations
                    canonical = _canonical_cycle(cycle)
                    if canonical not in cycles_seen:
                        cycles_seen.add(canonical)
                        report.cycles.append(list(cycle))
                elif neighbour not in visited:
                    # equivalent to entering dfs(neighbour)
                    visited.add(neighbour)
                    on_stack.add(neighbour)
                    path.append(neighbour)
                    stack_ids.append(neighbour)
                    stack_idx.append(0)

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
        by_id = self._by_id_index()
        manual = {AgentStatus.IN_PROGRESS, AgentStatus.ATTEMPTED, AgentStatus.NEEDS_HUMAN}
        for node in self.nodes:
            if node.status.agent in manual:
                continue
            if node.status.formal == FormalStatus.PROVED:
                node.status.agent = AgentStatus.SOLVED
                continue
            deps_ok = all(
                (dep := by_id.get(dep_id)) and dep.status.formal in COMPLETE_FORMAL_STATUSES
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
    def from_nodes(
        cls, name: str, nodes: Iterable[BlueprintNode], sources: Iterable[str] = ()
    ) -> BlueprintProject:
        return cls(name=name, nodes=list(nodes), source_files=list(sources))


def _canonical_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Return a rotation-invariant form of ``cycle`` (excluding the duplicate tail)."""
    if len(cycle) <= 1:
        return cycle
    # Drop the duplicated last element if it matches the start of the cycle.
    body = cycle[:-1] if cycle[-1] == cycle[0] else cycle
    rotations = [body[i:] + body[:i] for i in range(len(body))]
    return min(rotations)
