from __future__ import annotations

from pathlib import Path

import pytest

from isabelle_blueprint.isabelle.source_index import build_index, session_theory_files


def _session(tmp_path: Path) -> list[Path]:
    (tmp_path / "ROOT").write_text(
        "session Demo = HOL +\n  theories\n    A\n    B\n", encoding="utf-8"
    )
    (tmp_path / "A.thy").write_text(
        "theory A\nimports Main\nbegin\n"
        'definition foo :: "nat" where "foo = 0"\n'
        'fun bar :: "nat => nat" where "bar n = n + foo"\n'
        'lemma base: "foo = 0" by (simp add: foo_def)\n'
        "end\n",
        encoding="utf-8",
    )
    (tmp_path / "B.thy").write_text(
        "theory B\nimports A\nbegin\n"
        'lemma uses_base: "bar 0 = 0" using base sorry\n'
        'theorem main_thm: "bar 1 = 1" oops\n'
        "end\n",
        encoding="utf-8",
    )
    return [tmp_path / "A.thy", tmp_path / "B.thy"]


def test_entries_across_kinds(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    by_name = {(e.theory, e.name): e.kind for e in index.entries}
    assert by_name[("A", "foo")] == "definition"
    assert by_name[("A", "bar")] == "fun"
    assert by_name[("A", "base")] == "lemma"
    assert by_name[("B", "uses_base")] == "lemma"
    assert by_name[("B", "main_thm")] == "theorem"


def test_reference_graph_and_callers_callees(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    assert index.reference_graph["A.base"] == {"A.foo"}
    assert index.reference_graph["B.uses_base"] == {"A.bar", "A.base"}
    assert index.callers("base") == ["B.uses_base"]
    assert index.callees("base") == ["A.foo"]


def test_transitive_closure(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    assert set(index.callees("uses_base", transitive=True)) == {"A.foo", "A.bar", "A.base"}


def test_theory_deps_forward_and_reverse(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    assert index.theory_deps("B") == (["A"], [])
    assert index.theory_deps("A") == ([], ["B"])


def test_sorry_and_oops_detection(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    markers = {(m.token, m.entry) for m in index.sorries}
    assert markers == {("sorry", "uses_base"), ("oops", "main_thm")}


def test_sorry_in_cartouche_prose_is_ignored(tmp_path: Path) -> None:
    # `sorry`/`oops` appearing inside text cartouches (prose) must not be
    # reported as proof gaps; only the real proof gap on the lemma counts.
    thy = tmp_path / "M.thy"
    thy.write_text(
        "theory M imports Main begin\n"
        "text \\<open>This note mentions sorry and oops in prose.\\<close>\n"
        'lemma real_gap: "True" sorry\n'
        "end\n",
        encoding="utf-8",
    )
    index = build_index([thy])
    assert [(m.token, m.line) for m in index.sorries] == [("sorry", 3)]


def test_unreferenced_entries(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    # Both B entries are endpoints: nothing in the tree references them.
    assert index.unreferenced_entries() == ["B.uses_base", "B.main_thm"]


def test_imported_facts_are_acyclic_and_ordered(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    facts = index.imported_facts()
    order = {fact.node_id: i for i, fact in enumerate(facts)}
    # every dependency points strictly earlier -> acyclic DAG
    for fact in facts:
        for dep in fact.uses:
            assert order[dep] < order[fact.node_id]
    # A's facts come before B's (topo by import)
    a_facts = [f for f in facts if f.theory == "A"]
    b_facts = [f for f in facts if f.theory == "B"]
    assert max(order[f.node_id] for f in a_facts) < min(order[f.node_id] for f in b_facts)


def test_import_cycle_flagged(tmp_path: Path) -> None:
    (tmp_path / "X.thy").write_text(
        'theory X\nimports Y\nbegin\nlemma lx: "True" by simp\nend\n', encoding="utf-8"
    )
    (tmp_path / "Y.thy").write_text(
        'theory Y\nimports X\nbegin\nlemma ly: "True" by simp\nend\n', encoding="utf-8"
    )
    index = build_index([tmp_path / "X.thy", tmp_path / "Y.thy"])
    assert index.has_import_cycle is True
    # imported_facts must still be acyclic despite the import cycle
    facts = index.imported_facts()
    order = {fact.node_id: i for i, fact in enumerate(facts)}
    for fact in facts:
        for dep in fact.uses:
            assert order[dep] < order[fact.node_id]


def test_external_vs_in_project_imports(tmp_path: Path) -> None:
    index = build_index(_session(tmp_path))
    assert index.in_project_imports["B"] == ["A"]
    assert "Main" in index.external_imports["A"]
    assert "A" not in index.external_imports["B"]


def test_session_theory_files_single_session(tmp_path: Path) -> None:
    files = _session(tmp_path)
    resolved = session_theory_files(tmp_path)
    assert [p.name for p in resolved] == [p.name for p in files]


def test_session_theory_files_multi_session_requires_name(tmp_path: Path) -> None:
    (tmp_path / "ROOT").write_text(
        "session One = HOL +\n  theories\n    A\n\nsession Two = HOL +\n  theories\n    B\n",
        encoding="utf-8",
    )
    (tmp_path / "A.thy").write_text("theory A\nbegin\nend\n", encoding="utf-8")
    (tmp_path / "B.thy").write_text("theory B\nbegin\nend\n", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple sessions"):
        session_theory_files(tmp_path)
    assert [p.name for p in session_theory_files(tmp_path, "Two")] == ["B.thy"]
    with pytest.raises(ValueError, match="not found"):
        session_theory_files(tmp_path, "Nope")


def test_session_theory_files_named_session_no_files_raises(tmp_path: Path) -> None:
    # A named session whose theory files cannot be resolved must raise rather
    # than silently falling back to a directory glob.
    (tmp_path / "ROOT").write_text(
        "session Empty = HOL +\n  theories\n    Ghost\n",
        encoding="utf-8",
    )
    # A stray .thy that a glob fallback would have picked up.
    (tmp_path / "Stray.thy").write_text("theory Stray\nbegin\nend\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no resolvable theory files"):
        session_theory_files(tmp_path, "Empty")
