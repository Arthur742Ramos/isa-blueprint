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


def test_lint_clean_project_has_no_duplicate_title(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["lint", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in data["findings"]}
    assert "duplicate-title" not in codes


def test_lint_flags_duplicate_titles(tmp_path: Path, capsys) -> None:
    body = """# dup

::: lemma {#a}
title: Same Title
isabelle: Demo.a
status: stub

A statement.

Sketch.
:::

::: theorem {#b}
title:   same title
isabelle: Demo.b
status: stub
uses: a

Another statement.

Because a holds.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["lint", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    dup = [f for f in data["findings"] if f["code"] == "duplicate-title"]
    assert {f["node_id"] for f in dup} == {"a", "b"}
    assert all(f["severity"] == "warning" for f in dup)
    assert any("'b'" in f["message"] for f in dup if f["node_id"] == "a")
    assert any("'a'" in f["message"] for f in dup if f["node_id"] == "b")


def test_lint_markdown_renders_findings_table(tmp_path: Path, capsys) -> None:
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

    rc = cli_main(["lint", str(tmp_path), "--format", "markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# lint-test lint")
    assert "| Code | Severity | Node | Message |" in out
    assert "| --- | --- | --- | --- |" in out
    assert "| missing-dependency | error | a |" in out


def test_lint_markdown_strict_trips_exit(tmp_path: Path, capsys) -> None:
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

    rc = cli_main(["lint", str(tmp_path), "--format", "markdown", "--strict"])

    assert rc == 2
    out = capsys.readouterr().out
    assert "| Code | Severity | Node | Message |" in out


_SELF_DEP = """# self-dep

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub
uses: a

A statement.

Sketch.
:::
"""


def test_lint_flags_self_dependency(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _SELF_DEP)

    rc = cli_main(["lint", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    findings = [f for f in data["findings"] if f["code"] == "self-dependency"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "error"
    assert finding["node_id"] == "a"
    assert "'a'" in finding["message"]


def test_lint_self_dependency_trips_strict(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _SELF_DEP)

    rc = cli_main(["lint", str(tmp_path), "--strict", "--json"])

    assert rc == 2
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert any(f["code"] == "self-dependency" for f in data["findings"])


def test_lint_clean_project_has_no_self_dependency(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["lint", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in data["findings"]}
    assert "self-dependency" not in codes


