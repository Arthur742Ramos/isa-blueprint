"""IsabelleBlueprint: planning, dependency tracking, and task orchestration for Isabelle."""
from __future__ import annotations

from importlib import metadata as _metadata

#: Version used when the package is run straight from a source tree that was
#: never installed (so distribution metadata is unavailable). Keep this in sync
#: with ``pyproject.toml`` -- ``tests/test_packaging.py`` enforces the match so
#: the two can never drift again (they did: ``1.11.0`` shipped as ``1.12.0``).
_FALLBACK_VERSION = "1.16.0"

try:
    __version__ = _metadata.version("isabelle-blueprint")
except _metadata.PackageNotFoundError:  # pragma: no cover - only when uninstalled
    __version__ = _FALLBACK_VERSION

__all__ = ["__version__"]

