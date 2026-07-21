"""End-to-end, black-box tests for the packaged command-line tool.

Unlike the rest of the suite (which calls ``cli.main`` in-process), these tests
drive the *packaged* entry point as a subprocess::

    python -m isabelle_blueprint ...

so they exercise the real argument parser, the ``__main__`` module, process
exit codes, and on-disk artifacts exactly as a user or CI job would. They also
validate that the JSON emitted by the published commands conforms to the JSON
Schemas shipped inside the wheel -- turning the "stable contracts" promise in
the README into an enforced, end-to-end guarantee.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.resources import files as resource_files
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)

PKG_ROOT = Path(__file__).resolve().parents[1]

# A canonical, single-node blueprint used to force "node removed" regressions.
MINIMAL_BLUEPRINT = """\
# Shrunk blueprint

::: definition {#def-keep}
title: Keep me
isabelle: Demo.keep
status: written

Only one node survives here.
:::
"""


def run(
    *args: str,
    cwd: Path | None = None,
    expect_code: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m isabelle_blueprint <args>`` as a subprocess.

    Output is decoded as UTF-8 and colour is disabled so assertions are stable
    across platforms. When ``expect_code`` is given the exit status is asserted
    with a helpful failure message.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "isabelle_blueprint", *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if expect_code is not None:
        assert proc.returncode == expect_code, (
            f"`isabelle-blueprint {' '.join(args)}` exited {proc.returncode}, "
            f"expected {expect_code}.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def load_schema(name: str) -> dict:
    # Read from the *installed* package (the wheel under test in CI), not the
    # source checkout, so a wheel that failed to ship a schema is caught here
    # rather than silently passing against the working tree.
    text = (resource_files("isabelle_blueprint") / "schemas" / f"{name}.schema.json").read_text(
        encoding="utf-8"
    )
    return json.loads(text)


def assert_conforms(instance: object, schema_name: str) -> None:
    """Validate ``instance`` against the packaged ``<schema_name>.schema.json``."""
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "schema {} violations:\n{}".format(
        schema_name,
        "\n".join(f"  at {list(e.path)}: {e.message}" for e in errors[:6]),
    )


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def stdout_json(proc: subprocess.CompletedProcess[str]) -> object:
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def agent_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Scaffold an ``agent-ready`` project once and add a node for richer graphs."""
    root = tmp_path_factory.mktemp("e2e_agent")
    run("init", "demo", "--template", "agent-ready", cwd=root, expect_code=0)
    project = root / "demo"
    run("new", "theorem", "extra-result", "--append", cwd=project, expect_code=0)
    return project


@pytest.fixture
def fresh_project(tmp_path: Path) -> Path:
    """Scaffold an isolated ``minimal`` project for mutation/regression tests."""
    run("init", "iso", "--template", "minimal", cwd=tmp_path, expect_code=0)
    return tmp_path / "iso"


# --------------------------------------------------------------------------- #
# Packaging / entry points
# --------------------------------------------------------------------------- #
def test_module_entry_point_reports_version() -> None:
    """`python -m isabelle_blueprint --version` runs through ``__main__``."""
    expected = _declared_version()
    proc = run("--version", expect_code=0)
    assert expected in proc.stdout


def test_console_scripts_are_declared() -> None:
    import tomllib

    data = tomllib.loads((PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["isabelle-blueprint"] == "isabelle_blueprint.cli:main"
    assert scripts["isabelle-blueprint-mcp"] == "isabelle_blueprint.mcp_server:main"


def _declared_version() -> str:
    import tomllib

    data = tomllib.loads((PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# --------------------------------------------------------------------------- #
# Scaffolding
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "template",
    ["minimal", "agent-ready", "afp", "course-notes", "research-paper"],
)
def test_init_every_template_scaffolds_a_usable_project(tmp_path: Path, template: str) -> None:
    run("init", "proj", "--template", template, cwd=tmp_path, expect_code=0)
    project = tmp_path / "proj"
    assert (project / "isabelle-blueprint.toml").exists()
    blueprint = (project / "blueprint.md").exists() or (project / "blueprint.tex").exists()
    assert blueprint, "scaffold did not emit a blueprint source"
    # A freshly scaffolded project must validate and report without Isabelle.
    run("status", ".", cwd=project, expect_code=0)
    run("report", ".", cwd=project, expect_code=0)
    assert_conforms(read_json(project / "build" / "summary.json"), "summary")


def test_init_latex_lifecycle(tmp_path: Path) -> None:
    run(
        "init", "tex", "--template", "agent-ready", "--format", "latex", cwd=tmp_path, expect_code=0
    )
    project = tmp_path / "tex"
    tex = project / "blueprint.tex"
    assert tex.exists(), "latex scaffold should emit blueprint.tex"
    before = tex.read_text(encoding="utf-8")
    run("new", "theorem", "tex-main", "--append", cwd=project, expect_code=0)
    after = tex.read_text(encoding="utf-8")
    assert len(after) > len(before), "new --append should grow the LaTeX source"
    run("report", ".", cwd=project, expect_code=0)
    status = stdout_json(run("status", ".", "--json", cwd=project, expect_code=0))
    assert_conforms(status, "status")


# --------------------------------------------------------------------------- #
# Reporting / JSON contracts
# --------------------------------------------------------------------------- #
def test_report_writes_all_artifacts(agent_project: Path) -> None:
    run("report", ".", cwd=agent_project, expect_code=0)
    build = agent_project / "build"
    for artifact in ("project.json", "summary.json", "report.md", "badge.json", "badge.svg"):
        assert (build / artifact).exists(), f"report did not write {artifact}"
    assert_conforms(read_json(build / "summary.json"), "summary")
    assert_conforms(read_json(build / "project.json"), "project")


def test_status_json_conforms_and_agrees_with_report(agent_project: Path) -> None:
    run("report", ".", cwd=agent_project, expect_code=0)
    status = stdout_json(run("status", ".", "--json", cwd=agent_project, expect_code=0))
    assert_conforms(status, "status")
    summary = read_json(agent_project / "build" / "summary.json")
    assert status["metrics"]["node_count"] == summary["node_count"]


def test_roadmap_json_and_written_artifacts_conform(agent_project: Path) -> None:
    roadmap = stdout_json(run("roadmap", ".", "--json", cwd=agent_project, expect_code=0))
    assert_conforms(roadmap, "roadmap")
    run("roadmap", ".", "--write", cwd=agent_project, expect_code=0)
    written = agent_project / "build" / "roadmap.json"
    assert written.exists()
    assert_conforms(read_json(written), "roadmap")


def test_tasks_artifacts_conform(agent_project: Path) -> None:
    run("tasks", ".", cwd=agent_project, expect_code=0)
    tasks_json = agent_project / "build" / "tasks.json"
    assert tasks_json.exists()
    payload = read_json(tasks_json)
    assert_conforms(payload, "tasks")
    assert isinstance(payload["tasks"], list)


def test_agent_context_json_conforms(agent_project: Path) -> None:
    context = stdout_json(run("agent-context", ".", "--json", cwd=agent_project, expect_code=0))
    assert_conforms(context, "agent-context")


def test_graph_all_formats_emit_and_conform(agent_project: Path) -> None:
    run("graph", ".", "--format", "all", cwd=agent_project, expect_code=0)
    build = agent_project / "build"
    graph = read_json(build / "graph.json")
    assert_conforms(graph, "graph")
    assert (build / "graph.dot").exists()
    assert (build / "graph.mmd").exists() or (build / "graph.mermaid").exists()
    # When Graphviz is installed (the CI e2e job installs it), `--format all`
    # must actually render SVG -- assert it so a silent rendering regression is
    # caught. Stays portable: skipped where `dot` is unavailable.
    import shutil

    if shutil.which("dot"):
        svg = build / "graph.svg"
        assert svg.exists(), "graph --format all should write graph.svg when Graphviz is installed"
        assert "<svg" in svg.read_text(encoding="utf-8").lower(), "graph.svg is not real SVG output"


def test_gate_passes_clean_project(agent_project: Path) -> None:
    proc = run("gate", ".", "--json", cwd=agent_project, expect_code=0)
    gate = stdout_json(proc)
    assert gate["ok"] is True
    assert isinstance(gate["checks"], (list, dict))


def test_cross_command_node_counts_are_consistent(agent_project: Path) -> None:
    """status / summary / graph / project must all report the same node count."""
    run("report", ".", cwd=agent_project, expect_code=0)
    run("graph", ".", "--format", "json", cwd=agent_project, expect_code=0)
    status = stdout_json(run("status", ".", "--json", cwd=agent_project, expect_code=0))
    build = agent_project / "build"
    summary = read_json(build / "summary.json")
    graph = read_json(build / "graph.json")
    project = read_json(build / "project.json")

    counts = {
        "status": status["metrics"]["node_count"],
        "summary": summary["node_count"],
        "graph": len(graph["nodes"]),
        "project": len(project["nodes"]),
    }
    assert len(set(counts.values())) == 1, f"node-count disagreement: {counts}"
    assert counts["status"] >= 3, "agent_project should have >=3 nodes after --append"


# --------------------------------------------------------------------------- #
# fmt round-trip
# --------------------------------------------------------------------------- #
def test_fmt_is_idempotent(fresh_project: Path) -> None:
    run("fmt", ".", cwd=fresh_project, expect_code=0)
    # Re-formatting an already-canonical blueprint reports no drift.
    run("fmt", ".", "--check", cwd=fresh_project, expect_code=0)


# --------------------------------------------------------------------------- #
# diff regression detection
# --------------------------------------------------------------------------- #
def test_diff_flags_removed_node_as_regression(fresh_project: Path) -> None:
    run("report", ".", cwd=fresh_project, expect_code=0)
    baseline = fresh_project / "baseline.json"
    baseline.write_bytes((fresh_project / "build" / "project.json").read_bytes())

    # Shrink the blueprint so the baseline has nodes the current project lacks.
    (fresh_project / "blueprint.md").write_text(MINIMAL_BLUEPRINT, encoding="utf-8")

    diff = stdout_json(run("diff", str(baseline), ".", "--json", cwd=fresh_project, expect_code=0))
    assert diff["has_regression"] is True
    assert diff["regression_count"] >= 1
    assert diff["removed"], "removed nodes should be listed"

    # The same diff under --fail-on-regression must exit 5.
    run("diff", str(baseline), ".", "--fail-on-regression", cwd=fresh_project, expect_code=5)


def test_diff_against_self_has_no_regression(fresh_project: Path) -> None:
    run("report", ".", cwd=fresh_project, expect_code=0)
    baseline = fresh_project / "baseline.json"
    baseline.write_bytes((fresh_project / "build" / "project.json").read_bytes())
    diff = stdout_json(run("diff", str(baseline), ".", "--json", cwd=fresh_project, expect_code=0))
    assert diff["has_regression"] is False
    assert diff["regression_count"] == 0


# --------------------------------------------------------------------------- #
# Shell completion
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
def test_completion_scripts_render(shell: str) -> None:
    proc = run("completion", shell, expect_code=0)
    assert proc.stdout.strip(), f"{shell} completion produced no output"


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
def test_schema_command_exports_valid_schemas(tmp_path: Path) -> None:
    out = tmp_path / "schemas"
    run("schema", "--out", str(out), expect_code=0)
    exported = sorted(out.glob("*.schema.json"))
    assert exported, "schema --out wrote nothing"
    for path in exported:
        # Every exported schema must itself be a valid draft 2020-12 schema.
        Draft202012Validator.check_schema(read_json(path))


def test_single_schema_prints_to_stdout() -> None:
    proc = run("schema", "status", expect_code=0)
    payload = json.loads(proc.stdout)
    assert payload["title"]
    Draft202012Validator.check_schema(payload)


def test_packaged_schemas_are_valid_metaschemas() -> None:
    schemas_dir = resource_files("isabelle_blueprint") / "schemas"
    files = sorted(
        (p for p in schemas_dir.iterdir() if p.name.endswith(".schema.json")),
        key=lambda p: p.name,
    )
    assert files, "no packaged schemas found in the installed package"
    for path in files:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
def test_report_on_missing_project_fails_cleanly(tmp_path: Path) -> None:
    proc = run("report", str(tmp_path / "nope"), expect_code=1)
    assert "not found" in (proc.stdout + proc.stderr).lower()


def test_malformed_blueprint_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "bad"
    project.mkdir()
    (project / "isabelle-blueprint.toml").write_text('blueprint = "blueprint.md"', encoding="utf-8")
    (project / "blueprint.md").write_text("::: lemma {#x}\nbroken: [unclosed\n", encoding="utf-8")
    proc = run("check", ".", cwd=project, expect_code=1)
    assert proc.stdout or proc.stderr


def test_unknown_command_is_rejected() -> None:
    proc = run("definitely-not-a-command")
    assert proc.returncode != 0
