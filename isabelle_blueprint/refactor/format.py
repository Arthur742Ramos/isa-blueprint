"""Canonicalize Markdown blueprint sources (the ``fmt`` command).

``fmt`` parses each Markdown blueprint file and re-renders it through the same
interchange writer the round-trip tests rely on, so the result is a stable,
canonical form: one node per ``:::`` block, metadata in a fixed order, and the
full three-axis status block spelled out. This makes diffs small and reviewable
and gives CI a cheap "is the blueprint canonical?" gate via ``--check``.

The transform is intentionally limited to the Markdown interchange format. The
LaTeX writer emits a whole standalone document, so reformatting ``.tex`` sources
in place is out of scope; those files are reported as skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.parser.latex import render_markdown_blueprint
from isabelle_blueprint.parser.markdown import parse_blueprint_text


def format_markdown_source(text: str, *, source: str, project_name: str) -> str:
    """Return the canonical interchange rendering of one Markdown blueprint file."""
    project = parse_blueprint_text(text, source=source, project_name=project_name)
    return render_markdown_blueprint(project)


@dataclass
class FormatFileResult:
    """Outcome of formatting (or checking) a single blueprint file."""

    path: str
    changed: bool
    skipped: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "changed": self.changed,
            "skipped": self.skipped,
            "reason": self.reason,
        }


@dataclass
class FormatResult:
    """Aggregate outcome of a ``fmt`` run."""

    check_only: bool
    files: list[FormatFileResult] = field(default_factory=list)

    @property
    def changed_paths(self) -> list[str]:
        return [f.path for f in self.files if f.changed and not f.skipped]

    @property
    def would_change(self) -> bool:
        return bool(self.changed_paths)

    def to_dict(self) -> dict[str, object]:
        return {
            "check_only": self.check_only,
            "changed": self.changed_paths,
            "files": [f.to_dict() for f in self.files],
        }


def format_blueprint_paths(
    paths: list[Path],
    *,
    project_name: str,
    check_only: bool,
) -> FormatResult:
    """Format (or check) every Markdown blueprint in ``paths``.

    Non-Markdown sources are recorded as skipped. When ``check_only`` is false a
    file whose canonical form differs from disk is rewritten; otherwise nothing
    is written and the drift is reported via :attr:`FormatResult.would_change`.
    """
    result = FormatResult(check_only=check_only)
    for path in paths:
        if path.suffix.lower() != ".md":
            result.files.append(
                FormatFileResult(str(path), changed=False, skipped=True, reason="not a .md source")
            )
            continue
        original = path.read_text(encoding="utf-8")
        formatted = format_markdown_source(original, source=str(path), project_name=project_name)
        changed = formatted != original
        if changed and not check_only:
            path.write_text(formatted, encoding="utf-8")
        result.files.append(FormatFileResult(str(path), changed=changed))
    return result
