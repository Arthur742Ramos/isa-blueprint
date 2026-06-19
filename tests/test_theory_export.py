from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from isabelle_blueprint.isabelle.theory_export import (
    generate_theory_scaffold,
    sanitize_theory_name,
)
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind
from isabelle_blueprint.model.project import BlueprintProject


def _node(
    node_id: str,
    kind: NodeKind,
    *,
    title: str = "",
    statement: str = "",
    goal: str | None = None,
    uses: list[str] | None = None,
    fact: str | None = None,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=kind,
        title=title or node_id,
        statement=statement,
        goal=goal,
        uses=uses or [],
        isabelle=IsabelleRef(fact=fact),
    )


def _project(name: str, nodes: list[BlueprintNode]) -> BlueprintProject:
    return BlueprintProject(name=name, nodes=nodes)


def test_theory_header_imports_begin_end():
    project = _project("My Project", [])
    out = generate_theory_scaffold(project)
    assert out.startswith("theory My_Project\n  imports Main\nbegin\n")
    assert out.rstrip().endswith("end")


def test_goal_bearing_node_yields_lemma_sorry():
    project = _project(
        "P",
        [_node("add-zero", NodeKind.LEMMA, goal="x + 0 = (x::nat)", fact="Demo.add_zero")],
    )
    out = generate_theory_scaffold(project)
    assert 'lemma add_zero: "x + 0 = (x::nat)"' in out
    assert "\n  sorry\n" in out


def test_lemma_name_falls_back_to_sanitized_id_without_fact():
    project = _project("P", [_node("foo-bar", NodeKind.LEMMA, goal="True")])
    out = generate_theory_scaffold(project)
    assert 'lemma foo_bar: "True"' in out


def test_goalless_node_yields_todo_comment():
    project = _project(
        "P", [_node("def-x", NodeKind.DEFINITION, title="A definition", statement="x is x")]
    )
    out = generate_theory_scaffold(project)
    assert "(* TODO: formalize definition def-x: A definition *)" in out
    assert "lemma" not in out


def test_statement_and_uses_rendered_as_comments():
    project = _project(
        "P",
        [
            _node("dep", NodeKind.LEMMA, goal="True", fact="Demo.dep_fact"),
            _node(
                "main",
                NodeKind.THEOREM,
                title="Main",
                statement="line one\nline two",
                goal="False",
                uses=["dep"],
            ),
        ],
    )
    out = generate_theory_scaffold(project)
    assert "(*   line one *)" in out
    assert "(*   line two *)" in out
    # uses references the dependency by its Isabelle fact name.
    assert "(*   uses: Demo.dep_fact *)" in out


def test_topological_order_dep_precedes_dependent():
    project = _project(
        "P",
        [
            _node("top", NodeKind.THEOREM, goal="True", uses=["bottom"]),
            _node("bottom", NodeKind.LEMMA, goal="True"),
        ],
    )
    out = generate_theory_scaffold(project)
    assert out.index("[bottom]") < out.index("[top]")


def test_theory_name_sanitization():
    assert sanitize_theory_name("my-project 1") == "my_project_1"
    assert sanitize_theory_name("123go") == "T_123go"
    assert sanitize_theory_name("") == "Blueprint"
    assert sanitize_theory_name("Good_Name'") == "Good_Name'"


def test_theory_name_override():
    project = _project("Ignored", [])
    out = generate_theory_scaffold(project, theory_name="Chosen-Name")
    assert out.startswith("theory Chosen_Name\n")


def test_goal_with_symbol_and_quote_is_escaped_well_formed():
    # \<forall> must survive (no backslash doubling); an inner double-quote is escaped.
    goal = '\\<forall>x. x = x \\<and> y = "z"'
    project = _project("P", [_node("q", NodeKind.LEMMA, goal=goal)])
    out = generate_theory_scaffold(project)
    lemma_line = next(line for line in out.splitlines() if line.startswith("lemma q:"))
    # Symbol token kept with a single backslash.
    assert r"\<forall>" in lemma_line
    assert r"\\<forall>" not in lemma_line
    # The embedded double-quote is backslash-escaped so it cannot terminate early.
    assert r'\"' in lemma_line
    # Exactly one opening and one closing unescaped quote delimit the proposition.
    assert lemma_line.startswith('lemma q: "')
    assert lemma_line.endswith('"')


def test_output_writes_file(tmp_path: Path):
    from isabelle_blueprint import cli

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "blueprint.md").write_text(
        "::: lemma {#add-zero}\n"
        "title: Add zero\n"
        "isabelle: Demo.add_zero\n"
        "goal: x + 0 = (x::nat)\n"
        "status: stub\n"
        "\n"
        "x plus zero is x.\n"
        ":::\n",
        encoding="utf-8",
    )
    out_file = tmp_path / "Scaffold.thy"
    rc = cli.main(["export-theory", str(project_dir), "--output", str(out_file)])
    assert rc == 0
    text = out_file.read_text(encoding="utf-8")
    assert 'lemma add_zero: "x + 0 = (x::nat)"' in text
    assert text.startswith("theory ")


def test_stdout_default(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    from isabelle_blueprint import cli

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "blueprint.md").write_text(
        "::: lemma {#add-zero}\n"
        "title: Add zero\n"
        "goal: x + 0 = (x::nat)\n"
        "status: stub\n"
        "\n"
        "x plus zero is x.\n"
        ":::\n",
        encoding="utf-8",
    )
    rc = cli.main(["export-theory", str(project_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("theory ")
    assert 'lemma add_zero: "x + 0 = (x::nat)"' in captured.out


@pytest.mark.skipif(shutil.which("isabelle") is None, reason="isabelle not on PATH")
def test_generated_theory_builds_in_real_isabelle(tmp_path: Path):
    project = _project(
        "Real_Build_Demo",
        [
            _node("add-zero", NodeKind.LEMMA, goal="x + 0 = (x::nat)", fact="Demo.add_zero"),
            _node(
                "mul-one",
                NodeKind.THEOREM,
                goal="x * 1 = (x::nat)",
                uses=["add-zero"],
                fact="Demo.mul_one",
            ),
        ],
    )
    theory_name = "Real_Build_Demo"
    thy_text = generate_theory_scaffold(project, theory_name=theory_name)
    assert 'lemma add_zero: "x + 0 = (x::nat)"' in thy_text

    session_dir = tmp_path / "build"
    session_dir.mkdir()
    (session_dir / f"{theory_name}.thy").write_text(thy_text, encoding="utf-8")
    (session_dir / "ROOT").write_text(
        f'session "Demo_Build" = "HOL" +\n'
        f"  theories\n"
        f"    {theory_name}\n",
        encoding="utf-8",
    )
    # `sorry` only builds under quick_and_dirty.
    result = subprocess.run(
        ["isabelle", "build", "-o", "quick_and_dirty", "-D", str(session_dir)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
