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


def test_gate_min_grade_below_threshold_fails(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--min-grade", "A"])

    assert rc == 5
    out = capsys.readouterr().out
    assert "gate FAIL" in out
    assert "[FAIL] min_grade" in out
    assert "threshold A" in out


def test_gate_min_grade_json_check_present(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--json", "--min-grade", "A"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    names = {check["name"] for check in data["checks"]}
    assert "min_grade" in names
    assert "min_grade" in data["failed"]
    check = next(c for c in data["checks"] if c["name"] == "min_grade")
    assert check["ok"] is False
    assert "detail" in check


def test_gate_min_grade_met_passes(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _PROVED)

    rc = cli_main(["gate", str(tmp_path), "--min-grade", "F"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "gate PASS" in out
    assert "[ok] min_grade" in out


def test_gate_min_grade_invalid_choice_rejected(tmp_path: Path) -> None:
    _write_project(tmp_path, _CLEAN)

    import pytest

    with pytest.raises(SystemExit):
        cli_main(["gate", str(tmp_path), "--min-grade", "Z"])


def test_gate_without_min_grade_unchanged(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    names = {check["name"] for check in data["checks"]}
    assert names == {"lint"}


def test_gate_min_grade_ungradeable_project_fails(tmp_path: Path, capsys) -> None:
    # A project with no nodes has an undefined scorecard grade; the gate must
    # fail the min_grade check (unlike scorecard --min-grade, which passes).
    _write_project(tmp_path, "# gate-test\n\nNo gradeable components here.\n")

    rc = cli_main(["gate", str(tmp_path), "--json", "--min-grade", "F"])

    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    check = next(c for c in data["checks"] if c["name"] == "min_grade")
    assert check["ok"] is False
    assert "undefined" in check["detail"]
    assert "min_grade" in data["failed"]


def test_gate_markdown_passing_project(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--markdown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "# Gate: gate-test" in out
    assert "**Overall:** PASS" in out
    assert "| Check | OK | Detail |" in out
    # one row per check; the lint check is always present
    assert "| lint | yes |" in out
    assert "\033[" not in out  # no ANSI colour leaks into Markdown


def test_gate_markdown_failing_gate_exits_5(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN_CYCLE)

    rc = cli_main(["gate", str(tmp_path), "--markdown"])

    assert rc == 5
    out = capsys.readouterr().out
    assert "# Gate: gate-test" in out
    assert "**Overall:** FAIL" in out
    assert "| lint | no |" in out


def test_gate_markdown_and_json_are_mutually_exclusive(tmp_path: Path) -> None:
    _write_project(tmp_path, _CLEAN)

    import pytest

    with pytest.raises(SystemExit):
        cli_main(["gate", str(tmp_path), "--markdown", "--json"])


def teardown_function() -> None:
    # A --color always test below forces colour on; reset so it never leaks.
    from isabelle_blueprint import console

    console.set_enabled(False)


def test_gate_verdict_is_coloured_when_enabled(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _BROKEN_CYCLE)

    rc = cli_main(["gate", str(tmp_path), "--color", "always"])

    assert rc == 5
    out = capsys.readouterr().out
    assert "\033[" in out  # FAIL verdict / marks painted


def test_gate_verdict_is_plain_without_colour(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _CLEAN)

    rc = cli_main(["gate", str(tmp_path), "--color", "never"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "\033[" not in out
    assert "gate PASS" in out  # plain text unchanged
