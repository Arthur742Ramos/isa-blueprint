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
