"""Compatibility and version-pin checks for Isabelle/AFP projects."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from isabelle_blueprint.config import BlueprintConfig


@dataclass
class CompatibilityIssue:
    severity: str
    code: str
    message: str
    path: str | None = None


@dataclass
class CompatibilityReport:
    project_root: str
    isabelle_executable: str
    isabelle_available: bool
    expected_isabelle_version: str | None = None
    actual_isabelle_version: str | None = None
    configured_session: str | None = None
    discovered_sessions: list[str] = field(default_factory=list)
    afp_root: str | None = None
    afp_entry: str | None = None
    issues: list[CompatibilityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(issue.severity != "error" for issue in self.issues)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        return data


_SESSION_RE = re.compile(r'^\s*session\s+"?([^"\s=]+)"?\s*=', re.MULTILINE)


def check_compatibility(config: BlueprintConfig, *, isabelle_executable: str | None = None) -> CompatibilityReport:
    """Check local Isabelle, session, and optional AFP compatibility pins."""
    executable = isabelle_executable or config.isabelle_executable
    report = CompatibilityReport(
        project_root=str(config.project_root),
        isabelle_executable=executable,
        isabelle_available=shutil.which(executable) is not None,
        expected_isabelle_version=config.isabelle_version,
        configured_session=config.isabelle_session,
        afp_root=str(config.afp_root) if config.afp_root else None,
        afp_entry=config.afp_entry,
    )

    _check_isabelle_version(report, executable)
    _check_session(report, config)
    _check_afp(report, config)
    return report


def write_compat_report(report: CompatibilityReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


def _check_isabelle_version(report: CompatibilityReport, executable: str) -> None:
    resolved_executable = shutil.which(executable)
    if not resolved_executable:
        report.issues.append(
            CompatibilityIssue("error", "isabelle-missing", f"Isabelle executable {executable!r} not found")
        )
        return
    try:
        proc = subprocess.run(
            [resolved_executable, "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.issues.append(
            CompatibilityIssue("error", "isabelle-version-failed", f"Could not run `isabelle version`: {exc}")
        )
        return
    if proc.returncode != 0:
        report.issues.append(
            CompatibilityIssue(
                "error",
                "isabelle-version-failed",
                f"`isabelle version` exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}",
            )
        )
        return
    report.actual_isabelle_version = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if report.expected_isabelle_version and report.actual_isabelle_version != report.expected_isabelle_version:
        report.issues.append(
            CompatibilityIssue(
                "error",
                "isabelle-version-mismatch",
                f"Expected Isabelle {report.expected_isabelle_version}, found {report.actual_isabelle_version}",
            )
        )


def _check_session(report: CompatibilityReport, config: BlueprintConfig) -> None:
    roots = _root_files(config.project_root) + [
        root for d in config.isabelle_dirs for root in _root_files(d)
    ]
    sessions: set[str] = set()
    for root_file in roots:
        try:
            sessions.update(_SESSION_RE.findall(root_file.read_text(encoding="utf-8")))
        except OSError:
            continue
    report.discovered_sessions = sorted(sessions)

    if not config.isabelle_session:
        report.issues.append(
            CompatibilityIssue(
                "warning",
                "session-not-configured",
                "No [isabelle].session configured; fact checks can only validate blueprint structure",
            )
        )
        return
    if config.isabelle_session not in sessions:
        searched = ", ".join(str(path) for path in roots) or "no ROOT/ROOTS files"
        report.issues.append(
            CompatibilityIssue(
                "error",
                "session-not-found",
                f"Configured session {config.isabelle_session!r} was not found in {searched}",
            )
        )


def _check_afp(report: CompatibilityReport, config: BlueprintConfig) -> None:
    if config.afp_root is None:
        if config.afp_required or config.afp_entry:
            report.issues.append(
                CompatibilityIssue("error", "afp-root-missing", "[afp].root is required but not configured")
            )
        return
    if not config.afp_root.exists():
        report.issues.append(
            CompatibilityIssue("error", "afp-root-not-found", f"AFP root does not exist: {config.afp_root}")
        )
        return
    if not ((config.afp_root / "thys").exists() or (config.afp_root / "ROOTS").exists()):
        report.issues.append(
            CompatibilityIssue(
                "warning",
                "afp-root-unusual",
                f"AFP root does not contain a thys/ directory or ROOTS file: {config.afp_root}",
            )
        )
    if config.afp_entry:
        entry_dir = config.afp_root / "thys" / config.afp_entry
        if not entry_dir.exists():
            report.issues.append(
                CompatibilityIssue(
                    "error",
                    "afp-entry-not-found",
                    f"AFP entry {config.afp_entry!r} not found under {config.afp_root / 'thys'}",
                )
            )
        elif not _root_files(entry_dir):
            report.issues.append(
                CompatibilityIssue(
                    "warning",
                    "afp-entry-no-root",
                    f"AFP entry {config.afp_entry!r} has no ROOT/ROOTS file",
                    path=str(entry_dir),
                )
            )


def _root_files(directory: Path) -> list[Path]:
    roots: list[Path] = []
    seen_dirs: set[Path] = set()
    seen_roots: set[Path] = set()
    _collect_root_files(directory, roots, seen_dirs, seen_roots)
    return roots


def _collect_root_files(directory: Path, roots: list[Path], seen_dirs: set[Path], seen_roots: set[Path]) -> None:
    directory = directory.resolve()
    if directory in seen_dirs:
        return
    seen_dirs.add(directory)

    root = directory / "ROOT"
    if root.exists():
        resolved_root = root.resolve()
        if resolved_root not in seen_roots:
            roots.append(root)
            seen_roots.add(resolved_root)

    roots_file = directory / "ROOTS"
    if not roots_file.exists():
        return
    try:
        lines = roots_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if len(entry) >= 2 and entry[0] in {"'", '"'} and entry[-1] == entry[0]:
            entry = entry[1:-1]
        _collect_root_files(directory / entry, roots, seen_dirs, seen_roots)


__all__ = [
    "CompatibilityIssue",
    "CompatibilityReport",
    "check_compatibility",
    "write_compat_report",
]
