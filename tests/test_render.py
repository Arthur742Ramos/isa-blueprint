"""Smoke tests for the static site renderer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import isabelle_blueprint.render.site as site_mod
from isabelle_blueprint.agents.assignments import AssignmentStore, set_assignment
from isabelle_blueprint.agents.memory import AgentMemory, AgentMemoryAttempt, add_memory_attempt
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import AgentStatus, BlueprintStatus, FormalStatus
from isabelle_blueprint.render.site import node_filename, render_site


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
    for name in ("index.html", "graph.html", "status.html", "tasks.html", "roadmap.html"):
        assert (tmp_path / name).exists(), f"missing {name}"
    # Per-node pages (filenames are slug+hash sanitised).
    assert (tmp_path / "nodes" / node_filename("def-a")).exists()
    assert (tmp_path / "nodes" / node_filename("lem-b")).exists()
    # JSON dumps.
    project_data = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert project_data["name"] == "smoke"
    tasks_data = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert isinstance(tasks_data["tasks"], list)
    roadmap_data = json.loads((tmp_path / "roadmap.json").read_text(encoding="utf-8"))
    assert roadmap_data["summary"]["node_count"] == 2
    # DOT + JSON graph artifacts.
    assert (tmp_path / "graph.dot").exists()
    assert (tmp_path / "graph.json").exists()
    assert (tmp_path / ".isabelle-blueprint-manifest.json").exists()
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
    text = (tmp_path / "nodes" / node_filename("lem-b")).read_text(encoding="utf-8")
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
    assert "data-filter-search" in body
    assert "data-search=" in body


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


def test_render_site_reconciles_removed_nodes_and_preserves_unmanaged_files(tmp_path: Path):
    render_site(_project(), tmp_path)
    removed_page = tmp_path / "nodes" / node_filename("lem-b")
    assert removed_page.exists()
    cname = tmp_path / "CNAME"
    cname.write_text("example.test\n", encoding="utf-8")

    original = _project()
    smaller = BlueprintProject.from_nodes("smoke", [original.nodes[0]], sources=["smoke.md"])
    render_site(smaller, tmp_path)

    assert not removed_page.exists()
    assert cname.read_text(encoding="utf-8") == "example.test\n"
    assert (tmp_path / "nodes" / node_filename("def-a")).exists()


def test_render_site_removes_optional_artifacts_that_disappear(tmp_path: Path, monkeypatch):
    render_site(_project(), tmp_path)
    stale_svg = tmp_path / "graph.svg"
    stale_svg.write_text("old svg", encoding="utf-8")
    manifest_path = tmp_path / ".isabelle-blueprint-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append("graph.svg")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(site_mod, "render_svg", lambda *args, **kwargs: None)
    render_site(_project(), tmp_path)

    assert not stale_svg.exists()


def test_render_site_failure_keeps_previous_published_site(tmp_path: Path, monkeypatch):
    render_site(_project(), tmp_path)
    before = (tmp_path / "index.html").read_text(encoding="utf-8")

    def fail(*args, **kwargs):
        raise RuntimeError("template failure")

    monkeypatch.setattr(site_mod, "_render_page", fail)
    with pytest.raises(RuntimeError, match="template failure"):
        render_site(_project(), tmp_path)

    assert (tmp_path / "index.html").read_text(encoding="utf-8") == before
    assert not list(tmp_path.parent.glob(f".{tmp_path.name}.*"))


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


def test_inline_dependency_graph_has_accessible_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The figure describes the graph once and hides Graphviz's duplicate titles."""
    monkeypatch.setattr(
        "isabelle_blueprint.render.site.render_svg",
        lambda *_args, **_kwargs: (
            '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
            '<title>G</title><g class="node"><title>def-a</title></g></svg>'
        ),
    )
    render_site(_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")

    assert '<figure class="graph-frame" data-graph-host' in body
    assert 'aria-labelledby="dependency-graph-caption"' in body
    assert '<figcaption id="dependency-graph-caption" class="sr-only">' in body
    assert "The dependency levels and links below" in body
    assert '<svg aria-hidden="true" focusable="false"' in body
    assert 'data-graph-filters-count aria-live="polite"' in body


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
    assert "is-dimmed" in graph_text
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


def test_render_site_shows_next_task_and_trend_delta(tmp_path: Path):
    entries = [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "coverage_percent": 0,
            "node_count": 2,
            "proved_count": 0,
            "problem_count": 2,
        },
        {
            "timestamp": "2025-01-02T00:00:00Z",
            "coverage_percent": 50,
            "node_count": 3,
            "proved_count": 1,
            "problem_count": 1,
        },
    ]
    render_site(_project(), tmp_path, trends=entries)

    body = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Next action" in body
    assert "Changed since last report" in body
    assert "coverage delta" in body


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


def test_render_site_renders_roadmap_page(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "roadmap.html").read_text(encoding="utf-8")

    assert "Roadmap" in body
    assert "roadmap-swimlanes" in body
    assert 'data-filter-scope="roadmap"' in body
    assert "Copy handoff command" in body


def test_tasks_page_renders_task_board_and_memory(tmp_path: Path):
    memory = AgentMemory()
    add_memory_attempt(
        memory,
        "def-a",
        AgentMemoryAttempt(
            timestamp="2026-01-01T00:00:00Z",
            outcome="blocked",
            summary="needs helper",
            next_step="split the goal",
        ),
    )

    render_site(_project(), tmp_path, memory=memory)
    body = (tmp_path / "tasks.html").read_text(encoding="utf-8")

    assert "Task board" in body
    assert "split the goal" in body
    assert "task-column-ready" in body


def test_tasks_page_renders_attempted_agent_status_separately(tmp_path: Path):
    project = _project()
    project.nodes[0].status.agent = AgentStatus.ATTEMPTED
    project.nodes[0].status.formal = FormalStatus.FOUND

    render_site(project, tmp_path)
    body = (tmp_path / "tasks.html").read_text(encoding="utf-8")

    assert "Attempted" in body
    assert "task-column-attempted" in body
    assert (
        '<article class="task-column task-column-blocked">\n        '
        "<h3>Blocked <span>0</span></h3>" in body
    )


# ---------------------------------------------------------------------------
# v1.10 critical-path overlay + owner annotations
# ---------------------------------------------------------------------------


def _proved_project():
    a = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        isabelle=IsabelleRef(fact="Demo.a_def"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.PROVED),
    )
    return BlueprintProject.from_nodes("proved", [a], sources=["proved.md"])


def test_graph_page_renders_critical_path_panel(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "Critical path" in body
    # The sample nodes are NAMED (incomplete), so a real chain def-a -> lem-b exists.
    assert 'data-critical="true"' in body
    assert "★" in body
    # def-a unblocks lem-b, so it surfaces as a bottleneck.
    assert "Bottlenecks" in body
    assert "unblocks 1" in body


def test_render_site_writes_critical_path_json(tmp_path: Path):
    render_site(_project(), tmp_path)
    payload = json.loads((tmp_path / "critical-path.json").read_text(encoding="utf-8"))
    assert payload["longest"]["goal_id"] == "lem-b"
    assert payload["longest"]["path"] == ["def-a", "lem-b"]


def test_critical_path_panel_empty_state_when_all_proved(tmp_path: Path):
    render_site(_proved_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "Critical path" in body
    assert "no critical path remains" in body
    assert 'data-critical="true"' not in body


def test_graph_page_renders_owner_filter_and_badges(tmp_path: Path):
    store = AssignmentStore()
    set_assignment(store, "def-a", "alice")
    render_site(_project(), tmp_path, assignments=store)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    # Owner filter toolbar wired for filters.js.
    assert 'data-filter-scope="graph-owners"' in body
    assert 'data-filter-dim="owner"' in body
    assert 'data-filter-value="alice"' in body
    # lem-b is unassigned, so the sentinel chip + row value appear.
    assert 'data-filter-value="__unassigned"' in body
    assert 'data-owner="alice"' in body
    assert 'data-owner="__unassigned"' in body
    # The assigned owner is rendered as a badge.
    assert "alice" in body


def test_graph_page_has_no_owner_toolbar_without_assignments(tmp_path: Path):
    render_site(_project(), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert 'data-filter-scope="graph-owners"' not in body
    assert 'data-filter-dim="owner"' not in body


def test_graph_page_ignores_stale_owner_assignments(tmp_path: Path):
    store = AssignmentStore()
    set_assignment(store, "ghost-node", "nobody")
    render_site(_project(), tmp_path, assignments=store)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    # The stale id matches no project node, so no owner UI should appear.
    assert "nobody" not in body
    assert 'data-filter-scope="graph-owners"' not in body


def test_node_page_shows_owner_and_critical_marker(tmp_path: Path):
    store = AssignmentStore()
    set_assignment(store, "def-a", "alice")
    render_site(_project(), tmp_path, assignments=store)
    text = (tmp_path / "nodes" / node_filename("def-a")).read_text(encoding="utf-8")
    assert "Owner" in text
    assert "alice" in text
    assert "on the critical path" in text


def test_critical_path_panel_flags_cycles(tmp_path: Path):
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
    # All remaining work is cycle-tangled, so no acyclic chain can be ordered.
    assert "tangled in dependency cycles" in body
    assert 'data-critical="true"' not in body


def test_critical_path_panel_warns_about_coexisting_cycles(tmp_path: Path):
    # An acyclic chain (def-a -> lem-b) plus a separate incomplete cycle (x <-> y):
    # the panel renders the chain but must still flag the lingering cycle.
    a = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        isabelle=IsabelleRef(fact="Demo.a_def"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    b = BlueprintNode(
        id="lem-b",
        kind=NodeKind.LEMMA,
        title="B",
        uses=["def-a"],
        isabelle=IsabelleRef(fact="Demo.b"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    x = BlueprintNode(
        id="cyc-x",
        kind=NodeKind.LEMMA,
        title="X",
        uses=["cyc-y"],
        isabelle=IsabelleRef(fact="Demo.x"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    y = BlueprintNode(
        id="cyc-y",
        kind=NodeKind.LEMMA,
        title="Y",
        uses=["cyc-x"],
        isabelle=IsabelleRef(fact="Demo.y"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    render_site(BlueprintProject.from_nodes("mixed", [a, b, x, y]), tmp_path)
    body = (tmp_path / "graph.html").read_text(encoding="utf-8")
    # The acyclic chain still renders...
    assert 'data-critical="true"' in body
    # ...but the lingering cycle is also called out.
    assert "dependency cycle(s) also remain" in body


# ---------------------------------------------------------------------------
# v1.15 render hardening: path-traversal safety, autoescaping, MathJax
# ---------------------------------------------------------------------------


def _traversal_project():
    evil = BlueprintNode(
        id="../../evil",
        kind=NodeKind.LEMMA,
        title="Escape attempt",
        statement="trying to break out",
        isabelle=IsabelleRef(fact="Demo.evil"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    return BlueprintProject.from_nodes("evil", [evil], sources=["evil.md"])


def test_node_id_traversal_cannot_escape_output_dir(tmp_path: Path):
    outer = tmp_path / "outside.html"
    output_dir = tmp_path / "site"
    render_site(_traversal_project(), output_dir)

    # The malicious id must NOT have written a file outside the output dir.
    assert not outer.exists()
    assert not (tmp_path / "evil.html").exists()
    # Every file produced stays inside output_dir.
    output_resolved = output_dir.resolve()
    for path in output_dir.rglob("*"):
        assert path.resolve().is_relative_to(output_resolved)
    # The sanitised page lives under nodes/ and is a single path component.
    page = output_dir / "nodes" / node_filename("../../evil")
    assert page.exists()
    assert page.parent.resolve() == (output_dir / "nodes").resolve()


def test_node_links_use_sanitised_filename(tmp_path: Path):
    output_dir = tmp_path / "site"
    render_site(_traversal_project(), output_dir)
    safe_name = node_filename("../../evil")
    # The status table links to the sanitised file, never the raw traversal id.
    status = (output_dir / "status.html").read_text(encoding="utf-8")
    assert f"nodes/{safe_name}" in status
    assert "../../evil.html" not in status


def test_render_refuses_when_nodes_dir_is_symlink(tmp_path: Path):
    # An attacker pre-creates ``nodes/`` as a symlink pointing OUTSIDE the
    # site root. ``mkdir(exist_ok=True)`` would happily accept it and per-node
    # writes would land in ``outside/``. The renderer must refuse.
    outside = tmp_path / "outside"
    outside.mkdir()
    output_dir = tmp_path / "site"
    output_dir.mkdir()
    (output_dir / "nodes").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        render_site(_project(), output_dir)

    # Nothing leaked into the symlink target.
    assert list(outside.iterdir()) == []


def test_render_autoescapes_user_supplied_values(tmp_path: Path):
    node = BlueprintNode(
        id="xss-node",
        kind=NodeKind.LEMMA,
        title="<script>alert(1)</script>",
        statement="payload <img src=x onerror=alert(2)> end",
        isabelle=IsabelleRef(fact="Demo.xss"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    project = BlueprintProject.from_nodes("xss", [node], sources=["xss.md"])
    render_site(project, tmp_path)

    page = (tmp_path / "nodes" / node_filename("xss-node")).read_text(encoding="utf-8")
    # The raw tags from user data must be escaped, not emitted live.
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img src=x onerror=alert(2)>" not in page
    assert "&lt;img src=x onerror=alert(2)&gt;" in page


def test_statement_paragraph_breaks_preserved(tmp_path: Path):
    node = BlueprintNode(
        id="multi",
        kind=NodeKind.LEMMA,
        title="Multi",
        statement="first para\n\nsecond para",
        isabelle=IsabelleRef(fact="Demo.multi"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    project = BlueprintProject.from_nodes("multi", [node], sources=["multi.md"])
    render_site(project, tmp_path)
    page = (tmp_path / "nodes" / node_filename("multi")).read_text(encoding="utf-8")
    # The double newline becomes a real paragraph split, not escaped markup.
    assert "first para</p><p>second para" in page


def test_math_statement_remains_readable_without_mathjax(tmp_path: Path):
    node = BlueprintNode(
        id="math-node",
        kind=NodeKind.LEMMA,
        title="Divisibility",
        statement="$a \\mid b$ and $c < d$",
        isabelle=IsabelleRef(fact="Demo.math"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.NAMED),
    )
    project = BlueprintProject.from_nodes("math", [node], sources=["math.md"])
    render_site(project, tmp_path)
    page = (tmp_path / "nodes" / node_filename("math-node")).read_text(encoding="utf-8")
    # MathJax progressively enhances this source text. If the CDN is unavailable,
    # the notation remains visible, while the comparison operator stays escaped.
    assert "$a \\mid b$" in page
    assert "$c &lt; d$" in page


def test_rendered_tables_have_captions_and_scoped_headers(tmp_path: Path):
    entry = {
        "timestamp": "2025-01-01T00:00:00Z",
        "commit_sha": "deadbeef",
        "branch": "main",
        "coverage_percent": 50,
        "node_count": 2,
        "proved_count": 1,
        "problem_count": 0,
    }
    render_site(_project(), tmp_path, trends=[entry])

    status = (tmp_path / "status.html").read_text(encoding="utf-8")
    assert (
        '<caption class="sr-only">Blueprint nodes and their blueprint, formal, and agent '
        "statuses.</caption>"
    ) in status
    assert status.count('scope="col"') == 7
    assert status.count('scope="row"') == 2

    trends = (tmp_path / "trends.html").read_text(encoding="utf-8")
    assert (
        '<caption class="sr-only">Blueprint coverage and problem history by recorded run.</caption>'
    ) in trends
    assert trends.count('scope="col"') == 7
    assert trends.count('scope="row"') == 1


def test_base_layout_uses_pinned_mathjax_with_integrity(tmp_path: Path):
    source = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"
    integrity = "sha384-Wuix6BuhrWbjDBs24bXrjf4ZQ5aFeFWBuKkFekO2t8xFU0iNaLQfp2K6/1Nxveei"
    render_site(_project(), tmp_path)
    for name in ("index.html", "nodes/" + node_filename("def-a")):
        body = (tmp_path / name).read_text(encoding="utf-8")
        assert "MathJax" in body
        assert f'src="{source}"' in body
        assert f'integrity="{integrity}"' in body
        assert 'crossorigin="anonymous"' in body
        assert 'referrerpolicy="no-referrer"' in body
        assert "mathjax@3/es5" not in body
        assert "defer" in body
        assert "inlineMath" in body
