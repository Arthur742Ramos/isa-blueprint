from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.cli import main as cli_main


def _write_project(tmp_path: Path, body: str, *, name: str = "prom-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(body, encoding="utf-8")


_TWO_NODES = """# prom-test

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
status: proved
uses: a

Depends on a.

Because a holds.
:::
"""


def test_prometheus_emits_project_gauges(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    rc = cli_main(["prometheus", str(tmp_path), "--no-burndown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "# HELP isabelle_blueprint_nodes_total" in out
    assert "# TYPE isabelle_blueprint_nodes_total gauge" in out
    assert "isabelle_blueprint_nodes_total 2" in out
    assert "isabelle_blueprint_proved_total 1" in out
    # one formal target (b proved), so coverage is defined.
    assert "isabelle_blueprint_coverage_defined 1" in out
    assert "isabelle_blueprint_coverage_ratio" in out
    # no per-node label series should be present.
    assert "{" not in out


def test_prometheus_coverage_undefined(tmp_path: Path, capsys) -> None:
    body = """# prom-test

::: lemma {#a}
title: A
status: stub

Just text.
:::
"""
    _write_project(tmp_path, body)

    rc = cli_main(["prometheus", str(tmp_path), "--no-burndown"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "isabelle_blueprint_coverage_defined 0" in out
    assert "isabelle_blueprint_coverage_ratio" not in out


def test_prometheus_writes_output_file(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)
    out_file = tmp_path / "metrics" / "blueprint.prom"

    rc = cli_main(
        ["prometheus", str(tmp_path), "--no-burndown", "--output", str(out_file)]
    )

    assert rc == 0
    assert out_file.exists()
    text = out_file.read_text(encoding="utf-8")
    assert "isabelle_blueprint_nodes_total 2" in text
