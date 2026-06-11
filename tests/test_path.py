"""Tests for the ``path`` dependency-trace command and its report module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.impact import UnknownNodeError
from isabelle_blueprint.report.path import build_path_analysis, path_payload, render_path


def _node(node_id: str, *, uses: tuple[str, ...] = ()) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        uses=list(uses),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=FormalStatus.MISSING),
    )


def _diamond() -> BlueprintProject:
    # top -> {mid1, mid2} -> base
    nodes = [
        _node("base"),
        _node("mid1", uses=("base",)),
        _node("mid2", uses=("base",)),
        _node("top", uses=("mid1", "mid2")),
    ]
    return BlueprintProject.from_nodes("diamond", nodes, sources=["demo.md"])


# --------------------------------------------------------------------------- #
# build_path_analysis
# --------------------------------------------------------------------------- #
def test_finds_shortest_and_all_paths_in_a_diamond() -> None:
    analysis = build_path_analysis(_diamond(), "top", "base")
    assert analysis.connected is True
    assert analysis.distance == 2
    assert analysis.shortest_path == ["top", "mid1", "base"]
    assert analysis.paths == [["top", "mid1", "base"], ["top", "mid2", "base"]]
    assert analysis.paths_truncated is False
    assert analysis.reverse_connected is False


def test_unconnected_reports_reverse_dependency_hint() -> None:
    analysis = build_path_analysis(_diamond(), "base", "top")
    assert analysis.connected is False
    assert analysis.distance is None
    assert analysis.shortest_path == []
    assert analysis.reverse_connected is True


def test_source_equals_target_is_a_trivial_path() -> None:
    analysis = build_path_analysis(_diamond(), "base", "base")
    assert analysis.connected is True
    assert analysis.distance == 0
    assert analysis.shortest_path == ["base"]
    assert analysis.reverse_connected is False


def test_unknown_node_raises() -> None:
    project = _diamond()
    with pytest.raises(UnknownNodeError):
        build_path_analysis(project, "top", "ghost")
    with pytest.raises(UnknownNodeError):
        build_path_analysis(project, "ghost", "base")


def test_max_paths_truncates() -> None:
    # top -> m0..m4 -> base : five distinct simple paths.
    nodes = [_node("base"), _node("top", uses=tuple(f"m{i}" for i in range(5)))]
    nodes.extend(_node(f"m{i}", uses=("base",)) for i in range(5))
    project = BlueprintProject.from_nodes("fan", nodes, sources=["demo.md"])

    analysis = build_path_analysis(project, "top", "base", max_paths=2)
    assert analysis.paths_truncated is True
    assert len(analysis.paths) == 2
    # The shortest path is still reported exactly (length is uniform here).
    assert analysis.shortest_path[0] == "top" and analysis.shortest_path[-1] == "base"


def test_traversal_is_cycle_safe() -> None:
    # b <-> c form a cycle; a -> b. Path a -> c must terminate, not hang.
    nodes = [
        _node("a", uses=("b",)),
        _node("b", uses=("c",)),
        _node("c", uses=("b",)),
    ]
    project = BlueprintProject.from_nodes("cyc", nodes, sources=["demo.md"])
    analysis = build_path_analysis(project, "a", "c")
    assert analysis.connected is True
    assert analysis.shortest_path == ["a", "b", "c"]


def test_payload_matches_to_dict() -> None:
    analysis = build_path_analysis(_diamond(), "top", "base")
    assert path_payload(analysis) == analysis.to_dict()


def test_render_mentions_chain_and_swap_hint() -> None:
    connected = render_path(build_path_analysis(_diamond(), "top", "base"))
    assert "Shortest chain" in connected
    assert "top` -> `mid1` -> `base" in connected

    missing = render_path(build_path_analysis(_diamond(), "base", "top"))
    assert "No dependency path" in missing
    assert "swap" in missing


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #
_BLUEPRINT = """# path-cli

::: definition {#base}
title: Base
isabelle: Demo.base
status: stub
:::
Base.
:::

::: lemma {#mid}
title: Mid
isabelle: Demo.mid
uses:
  - base
status: stub
:::
Mid.
:::

::: theorem {#top}
title: Top
isabelle: Demo.top
uses:
  - mid
status: stub
:::
Top.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "path-cli"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def test_cli_path_json_conforms_to_schema(tmp_path: Path, capsys) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    _write_project(tmp_path)

    rc = cli_main(["path", "top", "base", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["connected"] is True
    assert data["shortest_path"] == ["top", "mid", "base"]

    schema_dir = Path(__file__).resolve().parents[1] / "isabelle_blueprint" / "schemas"
    schema = json.loads((schema_dir / "path.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)


def test_cli_path_text_output(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["path", "top", "base", str(tmp_path)])
    assert rc == 0
    assert "Shortest chain" in capsys.readouterr().out


def test_cli_require_exits_six_when_absent(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    # base does not depend on top, so --require must fail.
    rc = cli_main(["path", "base", "top", str(tmp_path), "--require"])
    assert rc == 6
    capsys.readouterr()


def test_cli_require_exits_zero_when_present(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["path", "top", "base", str(tmp_path), "--require"])
    assert rc == 0
    capsys.readouterr()


def test_cli_unknown_node_errors(tmp_path: Path) -> None:
    _write_project(tmp_path)
    rc = cli_main(["path", "top", "ghost", str(tmp_path)])
    assert rc == 1


def test_path_schema_is_registered() -> None:
    from isabelle_blueprint.schemas import available_schemas

    assert "path" in available_schemas()


def test_schema_command_prints_path_schema(capsys) -> None:
    rc = cli_main(["schema", "path"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "IsabelleBlueprint dependency path"
