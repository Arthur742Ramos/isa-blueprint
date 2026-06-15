from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.tags import (
    TAGS_SCHEMA_VERSION,
    build_tag_gate,
    build_tag_report,
    render_tag_report,
    render_tags_markdown,
)


def _node(
    node_id: str,
    *,
    tags: list[str] | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
        tags=list(tags or []),
    )


def _project(*nodes: BlueprintNode, name: str = "tg") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _stat(report, tag: str):
    return next(stat for stat in report.tags if stat.tag == tag)


def test_multi_tag_nodes_counted_under_each_tag() -> None:
    project = _project(
        _node("a", tags=["core", "alg"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.MISSING),
        _node("c"),
    )

    report = build_tag_report(project)

    assert report.total_nodes == 3
    assert report.untagged_count == 1
    assert _stat(report, "core").node_count == 2
    assert _stat(report, "alg").node_count == 1


def test_per_tag_target_and_coverage_counts() -> None:
    project = _project(
        _node("a", tags=["core"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.FOUND),
        _node("c", tags=["core"], formal=FormalStatus.BROKEN),
        _node("d", tags=["core"], formal=FormalStatus.MISSING),
    )

    core = _stat(build_tag_report(project), "core")

    assert core.node_count == 4
    assert core.formal_target_count == 3  # missing is not a target
    assert core.proved_count == 1
    assert core.found_count == 1
    assert core.problem_count == 1  # broken
    assert core.coverage_percent == 33  # 1 * 100 // 3, truncated


def test_coverage_none_without_targets() -> None:
    project = _project(_node("a", tags=["doc"], formal=FormalStatus.MISSING))

    assert _stat(build_tag_report(project), "doc").coverage_percent is None


def test_tags_sorted_by_usage_then_alpha() -> None:
    project = _project(
        _node("a", tags=["beta"]),
        _node("b", tags=["beta"]),
        _node("c", tags=["alpha"]),
        _node("d", tags=["gamma"]),
    )

    report = build_tag_report(project)
    ordered = [stat.tag for stat in report.tags]

    # 'beta' has 2 nodes, so it leads; the two single-node tags tie and sort
    # alphabetically.
    assert ordered == ["beta", "alpha", "gamma"]


def test_duplicate_tag_on_one_node_not_double_counted() -> None:
    project = _project(_node("a", tags=["core", "core"]))

    report = build_tag_report(project)

    assert _stat(report, "core").node_count == 1
    assert len(report.tags) == 1


def test_to_dict_shape() -> None:
    project = _project(_node("a", tags=["core"], formal=FormalStatus.PROVED))

    data = build_tag_report(project).to_dict()

    assert data["schema_version"] == TAGS_SCHEMA_VERSION
    assert data["project"] == "tg"
    assert data["total_nodes"] == 1
    assert data["tag_count"] == 1
    assert data["tags"][0]["tag"] == "core"


def test_render_table_and_empty() -> None:
    text = render_tag_report(build_tag_report(_project(_node("a", tags=["core"]))))
    assert "| Tag |" in text
    assert "core" in text

    empty = render_tag_report(build_tag_report(_project(_node("a"))))
    assert "no tagged nodes" in empty


def _write_project(tmp_path: Path, body: str, *, name: str = "tag-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# tag-test

::: definition {#a}
title: A
isabelle: Demo.a
status: stub
tags: core, alg

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status: stub
uses: a
tags: core

Depends on a.

Sketch.
:::

::: lemma {#c}
title: C
isabelle: Demo.c
status: stub

Untagged.

Sketch.
:::
"""


def test_cli_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "tag-test tags" in out
    assert "core" in out
    assert "1 untagged" in out


def test_cli_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "tag-test"
    assert data["schema_version"] == TAGS_SCHEMA_VERSION
    assert data["total_nodes"] == 3
    assert data["untagged_count"] == 1
    tags = {stat["tag"]: stat for stat in data["tags"]}
    assert tags["core"]["node_count"] == 2
    assert tags["alg"]["node_count"] == 1


def test_filter_restricts_to_named_tags() -> None:
    project = _project(
        _node("a", tags=["core", "alg"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.MISSING),
        _node("c", tags=["doc"]),
        _node("d"),
    )

    report = build_tag_report(project, only=["core"])

    assert [stat.tag for stat in report.tags] == ["core"]
    assert _stat(report, "core").node_count == 2
    # Project-wide structure is unaffected by the filter.
    assert report.total_nodes == 4
    assert report.untagged_count == 1


def test_filter_unknown_tag_yields_empty_row() -> None:
    project = _project(_node("a", tags=["core"], formal=FormalStatus.PROVED))

    report = build_tag_report(project, only=["nope"])

    assert [stat.tag for stat in report.tags] == ["nope"]
    nope = _stat(report, "nope")
    assert nope.node_count == 0
    assert nope.formal_target_count == 0
    assert nope.coverage_percent is None


def test_filter_none_matches_unfiltered() -> None:
    project = _project(
        _node("a", tags=["core"], formal=FormalStatus.PROVED),
        _node("b", tags=["alg"]),
    )

    assert build_tag_report(project, only=None).to_dict() == (
        build_tag_report(project).to_dict()
    )


def test_filter_dedupes_repeated_tag_request() -> None:
    project = _project(_node("a", tags=["core"]))

    report = build_tag_report(project, only=["core", "core"])

    assert [stat.tag for stat in report.tags] == ["core"]


def test_cli_tag_filter_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--json", "--tag", "core"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # Same keys, just a filtered tag list.
    assert data["total_nodes"] == 3
    assert data["untagged_count"] == 1
    assert data["tag_count"] == 1
    assert [stat["tag"] for stat in data["tags"]] == ["core"]
    assert data["tags"][0]["node_count"] == 2


def test_cli_tag_filter_repeatable_and_unknown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(
        ["tags", str(tmp_path), "--json", "--tag", "alg", "--tag", "ghost"]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    tags = {stat["tag"]: stat for stat in data["tags"]}
    assert set(tags) == {"alg", "ghost"}
    assert tags["alg"]["node_count"] == 1
    assert tags["ghost"]["node_count"] == 0
    assert tags["ghost"]["coverage_percent"] is None


def test_cli_tag_filter_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--tag", "core"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "core" in out
    assert "alg" not in out
    # Untagged count stays project-wide.
    assert "1 untagged" in out


_GATE_BODY = """# gate-test

::: definition {#a}
title: A
isabelle: Demo.a
status:
  formal: proved
tags: core, alg

Proved.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Demo.b
status:
  formal: found
tags: core

Found, not proved.

Sketch.
:::
"""


def test_build_tag_gate_flags_low_coverage_tags() -> None:
    project = _project(
        _node("a", tags=["core", "alg"], formal=FormalStatus.PROVED),
        _node("b", tags=["core"], formal=FormalStatus.FOUND),
    )
    report = build_tag_report(project)

    # core is 50% (1 of 2 proved); alg is 100%.
    gate = build_tag_gate(report, 80)

    assert gate.fail_under == 80
    assert gate.failing_tags == ("core",)
    assert gate.ok is False
    assert gate.to_dict() == {
        "fail_under": 80,
        "failing_tags": ["core"],
        "ok": False,
    }


def test_build_tag_gate_ignores_targetless_tags() -> None:
    project = _project(_node("a", tags=["doc"], formal=FormalStatus.MISSING))
    report = build_tag_report(project)

    # 'doc' has no formal targets (coverage None), so it never fails the gate.
    gate = build_tag_gate(report, 100)

    assert gate.failing_tags == ()
    assert gate.ok is True


def test_cli_fail_under_exits_5(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _GATE_BODY)

    rc = cli_main(["tags", str(tmp_path), "--fail-under", "80"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "fail-under 80% policy triggered" in captured.err
    assert "core" in captured.err
    # Table still printed to stdout.
    assert "tag-test tags" in captured.out


def test_cli_fail_under_json_gate_object(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _GATE_BODY)

    rc = cli_main(["tags", str(tmp_path), "--json", "--fail-under", "80"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    # Existing keys are untouched; gate is additive.
    assert data["schema_version"] == TAGS_SCHEMA_VERSION
    assert data["gate"] == {
        "fail_under": 80,
        "failing_tags": ["core"],
        "ok": False,
    }


def test_cli_fail_under_passes_when_all_meet_threshold(
    tmp_path: Path, capsys
) -> None:
    _write_project(tmp_path, _GATE_BODY)

    rc = cli_main(["tags", str(tmp_path), "--json", "--fail-under", "50"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["gate"]["ok"] is True
    assert data["gate"]["failing_tags"] == []


def test_cli_fail_under_respects_tag_filter(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _GATE_BODY)

    # alg is 100%; restricting to it means the otherwise-failing core is ignored.
    rc = cli_main(
        ["tags", str(tmp_path), "--json", "--tag", "alg", "--fail-under", "90"]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["gate"]["ok"] is True
    assert data["gate"]["failing_tags"] == []


def test_cli_absent_fail_under_unchanged(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _GATE_BODY)

    rc = cli_main(["tags", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "gate" not in data


def test_render_tags_markdown_escapes_pipe() -> None:
    project = _project(
        _node("a", tags=["a|b"], formal=FormalStatus.PROVED),
    )
    report = build_tag_report(project)

    out = render_tags_markdown(report)

    assert "Proved-coverage%" in out
    assert r"a\|b" in out
    assert "| a|b |" not in out


def test_cli_markdown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "# tag-test tags" in out
    assert (
        "| Tag | Nodes | Formal targets | Proved | Found | Problems | "
        "Proved-coverage% |"
    ) in out
    # core carries two nodes; the row must be present.
    assert "| core | 2 |" in out
    assert "Untagged nodes: 1" in out


def test_cli_markdown_composes_with_tag_filter(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["tags", str(tmp_path), "--markdown", "--tag", "core"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "| core | 2 |" in out
    assert "| alg |" not in out


def test_cli_markdown_fail_under_gate_exits_5(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _GATE_BODY)

    rc = cli_main(["tags", str(tmp_path), "--markdown", "--fail-under", "80"])

    assert rc == 5
    captured = capsys.readouterr()
    assert "Proved-coverage%" in captured.out
    assert "fail-under 80% policy triggered" in captured.err


def test_cli_markdown_and_json_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path, _BODY)

    try:
        cli_main(["tags", str(tmp_path), "--markdown", "--json"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse should reject the combination
        raise AssertionError("expected --markdown/--json to be mutually exclusive")
