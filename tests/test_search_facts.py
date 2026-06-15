from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main

_THY = """theory Demo
imports Main
begin

lemma add_comm: "a + b = b + (a::nat)"
  by simp

lemma add_assoc: "(a + b) + c = a + (b + (c::nat))"
  by simp

definition double :: "nat => nat" where
  "double n = n + n"

theorem mul_comm: "a * b = b * (a::nat)"
  by simp

end
"""


def _write_project(tmp_path: Path, body: str, *, name: str = "sf-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


def _write_theory(tmp_path: Path) -> Path:
    thy = tmp_path / "Demo.thy"
    thy.write_text(_THY, encoding="utf-8")
    return thy


def test_search_facts_free_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# sf-test\n")
    thy = _write_theory(tmp_path)

    rc = cli_main(
        ["search-facts", str(tmp_path), "--theory", str(thy), "--query", "comm", "--json"]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    keys = {hit["key"] for hit in data["hits"]}
    assert "Demo.add_comm" in keys
    assert "Demo.mul_comm" in keys


def test_search_facts_kind_filter(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# sf-test\n")
    thy = _write_theory(tmp_path)

    rc = cli_main(
        [
            "search-facts",
            str(tmp_path),
            "--theory",
            str(thy),
            "--query",
            "double",
            "--kind",
            "definition",
            "--json",
        ]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert all(hit["kind"] == "definition" for hit in data["hits"])
    assert any(hit["key"] == "Demo.double" for hit in data["hits"])


def test_search_facts_matches_unresolved_targets(tmp_path: Path, capsys) -> None:
    body = """# sf-test

::: lemma {#comm}
title: Addition commutes
isabelle: Demo.add_commm
status: not_found

a + b = b + a.

By induction.
:::
"""
    _write_project(tmp_path, body)
    thy = _write_theory(tmp_path)

    rc = cli_main(["search-facts", str(tmp_path), "--theory", str(thy), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["matches"]) == 1
    match = data["matches"][0]
    assert match["node_id"] == "comm"
    assert match["target_fact"] == "Demo.add_commm"
    hit_keys = {hit["key"] for hit in match["hits"]}
    assert "Demo.add_comm" in hit_keys


def test_search_facts_text_output(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# sf-test\n")
    thy = _write_theory(tmp_path)

    rc = cli_main(
        ["search-facts", str(tmp_path), "--theory", str(thy), "--query", "nomatchxyz"]
    )

    assert rc == 0
    assert "no declarations match" in capsys.readouterr().out


def test_search_facts_markdown_free_text(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, "# sf-test\n")
    thy = _write_theory(tmp_path)

    rc = cli_main(
        [
            "search-facts",
            str(tmp_path),
            "--theory",
            str(thy),
            "--query",
            "comm",
            "--markdown",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "# Fact search: comm" in out
    assert "| Fact | Score | Theory |" in out
    assert "`Demo.add_comm`" in out


def test_search_facts_markdown_target_mode(tmp_path: Path, capsys) -> None:
    body = """# sf-test

::: lemma {#comm}
title: Addition commutes
isabelle: Demo.add_commm
status: not_found

a + b = b + a.

By induction.
:::
"""
    _write_project(tmp_path, body)
    thy = _write_theory(tmp_path)

    rc = cli_main(["search-facts", str(tmp_path), "--theory", str(thy), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "# Fact search: unresolved targets" in out
    assert "## `comm` (target `Demo.add_commm`)" in out
    assert "| Fact | Score | Theory |" in out
    assert "`Demo.add_comm`" in out


def test_search_facts_markdown_rejects_json(tmp_path: Path) -> None:
    _write_project(tmp_path, "# sf-test\n")
    thy = _write_theory(tmp_path)

    with pytest.raises(SystemExit):
        cli_main(
            [
                "search-facts",
                str(tmp_path),
                "--theory",
                str(thy),
                "--query",
                "comm",
                "--markdown",
                "--json",
            ]
        )


def test_search_index_rejects_nonpositive_limit() -> None:
    """A negative ``limit`` once fell through to ``hits[:limit]`` and silently
    dropped the lowest-ranked hit; non-positive limits must return nothing."""
    from isabelle_blueprint.isabelle.fact_search import search_index
    from isabelle_blueprint.isabelle.source_index import SourceEntry, SourceIndex

    index = SourceIndex([])
    index.entries = [
        SourceEntry(kind="lemma", name="add_comm", theory="Demo", line=1, path="Demo.thy"),
        SourceEntry(kind="lemma", name="add_assoc", theory="Demo", line=2, path="Demo.thy"),
        SourceEntry(kind="lemma", name="add_zero", theory="Demo", line=3, path="Demo.thy"),
    ]

    assert len(search_index(index, "add", limit=2)) == 2
    assert search_index(index, "add", limit=0) == []
    assert search_index(index, "add", limit=-1) == []
