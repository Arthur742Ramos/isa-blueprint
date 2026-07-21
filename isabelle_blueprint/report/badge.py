"""Shareable status badge for an :class:`~isabelle_blueprint.model.project.BlueprintProject`.

Two artefacts are produced:

* A shields.io-style ``endpoint`` JSON payload (``badge.json``). Hosting it
  alongside the static site lets users embed the badge with
  ``https://img.shields.io/endpoint?url=...``, so the colour stays in sync
  with the latest run without us having to touch shields.io ourselves.
* A self-contained flat SVG (``badge.svg``). Hand-rolled so it works offline
  - no font downloads, no external CSS, no scripts - and so README badges
  keep rendering even when shields.io is unreachable.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics

# Shields-style colours, keyed to make later tweaks obvious.
COLOR_GRAY = "lightgrey"
COLOR_RED = "red"
COLOR_ORANGE = "orange"
COLOR_YELLOW = "yellow"
COLOR_GREEN = "green"
COLOR_BRIGHT_GREEN = "brightgreen"

# Hex equivalents used by the embedded SVG (shields itself maps the names to
# these colours for its flat style).
_HEX_FOR_COLOR: dict[str, str] = {
    COLOR_GRAY: "#9f9f9f",
    COLOR_RED: "#e05d44",
    COLOR_ORANGE: "#fe7d37",
    COLOR_YELLOW: "#dfb317",
    COLOR_GREEN: "#97ca00",
    COLOR_BRIGHT_GREEN: "#4c1",
}

DEFAULT_LABEL = "blueprint"


def coverage_color(metrics: StatusMetrics) -> str:
    """Pick a badge colour from ``metrics``.

    * No nodes / no formal targets -> gray (nothing to report yet).
    * Any problem status -> red (something is actively broken).
    * Otherwise scale from red (<25%) through brightgreen (==100%).

    ``stale`` deliberately does **not** force red - it usually just means a
    dependency moved and we haven't re-run ``check`` yet.
    """
    if metrics.node_count == 0 or metrics.formal_target_count == 0:
        return COLOR_GRAY
    if metrics.has_problems:
        return COLOR_RED
    percent = metrics.coverage_percent or 0
    if percent >= 100:
        return COLOR_BRIGHT_GREEN
    if percent >= 75:
        return COLOR_GREEN
    if percent >= 50:
        return COLOR_YELLOW
    if percent >= 25:
        return COLOR_ORANGE
    return COLOR_RED


def coverage_message(metrics: StatusMetrics) -> str:
    """Render the right-hand side of the badge for ``metrics``."""
    if metrics.node_count == 0:
        return "no nodes"
    if metrics.formal_target_count == 0:
        return "no formal targets"
    percent = metrics.coverage_percent or 0
    parts = [f"{percent}% proved ({metrics.proved_count}/{metrics.formal_target_count})"]
    if metrics.has_problems:
        parts.append(f"{metrics.problem_count} problem{'s' if metrics.problem_count != 1 else ''}")
    return ", ".join(parts)


def build_endpoint_payload(
    project: BlueprintProject,
    *,
    label: str = DEFAULT_LABEL,
) -> dict[str, object]:
    """Return the shields.io ``endpoint`` JSON payload for ``project``."""
    metrics = build_status_metrics(project)
    return {
        "schemaVersion": 1,
        "label": label,
        "message": coverage_message(metrics),
        "color": coverage_color(metrics),
    }


def render_badge_svg(
    label: str,
    message: str,
    color: str,
    *,
    label_color: str = "#555",
) -> str:
    """Render a flat-style SVG badge.

    The geometry is a simplified version of the shields.io "flat" style: a
    label rectangle on the left, a message rectangle on the right, both 20px
    tall. Text widths use a crude 7-pixels-per-char heuristic plus 10px of
    horizontal padding - good enough for short status messages and avoids
    depending on a real font metrics library.
    """
    safe_label = xml_escape(label)
    safe_message = xml_escape(message)
    color_hex = _HEX_FOR_COLOR.get(color, color)

    label_w = max(40, 10 + 7 * len(label))
    message_w = max(40, 10 + 7 * len(message))
    total_w = label_w + message_w

    label_text_x = label_w / 2
    message_text_x = label_w + message_w / 2

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="20" role="img" '
        f'aria-label="{safe_label}: {safe_message}">'
        f"<title>{safe_label}: {safe_message}</title>"
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f"</linearGradient>"
        f'<clipPath id="r"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label_w}" height="20" fill="{label_color}"/>'
        f'<rect x="{label_w}" width="{message_w}" height="20" fill="{color_hex}"/>'
        f'<rect width="{total_w}" height="20" fill="url(#s)"/>'
        f"</g>"
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        f'text-rendering="geometricPrecision" font-size="110">'
        f'<text x="{label_text_x * 10}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{label_w * 10 - 20}">{safe_label}</text>'
        f'<text x="{label_text_x * 10}" y="140" '
        f'transform="scale(.1)" textLength="{label_w * 10 - 20}">{safe_label}</text>'
        f'<text x="{message_text_x * 10}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{message_w * 10 - 20}">{safe_message}</text>'
        f'<text x="{message_text_x * 10}" y="140" '
        f'transform="scale(.1)" textLength="{message_w * 10 - 20}">{safe_message}</text>'
        f"</g></svg>"
    )


def write_badge_endpoint(
    project: BlueprintProject,
    path: Path,
    *,
    label: str = DEFAULT_LABEL,
) -> Path:
    """Write the shields.io endpoint payload to ``path``."""
    payload = build_endpoint_payload(project, label=label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_badge_svg(
    project: BlueprintProject,
    path: Path,
    *,
    label: str = DEFAULT_LABEL,
) -> Path:
    """Write the self-contained SVG badge to ``path``."""
    metrics = build_status_metrics(project)
    svg = render_badge_svg(label, coverage_message(metrics), coverage_color(metrics))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path
