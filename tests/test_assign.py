from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.agents.assignments import (
    AssignmentStore,
    load_assignments,
    set_assignment,
    write_assignments,
)
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.errors import BlueprintError

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


def test_assign_json_has_count_and_owners_map(tmp_path: Path, capsys) -> None:
    # The list view JSON exposes a stable node_id -> owner map plus a count,
    # alongside the existing per-node assignment records.
    _write_project(tmp_path)
    cli_main(["assign", "a", "--project-dir", str(tmp_path), "--owner", "alice"])
    capsys.readouterr()

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 1
    assert data["owners"] == {"a": "alice"}


def test_assign_json_empty_count_and_owners(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 0
    assert data["owners"] == {}


def test_assign_owner_without_node_is_rejected(tmp_path: Path, capsys) -> None:
    # Previously `assign --owner alice` (no node id) silently listed and exited
    # 0, discarding the owner -- a coordination footgun.
    _write_project(tmp_path)

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--owner", "alice"])

    assert rc == 1
    assert "require a node id" in capsys.readouterr().err


def test_assign_note_without_owner_is_rejected(tmp_path: Path, capsys) -> None:
    # A note is only stored alongside an owner; `assign a --note x` with no owner
    # used to fall through to a lookup and silently drop the note.
    _write_project(tmp_path)

    rc = cli_main(["assign", "a", "--project-dir", str(tmp_path), "--note", "solo note"])

    assert rc == 1
    assert "--note requires --owner" in capsys.readouterr().err


def test_assign_clear_with_owner_is_rejected(tmp_path: Path, capsys) -> None:
    # `--clear` runs before the set branch, so combining it with --owner/--note
    # would silently ignore them. Reject the contradictory combination outright.
    _write_project(tmp_path)

    rc = cli_main(
        ["assign", "a", "--project-dir", str(tmp_path), "--clear", "--owner", "alice"]
    )

    assert rc == 1
    assert "--clear cannot be combined with --owner/--note" in capsys.readouterr().err


def test_assign_clear_with_note_is_rejected(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(
        ["assign", "a", "--project-dir", str(tmp_path), "--clear", "--note", "x"]
    )

    assert rc == 1
    assert "--clear cannot be combined with --owner/--note" in capsys.readouterr().err


def test_assign_empty_list(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["assign", "--project-dir", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["assignments"] == []


def test_load_assignments_corrupt_store_warns_and_returns_empty(tmp_path: Path) -> None:
    # Mirrors load_agent_memory: a corrupt store is tolerated in the default
    # (read) path with a warning, so a malformed file does not break read views.
    path = tmp_path / "assignments.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.warns(UserWarning, match="ignoring unreadable assignments"):
        store = load_assignments(path)

    assert store.nodes == {}


def test_load_assignments_corrupt_store_raises_in_strict_mode(tmp_path: Path) -> None:
    # Strict mode is used before a write so we never clobber a corrupt file with
    # an empty store.
    path = tmp_path / "assignments.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(BlueprintError):
        load_assignments(path, strict=True)


def test_write_assignments_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    # write_assignments writes a temp sibling then renames, so a concurrent
    # reader never sees a half-written file. Verify the rename completes (no
    # lingering .tmp) and the store round-trips.
    path = tmp_path / "assignments.json"
    store = AssignmentStore()
    set_assignment(store, "main", "alice", note="lead")

    write_assignments(store, path)

    assert path.exists()
    assert not (tmp_path / "assignments.json.tmp").exists()
    reloaded = load_assignments(path)
    assert reloaded.nodes["main"].owner == "alice"
    # The persisted file is always complete, valid JSON (never a partial write).
    json.loads(path.read_text(encoding="utf-8"))
