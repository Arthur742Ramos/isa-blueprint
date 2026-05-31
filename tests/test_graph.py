"""Tests for the dependency-graph builder and Graphviz renderer."""
from __future__ import annotations

from isabelle_blueprint.graph.dependency_graph import build_graph, dependency_levels
from isabelle_blueprint.graph.graphviz_render import render_dot, render_json
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject


def _project(*pairs):
    nodes = []
    for nid, deps in pairs:
        nodes.append(
            BlueprintNode(
                id=nid,
                kind=NodeKind.LEMMA,
                title=nid.upper(),
                uses=list(deps),
                isabelle=IsabelleRef(fact=f"Demo.{nid}"),
                status=NodeStatus(),
            )
        )
    return BlueprintProject.from_nodes("p", nodes)


def test_build_graph_collects_edges_and_reverse_edges():
    project = _project(("a", []), ("b", ["a"]), ("c", ["a", "b"]))
    g = build_graph(project)
    assert set(g.nodes) == {"a", "b", "c"}
    assert g.edges["c"] == ["a", "b"]
    assert "c" in g.reverse_edges["a"]
    assert "c" in g.reverse_edges["b"]


def test_build_graph_drops_missing_dep_edges():
    project = _project(("a", ["missing"]))
    g = build_graph(project)
    assert g.edges["a"] == []  # missing dep silently dropped at build time


def test_dependency_levels_topological():
    project = _project(("a", []), ("b", ["a"]), ("c", ["a", "b"]))
    levels = dependency_levels(project)
    # 'a' must come strictly before 'b', and 'b' before 'c'.
    flat = [n for level in levels for n in level]
    assert flat.index("a") < flat.index("b") < flat.index("c")


def test_dependency_levels_handles_cycle_by_grouping_at_end():
    project = _project(("a", ["b"]), ("b", ["a"]))
    levels = dependency_levels(project)
    assert {"a", "b"}.issubset(set(n for lvl in levels for n in lvl))


def test_render_dot_contains_all_nodes_and_edges():
    project = _project(("a", []), ("b", ["a"]))
    dot = render_dot(project)
    assert "digraph" in dot
    assert '"a"' in dot
    assert '"b"' in dot
    # Edge syntax: "b" -> "a" (depends-on direction)
    assert '"b"' in dot and '"a"' in dot
    assert "->" in dot


def test_render_json_shape():
    import json

    project = _project(("a", []), ("b", ["a"]))
    data = json.loads(render_json(project))
    assert "nodes" in data and "edges" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"a", "b"}
    assert any(e["source"] == "b" and e["target"] == "a" for e in data["edges"])
