from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main


def _write_project(tmp_path: Path, body: str, *, name: str = "lint-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_CLEAN = """# lint-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.

Proof sketch goes here.
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


def test_lint_clean_project_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["lint", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "lint" in out.lower()


def test_lint_json_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["lint", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "lint-test"
    assert set(data["counts"]) == {"error", "warning", "info", "total"}
    assert isinstance(data["findings"], list)
    assert data["ok"] is True


def test_lint_strict_fails_on_missing_dependency(tmp_path: Path, capsys) -> None:
    body = """# broken

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: ghost

A statement.

Sketch.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["lint", str(tmp_path), "--strict", "--json"])

    assert rc == 2
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    codes = {f["code"] for f in data["findings"]}
    assert "missing-dependency" in codes


def test_lint_without_strict_returns_zero_even_with_errors(tmp_path: Path, capsys) -> None:
    body = """# broken

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: ghost

A statement.

Sketch.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["lint", str(tmp_path)])

    assert rc == 0
    capsys.readouterr()
