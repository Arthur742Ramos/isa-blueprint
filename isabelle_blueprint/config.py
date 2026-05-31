"""Project configuration loader.

Reads ``isabelle-blueprint.toml`` (if present) to discover blueprint sources,
output paths, and Isabelle session names.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BlueprintConfig:
    """Resolved project configuration."""

    project_root: Path
    blueprint_path: Path
    build_dir: Path
    site_dir: Path
    isabelle_session: str | None = None
    isabelle_dirs: list[Path] = field(default_factory=list)
    isabelle_executable: str = "isabelle"
    project_name: str = "Untitled IsabelleBlueprint project"

    @property
    def check_report_path(self) -> Path:
        return self.build_dir / "check_report.json"

    @property
    def project_json_path(self) -> Path:
        return self.build_dir / "project.json"

    @property
    def graph_dot_path(self) -> Path:
        return self.build_dir / "graph.dot"

    @property
    def graph_json_path(self) -> Path:
        return self.build_dir / "graph.json"

    @property
    def graph_svg_path(self) -> Path:
        return self.build_dir / "graph.svg"

    @property
    def tasks_json_path(self) -> Path:
        return self.build_dir / "tasks.json"

    @property
    def tasks_md_path(self) -> Path:
        return self.build_dir / "tasks.md"

    @property
    def checker_theory_path(self) -> Path:
        return self.build_dir / "Blueprint_Check.thy"


DEFAULT_CONFIG_NAME = "isabelle-blueprint.toml"
DEFAULT_BLUEPRINT_NAME = "blueprint.md"


def load_config(project_root: Path | None = None) -> BlueprintConfig:
    """Load configuration from ``isabelle-blueprint.toml`` in the project root.

    If the file is absent, a default configuration is returned that assumes
    ``blueprint.md`` lives at the project root.
    """
    root = Path(project_root or Path.cwd()).resolve()
    config_path = root / DEFAULT_CONFIG_NAME
    raw: dict = {}
    if config_path.exists():
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)

    project_section = raw.get("project", {})
    isabelle_section = raw.get("isabelle", {})
    output_section = raw.get("output", {})

    blueprint_path = root / project_section.get("blueprint", DEFAULT_BLUEPRINT_NAME)
    build_dir = root / output_section.get("build_dir", "build")
    site_dir = root / output_section.get("site_dir", "site")
    isabelle_session = isabelle_section.get("session")
    isabelle_dirs = [root / d for d in isabelle_section.get("dirs", [])]
    isabelle_executable = isabelle_section.get("executable", "isabelle")
    project_name = project_section.get("name", "Untitled IsabelleBlueprint project")

    return BlueprintConfig(
        project_root=root,
        blueprint_path=blueprint_path.resolve(),
        build_dir=build_dir.resolve(),
        site_dir=site_dir.resolve(),
        isabelle_session=isabelle_session,
        isabelle_dirs=isabelle_dirs,
        isabelle_executable=isabelle_executable,
        project_name=project_name,
    )
