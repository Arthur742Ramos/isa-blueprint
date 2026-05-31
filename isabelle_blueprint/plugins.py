"""Plugin discovery for IsabelleBlueprint.

v0.9 ships a deliberately small plugin contract: third-party packages can
register **status providers** under the
``isabelle_blueprint.status_providers`` entry-point group. A status provider
is a callable ``provider(project) -> Iterable[StatusAnnotation]`` (or any
iterable of dicts with ``node_id`` and free-form ``data``) that the caller
can fold into report output. The discovery layer is intentionally small and
permissive so that misbehaving plugins never abort a CLI run.

Future versions may add ``isabelle_blueprint.node_kinds`` and
``isabelle_blueprint.report_renderers`` entry-point groups; those names are
reserved but not loaded yet.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any, Callable

STATUS_PROVIDER_GROUP = "isabelle_blueprint.status_providers"


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


def discover_status_providers() -> list[LoadedPlugin]:
    """Discover and load all registered status-provider plugins.

    Loading errors are logged via :func:`warnings.warn` and the offending
    entry-point is skipped; an individual broken plugin must not break
    the CLI.
    """
    loaded: list[LoadedPlugin] = []
    for ep in _iter_entry_points(STATUS_PROVIDER_GROUP):
        try:
            func = ep.load()
        except Exception as exc:  # noqa: BLE001 - plugin code is third-party
            warnings.warn(
                f"failed to load status provider {ep.name!r}: {exc}",
                stacklevel=2,
            )
            continue
        if not callable(func):
            warnings.warn(
                f"status provider {ep.name!r} is not callable; skipping",
                stacklevel=2,
            )
            continue
        dist_name: str | None = None
        dist = getattr(ep, "dist", None)
        if dist is not None:
            dist_name = getattr(dist, "name", None) or getattr(dist, "project_name", None)
        loaded.append(LoadedPlugin(name=ep.name, dist=dist_name, callable_=func))
    return loaded


def run_status_providers(project, plugins: list[LoadedPlugin] | None = None) -> list[dict[str, Any]]:
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
