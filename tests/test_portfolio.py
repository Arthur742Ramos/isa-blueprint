from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.report.portfolio import (
    PORTFOLIO_SCHEMA_VERSION,
    build_portfolio,
    coverage_gate_failures,
    discover_project_roots,
    portfolio_payload,
    render_portfolio_csv,
    render_portfolio_markdown,
    render_portfolio_report,
    sort_portfolio_report,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _node_md(node_id: str, *, formal: str = "named", uses: list[str] | None = None) -> str:
    uses_block = ""
    if uses:
        dep_lines = "\n".join(f"  - {dep}" for dep in uses)
        uses_block = f"uses:\n{dep_lines}\n"
    return (
        f"::: lemma {{#{node_id}}}\n"
        f"title: {node_id.upper()}\n"
        f"isabelle: Demo.{node_id}\n"
        f"{uses_block}"
        f"status:\n  formal: {formal}\n\n"
        f"Statement {node_id}.\n"
        ":::\n"
    )


def _write_project(project_dir: Path, *, name: str, body: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n', encoding="utf-8"
    )
    (project_dir / "blueprint.md").write_text(f"# {name}\n\n{body}", encoding="utf-8")


def _nodes(*node_md: str) -> str:
    return "\n".join(node_md)


def test_discover_project_roots_prunes_nested_and_skip_dirs(tmp_path: Path) -> None:
    _write_project(tmp_path, name="root", body=_node_md("r"))
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a"))
    # Nested project under alpha must NOT be descended into.
    _write_project(tmp_path / "alpha" / "inner", name="inner", body=_node_md("i"))
    # A project sitting inside a skip dir must be ignored entirely.
    _write_project(tmp_path / "build" / "ghost", name="ghost", body=_node_md("g"))

    roots = discover_project_roots(tmp_path)
    relatives = [
        "." if root == tmp_path.resolve() else root.relative_to(tmp_path.resolve()).as_posix()
        for root in roots
    ]

    assert relatives == [".", "alpha"]


def test_build_portfolio_aggregates_coverage_and_health(tmp_path: Path) -> None:
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a", formal="proved"), _node_md("b", formal="proved")),
    )
    _write_project(
        tmp_path / "beta",
        name="beta",
        body=_nodes(_node_md("c", formal="proved"), _node_md("d", formal="named")),
    )

    report = build_portfolio(tmp_path)

    assert report.schema_version == PORTFOLIO_SCHEMA_VERSION
    totals = report.totals
    assert totals.project_count == 2
    assert totals.loaded_count == 2
    assert totals.error_count == 0
    assert totals.formal_target_count == 4
    assert totals.proved_count == 3
    assert totals.coverage_percent == 75
    assert totals.projects_complete == 1

    by_id = {project.id: project for project in report.projects}
    assert by_id["alpha"].coverage_percent == 100
    assert by_id["alpha"].health == "complete"
    assert by_id["beta"].coverage_percent == 50


def test_build_portfolio_records_unparseable_project_as_error(tmp_path: Path) -> None:
    _write_project(tmp_path / "ok", name="ok", body=_node_md("a", formal="proved"))
    # A config marker with no blueprint.md is discovered but fails to load.
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "isabelle-blueprint.toml").write_text('[project]\nname = "bad"\n', encoding="utf-8")

    report = build_portfolio(tmp_path)
    by_id = {project.id: project for project in report.projects}

    assert report.totals.project_count == 2
    assert report.totals.loaded_count == 1
    assert report.totals.error_count == 1
    assert by_id["ok"].error is None
    assert by_id["bad"].error is not None
    # Errored projects do not contaminate the aggregate counts.
    assert report.totals.proved_count == 1


def test_build_portfolio_coverage_none_without_targets(tmp_path: Path) -> None:
    # A node with no Isabelle ref is not a formal target, so coverage is undefined.
    body = "::: lemma {#text-only}\ntitle: Text only\n\nJust prose, no formal ref.\n:::\n"
    _write_project(tmp_path / "draft", name="draft", body=body)

    report = build_portfolio(tmp_path)
    project = report.projects[0]

    assert project.formal_target_count == 0
    assert project.coverage_percent is None
    assert report.totals.coverage_percent is None


def test_build_portfolio_no_projects(tmp_path: Path) -> None:
    report = build_portfolio(tmp_path)

    assert report.totals.project_count == 0
    assert report.projects == []
    assert "no IsabelleBlueprint projects" in render_portfolio_report(report)


def test_portfolio_payload_is_json_round_trippable(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    payload = portfolio_payload(build_portfolio(tmp_path))
    restored = json.loads(json.dumps(payload))

    assert restored["schema_version"] == PORTFOLIO_SCHEMA_VERSION
    assert restored["totals"]["loaded_count"] == 1
    assert restored["projects"][0]["id"] == "alpha"


def test_cli_portfolio_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    exit_code = cli_main(["portfolio", str(tmp_path), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["totals"]["proved_count"] == 1
    assert payload["projects"][0]["health"] == "complete"


def test_cli_portfolio_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    exit_code = cli_main(["portfolio", str(tmp_path)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Portfolio:" in out
    assert "alpha" in out


def test_cli_portfolio_fail_on_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_project(tmp_path / "broken", name="broken", body=_node_md("a", formal="broken"))

    exit_code = cli_main(["portfolio", str(tmp_path), "--fail-on-problem"])
    capsys.readouterr()

    assert exit_code == 5


def test_build_portfolio_records_malformed_toml_as_error(tmp_path: Path) -> None:
    _write_project(tmp_path / "ok", name="ok", body=_node_md("a", formal="proved"))
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    # Invalid TOML must surface as an error entry, not abort the roll-up.
    (bad_dir / "isabelle-blueprint.toml").write_text("this = = broken", encoding="utf-8")
    (bad_dir / "blueprint.md").write_text("# bad\n", encoding="utf-8")

    report = build_portfolio(tmp_path)
    by_id = {project.id: project for project in report.projects}

    assert report.totals.error_count == 1
    assert report.totals.loaded_count == 1
    assert by_id["bad"].error is not None


def test_build_portfolio_all_errored_keeps_counts_zero(tmp_path: Path) -> None:
    for name in ("one", "two"):
        project_dir = tmp_path / name
        project_dir.mkdir(parents=True, exist_ok=True)
        # Config marker present (discovered) but no blueprint.md (load fails).
        (project_dir / "isabelle-blueprint.toml").write_text(
            f'[project]\nname = "{name}"\n', encoding="utf-8"
        )

    report = build_portfolio(tmp_path)
    totals = report.totals

    assert totals.project_count == 2
    assert totals.loaded_count == 0
    assert totals.error_count == 2
    assert totals.proved_count == 0
    assert totals.formal_target_count == 0
    assert totals.coverage_percent is None
    assert totals.projects_complete == 0


def test_discover_finds_blueprint_md_only_project(tmp_path: Path) -> None:
    # No TOML config: the blueprint.md marker alone makes it a project.
    solo = tmp_path / "solo"
    solo.mkdir(parents=True, exist_ok=True)
    (solo / "blueprint.md").write_text(
        f"# solo\n\n{_node_md('a', formal='proved')}", encoding="utf-8"
    )

    report = build_portfolio(tmp_path)

    assert [project.id for project in report.projects] == ["solo"]
    assert report.totals.proved_count == 1


def test_cli_portfolio_fail_on_problem_load_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A discovered-but-unloadable project should trip --fail-on-problem too.
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "isabelle-blueprint.toml").write_text('[project]\nname = "bad"\n', encoding="utf-8")

    exit_code = cli_main(["portfolio", str(tmp_path), "--fail-on-problem"])
    capsys.readouterr()

    assert exit_code == 5


def test_cli_portfolio_fail_on_problem_clean_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    exit_code = cli_main(["portfolio", str(tmp_path), "--fail-on-problem"])
    capsys.readouterr()

    assert exit_code == 0


def test_render_portfolio_csv_header_and_rows(tmp_path: Path) -> None:
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a", formal="proved"), _node_md("b", formal="named")),
    )

    text = render_portfolio_csv(build_portfolio(tmp_path))
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0] == [
        "name",
        "path",
        "node_count",
        "coverage_percent",
        "proved_count",
        "problem_count",
        "has_cycles",
        "health",
    ]
    by_name = {row[0]: row for row in rows[1:]}
    assert "alpha" in by_name
    assert by_name["alpha"][1] == "alpha"
    assert by_name["alpha"][4] == "1"


def test_cli_portfolio_csv_examples_tree(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--csv"])
    out = capsys.readouterr().out

    assert exit_code == 0
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == [
        "name",
        "path",
        "node_count",
        "coverage_percent",
        "proved_count",
        "problem_count",
        "has_cycles",
        "health",
    ]
    names = {row[0] for row in rows[1:]}
    # A known example project name appears as a CSV row.
    assert "Infinitude of the primes" in names


def test_cli_portfolio_csv_and_json_mutually_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["portfolio", str(tmp_path), "--csv", "--json"])

    assert excinfo.value.code == 2


def test_render_portfolio_markdown_header_and_rows(tmp_path: Path) -> None:
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a", formal="proved"), _node_md("b", formal="named")),
    )

    text = render_portfolio_markdown(build_portfolio(tmp_path))

    assert text.startswith("## Portfolio")
    assert "**Totals:**" in text
    assert "| Project | Nodes | Coverage | Proved | Problems | Cycles | Health |" in text
    assert "| --- | --- | --- | --- | --- | --- | --- |" in text
    assert "| alpha |" in text


def test_render_portfolio_markdown_escapes_pipe_in_name(tmp_path: Path) -> None:
    _write_project(
        tmp_path / "alpha",
        name="a|b",
        body=_node_md("a", formal="proved"),
    )

    text = render_portfolio_markdown(build_portfolio(tmp_path))

    assert r"a\|b" in text


def test_cli_portfolio_markdown_examples_tree(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--markdown"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "## Portfolio" in out
    assert "| Project | Nodes | Coverage | Proved | Problems | Cycles | Health |" in out
    # A known example project name appears as a Markdown table row.
    assert "| Infinitude of the primes |" in out


def test_cli_portfolio_markdown_and_json_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["portfolio", str(tmp_path), "--markdown", "--json"])

    assert excinfo.value.code == 2


def test_cli_portfolio_markdown_and_csv_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a", formal="proved"))

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["portfolio", str(tmp_path), "--markdown", "--csv"])

    assert excinfo.value.code == 2


def test_cli_portfolio_min_coverage_trips_and_lists_projects(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A high floor over the examples tree fails: several projects sit below 100%.
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--min-coverage", "100"])
    captured = capsys.readouterr()

    assert exit_code == 5
    assert "coverage gate failed" in captured.err
    assert "100%" in captured.err
    # A known sub-100% example project is named (by its relative path) in stderr.
    assert "euclid-primes" in captured.err


def test_cli_portfolio_min_coverage_zero_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--min-coverage", "0"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "coverage gate failed" not in captured.err


def test_cli_portfolio_no_min_coverage_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Absent the flag, a sub-100% portfolio still exits 0 (behaviour unchanged).
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "coverage gate" not in captured.err


def test_cli_portfolio_min_coverage_json_gate_object(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--json", "--min-coverage", "100"])
    out = capsys.readouterr().out

    assert exit_code == 5
    payload = json.loads(out)
    gate = payload["coverage_gate"]
    assert gate["min_coverage"] == 100
    assert gate["ok"] is False
    assert "euclid-primes" in gate["failing_projects"]


def test_cli_portfolio_min_coverage_json_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--json", "--min-coverage", "0"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    assert payload["coverage_gate"] == {
        "min_coverage": 0,
        "failing_projects": [],
        "ok": True,
    }


def test_cli_portfolio_json_no_gate_key_without_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(["portfolio", str(EXAMPLES_DIR), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "coverage_gate" not in json.loads(out)


def test_cli_portfolio_min_coverage_composes_with_fail_on_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Clean (no problems) but sub-threshold coverage still trips the gate.
    _write_project(
        tmp_path / "half",
        name="half",
        body=_nodes(_node_md("a", formal="proved"), _node_md("b", formal="named")),
    )

    exit_code = cli_main(
        [
            "portfolio",
            str(tmp_path),
            "--fail-on-problem",
            "--min-coverage",
            "75",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 5
    assert "half" in captured.err


def test_coverage_gate_failures_ignores_undefined_coverage(tmp_path: Path) -> None:
    _write_project(tmp_path / "full", name="full", body=_node_md("a", formal="proved"))
    # A project with no formal targets has undefined coverage and never fails.
    draft_body = "::: lemma {#text-only}\ntitle: Text only\n\nJust prose.\n:::\n"
    _write_project(tmp_path / "draft", name="draft", body=draft_body)

    report = build_portfolio(tmp_path)

    assert coverage_gate_failures(report, 100) == []


@pytest.mark.parametrize("value", ["150", "-1", "101"])
def test_cli_portfolio_min_coverage_out_of_range_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["portfolio", str(tmp_path), "--min-coverage", value])

    # argparse rejects an invalid --min-coverage as a usage error (exit 2).
    assert excinfo.value.code == 2


def _write_sort_tree(tmp_path: Path) -> None:
    # gamma: highest coverage; beta: middle; alpha: lowest. Discovery order is
    # alpha, beta, gamma (sorted by relative path).
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a1", formal="named"), _node_md("a2", formal="named")),
    )
    _write_project(
        tmp_path / "beta",
        name="beta",
        body=_nodes(_node_md("b1", formal="proved"), _node_md("b2", formal="named")),
    )
    _write_project(
        tmp_path / "gamma",
        name="gamma",
        body=_nodes(_node_md("g1", formal="proved"), _node_md("g2", formal="proved")),
    )


def test_cli_portfolio_sort_coverage_descending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_sort_tree(tmp_path)

    exit_code = cli_main(["portfolio", str(tmp_path), "--json", "--sort", "coverage"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    names = [p["name"] for p in payload["projects"]]
    assert names == ["gamma", "beta", "alpha"]
    coverages = [p["coverage_percent"] for p in payload["projects"]]
    assert coverages == sorted(coverages, reverse=True)


def test_cli_portfolio_sort_name_ascending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(tmp_path / "zeta", name="zeta", body=_node_md("z"))
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a"))
    _write_project(tmp_path / "mu", name="mu", body=_node_md("m"))

    exit_code = cli_main(["portfolio", str(tmp_path), "--json", "--sort", "name"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    names = [p["name"] for p in payload["projects"]]
    assert names == ["alpha", "mu", "zeta"]


def test_cli_portfolio_sort_default_is_byte_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_sort_tree(tmp_path)

    assert cli_main(["portfolio", str(tmp_path), "--json"]) == 0
    baseline = capsys.readouterr().out
    assert cli_main(["portfolio", str(tmp_path), "--json", "--sort", "name"]) == 0
    capsys.readouterr()
    # Re-run without --sort: identical to the original output.
    assert cli_main(["portfolio", str(tmp_path), "--json"]) == 0
    assert capsys.readouterr().out == baseline


def test_cli_portfolio_sort_rejects_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["portfolio", str(tmp_path), "--sort", "bogus"])

    assert excinfo.value.code == 2


def test_cli_portfolio_sort_nodes_descending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # alpha: 2 nodes, beta: 3 nodes, gamma: 1 node. Discovery order is
    # alpha, beta, gamma; --sort nodes must reorder by node count, highest first.
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a1"), _node_md("a2")),
    )
    _write_project(
        tmp_path / "beta",
        name="beta",
        body=_nodes(_node_md("b1"), _node_md("b2"), _node_md("b3")),
    )
    _write_project(tmp_path / "gamma", name="gamma", body=_node_md("g1"))

    assert cli_main(["portfolio", str(tmp_path), "--json", "--sort", "nodes"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in payload["projects"]]
    assert names == ["beta", "alpha", "gamma"]
    counts = [p["node_count"] for p in payload["projects"]]
    assert counts == sorted(counts, reverse=True)


def test_cli_portfolio_sort_problems_descending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # alpha: 0 problems, beta: 2 problems, gamma: 1 problem. Discovery order is
    # alpha, beta, gamma; --sort problems lists the most-troubled project first.
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a1", formal="proved"))
    _write_project(
        tmp_path / "beta",
        name="beta",
        body=_nodes(_node_md("b1", formal="broken"), _node_md("b2", formal="broken")),
    )
    _write_project(tmp_path / "gamma", name="gamma", body=_node_md("g1", formal="broken"))

    assert cli_main(["portfolio", str(tmp_path), "--json", "--sort", "problems"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in payload["projects"]]
    assert names == ["beta", "gamma", "alpha"]
    counts = [p["problem_count"] for p in payload["projects"]]
    assert counts == sorted(counts, reverse=True)


def test_cli_portfolio_sort_undefined_metric_sorts_last(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # An errored project (config marker, no blueprint.md) has a None metric and
    # must sort after every loadable project regardless of the metric chosen.
    _write_project(
        tmp_path / "alpha",
        name="alpha",
        body=_nodes(_node_md("a1", formal="proved"), _node_md("a2", formal="proved")),
    )
    bad_dir = tmp_path / "zbad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "isabelle-blueprint.toml").write_text('[project]\nname = "zbad"\n', encoding="utf-8")

    assert cli_main(["portfolio", str(tmp_path), "--json", "--sort", "coverage"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in payload["projects"]]
    assert names[-1] == "zbad"
    assert payload["projects"][-1]["error"] is not None


def test_sort_portfolio_report_unknown_key_raises_value_error(tmp_path: Path) -> None:
    # Misuse outside the CLI must fail loudly rather than silently mis-ordering.
    _write_project(tmp_path / "alpha", name="alpha", body=_node_md("a1"))
    report = build_portfolio(tmp_path)

    with pytest.raises(ValueError, match="unknown sort key"):
        sort_portfolio_report(report, "bogus")


# --- --details: per-project problem nodes -----------------------------------


def _write_unhealthy_tree(tmp_path: Path) -> None:
    # sick: two actively-wrong nodes (broken + not_found). clean: all proved.
    _write_project(
        tmp_path / "sick",
        name="sick",
        body=_nodes(
            _node_md("p1", formal="broken"),
            _node_md("p2", formal="not_found"),
            _node_md("ok", formal="proved"),
        ),
    )
    _write_project(
        tmp_path / "clean",
        name="clean",
        body=_node_md("c", formal="proved"),
    )


def test_build_portfolio_records_problem_nodes(tmp_path: Path) -> None:
    _write_unhealthy_tree(tmp_path)

    report = build_portfolio(tmp_path)
    by_id = {project.id: project for project in report.projects}

    sick = by_id["sick"]
    assert [n.id for n in sick.problem_nodes] == ["p1", "p2"]
    assert {n.formal_status for n in sick.problem_nodes} == {"broken", "not_found"}
    # A clean project has no problem nodes; ``ok`` (proved) is never listed.
    assert by_id["clean"].problem_nodes == ()


def test_portfolio_payload_details_adds_problem_nodes_array(tmp_path: Path) -> None:
    _write_unhealthy_tree(tmp_path)
    report = build_portfolio(tmp_path)

    plain = portfolio_payload(report)
    assert "problem_nodes" not in plain["projects"][0]

    detailed = portfolio_payload(report, details=True)
    by_id = {p["id"]: p for p in detailed["projects"]}
    assert by_id["sick"]["problem_nodes"] == [
        {"id": "p1", "formal_status": "broken"},
        {"id": "p2", "formal_status": "not_found"},
    ]
    assert by_id["clean"]["problem_nodes"] == []


def test_cli_portfolio_details_json_lists_problem_node_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_unhealthy_tree(tmp_path)

    exit_code = cli_main(["portfolio", str(tmp_path), "--json", "--details"])
    out = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(out)
    by_id = {p["id"]: p for p in payload["projects"]}
    assert [n["id"] for n in by_id["sick"]["problem_nodes"]] == ["p1", "p2"]


def test_cli_portfolio_json_unchanged_without_details(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_unhealthy_tree(tmp_path)

    assert cli_main(["portfolio", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    for project in payload["projects"]:
        assert "problem_nodes" not in project


def test_cli_portfolio_details_text_lists_problem_nodes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_unhealthy_tree(tmp_path)

    exit_code = cli_main(["portfolio", str(tmp_path), "--details"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Problem details:" in out
    assert "p1 (broken)" in out
    assert "p2 (not_found)" in out


def test_cli_portfolio_text_default_unchanged_by_details(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_unhealthy_tree(tmp_path)

    assert cli_main(["portfolio", str(tmp_path)]) == 0
    baseline = capsys.readouterr().out
    assert "Problem details:" not in baseline


def test_cli_portfolio_details_examples_tree_default_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The bundled examples are healthy: --details adds a "(none)" breakdown but
    # leaves the rollup section byte-identical to the default output.
    assert cli_main(["portfolio", str(EXAMPLES_DIR)]) == 0
    baseline = capsys.readouterr().out

    assert cli_main(["portfolio", str(EXAMPLES_DIR), "--details"]) == 0
    detailed = capsys.readouterr().out

    assert detailed.startswith(baseline.rstrip("\n"))
    assert "Problem details:" in detailed
    assert "(none)" in detailed


def test_render_portfolio_csv_details_adds_column_no_cr(tmp_path: Path) -> None:
    _write_unhealthy_tree(tmp_path)
    report = build_portfolio(tmp_path)

    text = render_portfolio_csv(report, details=True)
    rows = list(csv.reader(io.StringIO(text)))

    assert rows[0][-1] == "problem_nodes"
    by_name = {row[0]: row for row in rows[1:]}
    assert "p1 (broken)" in by_name["sick"][-1]
    assert "p2 (not_found)" in by_name["sick"][-1]
    assert by_name["clean"][-1] == ""


def test_render_portfolio_csv_unchanged_without_details(tmp_path: Path) -> None:
    _write_unhealthy_tree(tmp_path)
    report = build_portfolio(tmp_path)

    rows = list(csv.reader(io.StringIO(render_portfolio_csv(report))))
    assert rows[0] == [
        "name",
        "path",
        "node_count",
        "coverage_percent",
        "proved_count",
        "problem_count",
        "has_cycles",
        "health",
    ]


def test_render_portfolio_markdown_details_adds_column(tmp_path: Path) -> None:
    _write_unhealthy_tree(tmp_path)
    report = build_portfolio(tmp_path)

    text = render_portfolio_markdown(report, details=True)

    header = "| Project | Nodes | Coverage | Proved | Problems | Cycles | Health | Problem nodes |"
    assert header in text
    assert "p1 (broken)" in text


def test_cli_portfolio_details_composes_with_fail_on_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_unhealthy_tree(tmp_path)

    exit_code = cli_main(["portfolio", str(tmp_path), "--details", "--fail-on-problem"])
    out = capsys.readouterr().out

    # --fail-on-problem still trips (exit 5) and the breakdown is printed.
    assert exit_code == 5
    assert "p1 (broken)" in out
