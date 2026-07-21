from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from isabelle_blueprint.agents.tasks import generate_tasks
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.roadmap import (
    build_roadmap,
    render_roadmap,
    render_roadmap_markdown,
    render_roadmap_mermaid,
    write_roadmap,
)


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


def test_cli_roadmap_mermaid_emits_staged_flowchart(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--mermaid"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("flowchart")
    assert "subgraph stage1" in out
    assert "n_b" in out
    assert "n_b --> n_c" in out
    # `a` is proved (a complete dependency of `b`) so it is absent from `b`'s
    # blocked_by, yet the diagram must still follow the full `uses` graph.
    assert "n_a --> n_b" in out


def test_cli_roadmap_csv_emits_node_rows(capsys) -> None:
    example = Path("examples/euclid-primes")

    rc = cli_main(["roadmap", str(example), "--csv"])

    assert rc == 0
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == [
        "stage",
        "node_id",
        "kind",
        "formal_status",
        "agent_status",
        "blocked_by_count",
    ]
    by_id = {row[1]: row for row in rows[1:]}
    # `prime-pred` has no dependencies, so it lands in the first stage.
    assert by_id["prime-pred"][0] == "1"
    assert by_id["prime-pred"][2] == "definition"


def test_cli_roadmap_csv_respects_status_filter(capsys) -> None:
    example = Path("examples/euclid-primes")

    rc = cli_main(["roadmap", str(example), "--csv", "--status", "complete"])

    assert rc == 0
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    ids = {row[1] for row in rows[1:]}
    # Only proved/found nodes survive the `complete` status filter.
    assert "dvd-factorial" in ids
    assert "infinitude-primes" not in ids


def test_cli_roadmap_csv_rejects_json_combo(tmp_path: Path) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--csv", "--json"])

    assert rc != 0


def test_render_roadmap_markdown_escapes_pipe_in_cells() -> None:
    project = BlueprintProject.from_nodes(
        "md-escape",
        [_node("a|b", FormalStatus.NAMED)],
    )
    roadmap = build_roadmap(project, generate_tasks(project))

    out = render_roadmap_markdown(roadmap)

    assert "# md-escape roadmap" in out
    assert "## Stage 1" in out
    assert r"a\|b" in out
    assert "| id | kind | formal status | agent status | blocker count |" in out


def test_cli_roadmap_markdown_emits_staged_tables(capsys) -> None:
    example = Path("examples/euclid-primes")

    rc = cli_main(["roadmap", str(example), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# ")
    assert "## Stage 1" in out
    assert "| id | kind | formal status | agent status | blocker count |" in out
    # `prime-pred` has no dependencies, so it lands in the first stage.
    assert "| prime-pred | definition |" in out


def test_cli_roadmap_markdown_respects_status_filter(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--markdown", "--status", "ready"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "| b |" in out
    assert "| c |" not in out


def test_cli_roadmap_markdown_rejects_json_combo(tmp_path: Path) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--markdown", "--json"])

    assert rc != 0


def test_cli_roadmap_csv_rejects_mermaid_combo(tmp_path: Path) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--csv", "--mermaid"])

    assert rc != 0


def test_cli_roadmap_mermaid_rejects_json_combo(tmp_path: Path) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--mermaid", "--json"])

    assert rc != 0


def test_cli_roadmap_mermaid_respects_status_filter(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--mermaid", "--status", "ready"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "flowchart" in out
    assert "n_b" in out
    assert "n_c" not in out


def test_roadmap_mermaid_label_leaves_pipe_unescaped() -> None:
    # The roadmap flowchart historically did NOT escape `|` in node-id labels.
    # After routing through the shared mermaid_label helper that escaping must
    # stay disabled so the emitted Mermaid output is byte-identical.
    project = BlueprintProject.from_nodes(
        "pipe-roadmap",
        [
            _node("root", FormalStatus.PROVED),
            _node("a|b", FormalStatus.NAMED, uses=["root"]),
        ],
    )
    roadmap = build_roadmap(project, generate_tasks(project))

    mermaid = render_roadmap_mermaid(roadmap)

    assert "flowchart" in mermaid
    # The raw pipe survives in the label; it is never rewritten to `&#124;`.
    label_line = next(
        line for line in mermaid.splitlines() if line.lstrip().startswith("n_a_124_b[")
    )
    assert '["a|b"]' in label_line
    assert "&#124;" not in mermaid


def test_cli_roadmap_write_outputs_artifacts(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--write"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "roadmap json ->" in out
    assert (tmp_path / "build" / "roadmap.json").exists()
    assert (tmp_path / "build" / "roadmap.md").exists()


def test_cli_roadmap_strict_ignores_ordinary_blocked_work(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--strict"])

    assert rc == 0
    captured = capsys.readouterr()
    assert "roadmap strict:" not in captured.err
    assert "blocked-main" not in captured.out


def test_cli_roadmap_strict_fails_cycles_stale_problem_and_missing_deps(
    tmp_path: Path,
    capsys,
) -> None:
    _write_strict_failure_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--strict", "--json", "--status", "ready"])

    assert rc == 9
    captured = capsys.readouterr()
    assert json.loads(captured.out)["filters"]["status"] == ["ready"]
    assert "[cycles]" in captured.err
    assert "[problem]" in captured.err
    assert "[stale]" in captured.err
    assert "[missing-deps]" in captured.err


def test_cli_roadmap_filters_json_stages_without_changing_summary(
    tmp_path: Path,
    capsys,
) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(
        [
            "roadmap",
            str(tmp_path),
            "--json",
            "--status",
            "ready",
            "--kind",
            "theorem",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["node_count"] == 3
    assert data["filters"] == {"status": ["ready"], "stage": [], "kind": ["theorem"]}
    items = [item for stage in data["stages"] for item in stage["items"]]
    assert [item["node_id"] for item in items] == ["b"]
    assert items[0]["kind"] == "theorem"


def test_cli_roadmap_diff_is_computed_before_filters(tmp_path: Path, capsys) -> None:
    previous = BlueprintProject.from_nodes(
        "diff-test",
        [
            _node("a", FormalStatus.PROVED),
            _node("b", FormalStatus.NAMED, uses=["a"], kind=NodeKind.THEOREM),
            _node("c", FormalStatus.NAMED, uses=["b"]),
        ],
    )
    previous_path = tmp_path / "previous-roadmap.json"
    previous_path.write_text(
        json.dumps(build_roadmap(previous, generate_tasks(previous)).to_dict()),
        encoding="utf-8",
    )
    _write_diff_project(tmp_path)

    rc = cli_main(
        [
            "roadmap",
            str(tmp_path),
            "--json",
            "--since",
            str(previous_path),
            "--status",
            "ready",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [item["node_id"] for item in data["diff"]["newly_complete"]] == ["b"]
    assert [item["node_id"] for item in data["diff"]["newly_ready"]] == ["c"]
    assert [item["node_id"] for stage in data["stages"] for item in stage["items"]] == ["c"]


def test_cli_roadmap_write_ignores_filters_for_canonical_artifacts(
    tmp_path: Path,
    capsys,
) -> None:
    _write_roadmap_project(tmp_path)

    rc = cli_main(["roadmap", str(tmp_path), "--write", "--status", "ready"])

    assert rc == 0
    capsys.readouterr()
    data = json.loads((tmp_path / "build" / "roadmap.json").read_text(encoding="utf-8"))
    assert "filters" not in data
    assert data["summary"]["node_count"] == 3
    items = [item for stage in data["stages"] for item in stage["items"]]
    assert {item["node_id"] for item in items} == {"a", "b", "c"}


def test_cli_roadmap_assignees_text_shows_owner_and_unassigned(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path), "--assignees"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "owner `alice`" in out
    # `a`/`c` have no assignment and are surfaced as unassigned.
    assert "owner `(unassigned)`" in out


def test_cli_roadmap_without_assignees_omits_owner(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "owner" not in out


def test_cli_roadmap_assignees_json_adds_owner_field(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path), "--json", "--assignees"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert _item(data, "b")["owner"] == "alice"
    # Unassigned nodes carry an explicit null owner.
    assert _item(data, "a")["owner"] is None


def test_cli_roadmap_json_without_assignees_omits_owner_key(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "owner" not in _item(data, "b")


def test_cli_roadmap_assignees_json_validates_against_schema(tmp_path: Path, capsys) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    from isabelle_blueprint.schemas import read_schema

    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path), "--json", "--assignees"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    schema = json.loads(read_schema("roadmap"))
    jsonschema.Draft202012Validator(schema).validate(data)


def test_cli_roadmap_assignees_markdown_adds_owner_column(tmp_path: Path, capsys) -> None:
    _write_roadmap_project(tmp_path)
    assert cli_main(["assign", "b", "--project-dir", str(tmp_path), "--owner", "alice"]) == 0
    capsys.readouterr()

    rc = cli_main(["roadmap", str(tmp_path), "--markdown", "--assignees"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "| id | kind | formal status | agent status | blocker count | owner |" in out
    assert "| alice |" in out
    assert "| (unassigned) |" in out


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

::: theorem {#b}
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


def _write_strict_failure_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Strict failures"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# Strict failures

::: lemma {#cycle-a}
title: Cycle A
uses:
  - cycle-b
status:
  formal: named

A.
:::

::: lemma {#cycle-b}
title: Cycle B
uses:
  - cycle-a
status:
  formal: named

B.
:::

::: lemma {#problem}
title: Problem
status:
  formal: not_found

Problem.
:::

::: lemma {#stale}
title: Stale
status:
  formal: stale

Stale.
:::

::: lemma {#missing}
title: Missing
uses:
  - absent
status:
  formal: named

Missing.
:::
""",
        encoding="utf-8",
    )


def _write_diff_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "diff-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# diff-test

::: lemma {#a}
title: A
isabelle: Demo.a
status:
  formal: proved

A.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
uses:
  - a
status:
  formal: proved

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
