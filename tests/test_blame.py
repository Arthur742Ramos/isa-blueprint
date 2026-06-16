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


def test_blame_node_is_an_alias_for_node_id(tmp_path: Path, capsys) -> None:
    # --node matches the single-node flag used by impact/memory/explain/next.
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--node", "b", "--json"])

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


def test_blame_without_node_id_lists_every_node(tmp_path: Path, capsys) -> None:
    # No --node-id -> the default TEXT view shows provenance for ALL nodes.
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "a  (A)" in out
    assert "b  (B)" in out


def test_blame_json_and_table_are_mutually_exclusive(tmp_path: Path) -> None:
    # --json and --table are competing output formats; argparse must reject both.
    _write_project(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli_main(["blame", str(tmp_path), "--json", "--table"])

    assert exc.value.code == 2


def test_blame_table_lists_every_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--table"])

    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    # One header row plus one compact row per node.
    assert lines[0].split() == ["NODE", "SOURCE", "GIT", "AGENT"]
    assert lines[1].startswith("a ")
    assert lines[2].startswith("b ")
    # Compact form: no multi-line detailed labels.
    assert "(no commit history)" not in out


def test_blame_table_single_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--node-id", "b", "--table"])

    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["NODE", "SOURCE", "GIT", "AGENT"]
    assert [line.split()[0] for line in lines[1:]] == ["b"]


def test_blame_markdown_lists_every_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "| Node | Source | Git | Agent memory |"
    assert lines[1] == "| --- | --- | --- | --- |"
    # One data row per node, leading with the node id cell.
    assert lines[2].startswith("| a |")
    assert lines[3].startswith("| b |")
    assert "(no commit history)" in out


def test_blame_markdown_single_node(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["blame", str(tmp_path), "--node-id", "b", "--markdown"])

    assert rc == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "| Node | Source | Git | Agent memory |"
    assert [line.split("|")[1].strip() for line in lines[2:]] == ["b"]


def test_blame_markdown_and_json_are_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli_main(["blame", str(tmp_path), "--markdown", "--json"])

    assert exc.value.code == 2


def test_blame_markdown_and_table_are_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli_main(["blame", str(tmp_path), "--markdown", "--table"])

    assert exc.value.code == 2
