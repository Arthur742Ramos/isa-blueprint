from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_BLUEPRINT = """# assign-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "assign-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def test_assign_set_and_list(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(
        ["assign", "a", "--project-dir", str(tmp_path), "--owner", "alice", "--note", "owns this"]
    )
    assert rc == 0
    capsys.readouterr()

    store = tmp_path / ".isabelle-blueprint" / "assignments.json"
    assert store.exists()

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    owners = {item["node_id"]: item["owner"] for item in data["assignments"]}
    assert owners["a"] == "alice"


def test_assign_clear(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    cli_main(["assign", "a", "--project-dir", str(tmp_path), "--owner", "bob"])
    capsys.readouterr()

    rc = cli_main(["assign", "a", "--project-dir", str(tmp_path), "--clear", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # After clearing, a single-node lookup reports no owner.
    owners = {item["node_id"]: item["owner"] for item in data["assignments"]}
    assert owners["a"] is None


def test_assign_unknown_node_errors(tmp_path: Path) -> None:
    _write_project(tmp_path)

    rc = cli_main(["assign", "ghost", "--project-dir", str(tmp_path), "--owner", "alice"])

    assert rc == 1


def test_assign_empty_list(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["assignments"] == []
