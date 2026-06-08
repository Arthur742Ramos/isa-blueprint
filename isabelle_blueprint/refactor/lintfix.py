"""Autofix a narrow, safe class of lint findings (the ``lint --fix`` command).

The only finding this touches is ``missing-dependency``: a ``uses`` entry that
references a node id that does not exist anywhere in the project. Those dangling
references are dropped and the affected Markdown file is rewritten through the
same interchange writer ``fmt`` uses, so the result stays canonical.

Two safety rails keep the fix trustworthy:

* It refuses to touch anything while *duplicate ids* or *dependency cycles* are
  present. Both indicate the blueprint is structurally inconsistent in a way the
  autofix cannot reason about, and silently rewriting files in that state risks
  losing information.
* The set of valid ids is computed **globally**, across every source file, so a
  cross-file dependency is never mistaken for a dangling one.

Only Markdown sources are rewritten; LaTeX blueprints are reported as skipped
(the LaTeX writer emits a whole standalone document, as with ``fmt``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.parser.latex import render_markdown_blueprint
from isabelle_blueprint.parser.markdown import parse_blueprint_text


@dataclass
class LintFixFileResult:
    """Outcome of autofixing (or previewing) a single blueprint file."""

    path: str
    changed: bool = False
    skipped: bool = False
    reason: str | None = None
    # (node_id, dropped_dependency) pairs removed from this file.
    removed: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "changed": self.changed,
            "skipped": self.skipped,
            "reason": self.reason,
            "removed": [
                {"node": node_id, "dependency": dep} for node_id, dep in self.removed
            ],
        }


@dataclass
class LintFixResult:
    """Aggregate outcome of a ``lint --fix`` run."""

    check_only: bool = False
    refused: bool = False
    refusal_reason: str | None = None
    files: list[LintFixFileResult] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return sum(len(f.removed) for f in self.files)

    @property
    def changed_paths(self) -> list[str]:
        return [f.path for f in self.files if f.changed and not f.skipped]

    @property
    def would_change(self) -> bool:
        return bool(self.changed_paths)

    def to_dict(self) -> dict[str, object]:
        return {
            "check_only": self.check_only,
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "removed_count": self.removed_count,
            "changed": self.changed_paths,
            "files": [f.to_dict() for f in self.files],
        }


def apply_lint_fixes(
    project: BlueprintProject,
    paths: list[Path],
    *,
    project_name: str,
    check_only: bool = False,
) -> LintFixResult:
    """Drop dangling ``uses`` references from every Markdown source in ``paths``.

    ``project`` is the merged project (across all files); its node ids define the
    set of valid dependency targets and its in-memory ``uses`` lists are pruned
    to match the on-disk fix so a caller can re-lint without re-reading.

    When ``check_only`` is true nothing is written; the result still reports what
    *would* change.
    """
    result = LintFixResult(check_only=check_only)

    report = project.validate()
    blockers: list[str] = []
    if report.duplicate_ids:
        blockers.append("duplicate ids")
    if report.cycles:
        blockers.append("dependency cycles")
    if blockers:
        result.refused = True
        result.refusal_reason = (
            "refusing to autofix while "
            + " and ".join(blockers)
            + " are present; resolve them first"
        )
        return result

    valid_ids = {node.id for node in project.nodes}

    for path in paths:
        if path.suffix.lower() != ".md":
            result.files.append(
                LintFixFileResult(
                    str(path), skipped=True, reason="not a .md source"
                )
            )
            continue

        original = path.read_text(encoding="utf-8")
        file_project = parse_blueprint_text(
            original, source=str(path), project_name=project_name
        )
        removed: list[tuple[str, str]] = []
        for node in file_project.nodes:
            kept: list[str] = []
            for dep in node.uses:
                if dep in valid_ids:
                    kept.append(dep)
                else:
                    removed.append((node.id, dep))
            node.uses = kept

        if not removed:
            result.files.append(LintFixFileResult(str(path), changed=False))
            continue

        rendered = render_markdown_blueprint(file_project)
        changed = rendered != original
        if changed and not check_only:
            path.write_text(rendered, encoding="utf-8")
        result.files.append(
            LintFixFileResult(str(path), changed=changed, removed=removed)
        )

    # Keep the in-memory merged project consistent with the on-disk fix so the
    # caller's follow-up lint report reflects the post-fix state.
    for node in project.nodes:
        node.uses = [dep for dep in node.uses if dep in valid_ids]

    return result


def render_lint_fix_summary(result: LintFixResult) -> str:
    """Render a concise human-readable summary of a fix run (trailing newline)."""
    if result.refused:
        return f"lint --fix: {result.refusal_reason}\n"
    lines: list[str] = []
    for entry in result.files:
        if entry.skipped:
            lines.append(f"  skipped {entry.path} ({entry.reason})")
            continue
        for node_id, dep in entry.removed:
            lines.append(
                f"  {entry.path} [{node_id}]: dropped dangling dependency {dep!r}"
            )
        if entry.changed:
            verb = "would rewrite" if result.check_only else "rewrote"
            lines.append(f"  {verb} {entry.path}")
    if not lines:
        return "lint --fix: no autofixable findings\n"
    verb = "would fix" if result.check_only else "fixed"
    header = f"lint --fix: {verb} {result.removed_count} dangling dependency reference(s)"
    return header + "\n" + "\n".join(lines) + "\n"
