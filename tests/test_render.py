"""Smoke tests for the static site renderer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.render.site import render_site


def _project():
    a = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        statement="def of A",
        isabelle=IsabelleRef(fact="Demo.a_def"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    b = BlueprintNode(
        id="lem-b",
        kind=NodeKind.LEMMA,
        title="B",
        statement="thing about B",
        informal_proof="by induction",
        uses=["def-a"],
        isabelle=IsabelleRef(fact="Demo.b_lem"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    return BlueprintProject.from_nodes("smoke", [a, b], sources=["smoke.md"])


def test_render_site_produces_expected_pages(tmp_path: Path):
    index = render_site(_project(), tmp_path)
    assert index.exists()
    for name in ("index.html", "graph.html", "status.html", "tasks.html"):
        assert (tmp_path / name).exists(), f"missing {name}"
    # Per-node pages.
    assert (tmp_path / "nodes" / "def-a.html").exists()
    assert (tmp_path / "nodes" / "lem-b.html").exists()
    # JSON dumps.
    project_data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert project_data["name"] == "smoke"
    tasks_data = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert isinstance(tasks_data["tasks"], list)
    # DOT + JSON graph artifacts.
    assert (tmp_path / "graph.dot").exists()
    assert (tmp_path / "graph.json").exists()
    # Static assets copied through.
    assert (tmp_path / "static" / "style.css").exists()


def test_render_site_index_mentions_node_titles(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "A" in body
    assert "B" in body
    assert 'class="status-bar"' in body
    assert "Dependency depth" in body


def test_node_page_lists_dependency(tmp_path: Path):
    render_site(_project(), tmp_path)
    text = (tmp_path / "nodes" / "lem-b.html").read_text(encoding="utf-8")
    assert "def-a" in text


def test_graph_page_renders_dependency_levels(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "Dependency levels" in body
    assert 'data-level="0"' in body
    assert 'data-level="1"' in body
    assert "def-a" in body
    assert "lem-b" in body


def test_graph_page_marks_cyclic_dependency_levels(tmp_path: Path):
    a = BlueprintNode(
        id="a",
        kind=NodeKind.LEMMA,
        title="A",
        uses=["b"],
        isabelle=IsabelleRef(fact="Demo.a"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    b = BlueprintNode(
        id="b",
        kind=NodeKind.LEMMA,
        title="B",
        uses=["a"],
        isabelle=IsabelleRef(fact="Demo.b"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    render_site(BlueprintProject.from_nodes("cycle", [a, b]), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert 'data-level="cycle"' in body
    assert "Cycle or cycle-dependent path detected" in body
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<div class="status-card-count">0</div>' in index
    assert "cycle-blocked nodes" in index


def test_status_page_includes_summary_and_filter_data(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "status.html").read_text(encoding="utf-8")
    assert 'class="status-summary"' in body
    assert 'data-blueprint="written" data-formal="named"' in body


def test_status_page_includes_interactive_filter_pills(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "status.html").read_text(encoding="utf-8")
    # The pill UI needs DOM hooks for filters.js to find.
    assert 'class="filters"' in body
    assert 'data-filter-dim="blueprint"' in body
    assert 'data-filter-dim="formal"' in body
    # The clear button + live count both need to exist for the JS no-op
    # guard to actually wire up.
    assert "data-filter-clear" in body
    assert "data-filter-count" in body


def test_render_site_emits_badge_artifacts(tmp_path: Path):
    render_site(_project(), tmp_path)
    badge_json = tmp_path / "badge.json"
    badge_svg = tmp_path / "badge.svg"
    assert badge_json.exists()
    assert badge_svg.exists()

    payload = json.loads(badge_json.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "blueprint"
    # Sample project has 2 named/0 proved nodes -> "0% proved (0/2)".
    assert "0% proved" in payload["message"]

    svg_text = badge_svg.read_text(encoding="utf-8")
    assert svg_text.startswith("<svg")
    assert svg_text.rstrip().endswith("</svg>")


def test_render_site_ships_filters_js_static_asset(tmp_path: Path):
    render_site(_project(), tmp_path)
    filters_js = tmp_path / "static" / "filters.js"
    assert filters_js.exists()
    js_text = filters_js.read_text(encoding="utf-8")
    # Loose contract check: the JS still wires up the DOM attrs the template
    # writes out, and still toggles the .is-hidden class our CSS targets.
    assert "data-filter-dim" in js_text
    assert "is-hidden" in js_text


def test_base_layout_loads_filters_script(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "status.html").read_text(encoding="utf-8")
    assert 'src="static/filters.js"' in body


# ---------------------------------------------------------------------------
# v0.8 graph filter + trends chart smoke coverage
# ---------------------------------------------------------------------------


def test_graph_page_contains_filter_toolbar(tmp_path: Path):
    """The graph page must expose the formal-status filter UI hooks."""
    render_site(_project(), tmp_path)
    if not (tmp_path / "graph.svg").exists():
        pytest.skip("graphviz not installed; filter toolbar is gated on inline SVG")
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "data-graph-filters" in body
    assert "data-graph-filters-reset" in body
    assert "data-graph-filters-count" in body
    # One pill per FormalStatus value.
    for status in FormalStatus:
        assert f'data-graph-formal="{status.value}"' in body


def test_render_site_emits_graph_and_trend_scripts(tmp_path: Path):
    """Both new JS files ship with their expected DOM hooks."""
    render_site(_project(), tmp_path)
    graph_js = tmp_path / "static" / "graph.js"
    trends_js = tmp_path / "static" / "trends.js"
    assert graph_js.exists()
    assert trends_js.exists()
    graph_text = graph_js.read_text(encoding="utf-8")
    trends_text = trends_js.read_text(encoding="utf-8")
    assert "data-graph-formal" in graph_text
    assert "is-hidden" in graph_text
    assert "data-trend-chart-host" in trends_text


def test_base_layout_loads_graph_and_trend_scripts(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert 'src="static/graph.js"' in body
    assert 'src="static/trends.js"' in body


def test_render_site_writes_trends_json_with_supplied_entries(tmp_path: Path):
    """``trends`` kwarg flows through to the shipped ``trends.json``."""
    entry = {
        "timestamp": "2025-01-01T00:00:00Z",
        "commit_sha": "deadbeef",
        "branch": "main",
        "coverage_percent": 50,
        "node_count": 2,
        "formal_target_count": 2,
        "proved_count": 1,
        "found_count": 1,
        "problem_count": 0,
        "stale_count": 0,
        "has_cycles": False,
    }
    render_site(_project(), tmp_path, trends=[entry])
    payload = json.loads((tmp_path / "trends.json").read_text(encoding="utf-8"))
    assert payload["entries"] == [entry]


def test_render_site_renders_trends_page(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "trends.html").read_text(encoding="utf-8")
    # Empty-state callout when no trends are supplied.
    assert "No trend history yet" in body
    # Nav link is present.
    assert "trends.html" in body


def test_render_site_renders_trends_page_with_data(tmp_path: Path):
    entry = {
        "timestamp": "2025-01-01T00:00:00Z",
        "commit_sha": "cafebabe",
        "branch": "feature",
        "coverage_percent": 75,
        "node_count": 4,
        "formal_target_count": 4,
        "proved_count": 3,
        "found_count": 4,
        "problem_count": 1,
        "stale_count": 0,
        "has_cycles": False,
    }
    render_site(_project(), tmp_path, trends=[entry])
    body = (tmp_path / "trends.html").read_text(encoding="utf-8")
    assert "data-trend-chart-host" in body
    # First 8 chars of the commit sha appear in the history table.
    assert "cafebabe"[:8] in body
    assert "feature" in body
