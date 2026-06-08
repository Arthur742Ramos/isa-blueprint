from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_DANGLING = """# Fix me

::: lemma {#base}
title: Base lemma
status:
  blueprint: written
:::

Base statement.
:::

::: theorem {#main}
title: Main theorem
uses:
  - base
  - ghost
status:
  blueprint: written
:::

Main statement.
:::
"""


def _write_single(tmp_path: Path, body: str, *, name: str = "Fix") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


def test_lint_fix_drops_dangling_dependency(tmp_path: Path, capsys) -> None:
    _write_single(tmp_path, _DANGLING)

    rc = cli_main(["lint", str(tmp_path), "--fix"])

    assert rc == 0
    text = (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert "ghost" not in text
    assert "- base" in text
    err = capsys.readouterr().err
    assert "dropped dangling dependency 'ghost'" in err


def test_lint_fix_dry_run_does_not_write(tmp_path: Path, capsys) -> None:
    _write_single(tmp_path, _DANGLING)
    before = (tmp_path / "blueprint.md").read_text(encoding="utf-8")

    rc = cli_main(["lint", str(tmp_path), "--fix", "--fix-dry-run"])

    assert rc == 0
    after = (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert after == before
    err = capsys.readouterr().err
    assert "would" in err
    assert "ghost" in err


def test_lint_fix_json_includes_fix_block(tmp_path: Path, capsys) -> None:
    _write_single(tmp_path, _DANGLING)

    rc = cli_main(["lint", str(tmp_path), "--fix", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "fix" in data
    assert data["fix"]["removed_count"] == 1
    assert any(r["dependency"] == "ghost" for f in data["fix"]["files"] for r in f["removed"])


def test_lint_fix_refuses_on_cycle(tmp_path: Path, capsys) -> None:
    body = """# Cycle

::: lemma {#a}
title: A
uses:
  - b
status:
  blueprint: written
:::

A.
:::

::: lemma {#b}
title: B
uses:
  - a
  - ghost
status:
  blueprint: written
:::

B.
:::
"""
    _write_single(tmp_path, body)
    before = (tmp_path / "blueprint.md").read_text(encoding="utf-8")

    rc = cli_main(["lint", str(tmp_path), "--fix"])

    assert rc == 2
    after = (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert after == before
    err = capsys.readouterr().err
    assert "refusing to autofix" in err


def test_lint_fix_preserves_cross_file_dependency(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Multi"\nblueprints = ["a.md", "b.md"]\n',
        encoding="utf-8",
    )
    (tmp_path / "a.md").write_text(
        """# A

::: lemma {#alpha}
title: Alpha
status:
  blueprint: written
:::

Alpha.
:::
""",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        """# B

::: theorem {#beta}
title: Beta
uses:
  - alpha
  - ghost
status:
  blueprint: written
:::

Beta.
:::
""",
        encoding="utf-8",
    )

    rc = cli_main(["lint", str(tmp_path), "--fix"])

    assert rc == 0
    b_text = (tmp_path / "b.md").read_text(encoding="utf-8")
    assert "- alpha" in b_text
    assert "ghost" not in b_text


def test_lint_fix_noop_when_clean(tmp_path: Path, capsys) -> None:
    body = """# Clean

::: lemma {#only}
title: Only
status:
  blueprint: written
:::

Only.
:::
"""
    _write_single(tmp_path, body)

    rc = cli_main(["lint", str(tmp_path), "--fix"])

    assert rc == 0
    err = capsys.readouterr().err
    assert "no autofixable findings" in err
