from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

# `status: stub` (legacy single-string) re-renders to the full three-axis block,
# so this source is guaranteed to be non-canonical.
_NONCANONICAL = """# fmt-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.
:::
"""


def _write(tmp_path: Path, body: str = _NONCANONICAL, name: str = "blueprint.md") -> Path:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "fmt-test"\n', encoding="utf-8"
    )
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_fmt_rewrites_noncanonical_and_is_idempotent(tmp_path: Path, capsys) -> None:
    path = _write(tmp_path)

    rc = cli_main(["fmt", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()
    formatted = path.read_text(encoding="utf-8")
    assert "blueprint: stub" in formatted  # full three-axis block now present

    # Running again makes no further change.
    rc = cli_main(["fmt", str(tmp_path)])
    assert rc == 0
    assert path.read_text(encoding="utf-8") == formatted


def test_fmt_check_reports_drift_without_writing(tmp_path: Path, capsys) -> None:
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")

    rc = cli_main(["fmt", str(tmp_path), "--check"])

    assert rc == 10
    assert path.read_text(encoding="utf-8") == before  # not modified
    assert "needs formatting" in capsys.readouterr().out


def test_fmt_check_passes_on_canonical(tmp_path: Path, capsys) -> None:
    _write(tmp_path)
    assert cli_main(["fmt", str(tmp_path)]) == 0  # canonicalize first
    capsys.readouterr()

    rc = cli_main(["fmt", str(tmp_path), "--check"])

    assert rc == 0
    assert "already canonical" in capsys.readouterr().out


def test_fmt_json_lists_changed_files(tmp_path: Path, capsys) -> None:
    _write(tmp_path)

    rc = cli_main(["fmt", str(tmp_path), "--check", "--json"])

    assert rc == 10
    data = json.loads(capsys.readouterr().out)
    assert data["check_only"] is True
    assert len(data["changed"]) == 1


def test_fmt_skips_latex_sources(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "fmt-tex"\nblueprint = "blueprint.tex"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.tex").write_text(
        "\\begin{lemma}\n\\label{a}\nBody.\n\\end{lemma}\n", encoding="utf-8"
    )

    rc = cli_main(["fmt", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"][0]["skipped"] is True


def test_fmt_diff_prints_unified_diff_without_writing(tmp_path: Path, capsys) -> None:
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")

    rc = cli_main(["fmt", str(tmp_path), "--diff"])

    assert rc == 10
    out = capsys.readouterr().out
    assert "--- " in out and "+++ " in out  # unified diff headers
    assert "@@" in out
    assert "+  blueprint: stub" in out  # the canonicalisation the diff would apply
    assert path.read_text(encoding="utf-8") == before  # nothing written


def test_fmt_diff_canonical_exits_zero(tmp_path: Path, capsys) -> None:
    _write(tmp_path)
    assert cli_main(["fmt", str(tmp_path)]) == 0  # canonicalize first
    capsys.readouterr()

    rc = cli_main(["fmt", str(tmp_path), "--diff"])

    assert rc == 0
    assert "already canonical" in capsys.readouterr().out


def test_fmt_diff_json_includes_diff_field(tmp_path: Path, capsys) -> None:
    _write(tmp_path)

    rc = cli_main(["fmt", str(tmp_path), "--diff", "--json"])

    assert rc == 10
    data = json.loads(capsys.readouterr().out)
    changed = [f for f in data["files"] if f["changed"]]
    assert len(changed) == 1
    assert "blueprint: stub" in changed[0]["diff"]
