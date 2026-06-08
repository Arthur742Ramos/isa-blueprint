from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main

_BODY = """# blame-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.

Proof sketch.
:::

::: theorem {#b}
title: B
isabelle: Demo.b
status: stub
uses: a

Depends on a.

Because a holds.
:::
"""


def _write_project(tmp_path: Path, *, name: str = "blame-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_BODY, encoding="utf-8")


def test_blame_without_git_or_memory(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "a  (A)" in out
    assert "(no commit history)" in out
    assert "(no recorded attempts)" in out


def test_blame_json_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in data["nodes"]] == ["a", "b"]
    first = data["nodes"][0]
    assert set(first) == {"id", "title", "source", "git", "memory"}
    assert first["git"] is None
    assert first["memory"] is None


def test_blame_single_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--node-id", "b", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in data["nodes"]] == ["b"]


def test_blame_unknown_node_errors(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--node-id", "nope"])

    assert rc == 1
    assert "unknown node id" in capsys.readouterr().err


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def test_blame_reads_git_history(tmp_path: Path, capsys) -> None:
    if shutil_which_git() is None:
        pytest.skip("git not available")
    _write_project(tmp_path)
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@example.test"], tmp_path)
    _git(["config", "user.name", "Tester"], tmp_path)
    _git(["add", "."], tmp_path)
    _git(["commit", "-m", "add blueprint"], tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    git_info = data["nodes"][0]["git"]
    assert git_info is not None
    assert git_info["author"] == "Tester"
    assert git_info["subject"] == "add blueprint"
    assert git_info["commit"]


def shutil_which_git() -> str | None:
    import shutil

    return shutil.which("git")
