from __future__ import annotations

from pathlib import Path

import pytest

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


def test_prometheus_static_labels_on_every_metric(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    rc = cli_main(
        [
            "prometheus",
            str(tmp_path),
            "--no-burndown",
            "--label",
            "env=ci",
            "--label",
            "team=hol",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    metric_lines = [
        line
        for line in out.splitlines()
        if line and not line.startswith("#")
    ]
    assert metric_lines
    for line in metric_lines:
        assert '{env="ci",team="hol"}' in line
    # the sample value still follows the closing brace.
    assert 'isabelle_blueprint_nodes_total{env="ci",team="hol"} 2' in out


def test_prometheus_label_value_escaped(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    rc = cli_main(
        [
            "prometheus",
            str(tmp_path),
            "--no-burndown",
            "--label",
            'note=a "quoted" \\ path',
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert 'note="a \\"quoted\\" \\\\ path"' in out


def test_prometheus_no_label_is_byte_identical(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    assert cli_main(["prometheus", str(tmp_path), "--no-burndown"]) == 0
    baseline = capsys.readouterr().out

    assert (
        cli_main(["prometheus", str(tmp_path), "--no-burndown", "--label", "x=y"]) == 0
    )
    labelled = capsys.readouterr().out

    assert "{" not in baseline
    assert baseline != labelled


def test_prometheus_rejects_malformed_label(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    with pytest.raises(SystemExit) as exc:
        cli_main(["prometheus", str(tmp_path), "--no-burndown", "--label", "nokey"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "key=value" in err


def test_prometheus_rejects_invalid_label_name(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path, _TWO_NODES)

    with pytest.raises(SystemExit) as exc:
        cli_main(["prometheus", str(tmp_path), "--no-burndown", "--label", "1bad=v"])

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid label name" in err
