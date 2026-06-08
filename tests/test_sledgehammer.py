from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main

_BP = """# Sledge

::: definition {#base}
title: Base def
isabelle: Demo.base
status:
  blueprint: written
  formal: found
:::

Base.
:::

::: theorem {#main}
title: Main theorem
isabelle: Demo.main_thm
uses:
  - base
status:
  blueprint: written
:::

Main statement.

## Proof

By base.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "Sledge"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BP, encoding="utf-8")


def test_attempt_sledgehammer_appends_block(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["attempt", str(tmp_path), "--node", "main", "--sledgehammer", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    prompt_path = Path(payload["prompt_path"])
    text = prompt_path.read_text(encoding="utf-8")
    assert "## Sledgehammer-first strategy" in text
    # Seeded with the unqualified target fact name and the dependency fact.
    assert "lemma main_thm:" in text
    assert "sledgehammer (add: Demo.base)" in text


def test_attempt_without_sledgehammer_has_no_block(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["attempt", str(tmp_path), "--node", "main", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    text = Path(payload["prompt_path"]).read_text(encoding="utf-8")
    assert "Sledgehammer-first strategy" not in text
