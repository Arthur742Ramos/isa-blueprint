"""Blueprint parsers."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from isabelle_blueprint.parser.latex import (
    parse_latex_file,
    parse_latex_text,
    render_markdown_blueprint,
)
from isabelle_blueprint.parser.markdown import (
    parse_blueprint_file as parse_markdown_file,
)
from isabelle_blueprint.parser.markdown import (
    parse_blueprint_text as parse_markdown_text,
)
from isabelle_blueprint.model.project import BlueprintProject


def parse_blueprint_file(path: Path | str, *, project_name: str | None = None) -> BlueprintProject:
    """Parse a Markdown or LaTeX blueprint file based on its suffix."""
    p = Path(path)
    if p.suffix.lower() == ".tex":
        return parse_latex_file(p, project_name=project_name)
    return parse_markdown_file(p, project_name=project_name)


def parse_blueprint_text(
    text: str,
    *,
    source: str = "<text>",
    project_name: str = "blueprint",
    format: str = "markdown",
) -> BlueprintProject:
    """Parse blueprint text in Markdown or LaTeX format."""
    if format.lower() in {"latex", "tex"}:
        return parse_latex_text(text, source=source, project_name=project_name)
    return parse_markdown_text(text, source=source, project_name=project_name)


def parse_blueprint(paths: Iterable[Path | str], *, project_name: str = "blueprint") -> BlueprintProject:
    """Parse one or more Markdown/LaTeX files into a single project."""
    nodes = []
    sources = []
    for path in paths:
        sub = parse_blueprint_file(path, project_name=project_name)
        nodes.extend(sub.nodes)
        sources.extend(sub.source_files)
    return BlueprintProject.from_nodes(project_name, nodes, sources)


__all__ = [
    "parse_blueprint",
    "parse_blueprint_file",
    "parse_blueprint_text",
    "parse_latex_file",
    "parse_latex_text",
    "parse_markdown_file",
    "parse_markdown_text",
    "render_markdown_blueprint",
]
