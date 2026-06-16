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
    (bad_dir / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "bad"\n', encoding="utf-8"
    )

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
    body = (
        "::: lemma {#text-only}\n"
        "title: Text only\n\n"
        "Just prose, no formal ref.\n"
        ":::\n"
    )
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


def test_cli_portfolio_fail_on_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    (bad_dir / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "bad"\n', encoding="utf-8"
    )

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
    exit_code = cli_main(
        ["portfolio", str(EXAMPLES_DIR), "--min-coverage", "100"]
    )
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
    exit_code = cli_main(
        ["portfolio", str(EXAMPLES_DIR), "--json", "--min-coverage", "100"]
    )
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
    exit_code = cli_main(
        ["portfolio", str(EXAMPLES_DIR), "--json", "--min-coverage", "0"]
    )
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
    draft_body = (
        "::: lemma {#text-only}\n"
        "title: Text only\n\n"
        "Just prose.\n"
        ":::\n"
    )
    _write_project(tmp_path / "draft", name="draft", body=draft_body)

    report = build_portfolio(tmp_path)

    assert coverage_gate_failures(report, 100) == []
