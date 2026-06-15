from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.staleness import (
    build_staleness_report,
    render_staleness_markdown,
    render_staleness_report,
    staleness_payload,
)


def _node(
    node_id: str,
    *,
    uses: list[str] | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
    last_checked: str | None = None,
    kind: NodeKind = NodeKind.LEMMA,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=node_id.upper(),
        uses=list(uses or []),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal, last_checked=last_checked),
    )


def _project(*nodes: BlueprintNode, name: str = "stale-test") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def test_clean_chain_is_not_stale() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.PROVED),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    assert report.trusted_count == 2
    assert report.stale_count == 0
    assert report.stale_nodes == []


def test_proved_on_broken_dependency_is_problem() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.BROKEN),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    assert report.stale_count == 1
    assert report.problem_count == 1
    node = report.stale_nodes[0]
    assert node.node_id == "b"
    assert node.severity == "problem"
    assert [(c.dep_id, c.reason) for c in node.causes] == [("a", "problem")]


def test_proved_on_unproven_dependency_is_incomplete() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.NAMED),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    assert report.incomplete_count == 1
    node = report.stale_nodes[0]
    assert node.severity == "incomplete"
    assert node.causes[0].reason == "incomplete"


def test_outdated_when_dependency_checked_later() -> None:
    report = build_staleness_report(
        _project(
            _node(
                "a",
                formal=FormalStatus.PROVED,
                last_checked="2024-02-01T00:00:00",
            ),
            _node(
                "b",
                uses=["a"],
                formal=FormalStatus.PROVED,
                last_checked="2024-01-01T00:00:00",
            ),
        )
    )
    assert report.outdated_count == 1
    node = report.stale_nodes[0]
    assert node.node_id == "b"
    assert node.severity == "outdated"
    assert node.causes[0].reason == "outdated"


def test_not_outdated_when_node_checked_later() -> None:
    report = build_staleness_report(
        _project(
            _node(
                "a",
                formal=FormalStatus.PROVED,
                last_checked="2024-01-01T00:00:00",
            ),
            _node(
                "b",
                uses=["a"],
                formal=FormalStatus.PROVED,
                last_checked="2024-02-01T00:00:00",
            ),
        )
    )
    assert report.stale_count == 0


def test_stale_dependency_has_its_own_reason() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.STALE),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    node = report.stale_nodes[0]
    assert node.severity == "outdated"
    assert node.causes[0].reason == "stale_dep"


def test_missing_dependency_is_detected() -> None:
    report = build_staleness_report(
        _project(
            _node("b", uses=["ghost"], formal=FormalStatus.PROVED),
        )
    )
    assert report.problem_count == 1
    node = report.stale_nodes[0]
    assert node.severity == "problem"
    assert node.causes[0].reason == "missing"
    assert node.causes[0].dep_id == "ghost"


def test_cycle_flags_trusted_nodes() -> None:
    report = build_staleness_report(
        _project(
            _node("a", uses=["b"], formal=FormalStatus.PROVED),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    assert report.has_cycles is True
    assert report.stale_count == 2
    for node in report.stale_nodes:
        assert node.in_cycle is True
        assert any(c.reason == "cycle" for c in node.causes)


def test_transitive_problem_keeps_distance() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.BROKEN),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
            _node("c", uses=["b"], formal=FormalStatus.PROVED),
        )
    )
    by_id = {node.node_id: node for node in report.stale_nodes}
    assert by_id["b"].causes[0].distance == 1
    assert by_id["c"].causes[0].distance == 2


def test_trusted_without_last_checked_counter() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.PROVED),
            _node("b", formal=FormalStatus.PROVED, last_checked="2024-01-01T00:00:00"),
            _node("c", formal=FormalStatus.NAMED),
        )
    )
    assert report.trusted_count == 2
    assert report.trusted_without_last_checked == 1


def test_payload_top_and_max_causes_truncation() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.BROKEN),
            _node("a2", formal=FormalStatus.BROKEN),
            _node("b", uses=["a", "a2"], formal=FormalStatus.PROVED),
            _node("c", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    payload = staleness_payload(report, top=1, max_causes=1)
    assert payload["schema_version"] == 1
    assert len(payload["stale_nodes"]) == 1
    first = payload["stale_nodes"][0]
    # cause_count reports the true total even when causes are truncated.
    assert first["cause_count"] >= 1
    assert len(first["causes"]) == 1


def test_render_reports_clean_state() -> None:
    report = build_staleness_report(_project(_node("a", formal=FormalStatus.PROVED)))
    text = render_staleness_report(report)
    assert "rest on trusted" in text


def _write_project(tmp_path: Path, body: str, *, name: str = "stale-cli") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_BODY = """# stale-cli

::: definition {#a}
title: A
isabelle: Demo.a
status: broken

A base.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
status: proved
uses: a

Rests on a.
:::
"""


def test_cli_staleness_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)
    rc = cli_main(["staleness", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "staleness" in out.lower()
    assert "`b`" in out


def test_cli_staleness_json(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)
    rc = cli_main(["staleness", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "stale-cli"
    assert data["stale_count"] == 1
    assert data["stale_nodes"][0]["node_id"] == "b"


def test_cli_staleness_fail_on_problem(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)
    rc = cli_main(["staleness", str(tmp_path), "--fail-on-problem"])
    assert rc == 5
    err = capsys.readouterr().err
    assert "broken/missing" in err


_INCOMPLETE_BODY = """# stale-cli

::: definition {#a}
title: A
isabelle: Demo.a
status: named

A base, not yet proven.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
status: proved
uses: a

Rests on unproven a.
:::
"""


def test_render_markdown_lists_flagged_node() -> None:
    report = build_staleness_report(
        _project(
            _node("a", formal=FormalStatus.NAMED),
            _node("b", uses=["a"], formal=FormalStatus.PROVED),
        )
    )
    md = render_staleness_markdown(report)
    assert "| Node | Title | Formal | Severity | Causes |" in md
    assert "| `b` |" in md
    assert "incomplete" in md


def test_cli_staleness_markdown(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _INCOMPLETE_BODY)
    rc = cli_main(["staleness", str(tmp_path), "--markdown"])
    assert rc == 0
    out = capsys.readouterr().out
    # Markdown table header is present...
    assert "| Node | Title | Formal | Severity | Causes |" in out
    assert "| --- | --- | --- | --- | --- |" in out
    # ...and the trusted node resting on an unproven dependency is listed.
    b_row = next(line for line in out.splitlines() if line.startswith("| `b` |"))
    assert "incomplete" in b_row
    assert "`a`" in b_row


def test_cli_staleness_markdown_rejects_json(tmp_path: Path) -> None:
    _write_project(tmp_path, _INCOMPLETE_BODY)
    with pytest.raises(SystemExit):
        cli_main(["staleness", str(tmp_path), "--markdown", "--json"])

