from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.config import load_config
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.refactor.rename import rename_node

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


_LATEX_BLUEPRINT = r"""\begin{lemma}
\label{a}
\isabelle{Demo.a}
A statement.
\end{lemma}

\begin{theorem}
\label{b}
\isabelle{Demo.b}
\uses{a}
Uses a.
\end{theorem}
"""


def _write_latex_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "rename-tex"\nblueprint = "blueprint.tex"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.tex").write_text(_LATEX_BLUEPRINT, encoding="utf-8")


def test_rename_rewrites_latex_label_and_uses(tmp_path: Path) -> None:
    _write_latex_project(tmp_path)
    config = load_config(tmp_path)

    result = rename_node(config, "a", "a2")

    text = (tmp_path / "blueprint.tex").read_text(encoding="utf-8")
    assert r"\label{a2}" in text
    assert r"\label{a}" not in text
    assert r"\uses{a2}" in text
    assert result.uses_updated >= 1


def test_rename_rekeys_json_stores(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_config(tmp_path)
    store = config.github_sync_state_path
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps({"schema_version": 1, "nodes": {"a": {"issue_number": 5}}}),
        encoding="utf-8",
    )

    result = rename_node(config, "a", "a2")

    data = json.loads(store.read_text(encoding="utf-8"))
    assert "a2" in data["nodes"]
    assert "a" not in data["nodes"]
    rekey = next(r for r in result.store_rekeys if r.name == "github-sync")
    assert rekey.changed is True


def test_rename_dry_run_does_not_touch_stores(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_config(tmp_path)
    store = config.github_sync_state_path
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps({"schema_version": 1, "nodes": {"a": {"issue_number": 5}}}),
        encoding="utf-8",
    )

    rename_node(config, "a", "a2", dry_run=True)

    data = json.loads(store.read_text(encoding="utf-8"))
    assert "a" in data["nodes"] and "a2" not in data["nodes"]


def test_rename_rejects_whitespace_new_id(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_config(tmp_path)

    try:
        rename_node(config, "a", "a 2")
    except BlueprintError as exc:
        assert "whitespace" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected BlueprintError for whitespace id")


def test_rename_rejects_identical_id(tmp_path: Path) -> None:
    _write_project(tmp_path)
    config = load_config(tmp_path)

    try:
        rename_node(config, "a", "a")
    except BlueprintError as exc:
        assert "identical" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected BlueprintError for identical id")
