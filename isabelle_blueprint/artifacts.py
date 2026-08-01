"""Safe publication helpers for generated artifact trees.

Generated sites are assembled in a temporary sibling directory and published
file-by-file only after rendering succeeds.  A small manifest lets later runs
remove files that the current run no longer emits without touching unrelated
user files in the output directory.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

MANIFEST_NAME = ".isabelle-blueprint-manifest.json"
MANIFEST_VERSION = 1


def create_staging_dir(output_dir: Path) -> Path:
    """Create a temporary sibling directory for a generated artifact tree."""

    if output_dir.is_symlink():
        raise ValueError(f"refusing to render through symlink: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))


def publish_staged(
    output_dir: Path,
    staging_dir: Path,
    managed_paths: Iterable[Path],
    *,
    legacy_paths: Iterable[Path] = (),
) -> None:
    """Publish staged files and reconcile paths from the previous run.

    Only paths listed in the previous manifest (or the explicitly supplied
    one-time legacy list) may be removed.  Files outside that set are left
    untouched, which allows site owners to keep files such as ``CNAME``.
    """

    output_path = output_dir
    if output_path.is_symlink():
        raise ValueError(f"refusing to publish through symlink: {output_path}")
    output_dir = output_path.resolve()
    staging_dir = staging_dir.resolve()
    if output_dir == staging_dir:
        raise ValueError(f"refusing to publish staging directory as output: {output_dir}")
    if not staging_dir.is_dir():
        raise ValueError(f"staging directory does not exist: {staging_dir}")

    new_paths = {_normalise_relative(path) for path in managed_paths}
    if MANIFEST_NAME in new_paths:
        raise ValueError(f"{MANIFEST_NAME} is reserved for the artifact manifest")
    for relative in new_paths:
        _safe_staging_path(staging_dir, relative)

    old_paths = _load_manifest(output_dir)
    if old_paths is None:
        old_paths = {_normalise_relative(path) for path in legacy_paths}
    if MANIFEST_NAME in old_paths:
        old_paths.remove(MANIFEST_NAME)

    output_dir.mkdir(parents=True, exist_ok=True)
    targets: list[tuple[str, Path, Path]] = []
    for relative in sorted(new_paths):
        source = _safe_staging_path(staging_dir, relative)
        target = _safe_output_path(output_dir, relative)
        _ensure_safe_parent(output_dir, relative)
        if target.exists() and target.is_dir() and not target.is_symlink():
            raise ValueError(f"artifact target is a directory: {target}")
        targets.append((relative, source, target))

    stale_targets: list[Path] = []
    for relative in sorted(old_paths - new_paths, reverse=True):
        target = _safe_output_path(output_dir, relative)
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                raise ValueError(f"refusing to remove generated directory: {target}")
            stale_targets.append(target)

    # Resolve every parent before replacing any file. A malformed tree must
    # fail as a whole rather than leaving a partially published site.
    for _, _, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
    for _, source, target in targets:
        os.replace(source, target)

    for target in stale_targets:
        target.unlink()

    manifest = {
        "version": MANIFEST_VERSION,
        "files": sorted(new_paths),
    }
    atomic_write_text(
        output_dir / MANIFEST_NAME,
        json.dumps(manifest, indent=2) + "\n",
    )


def discard_staging_dir(staging_dir: Path) -> None:
    """Remove a staging directory after publication or a failed render."""

    shutil.rmtree(staging_dir, ignore_errors=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text through a temporary sibling and an atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_generated_file(path: Path) -> None:
    """Remove an optional generated file without following a symlink."""

    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            raise ValueError(f"refusing to remove generated directory: {path}")
        path.unlink()


def _load_manifest(output_dir: Path) -> set[str] | None:
    path = output_dir / MANIFEST_NAME
    if not path.exists() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != MANIFEST_VERSION:
        return None
    files = payload.get("files")
    if not isinstance(files, list) or any(not isinstance(item, str) for item in files):
        return None
    try:
        return {_normalise_relative(Path(item)) for item in files}
    except ValueError:
        return None


def _normalise_relative(path: Path) -> str:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"artifact path must be a relative path: {path}")
    return path.as_posix()


def _safe_staging_path(staging_dir: Path, relative: str) -> Path:
    candidate = (staging_dir / relative).resolve()
    if not candidate.is_relative_to(staging_dir):
        raise ValueError(f"artifact path escapes staging directory: {relative}")
    if not candidate.is_file():
        raise ValueError(f"staged artifact is missing or not a file: {relative}")
    return candidate


def _safe_output_path(output_dir: Path, relative: str) -> Path:
    candidate = output_dir / relative
    resolved = candidate.resolve()
    if not resolved.is_relative_to(output_dir):
        raise ValueError(f"artifact path escapes output directory: {relative}")
    return candidate


def _ensure_safe_parent(output_dir: Path, relative: str) -> None:
    current = output_dir
    for part in Path(relative).parts[:-1]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"refusing to publish through symlink: {current}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"artifact parent is not a directory: {current}")


__all__ = [
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "atomic_write_text",
    "create_staging_dir",
    "discard_staging_dir",
    "publish_staged",
    "remove_generated_file",
]
