from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.fact_coverage import (
    FACT_COVERAGE_SCHEMA_VERSION,
    NO_FACT_LABEL,
    build_fact_coverage_report,
    render_fact_coverage_report,
)


def _node(
    node_id: str,
    *,
    fact: str | None = None,
    formal: FormalStatus = FormalStatus.MISSING,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=fact),
        status=NodeStatus(formal=formal),
    )


def _project(*nodes: BlueprintNode, name: str = "fc") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


def _theory(report, theory: str):
    return next(stat for stat in report.theories if stat.theory == theory)


def test_groups_by_theory_with_counts() -> None:
    project = _project(
        _node("a", fact="Alpha.a", formal=FormalStatus.PROVED),
        _node("b", fact="Alpha.b", formal=FormalStatus.FOUND),
        _node("c", fact="Beta.c", formal=FormalStatus.PROVED),
    )

    report = build_fact_coverage_report(project)

    assert report.total_nodes == 3
    assert {s.theory for s in report.theories} == {"Alpha", "Beta"}
    alpha = _theory(report, "Alpha")
    assert alpha.node_count == 2
    assert alpha.proved == 1
    assert alpha.found == 1
    assert alpha.coverage_percent == 50  # 1 of 2 targets proved
    beta = _theory(report, "Beta")
    assert beta.node_count == 1
    assert beta.proved == 1
    assert beta.coverage_percent == 100


def test_nodes_without_facts_grouped_under_no_fact() -> None:
    project = _project(
        _node("a", fact="Alpha.a", formal=FormalStatus.PROVED),
        _node("b"),  # no fact
        _node("c"),  # no fact
    )

    report = build_fact_coverage_report(project)

    no_fact = _theory(report, NO_FACT_LABEL)
    assert no_fact.node_count == 2
    # No formal targets (both missing) -> coverage undefined.
    assert no_fact.coverage_percent is None


def test_problem_status_counted() -> None:
    project = _project(
        _node("a", fact="Alpha.a", formal=FormalStatus.BROKEN),
        _node("b", fact="Alpha.b", formal=FormalStatus.PROVED),
    )

    alpha = _theory(build_fact_coverage_report(project), "Alpha")

    assert alpha.problem == 1
    assert alpha.coverage_percent == 50  # 1 of 2 targets proved


def test_theories_sorted_by_usage_then_alpha() -> None:
    project = _project(
        _node("a", fact="Beta.a"),
        _node("b", fact="Beta.b"),
        _node("c", fact="Alpha.c"),
        _node("d", fact="Gamma.d"),
    )

    report = build_fact_coverage_report(project)

    assert [s.theory for s in report.theories] == ["Beta", "Alpha", "Gamma"]


def test_to_dict_shape() -> None:
    project = _project(_node("a", fact="Alpha.a", formal=FormalStatus.PROVED))

    data = build_fact_coverage_report(project).to_dict()

    assert data["schema_version"] == FACT_COVERAGE_SCHEMA_VERSION
    assert data["project"] == "fc"
    assert data["total_nodes"] == 1
    assert data["theory_count"] == 1
    assert data["theories"][0]["theory"] == "Alpha"


def test_render_table_and_empty() -> None:
    text = render_fact_coverage_report(
        build_fact_coverage_report(_project(_node("a", fact="Alpha.a")))
    )
    assert "| Theory |" in text
    assert "Alpha" in text

    empty = render_fact_coverage_report(build_fact_coverage_report(_project()))
    assert "no nodes" in empty


_BODY = """# fc-test

::: definition {#a}
title: A
isabelle: Alpha.a
status:
  formal: proved

A base.

Sketch.
:::

::: lemma {#b}
title: B
isabelle: Alpha.b
status:
  formal: found
uses: a

Depends on a.

Sketch.
:::

::: lemma {#c}
title: C
isabelle: Beta.c
status:
  formal: proved

In Beta.

Sketch.
:::

::: lemma {#d}
title: D
status: stub

No fact.

Sketch.
:::
"""


def _write_project(tmp_path: Path, body: str, *, name: str = "fc-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


def test_cli_text_two_theories_and_no_fact(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["fact-coverage", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "fc-test fact coverage" in out
    assert "Alpha" in out
    assert "Beta" in out
    assert NO_FACT_LABEL in out


def test_cli_json_two_theories_and_no_fact(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BODY)

    rc = cli_main(["fact-coverage", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "fc-test"
    assert data["schema_version"] == FACT_COVERAGE_SCHEMA_VERSION
    assert data["total_nodes"] == 4
    by_theory = {s["theory"]: s for s in data["theories"]}
    assert by_theory["Alpha"]["node_count"] == 2
    assert by_theory["Alpha"]["proved"] == 1
    assert by_theory["Alpha"]["found"] == 1
    assert by_theory["Alpha"]["coverage_percent"] == 50
    assert by_theory["Beta"]["node_count"] == 1
    assert by_theory["Beta"]["coverage_percent"] == 100
    # Node d carries no Isabelle fact.
    assert by_theory[NO_FACT_LABEL]["node_count"] == 1
    assert by_theory[NO_FACT_LABEL]["coverage_percent"] is None
