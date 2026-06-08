from __future__ import annotations

import json
from pathlib import Path

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
