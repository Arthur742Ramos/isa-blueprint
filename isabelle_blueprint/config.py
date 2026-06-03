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
    isabelle_version: str | None = None
    isabelle_timeout: float | None = None
    project_name: str = "Untitled IsabelleBlueprint project"
    afp_root: Path | None = None
    afp_entry: str | None = None
    afp_required: bool = False
    extra_blueprint_paths: list[Path] = field(default_factory=list)

    @property
    def blueprint_paths(self) -> list[Path]:
        """All blueprint sources, primary first."""
        return [self.blueprint_path, *self.extra_blueprint_paths]

    @property
    def check_report_path(self) -> Path:
        return self.build_dir / "check_report.json"

    @property
    def dump_report_path(self) -> Path:
        return self.build_dir / "dump_report.json"

    @property
    def compat_report_path(self) -> Path:
        return self.build_dir / "compat_report.json"

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

    @property
    def check_cache_path(self) -> Path:
        """JSON cache file used by ``isabelle-blueprint check --incremental``."""
        return self.build_dir / "check-cache.json"

    @property
    def trends_path(self) -> Path:
        """JSON file storing coverage / problem counts across runs (v0.8)."""
        return self.build_dir / "trends.json"

    @property
    def agent_memory_path(self) -> Path:
        """Persistent human/agent attempt history for proof tasks."""
        return self.project_root / ".isabelle-blueprint" / "agent-memory.json"

    @property
    def github_sync_state_path(self) -> Path:
        """Persistent node-id to GitHub issue mapping used by task sync."""
        return self.project_root / ".isabelle-blueprint" / "github-sync.json"

    @property
    def assignments_path(self) -> Path:
        """Persistent node-id to owner mapping used by the ``assign`` command."""
        return self.project_root / ".isabelle-blueprint" / "assignments.json"


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
    afp_section = raw.get("afp", {})
    output_section = raw.get("output", {})

    blueprint_setting = project_section.get("blueprint", DEFAULT_BLUEPRINT_NAME)
    blueprints_setting = project_section.get("blueprints")
    if blueprints_setting is not None:
        if isinstance(blueprints_setting, str):
            blueprints_setting = [blueprints_setting]
        if not isinstance(blueprints_setting, list) or not blueprints_setting:
            raise ValueError(
                "[project].blueprints must be a non-empty list of paths"
            )
        all_blueprints = [str(p) for p in blueprints_setting]
    else:
        all_blueprints = [blueprint_setting]
    blueprint_path = (root / all_blueprints[0]).resolve()
    extra_blueprint_paths = [(root / p).resolve() for p in all_blueprints[1:]]
    build_dir = root / output_section.get("build_dir", "build")
    site_dir = root / output_section.get("site_dir", "site")
    isabelle_session = isabelle_section.get("session")
    isabelle_dirs = [root / d for d in isabelle_section.get("dirs", [])]
    isabelle_executable = isabelle_section.get("executable", "isabelle")
    isabelle_version = isabelle_section.get("version")
    isabelle_timeout_raw = isabelle_section.get("timeout")
    isabelle_timeout = float(isabelle_timeout_raw) if isabelle_timeout_raw is not None else None
    project_name = project_section.get("name", "Untitled IsabelleBlueprint project")
    afp_root_raw = afp_section.get("root")
    afp_root = (root / afp_root_raw).resolve() if afp_root_raw else None
    afp_entry = afp_section.get("entry")
    afp_required = bool(afp_section.get("required", False))

    return BlueprintConfig(
        project_root=root,
        blueprint_path=blueprint_path,
        build_dir=build_dir.resolve(),
        site_dir=site_dir.resolve(),
        isabelle_session=isabelle_session,
        isabelle_dirs=isabelle_dirs,
        isabelle_executable=isabelle_executable,
        isabelle_version=isabelle_version,
        isabelle_timeout=isabelle_timeout,
        project_name=project_name,
        afp_root=afp_root,
        afp_entry=afp_entry,
        afp_required=afp_required,
        extra_blueprint_paths=extra_blueprint_paths,
    )
