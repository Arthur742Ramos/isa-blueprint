from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.isabelle.theory_import import (
    import_theory_file,
    imported_theory_review,
    render_imported_blueprint,
)


def test_import_theory_finds_top_level_declarations(tmp_path: Path):
    thy = tmp_path / "Demo.thy"
    thy.write_text(
        """
theory Demo
imports Main
begin

lemma add_commute_demo[simp]: "a + b = b + a"
  by simp

theorem (in group) inv_inv_demo: "inv (inv x) = x"
  sorry

definition foo where "foo = True"

end
""",
        encoding="utf-8",
    )

    facts = import_theory_file(thy)

    assert [fact.kind for fact in facts] == ["lemma", "theorem", "definition"]
    assert facts[0].qualified_name == "Demo.add_commute_demo"
    assert facts[1].qualified_name == "Demo.inv_inv_demo"


def test_import_theory_reports_exact_line_numbers_across_blank_lines(tmp_path: Path):
    # Each declaration is separated by a blank line. The line number must point
    # at the declaration keyword itself, not drift onto a preceding blank line
    # (which an ^\s* anchor would do, since \s matches newlines in (?m) mode).
    thy = tmp_path / "Demo.thy"
    thy.write_text(
        "theory Demo\n"          # line 1
        "imports Main\n"         # line 2
        "begin\n"                # line 3
        "\n"                     # line 4
        'lemma first: "True"\n'  # line 5
        "  by simp\n"            # line 6
        "\n"                     # line 7
        'lemma second: "True"\n'  # line 8
        "  by simp\n"            # line 9
        "\n"                     # line 10
        "end\n",                 # line 11
        encoding="utf-8",
    )

    facts = import_theory_file(thy)

    by_name = {fact.name: fact.line for fact in facts}
    assert by_name["first"] == 5
    assert by_name["second"] == 8


def test_import_theory_tolerates_non_utf8_bytes(tmp_path: Path):
    # A stray non-UTF-8 byte (e.g. latin-1 content in a comment) must not crash
    # the importer; valid ASCII declarations are still found.
    thy = tmp_path / "Demo.thy"
    thy.write_bytes(
        b"theory Demo imports Main begin\n"
        b'(* compl\xe9ted by caf\xe9 *)\n'  # 0xe9 is invalid UTF-8
        b'lemma real_demo: "True" by simp\n'
        b"end\n"
    )

    facts = import_theory_file(thy)

    assert [fact.name for fact in facts] == ["real_demo"]


def test_import_theory_ignores_nested_comments(tmp_path: Path):
    thy = tmp_path / "Demo.thy"
    thy.write_text(
        """
theory Demo imports Main begin
(* lemma fake: "False" (* theorem also_fake: "False" *) *)
lemma real: "True" by simp
end
""",
        encoding="utf-8",
    )

    facts = import_theory_file(thy)

    assert [fact.name for fact in facts] == ["real"]


def test_render_imported_blueprint_contains_review_banner(tmp_path: Path):
    thy = tmp_path / "Demo.thy"
    thy.write_text(
        "theory Demo imports Main begin\nlemma real: \"True\" by simp\nend\n",
        encoding="utf-8",
    )

    text = render_imported_blueprint(import_theory_file(thy), project_name="Demo import")

    assert "# Demo import" in text
    assert "best-effort import" in text
    assert "isabelle: Demo.real" in text


def test_import_theory_suggests_dependencies_from_earlier_fact_mentions(tmp_path: Path):
    thy = tmp_path / "Demo.thy"
    thy.write_text(
        """
theory Demo imports Main begin
lemma base_fact: "True" by simp
lemma later_fact: "True" using base_fact by simp
end
""",
        encoding="utf-8",
    )

    facts = import_theory_file(thy)
    text = render_imported_blueprint(facts)
    review = imported_theory_review(facts)

    assert facts[1].uses == (facts[0].node_id,)
    assert f"  - {facts[0].node_id}" in text
    assert review["facts"][1]["suggested_uses"] == [facts[0].node_id]
