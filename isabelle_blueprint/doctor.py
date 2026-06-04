"""Environment diagnostics for IsabelleBlueprint projects."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from isabelle_blueprint import __version__
from isabelle_blueprint.config import DEFAULT_CONFIG_NAME, BlueprintConfig, load_config
from isabelle_blueprint.errors import BlueprintError, ParseError, ValidationError
from isabelle_blueprint.parser import parse_blueprint, parse_blueprint_file


@dataclass(frozen=True)
class DoctorCheck:
    """One diagnostic check."""

    name: str
    status: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DoctorReport:
    """Structured output for ``isabelle-blueprint doctor``."""

    project_dir: str
    checks: list[DoctorCheck]

    @property
    def has_errors(self) -> bool:
        return any(check.status == "error" for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == "warning" for check in self.checks)

    @property
    def ok(self) -> bool:
        return not self.has_errors

    def to_dict(self) -> dict[str, object]:
        return {
            "project_dir": self.project_dir,
            "ok": self.ok,
            "has_warnings": self.has_warnings,
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def run_doctor(project_dir: Path, *, isabelle_executable: str | None = None) -> DoctorReport:
    """Run local project diagnostics."""

    root = project_dir.resolve()
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "python",
            "ok" if sys.version_info >= (3, 11) else "error",
            f"Python {platform.python_version()}",
            {"executable": sys.executable},
        )
    )
    checks.append(DoctorCheck("package", "ok", f"IsabelleBlueprint {__version__}"))

    try:
        config = load_config(root)
    except (OSError, ValueError) as exc:
        checks.append(DoctorCheck("config", "error", f"Could not load configuration: {exc}"))
        return DoctorReport(str(root), checks)

    config_path = root / DEFAULT_CONFIG_NAME
    checks.append(
        DoctorCheck(
            "config",
            "ok",
            f"Loaded {config_path}" if config_path.exists() else "Using default configuration",
        )
    )
    checks.extend(_check_blueprints(config))
    checks.extend(_check_writable_outputs(config))
    checks.append(_check_graphviz())
    checks.append(_check_isabelle(config, isabelle_executable=isabelle_executable))
    checks.extend(_check_afp(config))
    return DoctorReport(str(root), checks)


def _check_blueprints(config: BlueprintConfig) -> list[DoctorCheck]:
    missing = [path for path in config.blueprint_paths if not path.exists()]
    if missing:
        return [
            DoctorCheck(
                "blueprints",
                "error",
                "Missing blueprint file(s)",
                {"missing": [str(path) for path in missing]},
            )
        ]
    try:
        if len(config.blueprint_paths) == 1:
            project = parse_blueprint_file(
                config.blueprint_paths[0], project_name=config.project_name
            )
        else:
            project = parse_blueprint(config.blueprint_paths, project_name=config.project_name)
        project.validate().raise_if_failed()
    except (OSError, BlueprintError, ParseError, ValidationError) as exc:
        return [DoctorCheck("blueprints", "error", f"Blueprint validation failed: {exc}")]
    return [
        DoctorCheck(
            "blueprints",
            "ok",
            f"Loaded {len(project.nodes)} node(s) from {len(config.blueprint_paths)} file(s)",
            {"files": [str(path) for path in config.blueprint_paths]},
        )
    ]


def _check_writable_outputs(config: BlueprintConfig) -> list[DoctorCheck]:
    return [
        _check_writable_dir("build_dir", config.build_dir),
        _check_writable_dir("site_dir", config.site_dir),
    ]


def _check_writable_dir(name: str, path: Path) -> DoctorCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".isabelle-blueprint-doctor"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return DoctorCheck(name, "error", f"{path} is not writable: {exc}")
    return DoctorCheck(name, "ok", f"{path} is writable")


def _check_graphviz() -> DoctorCheck:
    dot = shutil.which("dot")
    if dot is None:
        return DoctorCheck(
            "graphviz", "warning", "Graphviz `dot` not found; SVG graphs will be skipped"
        )
    return DoctorCheck("graphviz", "ok", f"Found dot at {dot}")


def _check_isabelle(
    config: BlueprintConfig,
    *,
    isabelle_executable: str | None,
) -> DoctorCheck:
    executable = isabelle_executable or config.isabelle_executable
    resolved = shutil.which(executable)
    if resolved is None:
        return DoctorCheck(
            "isabelle",
            "warning",
            f"Isabelle executable {executable!r} not found; check/dump will run in degraded mode",
        )
    try:
        proc = subprocess.run(
            [resolved, "version"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorCheck("isabelle", "warning", f"Could not run `{executable} version`: {exc}")
    output = (proc.stdout or proc.stderr).strip()
    status = "ok" if proc.returncode == 0 else "warning"
    message = output or f"Found Isabelle at {resolved}"
    if config.isabelle_version and config.isabelle_version not in output:
        return DoctorCheck(
            "isabelle",
            "warning",
            f"Expected {config.isabelle_version!r}, got {message!r}",
            {"executable": resolved, "return_code": proc.returncode},
        )
    return DoctorCheck(
        "isabelle",
        status,
        message,
        {"executable": resolved, "return_code": proc.returncode},
    )


def _check_afp(config: BlueprintConfig) -> list[DoctorCheck]:
    if config.afp_root is None and not config.afp_required:
        return [DoctorCheck("afp", "ok", "AFP is not required by configuration")]
    if config.afp_root is None:
        return [DoctorCheck("afp", "error", "AFP is required but [afp].root is not configured")]
    if not config.afp_root.exists():
        status = "error" if config.afp_required else "warning"
        return [DoctorCheck("afp", status, f"AFP root does not exist: {config.afp_root}")]
    if not config.afp_root.is_dir():
        return [DoctorCheck("afp", "error", f"AFP root is not a directory: {config.afp_root}")]
    details: dict[str, object] = {"root": str(config.afp_root)}
    if config.afp_entry:
        entry_path = config.afp_root / "thys" / config.afp_entry
        details["entry"] = config.afp_entry
        details["entry_path"] = str(entry_path)
        if not entry_path.exists():
            status = "error" if config.afp_required else "warning"
            return [DoctorCheck("afp", status, f"AFP entry not found: {entry_path}", details)]
    return [DoctorCheck("afp", "ok", f"AFP root is readable: {config.afp_root}", details)]

