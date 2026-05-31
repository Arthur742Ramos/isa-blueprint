"""Smoke tests for the static site renderer."""
from __future__ import annotations

import json
from pathlib import Path

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
