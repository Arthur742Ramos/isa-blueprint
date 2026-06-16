"""Packaged JSON Schema helpers."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from isabelle_blueprint.errors import BlueprintError

SCHEMA_NAMES = (
    "project",
    "graph",
    "tasks",
    "summary",
    "status",
    "roadmap",
    "agent-context",
    "config",
    "plugin-annotations",
    "agent-memory",
    "path",
    "scorecard",
    "tags",
    "orphans",
    "levels",
    "fact-coverage",
    "tag-cooccurrence",
    "depends",
)


def available_schemas() -> tuple[str, ...]:
    """Return schema names accepted by the CLI."""

    return SCHEMA_NAMES


def read_schema(name: str) -> str:
    """Read a packaged schema by short name."""

    if name not in SCHEMA_NAMES:
        raise BlueprintError(
            f"unknown schema {name!r}; choose one of: {', '.join(SCHEMA_NAMES)}"
        )
    schema = resources.files("isabelle_blueprint").joinpath("schemas", f"{name}.schema.json")
    return schema.read_text(encoding="utf-8")


def write_schemas(output_dir: Path, names: list[str] | None = None) -> dict[str, Path]:
    """Write selected schemas to ``output_dir``."""

    selected = names or list(SCHEMA_NAMES)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in selected:
        text = read_schema(name)
        path = output_dir / f"{name}.schema.json"
        path.write_text(text, encoding="utf-8")
        written[name] = path
    return written
