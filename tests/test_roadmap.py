from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.roadmap import build_roadmap, render_roadmap, write_roadmap


def _node(
    node_id: str,
    formal: FormalStatus,
    *,
    uses: list[str] | None = None,
    kind: NodeKind = NodeKind.LEMMA,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.replace("-", " ").title(),
        uses=uses or [],
        isabelle=IsabelleRef(fact=f"Demo.{node_id.replace('-', '_')}"),
        status=NodeStatus(formal=formal),
    )


def test_roadmap_groups_stages_and_suggests_path() -> None:
    project = BlueprintProject.from_nodes(
        "roadmap-test",
        [
            _node("root", FormalStatus.PROVED),
            _node("ready-lemma", FormalStatus.NAMED, uses=["root"]),
            _node("ready-theorem", FormalStatus.NAMED, uses=["root"], kind=NodeKind.THEOREM),
            _node("blocked-main", FormalStatus.NAMED, uses=["ready-theorem"]),
            _node("problem-node", FormalStatus.NOT_FOUND, uses=["root"]),
            _node("stale-node", FormalStatus.STALE, uses=["root"]),
        ],
    )

    roadmap = build_roadmap(project, generate_tasks(project))
    data = roadmap.to_dict()

    assert data["schema_version"] == 1
    assert data["summary"]["complete_count"] == 1  # type: ignore[index]
    assert data["summary"]["ready_count"] == 2  # type: ignore[index]
    assert data["summary"]["blocked_count"] == 1  # type: ignore[index]
    assert data["summary"]["problem_count"] == 1  # type: ignore[index]
    assert data["summary"]["stale_count"] == 1  # type: ignore[index]
    assert data["suggested_next_task"] == "task-ready-theorem"
    assert data["suggested_path"] == ["ready-theorem", "blocked-main"]

    blocked = _item(data, "blocked-main")
    assert blocked["blocked_by"][0]["id"] == "ready-theorem"
    assert blocked["blocked_by"][0]["status"] == "ready"
    assert "Suggested path: `ready-theorem` -> `blocked-main`" in render_roadmap(roadmap)


def test_roadmap_surfaces_cycles_as_problem_nodes() -> None:
    project = BlueprintProject.from_nodes(
        "cycle-test",
        [
            _node("a", FormalStatus.NAMED, uses=["b"]),
            _node("b", FormalStatus.NAMED, uses=["a"]),
        ],
    )

    roadmap = build_roadmap(project, generate_tasks(project))
    data = roadmap.to_dict()

    assert data["cycles"] == [["a", "b", "a"]]
    assert _item(data, "a")["status"] == "problem"
    assert _item(data, "b")["status"] == "problem"
    assert "Cycles" in render_roadmap(roadmap)


def test_write_roadmap_outputs_json_and_markdown(tmp_path: Path) -> None:
    project = BlueprintProject.from_nodes(
        "write-test",
        [_node("a", FormalStatus.PROVED), _node("b", FormalStatus.NAMED, uses=["a"])],
    )
    roadmap = build_roadmap(project, generate_tasks(project))

    paths = write_roadmap(roadmap, tmp_path)

    assert json.loads(paths["json"].read_text(encoding="utf-8"))["project"] == "write-test"
    assert paths["md"].read_text(encoding="utf-8").startswith("# write-test roadmap")


def test_cli_roadmap_json_output(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "CLI roadmap"
    assert data["summary"]["ready_count"] == 1
    assert data["suggested_next_task"] == "task-b"
    assert data["suggested_path"] == ["b", "c"]


def test_cli_roadmap_write_outputs_artifacts(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--write"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "roadmap json ->" in out
    assert (tmp_path / "build" / "roadmap.json").exists()
    assert (tmp_path / "build" / "roadmap.md").exists()


def _write_roadmap_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "CLI roadmap"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# CLI roadmap

::: lemma {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
uses:
  - a
status:
  formal: named

B.
:::

::: lemma {#c}
title: C
isabelle: Demo.c
uses:
  - b
status:
  formal: named

C.
:::
""",
        encoding="utf-8",
    )


def _item(data: dict[str, object], node_id: str) -> dict[str, object]:
    for stage in data["stages"]:  # type: ignore[index]
        for item in stage["items"]:
            if item["node_id"] == node_id:
                return item
    raise AssertionError(f"missing roadmap item {node_id!r}")
