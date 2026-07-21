"""Plugin discovery for IsabelleBlueprint.

Third-party packages can register status providers, node-kind providers, and
report renderers through entry-point groups.  The discovery layer is
deliberately permissive so a misbehaving plugin never aborts a CLI run.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

STATUS_PROVIDER_GROUP = "isabelle_blueprint.status_providers"
NODE_KIND_GROUP = "isabelle_blueprint.node_kinds"
REPORT_RENDERER_GROUP = "isabelle_blueprint.report_renderers"


@dataclass(frozen=True)
class LoadedPlugin:
    """A successfully loaded entry-point.

    ``name`` is the entry-point name (the left side of the ``=`` in
    ``pyproject.toml``); ``dist`` is the distribution name when available;
    ``callable_`` is the resolved object (typically a function).
    """

    name: str
    dist: str | None
    callable_: Callable[..., Any]


def _iter_entry_points(group: str):
    """Yield entry points in ``group``, handling old/new importlib.metadata APIs."""
    eps = importlib_metadata.entry_points()
    # Python 3.10+ returns an ``EntryPoints`` selection object.
    if hasattr(eps, "select"):
        return eps.select(group=group)
    # Older fallback (dict-like).
    return eps.get(group, [])  # type: ignore[attr-defined]


def _discover_plugins(group: str, label: str) -> list[LoadedPlugin]:
    """Discover and load all callable plugins in ``group``."""

    loaded: list[LoadedPlugin] = []
    for ep in _iter_entry_points(group):
        try:
            func = ep.load()
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            warnings.warn(
                f"failed to load {label} {ep.name!r}: {exc}",
                stacklevel=2,
            )
            continue
        if not callable(func):
            warnings.warn(
                f"{label} {ep.name!r} is not callable; skipping",
                stacklevel=2,
            )
            continue
        dist_name: str | None = None
        dist = getattr(ep, "dist", None)
        if dist is not None:
            dist_name = getattr(dist, "name", None) or getattr(dist, "project_name", None)
        loaded.append(LoadedPlugin(name=ep.name, dist=dist_name, callable_=func))
    return loaded


def discover_status_providers() -> list[LoadedPlugin]:
    """Discover and load all registered status-provider plugins."""

    return _discover_plugins(STATUS_PROVIDER_GROUP, "status provider")


def discover_node_kind_plugins() -> list[LoadedPlugin]:
    """Discover experimental node-kind providers."""

    return _discover_plugins(NODE_KIND_GROUP, "node-kind provider")


def discover_report_renderers() -> list[LoadedPlugin]:
    """Discover experimental report-renderer plugins."""

    return _discover_plugins(REPORT_RENDERER_GROUP, "report renderer")


def run_status_providers(
    project, plugins: list[LoadedPlugin] | None = None
) -> list[dict[str, Any]]:
    """Invoke each plugin against ``project`` and return collected annotations.

    Each plugin contributes zero or more dicts. A failing plugin is logged
    via :func:`warnings.warn` and skipped; the rest still run.
    """
    if plugins is None:
        plugins = discover_status_providers()
    annotations: list[dict[str, Any]] = []
    for plugin in plugins:
        try:
            result = plugin.callable_(project)
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            warnings.warn(
                f"status provider {plugin.name!r} raised {type(exc).__name__}: {exc}",
                stacklevel=2,
            )
            continue
        if result is None:
            continue
        try:
            for item in result:
                if isinstance(item, dict):
                    enriched = dict(item)
                    enriched.setdefault("plugin", plugin.name)
                    annotations.append(enriched)
        except TypeError:
            warnings.warn(
                f"status provider {plugin.name!r} did not return an iterable; skipping",
                stacklevel=2,
            )
            continue
    return annotations


def run_report_renderers(
    project,
    output_dir: Path,
    plugins: list[LoadedPlugin] | None = None,
) -> list[dict[str, Any]]:
    """Invoke report-renderer plugins and return artifact metadata.

    A renderer is called as ``renderer(project, output_dir)``.  It may return a
    path, a dict, or an iterable of paths/dicts.  Failures are warnings so
    third-party renderers cannot break the built-in report.
    """

    if plugins is None:
        plugins = discover_report_renderers()
    artifacts: list[dict[str, Any]] = []
    for plugin in plugins:
        try:
            result = plugin.callable_(project, output_dir)
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            warnings.warn(
                f"report renderer {plugin.name!r} raised {type(exc).__name__}: {exc}",
                stacklevel=2,
            )
            continue
        if result is None:
            continue
        if isinstance(result, (str, Path, dict)):
            values = [result]
        else:
            try:
                values = list(result)
            except TypeError:
                warnings.warn(
                    f"report renderer {plugin.name!r} returned a non-iterable artifact; skipping",
                    stacklevel=2,
                )
                continue
        for value in values:
            if isinstance(value, dict):
                artifact = dict(value)
            else:
                artifact = {"path": str(value)}
            artifact.setdefault("plugin", plugin.name)
            artifacts.append(artifact)
    return artifacts


def run_node_kind_plugins(plugins: list[LoadedPlugin] | None = None) -> list[dict[str, Any]]:
    """Invoke experimental node-kind providers.

    Providers are called with no arguments and should return dictionaries that
    describe additional node kinds for external tooling.
    """

    if plugins is None:
        plugins = discover_node_kind_plugins()
    kinds: list[dict[str, Any]] = []
    for plugin in plugins:
        try:
            result = plugin.callable_()
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            warnings.warn(
                f"node-kind provider {plugin.name!r} raised {type(exc).__name__}: {exc}",
                stacklevel=2,
            )
            continue
        if result is None:
            continue
        try:
            for item in result:
                if isinstance(item, dict):
                    enriched = dict(item)
                    enriched.setdefault("plugin", plugin.name)
                    kinds.append(enriched)
        except TypeError:
            warnings.warn(
                f"node-kind provider {plugin.name!r} did not return an iterable; skipping",
                stacklevel=2,
            )
    return kinds
