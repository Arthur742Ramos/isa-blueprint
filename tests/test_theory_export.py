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


def test_colliding_lemma_names_are_deduped():
    # Two distinct facts whose short names sanitize to the same identifier would
    # otherwise emit `Duplicate fact declaration` and fail the build.
    project = _project(
        "P",
        [
            _node("a", NodeKind.LEMMA, goal="x + 0 = (x::nat)", fact="Demo.add_zero"),
            _node("b", NodeKind.LEMMA, goal="0 + x = (x::nat)", fact="Other.add_zero"),
            _node("c", NodeKind.LEMMA, goal="x = x", fact="Third.add_zero"),
        ],
    )
    out = generate_theory_scaffold(project)
    names = [line.split(":")[0] for line in out.splitlines() if line.startswith("lemma ")]
    assert names == ["lemma add_zero", "lemma add_zero_2", "lemma add_zero_3"]
    assert len(names) == len(set(names))


def test_reserved_keyword_lemma_name_is_escaped():
    # `end`/`lemma` are Isabelle keywords; a bare `lemma end:` is a parse error.
    project = _project(
        "P",
        [
            _node("end", NodeKind.LEMMA, goal="True"),
            _node("lemma", NodeKind.LEMMA, goal="True", fact="Demo.lemma"),
        ],
    )
    out = generate_theory_scaffold(project)
    assert 'lemma end_: "True"' in out
    assert 'lemma lemma_: "True"' in out
    assert "lemma end:" not in out
    assert "lemma lemma:" not in out


def test_digit_leading_lemma_name_is_sanitized():
    # A node id / fact short name starting with a digit is not a valid identifier.
    project = _project("P", [_node("123-thm", NodeKind.LEMMA, goal="True")])
    out = generate_theory_scaffold(project)
    assert "lemma T_123_thm:" in out


def test_output_is_deterministic():
    project = _project(
        "P",
        [
            _node("top", NodeKind.THEOREM, goal="True", uses=["bottom"], fact="D.top"),
            _node("bottom", NodeKind.LEMMA, goal="False", fact="D.bottom"),
        ],
    )
    assert generate_theory_scaffold(project) == generate_theory_scaffold(project)


def test_empty_project_is_buildable_skeleton():
    out = generate_theory_scaffold(_project("Empty", []), theory_name="Empty")
    assert out == "theory Empty\n  imports Main\nbegin\n\nend\n"


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
    assert r"\"" in lemma_line
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
            # Goal carrying an Isabelle symbol token (\<forall>) and nested parens.
            _node(
                "add-zero",
                NodeKind.LEMMA,
                goal="\\<forall>x. x + 0 = (x::nat)",
                fact="Demo.add_zero",
            ),
            # Multi-level dependent; goal with an internal string literal and parens.
            _node(
                "mul-one",
                NodeKind.THEOREM,
                goal="(x * (1::nat)) = x \\<and> (''ab'' :: string) = ''ab''",
                uses=["add-zero", "external-dangling"],
                fact="Demo.mul_one",
            ),
            # Goalless node -> TODO comment, must not break the build.
            _node("a-def", NodeKind.DEFINITION, title="A definition", statement="prose"),
            # Colliding short fact names -> must be deduped, not Duplicate fact.
            _node("dup-a", NodeKind.LEMMA, goal="True", fact="A.same"),
            _node("dup-b", NodeKind.LEMMA, goal="True", fact="B.same"),
            # Reserved-word identifier -> must be escaped, not a parse error.
            _node("end", NodeKind.LEMMA, goal="True"),
        ],
    )
    theory_name = "Real_Build_Demo"
    thy_text = generate_theory_scaffold(project, theory_name=theory_name)
    assert 'lemma add_zero: "\\<forall>x. x + 0 = (x::nat)"' in thy_text
    assert "lemma same:" in thy_text and "lemma same_2:" in thy_text
    assert "lemma end_:" in thy_text

    session_dir = tmp_path / "build"
    session_dir.mkdir()
    (session_dir / f"{theory_name}.thy").write_text(thy_text, encoding="utf-8")
    (session_dir / "ROOT").write_text(
        f'session "Demo_Build" = "HOL" +\n  theories\n    {theory_name}\n',
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
