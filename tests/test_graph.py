"""Tests for the dependency-graph builder and Graphviz renderer."""

from __future__ import annotations

import pytest

from isabelle_blueprint.graph.dependency_graph import (
    UnknownNodeError,
    build_graph,
    dependency_levels,
    focus_subproject,
    incomplete_subproject,
    leaves_subproject,
    neighbourhood,
    roots_subproject,
)
from isabelle_blueprint.graph.graphviz_render import (
    _mermaid_id,
    render_d2,
    render_dot,
    render_graphml,
    render_json,
    render_mermaid,
    render_svg,
)
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus


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


def test_render_mermaid_contains_flowchart_nodes_and_edges():
    project = _project(("a", []), ("b", ["a"]))
    mermaid = render_mermaid(project)
    assert mermaid.startswith("flowchart BT")
    assert "-->" in mermaid
    assert "style" in mermaid
    # Both node ids appear in the flowchart body.
    assert "a" in mermaid and "b" in mermaid


def test_mermaid_id_is_injective_for_separator_variants():
    # ``a.b``, ``a-b``, ``a/b`` and ``a:b`` are all distinct blueprint ids; the
    # old mapping collapsed every separator to ``_`` and made them collide.
    ids = ["a.b", "a-b", "a/b", "a:b", "a_b"]
    mapped = [_mermaid_id(i) for i in ids]
    assert len(set(mapped)) == len(ids)


def test_render_mermaid_keeps_separator_distinct_nodes_connected():
    # Two ids differing only by separator must remain two nodes with a real edge
    # between them (previously both rendered as the same ``n_a_b`` node).
    project = _project(("a.b", []), ("a-b", ["a.b"]))
    mermaid = render_mermaid(project)
    assert _mermaid_id("a.b") in mermaid
    assert _mermaid_id("a-b") in mermaid
    assert f"{_mermaid_id('a-b')} --> {_mermaid_id('a.b')}" in mermaid


def test_cli_graph_format_mermaid_writes_mmd(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-fmt"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-fmt

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--format", "mermaid"])

    assert rc == 0
    capsys.readouterr()
    mmd = tmp_path / "build" / "graph.mmd"
    assert mmd.exists()
    assert mmd.read_text(encoding="utf-8").startswith("flowchart BT")
    # Only the mermaid artifact should be written for --format mermaid.
    assert not (tmp_path / "build" / "graph.dot").exists()


def test_render_graphml_shape():
    import xml.etree.ElementTree as ET

    project = _project(("a", []), ("b", ["a"]))
    xml = render_graphml(project)
    assert xml.startswith("<?xml")
    # It must be well-formed XML.
    root = ET.fromstring(xml)
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    nodes = root.findall(".//g:node", ns)
    edges = root.findall(".//g:edge", ns)
    assert {n.get("id") for n in nodes} == {"a", "b"}
    assert len(edges) == 1
    assert edges[0].get("source") == "b"
    assert edges[0].get("target") == "a"


def test_render_graphml_escapes_special_characters():
    # A title with XML metacharacters must be escaped, not break the document.
    nodes = [
        BlueprintNode(
            id="a",
            kind=NodeKind.LEMMA,
            title='A < B & "C"',
            isabelle=IsabelleRef(fact="Demo.a"),
            status=NodeStatus(),
        )
    ]
    project = BlueprintProject.from_nodes("p", nodes)
    xml = render_graphml(project)
    assert "&lt;" in xml and "&amp;" in xml
    import xml.etree.ElementTree as ET

    ET.fromstring(xml)  # must not raise


def test_neighbourhood_depth_limits():
    project = _project(("a", []), ("b", ["a"]), ("c", ["b"]), ("d", ["c"]))
    # Undirected hops from 'b': depth 1 reaches a and c.
    assert neighbourhood(project, "b", 1) == ["a", "b", "c"]
    # depth 0 is just the focus.
    assert neighbourhood(project, "b", 0) == ["b"]
    # Unlimited reaches the whole connected component (declaration order).
    assert neighbourhood(project, "b", None) == ["a", "b", "c", "d"]


def test_neighbourhood_unknown_node_raises():
    project = _project(("a", []))
    with pytest.raises(UnknownNodeError):
        neighbourhood(project, "ghost")


def test_neighbourhood_rejects_negative_depth():
    project = _project(("a", []))
    with pytest.raises(ValueError):
        neighbourhood(project, "a", -1)


def test_focus_subproject_prunes_to_neighbourhood():
    project = _project(("a", []), ("b", ["a"]), ("c", ["b"]), ("island", []))
    focused = focus_subproject(project, "b", 1)
    ids = {n.id for n in focused.nodes}
    assert ids == {"a", "b", "c"}
    assert focused.name == "p"
    assert "island" not in ids
    # The pruned project still builds a clean graph (no dangling edges).
    assert set(build_graph(focused).nodes) == ids


def test_focus_subproject_keeps_relevant_sources_when_nodes_tracked():
    # Nodes that carry per-node provenance: focusing keeps only the files
    # belonging to the surviving nodes and drops the pruned node's file.
    nodes = [
        BlueprintNode(
            id="a",
            kind=NodeKind.LEMMA,
            title="A",
            isabelle=IsabelleRef(fact="Demo.a"),
            status=NodeStatus(),
            source_file="a.md",
        ),
        BlueprintNode(
            id="island",
            kind=NodeKind.LEMMA,
            title="ISLAND",
            isabelle=IsabelleRef(fact="Demo.island"),
            status=NodeStatus(),
            source_file="island.md",
        ),
    ]
    project = BlueprintProject.from_nodes("p", nodes, ["a.md", "island.md"])
    focused = focus_subproject(project, "a", 0)
    assert {n.id for n in focused.nodes} == {"a"}
    assert focused.source_files == ["a.md"]


def test_focus_subproject_preserves_sources_without_node_provenance():
    # Sources supplied at the project level but no node tracks source_file:
    # focusing must not erase the caller-provided provenance.
    project = BlueprintProject.from_nodes(
        "p",
        _project(("a", []), ("island", [])).nodes,
        ["blueprint.md"],
    )
    assert all(node.source_file is None for node in project.nodes)
    focused = focus_subproject(project, "a", 0)
    assert {n.id for n in focused.nodes} == {"a"}
    assert focused.source_files == ["blueprint.md"]


def test_cli_graph_focus_writes_subgraph(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-focus"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-focus

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

B statement.
:::

::: lemma {#island}
title: Island
isabelle: Demo.island
status: stub

Island statement.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--format", "json", "--focus", "b"])

    assert rc == 0
    capsys.readouterr()
    import json

    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"a", "b"}  # island excluded from b's neighbourhood


def test_cli_graph_format_graphml_writes_file(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-gml"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-gml

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--format", "graphml"])

    assert rc == 0
    capsys.readouterr()
    gml = tmp_path / "build" / "graph.graphml"
    assert gml.exists()
    assert "graphml" in gml.read_text(encoding="utf-8")
    assert not (tmp_path / "build" / "graph.dot").exists()


def test_render_d2_contains_nodes_and_edges():
    project = _project(("a", []), ("b", ["a"]))
    d2 = render_d2(project)
    assert d2.startswith("direction: up")
    # Each node is keyed by id with the title as label.
    assert '"a": "a\\nA"' in d2
    assert '"b": "b\\nB"' in d2
    # The uses dependency b -> a is emitted as an edge.
    assert '"b" -> "a"' in d2
    # Status-based fill hints mirror the DOT colours.
    assert "style.fill:" in d2


def test_cli_graph_format_d2_writes_file(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-d2"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-d2

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

B builds on A.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--format", "d2"])

    assert rc == 0
    capsys.readouterr()
    d2_path = tmp_path / "build" / "graph.d2"
    assert d2_path.exists()
    text = d2_path.read_text(encoding="utf-8")
    assert '"a": "a\\nA"' in text
    assert '"b": "b\\nB"' in text
    assert '"b" -> "a"' in text
    # Only the d2 artifact should be written for --format d2.
    assert not (tmp_path / "build" / "graph.dot").exists()
    assert not (tmp_path / "build" / "graph.json").exists()
    assert not (tmp_path / "build" / "graph.svg").exists()
    assert not (tmp_path / "build" / "graph.mmd").exists()
    assert not (tmp_path / "build" / "graph.graphml").exists()


def test_cli_graph_format_all_excludes_d2(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-all-d2"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-all-d2

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--format", "all"])

    assert rc == 0
    capsys.readouterr()
    # d2 is opt-in only; the default `all` set stays byte-unchanged.
    assert not (tmp_path / "build" / "graph.d2").exists()


def test_cli_graph_focus_unknown_node_errors(tmp_path, capsys):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-focus-err"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-focus-err

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
""",
        encoding="utf-8",
    )
    from isabelle_blueprint.cli import main as cli_main

    rc = cli_main(["graph", str(tmp_path), "--focus", "ghost"])

    assert rc != 0
    err = capsys.readouterr().err
    assert "unknown node" in err


def test_render_svg_returns_none_without_graphviz(monkeypatch):
    import isabelle_blueprint.graph.graphviz_render as gr

    monkeypatch.setattr(gr.shutil, "which", lambda _exe: None)
    assert render_svg("digraph {}") is None


def test_render_svg_bounds_a_hung_dot_with_timeout(monkeypatch):
    """A hung ``dot`` must not block the caller forever.

    render_svg passes a ``timeout`` to the subprocess and degrades to an SVG
    comment when it fires, rather than raising or blocking indefinitely.
    """
    import subprocess

    import isabelle_blueprint.graph.graphviz_render as gr

    monkeypatch.setattr(gr.shutil, "which", lambda _exe: "/usr/bin/dot")

    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(gr.subprocess, "run", fake_run)

    out = render_svg("digraph {}", timeout=2.5)

    assert out is not None and "timed out" in out
    assert seen.get("timeout") == 2.5  # the bound was actually handed to dot


def test_roots_subproject_keeps_only_uninbound_nodes():
    # a <- b <- c and a <- d: roots are the nodes nothing else uses (b, c, d
    # are depended upon? no: b depends on a, c depends on b, d depends on a).
    # Roots = nodes with no incoming edge = c and d.
    project = _project(("a", []), ("b", ["a"]), ("c", ["b"]), ("d", ["a"]))
    roots = roots_subproject(project)
    assert {n.id for n in roots.nodes} == {"c", "d"}
    assert roots.name == "p"


def test_roots_subproject_drops_dangling_edges_to_pruned_nodes():
    # Two mutually independent roots that both depend on a shared leaf are kept;
    # the dangling edges to the pruned leaf are dropped by build_graph.
    project = _project(("leaf", []), ("r1", ["leaf"]), ("r2", ["leaf"]))
    roots = roots_subproject(project)
    assert {n.id for n in roots.nodes} == {"r1", "r2"}
    assert build_graph(roots).edges == {"r1": [], "r2": []}


def _write_chain_project(tmp_path):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-roots"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-roots

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

B statement.
:::
""",
        encoding="utf-8",
    )


def test_cli_graph_roots_only_json_excludes_depended_upon(tmp_path, capsys):
    import json

    from isabelle_blueprint.cli import main as cli_main

    _write_chain_project(tmp_path)
    rc = cli_main(["graph", str(tmp_path), "--format", "json", "--roots-only"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"b"}  # a is depended upon by b, so it is not a root


def test_cli_graph_without_roots_only_is_unchanged(tmp_path, capsys):
    import json

    from isabelle_blueprint.cli import main as cli_main

    _write_chain_project(tmp_path)
    rc = cli_main(["graph", str(tmp_path), "--format", "json"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"a", "b"}


def test_leaves_subproject_keeps_only_nodes_with_no_outgoing_edges():
    # a uses nothing, b uses a, c uses b, d uses a. Leaves = nodes that use
    # nothing = just a.
    project = _project(("a", []), ("b", ["a"]), ("c", ["b"]), ("d", ["a"]))
    leaves = leaves_subproject(project)
    assert {n.id for n in leaves.nodes} == {"a"}
    assert leaves.name == "p"


def test_leaves_subproject_drops_dangling_edges_to_pruned_nodes():
    # Two independent leaves; the node depending on them is pruned.
    project = _project(("l1", []), ("l2", []), ("top", ["l1", "l2"]))
    leaves = leaves_subproject(project)
    assert {n.id for n in leaves.nodes} == {"l1", "l2"}
    assert build_graph(leaves).edges == {"l1": [], "l2": []}


def test_cli_graph_leaves_only_json_excludes_non_leaf(tmp_path, capsys):
    import json

    from isabelle_blueprint.cli import main as cli_main

    _write_chain_project(tmp_path)
    rc = cli_main(["graph", str(tmp_path), "--format", "json", "--leaves-only"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"a"}  # b uses a, so b is not a leaf and is excluded


def test_cli_graph_roots_only_and_leaves_only_are_mutually_exclusive(tmp_path, capsys):
    from isabelle_blueprint.cli import main as cli_main

    _write_chain_project(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["graph", str(tmp_path), "--format", "json", "--roots-only", "--leaves-only"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not allowed with" in err


def _project_with_formal(*triples):
    nodes = []
    for nid, deps, formal in triples:
        nodes.append(
            BlueprintNode(
                id=nid,
                kind=NodeKind.LEMMA,
                title=nid.upper(),
                uses=list(deps),
                isabelle=IsabelleRef(fact=f"Demo.{nid}"),
                status=NodeStatus(formal=formal),
            )
        )
    return BlueprintProject.from_nodes("p", nodes)


def test_incomplete_subproject_keeps_only_unfinished_nodes():
    # proved/found are complete; missing/named/not_found/tainted are remaining work.
    project = _project_with_formal(
        ("done", [], FormalStatus.PROVED),
        ("exists", [], FormalStatus.FOUND),
        ("todo", ["done"], FormalStatus.MISSING),
        ("named", [], FormalStatus.NAMED),
    )
    incomplete = incomplete_subproject(project)
    assert {n.id for n in incomplete.nodes} == {"todo", "named"}
    assert incomplete.name == "p"


def test_incomplete_subproject_drops_dangling_edges_to_complete_nodes():
    # 'todo' uses a proved node; the edge to the pruned complete node is dropped.
    project = _project_with_formal(
        ("done", [], FormalStatus.PROVED),
        ("todo", ["done"], FormalStatus.MISSING),
    )
    incomplete = incomplete_subproject(project)
    assert {n.id for n in incomplete.nodes} == {"todo"}
    assert build_graph(incomplete).edges == {"todo": []}


def _write_mixed_formal_project(tmp_path):
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "graph-incomplete"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        """# graph-incomplete

::: lemma {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A statement.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: missing
uses: a

B statement.
:::
""",
        encoding="utf-8",
    )


def test_cli_graph_incomplete_only_json_excludes_proved_node(tmp_path, capsys):
    import json

    from isabelle_blueprint.cli import main as cli_main

    _write_mixed_formal_project(tmp_path)
    rc = cli_main(["graph", str(tmp_path), "--format", "json", "--incomplete-only"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"b"}  # a is proved (complete); b is missing (remaining work)


def test_cli_graph_without_incomplete_only_is_unchanged(tmp_path, capsys):
    import json

    from isabelle_blueprint.cli import main as cli_main

    _write_mixed_formal_project(tmp_path)
    rc = cli_main(["graph", str(tmp_path), "--format", "json"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "graph.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"a", "b"}


def test_cli_graph_incomplete_only_and_roots_only_are_mutually_exclusive(tmp_path, capsys):
    from isabelle_blueprint.cli import main as cli_main

    _write_mixed_formal_project(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(
            [
                "graph",
                str(tmp_path),
                "--format",
                "json",
                "--incomplete-only",
                "--roots-only",
            ]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not allowed with" in err
