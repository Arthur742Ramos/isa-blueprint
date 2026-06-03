from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_BLUEPRINT = """# rename-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

Uses a.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "rename-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


def test_rename_dry_run_does_not_write(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    before = (tmp_path / "blueprint.md").read_text(encoding="utf-8")

    rc = cli_main(
        ["rename", "a", "a2", "--project-dir", str(tmp_path), "--dry-run", "--json"]
    )

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["old_id"] == "a"
    assert data["new_id"] == "a2"
    assert (tmp_path / "blueprint.md").read_text(encoding="utf-8") == before


def test_rename_rewrites_sources_and_uses(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["rename", "a", "a2", "--project-dir", str(tmp_path)])

    assert rc == 0
    capsys.readouterr()
    text = (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert "{#a2}" in text
    assert "{#a}" not in text
    assert "uses: a2" in text


def test_rename_missing_old_id_errors(tmp_path: Path) -> None:
    _write_project(tmp_path)

    rc = cli_main(["rename", "ghost", "x", "--project-dir", str(tmp_path)])

    assert rc == 1


def test_rename_to_existing_id_errors(tmp_path: Path) -> None:
    _write_project(tmp_path)

    rc = cli_main(["rename", "a", "b", "--project-dir", str(tmp_path)])

    assert rc == 1


def test_rename_reparse_keeps_project_valid(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["rename", "a", "alpha", "--project-dir", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()

    # The renamed project should still load and lint cleanly.
    rc = cli_main(["lint", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in data["findings"]}
    assert "missing-dependency" not in codes
