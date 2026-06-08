from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main


def _write_project(tmp_path: Path, body: str, *, name: str = "gate-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_CLEAN = """# gate-test

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

_PROVED = """# gate-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: proved

A statement.

Proof sketch goes here.
:::
"""

_NOT_FOUND = """# gate-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: not_found

A statement.

Proof sketch goes here.
:::
"""

_BROKEN_CYCLE = """# gate-test

::: lemma {#a}
title: A
status: stub
uses: b

A statement.
:::

::: lemma {#b}
title: B
status: stub
uses: a

B statement.
:::
"""


def test_gate_clean_project_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "gate PASS" in out
    assert "[ok] lint" in out


def test_gate_lint_errors_fail_with_exit_5(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN_CYCLE)

    rc = cli_main(["gate", str(tmp_path)])

    assert rc == 5
    out = capsys.readouterr().out
    assert "gate FAIL" in out
    assert "[FAIL] lint" in out


def test_gate_min_coverage_undefined_fails(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--min-coverage", "50"])

    assert rc == 5
    out = capsys.readouterr().out
    assert "coverage is undefined" in out


def test_gate_min_coverage_met_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _PROVED)

    rc = cli_main(["gate", str(tmp_path), "--min-coverage", "100"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "gate PASS" in out
    assert "[ok] coverage" in out


def test_gate_fail_on_problem_status(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _NOT_FOUND)

    rc = cli_main(["gate", str(tmp_path), "--fail-on", "not_found"])

    assert rc == 5
    out = capsys.readouterr().out
    assert "[FAIL] fail-on" in out
    assert "a" in out


def test_gate_fail_on_problem_alias(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _NOT_FOUND)

    rc = cli_main(["gate", str(tmp_path), "--fail-on", "problem"])

    assert rc == 5


def test_gate_json_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--json", "--min-coverage", "10"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "gate-test"
    assert data["ok"] is False
    names = {check["name"] for check in data["checks"]}
    assert names == {"lint", "coverage"}
    assert "coverage" in data["failed"]
