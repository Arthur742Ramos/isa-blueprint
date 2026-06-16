"""Rename a blueprint node id everywhere it is *referenced as an id*.

Renaming is deliberately conservative: it rewrites only the syntactic positions
the parsers treat as ids (Markdown ``{#id}`` openers, ``id:`` metadata, ``uses``
references, and the LaTeX ``\\label`` / ``\\uses`` commands) and never touches
prose. The riskiest part is "did we rewrite the right things and nothing else",
so after rewriting in memory the whole project is re-parsed and verified before
anything is written to disk. If verification fails, the rename is aborted with a
:class:`BlueprintError` and no files are modified.

Persistent JSON stores keyed by node id (agent memory, GitHub sync state, and
assignments) are rekeyed in lock-step so history/ownership follow the rename.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.config import BlueprintConfig
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.parser import parse_blueprint
from isabelle_blueprint.parser.markdown import (
    _DIRECTIVE_CLOSE,
    _DIRECTIVE_OPEN,
    _FENCE_RE,
    _FRONTMATTER_FENCE,
    _looks_like_meta,
)

# Characters that may appear inside a node id (mirrors the parser id classes).
_ID_CHAR = r"[\w.\-/:]"


@dataclass
class StoreRekey:
    """A pending key rename inside one JSON store file."""

    name: str
    path: Path
    changed: bool

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "path": str(self.path), "changed": self.changed}


@dataclass
class FileEdit:
    """Per-file count of id edits that a rename would apply."""

    path: str
    edit_count: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "edit_count": self.edit_count}


@dataclass
class RenameResult:
    """Outcome of a (possibly dry-run) rename."""

    old_id: str
    new_id: str
    dry_run: bool
    changed_files: list[str] = field(default_factory=list)
    store_rekeys: list[StoreRekey] = field(default_factory=list)
    uses_updated: int = 0
    file_edits: list[FileEdit] = field(default_factory=list)

    @property
    def total_edits(self) -> int:
        """Total id edits across every source file plus rekeyed stores."""
        return sum(e.edit_count for e in self.file_edits) + sum(
            1 for s in self.store_rekeys if s.changed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "old_id": self.old_id,
            "new_id": self.new_id,
            "dry_run": self.dry_run,
            "changed_files": list(self.changed_files),
            "uses_updated": self.uses_updated,
            "stores": [s.to_dict() for s in self.store_rekeys],
            "total_edits": self.total_edits,
            "files": [e.to_dict() for e in self.file_edits],
        }


def rename_node(
    config: BlueprintConfig, old_id: str, new_id: str, *, dry_run: bool = False
) -> RenameResult:
    """Rename node ``old_id`` to ``new_id`` across all blueprint sources.

    Raises :class:`BlueprintError` when ``old_id`` is unknown, ``new_id`` already
    exists, the ids are equal/empty, or post-rewrite verification fails.
    """
    if not old_id or not new_id:
        raise BlueprintError("rename requires a non-empty old id and new id")
    if old_id == new_id:
        raise BlueprintError("old id and new id are identical; nothing to rename")
    if re.search(r"\s", new_id):
        raise BlueprintError(f"new id {new_id!r} must not contain whitespace")

    paths = [p for p in config.blueprint_paths if p.exists()]
    if not paths:
        raise BlueprintError("no blueprint source files found to rename in")

    project = parse_blueprint(paths, project_name=config.project_name)
    ids = {node.id for node in project.nodes}
    if old_id not in ids:
        raise BlueprintError(f"node id {old_id!r} not found in the blueprint")
    if new_id in ids:
        raise BlueprintError(f"target id {new_id!r} already exists; choose another")

    rewritten: dict[Path, str] = {}
    changed_files: list[str] = []
    file_edits: list[FileEdit] = []
    uses_updated = 0
    for path in paths:
        original = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".tex":
            new_text, count = _rewrite_latex(original, old_id, new_id)
        else:
            new_text, count = _rewrite_markdown(original, old_id, new_id)
        rewritten[path] = new_text
        if new_text != original:
            changed_files.append(str(path))
            file_edits.append(FileEdit(path=str(path), edit_count=count))
            uses_updated += count

    _verify_rename(config, rewritten, paths, old_id, new_id, ids)

    store_rekeys = _plan_store_rekeys(config, old_id, new_id)

    if not dry_run:
        # Write everything with a best-effort rollback: if any write fails part
        # way through, restore the files we already touched so the tree is not
        # left in a half-renamed state.
        written: list[tuple[Path, str]] = []
        try:
            for path, new_text in rewritten.items():
                original = path.read_text(encoding="utf-8")
                if new_text != original:
                    written.append((path, original))
                    path.write_text(new_text, encoding="utf-8")
            for rekey in store_rekeys:
                if rekey.changed:
                    _apply_store_rekey(rekey.path, old_id, new_id)
        except OSError:
            for path, original in reversed(written):
                try:
                    path.write_text(original, encoding="utf-8")
                except OSError:
                    pass
            raise

    return RenameResult(
        old_id=old_id,
        new_id=new_id,
        dry_run=dry_run,
        changed_files=changed_files,
        store_rekeys=store_rekeys,
        uses_updated=uses_updated,
        file_edits=file_edits,
    )


# ---------------------------------------------------------------------------
# Verification safety net
# ---------------------------------------------------------------------------


def _verify_rename(
    config: BlueprintConfig,
    rewritten: dict[Path, str],
    paths: list[Path],
    old_id: str,
    new_id: str,
    original_ids: set[str],
) -> None:
    """Re-parse the rewritten sources and assert the rename is exactly right."""
    from isabelle_blueprint.model.node import BlueprintNode
    from isabelle_blueprint.model.project import BlueprintProject

    nodes: list[BlueprintNode] = []
    seen: dict[str, str] = {}
    for path in paths:
        text = rewritten[path]
        fmt = "latex" if path.suffix.lower() == ".tex" else "markdown"
        from isabelle_blueprint.parser import parse_blueprint_text

        try:
            sub = parse_blueprint_text(
                text, source=str(path), project_name=config.project_name, format=fmt
            )
        except BlueprintError as exc:
            raise BlueprintError(
                f"rename aborted: rewritten {path} no longer parses ({exc})"
            ) from exc
        for node in sub.nodes:
            if node.id in seen:
                raise BlueprintError(
                    f"rename aborted: duplicate id {node.id!r} after rewrite"
                )
            seen[node.id] = str(path)
            nodes.append(node)

    new_ids = set(seen)
    expected = (original_ids - {old_id}) | {new_id}
    if new_ids != expected:
        raise BlueprintError(
            "rename aborted: post-rewrite id set does not match the expected set "
            f"(unexpected: {sorted(new_ids - expected)}, missing: {sorted(expected - new_ids)})"
        )
    if old_id in new_ids:
        raise BlueprintError(f"rename aborted: old id {old_id!r} still present after rewrite")
    if new_id not in new_ids:
        raise BlueprintError(f"rename aborted: new id {new_id!r} missing after rewrite")

    project = BlueprintProject.from_nodes(
        config.project_name, nodes, sources=[str(p) for p in paths]
    )
    for node in project.nodes:
        if old_id in node.uses:
            raise BlueprintError(
                f"rename aborted: node {node.id!r} still references old id {old_id!r} in uses"
            )


# ---------------------------------------------------------------------------
# Markdown rewriting
# ---------------------------------------------------------------------------


def _token_pattern(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!{_ID_CHAR}){re.escape(token)}(?!{_ID_CHAR})")


def _sub_token(text: str, old: str, new: str) -> tuple[str, int]:
    return _token_pattern(old).subn(lambda _m: new, text)


def _rewrite_markdown(text: str, old: str, new: str) -> tuple[str, int]:
    lines = text.split("\n")
    out: list[str] = []
    count = 0
    state = "OUTSIDE"
    fence_marker: str | None = None
    in_uses_block = False

    opener_id_re = re.compile(rf"(?<=#){re.escape(old)}(?!{_ID_CHAR})")

    for line in lines:
        if state == "OUTSIDE":
            if _DIRECTIVE_OPEN.match(line):
                new_line, n = opener_id_re.subn(lambda _m: new, line)
                out.append(new_line)
                count += n
                state = "HEADER"
                fence_marker = None
                in_uses_block = False
            else:
                out.append(line)
            continue

        if state == "HEADER":
            if _FRONTMATTER_FENCE.match(line):
                out.append(line)
                state = "FRONTMATTER"
                continue
            if _DIRECTIVE_CLOSE.match(line) or not line.strip():
                out.append(line)
                state = "BODY"
                continue
            if _looks_like_meta(line):
                new_line, n, in_uses_block = _rewrite_meta_line(line, old, new, in_uses_block)
                out.append(new_line)
                count += n
                state = "META"
                continue
            out.append(line)
            state = "BODY"
            fence_marker = _update_fence(line, fence_marker)
            continue

        if state == "META":
            if _DIRECTIVE_CLOSE.match(line) or not line.strip():
                out.append(line)
                state = "BODY"
                in_uses_block = False
                continue
            new_line, n, in_uses_block = _rewrite_meta_line(line, old, new, in_uses_block)
            out.append(new_line)
            count += n
            continue

        if state == "FRONTMATTER":
            if _FRONTMATTER_FENCE.match(line):
                out.append(line)
                state = "BODY"
                in_uses_block = False
                continue
            new_line, n, in_uses_block = _rewrite_meta_line(line, old, new, in_uses_block)
            out.append(new_line)
            count += n
            continue

        if state == "BODY":
            fence_match = _FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group("marker")
                if fence_marker is None:
                    fence_marker = marker[0]
                elif line.lstrip().startswith(fence_marker):
                    fence_marker = None
                out.append(line)
                continue
            if fence_marker is None and _DIRECTIVE_CLOSE.match(line):
                out.append(line)
                state = "OUTSIDE"
                continue
            out.append(line)
            continue

    return "\n".join(out), count


def _update_fence(line: str, fence_marker: str | None) -> str | None:
    fence_match = _FENCE_RE.match(line)
    if fence_match:
        marker = fence_match.group("marker")
        if fence_marker is None:
            return marker[0]
        if line.lstrip().startswith(fence_marker):
            return None
    return fence_marker


_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w-]*)\s*:(?P<rest>.*)$")
_LIST_ITEM_RE = re.compile(r"^(?P<prefix>\s*-\s+)(?P<rest>.*)$")


def _rewrite_meta_line(
    line: str, old: str, new: str, in_uses_block: bool
) -> tuple[str, int, bool]:
    """Rewrite id references on a single metadata line.

    Only the ``id`` value and ``uses`` references are rewritten; other metadata
    (``title``, ``status``, ...) is left untouched even if it happens to contain
    the same token. Returns ``(new_line, replacements, in_uses_block)``.
    """
    key_match = _KEY_RE.match(line)
    if key_match:
        key = key_match.group("key").lower()
        if key == "id":
            new_rest, n = _sub_token(key_match.group("rest"), old, new)
            rebuilt = f"{key_match.group('indent')}{key_match.group('key')}:{new_rest}"
            return rebuilt, n, False
        if key == "uses":
            new_rest, n = _sub_token(key_match.group("rest"), old, new)
            rebuilt = f"{key_match.group('indent')}{key_match.group('key')}:{new_rest}"
            # A bare ``uses:`` (or one introducing a flow list) may be followed by
            # a block list of ``- item`` lines.
            block_follows = key_match.group("rest").strip() == ""
            return rebuilt, n, block_follows
        # Any other key ends a uses block list.
        return line, 0, False

    if in_uses_block:
        item_match = _LIST_ITEM_RE.match(line)
        if item_match:
            new_rest, n = _sub_token(item_match.group("rest"), old, new)
            return f"{item_match.group('prefix')}{new_rest}", n, True
        # Not a list item -> the uses block has ended.
        return line, 0, False

    return line, 0, in_uses_block


# ---------------------------------------------------------------------------
# LaTeX rewriting
# ---------------------------------------------------------------------------


def _rewrite_latex(text: str, old: str, new: str) -> tuple[str, int]:
    count = 0

    def repl_label(match: re.Match[str]) -> str:
        nonlocal count
        if match.group("value") == old:
            count += 1
            return f"\\label{{{new}}}"
        return match.group(0)

    def repl_uses(match: re.Match[str]) -> str:
        nonlocal count
        inner = match.group("value")
        new_inner, n = _sub_token(inner, old, new)
        count += n
        return f"\\uses{{{new_inner}}}"

    text = re.sub(r"\\label\{(?P<value>[^{}]+)\}", repl_label, text)
    text = re.sub(r"\\uses\{(?P<value>[^{}]*)\}", repl_uses, text)
    return text, count


# ---------------------------------------------------------------------------
# JSON store rekeying
# ---------------------------------------------------------------------------


def _plan_store_rekeys(config: BlueprintConfig, old_id: str, new_id: str) -> list[StoreRekey]:
    stores = [
        ("agent-memory", config.agent_memory_path),
        ("github-sync", config.github_sync_state_path),
        ("assignments", config.assignments_path),
    ]
    rekeys: list[StoreRekey] = []
    for name, path in stores:
        changed = _store_has_node(path, old_id)
        rekeys.append(StoreRekey(name=name, path=path, changed=changed))
    return rekeys


def _store_has_node(path: Path, node_id: str) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    nodes = data.get("nodes") if isinstance(data, dict) else None
    return isinstance(nodes, dict) and node_id in nodes


def _apply_store_rekey(path: Path, old_id: str, new_id: str) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or old_id not in nodes:
        return
    # Preserve any existing entry under the new id only if old wins (rename
    # target was verified absent in the blueprint, but a stale store entry could
    # exist; the renamed node's history takes precedence).
    nodes[new_id] = nodes.pop(old_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
