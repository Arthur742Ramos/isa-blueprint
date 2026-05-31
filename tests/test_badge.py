"""Tests for :mod:`isabelle_blueprint.report.badge`."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report.badge import (
    COLOR_BRIGHT_GREEN,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    COLOR_YELLOW,
    build_endpoint_payload,
    coverage_color,
    coverage_message,
    render_badge_svg,
    write_badge_endpoint,
    write_badge_svg,
)
from isabelle_blueprint.report.metrics import StatusMetrics, build_status_metrics


def _node(node_id: str, formal: FormalStatus) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id,
        isabelle=IsabelleRef(fact=None if formal is FormalStatus.MISSING else f"Demo.{node_id}"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=formal),
    )


def _metrics(
    *,
    node_count: int = 4,
    formal_target_count: int = 4,
    proved_count: int = 0,
    found_count: int = 0,
    problem_count: int = 0,
    stale_count: int = 0,
    has_cycles: bool = False,
    coverage_percent: int | None = 0,
) -> StatusMetrics:
    return StatusMetrics(
        node_count=node_count,
        formal_target_count=formal_target_count,
        proved_count=proved_count,
        found_count=found_count,
        problem_count=problem_count,
        stale_count=stale_count,
        has_cycles=has_cycles,
        coverage_percent=coverage_percent,
    )


def test_no_nodes_yields_gray_with_no_nodes_message():
    m = _metrics(node_count=0, formal_target_count=0, coverage_percent=None)
    assert coverage_color(m) == COLOR_GRAY
    assert coverage_message(m) == "no nodes"


def test_no_formal_targets_yields_gray():
    m = _metrics(node_count=3, formal_target_count=0, coverage_percent=None)
    assert coverage_color(m) == COLOR_GRAY
    assert coverage_message(m) == "no formal targets"


def test_problem_status_forces_red_even_with_high_coverage():
    m = _metrics(
        node_count=4,
        formal_target_count=4,
        proved_count=4,
        problem_count=1,  # e.g. one tainted/broken proof
        coverage_percent=100,
    )
    # Even at 100% proved, an active problem must scream red.
    assert coverage_color(m) == COLOR_RED
    # And the message should mention it.
    msg = coverage_message(m)
    assert "1 problem" in msg


def test_stale_does_not_turn_badge_red():
    m = _metrics(
        node_count=4,
        formal_target_count=4,
        proved_count=3,
        stale_count=1,
        coverage_percent=75,
    )
    # stale_count alone does not affect has_problems / color.
    assert coverage_color(m) == COLOR_GREEN


def test_color_thresholds_step_through_palette():
    assert coverage_color(_metrics(proved_count=4, coverage_percent=100)) == COLOR_BRIGHT_GREEN
    assert coverage_color(_metrics(proved_count=3, coverage_percent=75)) == COLOR_GREEN
    assert coverage_color(_metrics(proved_count=2, coverage_percent=50)) == COLOR_YELLOW
    assert coverage_color(_metrics(proved_count=1, coverage_percent=25)) == COLOR_ORANGE
    assert coverage_color(_metrics(proved_count=0, coverage_percent=10)) == COLOR_RED


def test_coverage_message_quotes_proved_and_target():
    m = _metrics(proved_count=2, coverage_percent=50)
    assert coverage_message(m) == "50% proved (2/4)"


def test_render_badge_svg_is_well_formed_xml():
    svg = render_badge_svg("blueprint", "75% proved (3/4)", "green")
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    # role/aria attributes help screen readers - lock them in.
    assert root.attrib.get("role") == "img"
    assert "blueprint" in root.attrib.get("aria-label", "")


def test_render_badge_svg_escapes_dangerous_characters():
    svg = render_badge_svg("blue<script>", "100% & green", "green")
    # The raw chars must not appear in the rendered SVG.
    assert "<script>" not in svg
    assert "& green" not in svg
    # Escaped forms must.
    assert "&lt;script&gt;" in svg
    assert "&amp; green" in svg
    # And it must still be parseable XML.
    ET.fromstring(svg)


def test_build_endpoint_payload_has_schema_version_one():
    project = BlueprintProject.from_nodes(
        "demo",
        [_node("a", FormalStatus.PROVED), _node("b", FormalStatus.NAMED)],
    )
    payload = build_endpoint_payload(project)
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "blueprint"
    assert payload["color"] in {COLOR_RED, COLOR_ORANGE, COLOR_YELLOW, COLOR_GREEN}


def test_write_badge_endpoint_and_svg_create_files(tmp_path: Path):
    project = BlueprintProject.from_nodes(
        "demo",
        [_node("a", FormalStatus.PROVED), _node("b", FormalStatus.PROVED)],
    )
    json_path = write_badge_endpoint(project, tmp_path / "out" / "badge.json")
    svg_path = write_badge_svg(project, tmp_path / "out" / "badge.svg")
    assert json_path.exists()
    assert svg_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["color"] == COLOR_BRIGHT_GREEN  # 100% proved
    # SVG should be parseable and reference the bright-green hex shields uses.
    svg_text = svg_path.read_text(encoding="utf-8")
    ET.fromstring(svg_text)
    assert "#4c1" in svg_text


def test_endpoint_payload_uses_shared_metrics(tmp_path: Path):
    # Regression guard: the endpoint payload must agree with what
    # build_status_metrics says, so the badge cannot drift from the report.
    project = BlueprintProject.from_nodes(
        "demo",
        [_node("a", FormalStatus.PROVED), _node("b", FormalStatus.NAMED)],
    )
    payload = build_endpoint_payload(project)
    metrics = build_status_metrics(project)
    assert payload["message"] == coverage_message(metrics)
    assert payload["color"] == coverage_color(metrics)
