"""Contract tests for the JSON emitted by the path/scorecard/tags commands.

These commands ship versioned JSON (`--json`) but were added without packaged
JSON Schemas. This module adds and enforces those contracts, extending the
guarantee the rest of the CLI already provides: every published payload conforms
to a packaged ``*.schema.json``, and every packaged schema is itself a valid
draft 2020-12 schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.schemas import available_schemas, read_schema

pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)

_NEW_SCHEMAS = [
    "path",
    "scorecard",
    "tags",
    "orphans",
    "fact-coverage",
    "tag-cooccurrence",
    "proof-debt",
    "depends",
    "kinds",
    "critical-path",
    "matrix",
]

_BLUEPRINT = """# contracts

::: definition {#base}
title: Base
isabelle: Demo.base
tags: core
status: stub
:::
Base.
:::

::: lemma {#mid}
title: Mid
isabelle: Demo.mid
uses:
  - base
tags: core, alg
status: stub
:::
Mid.
:::

::: theorem {#top}
title: Top
isabelle: Demo.top
uses:
  - mid
status: stub
:::
Top.
:::
"""


def _schema(name: str) -> dict:
    return json.loads(read_schema(name))


def _validate(instance: object, name: str) -> None:
    Draft202012Validator(_schema(name)).validate(instance)


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "contracts"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_BLUEPRINT, encoding="utf-8")


@pytest.mark.parametrize("name", _NEW_SCHEMAS)
def test_schema_is_registered_and_metavalid(name: str) -> None:
    assert name in available_schemas()
    Draft202012Validator.check_schema(_schema(name))


@pytest.mark.parametrize("name", _NEW_SCHEMAS)
def test_schema_command_prints_valid_schema(name: str, capsys) -> None:
    assert cli_main(["schema", name]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"]
    Draft202012Validator.check_schema(payload)


def test_path_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["path", "top", "base", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["found"] is True
    _validate(data, "path")


def test_scorecard_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["scorecard", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "components" in data
    _validate(data, "scorecard")


def test_scorecard_json_with_gate_conforms(tmp_path: Path, capsys) -> None:
    # --min-grade adds an optional `gate` object; the published schema must
    # describe it so the contract stays accurate for CI consumers.
    _write_project(tmp_path)
    assert cli_main(["scorecard", str(tmp_path), "--json", "--min-grade", "A+"]) == 5
    data = json.loads(capsys.readouterr().out)
    assert data["gate"]["min_grade"] == "A+"
    _validate(data, "scorecard")


def test_tags_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["tags", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # The blueprint declares tagged nodes, so the TagStat item shape is exercised.
    assert data["tag_count"] >= 1
    _validate(data, "tags")


_ORPHAN_BLUEPRINT = (
    _BLUEPRINT
    + """
::: lemma {#orbit_a}
title: Orbit A
isabelle: Demo.orbit_a
uses:
  - orbit_b
status: stub
:::
Orbit A.
:::

::: lemma {#orbit_b}
title: Orbit B
isabelle: Demo.orbit_b
uses:
  - orbit_a
status: stub
:::
Orbit B.
:::
"""
)


def test_orphans_json_conforms(tmp_path: Path, capsys) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "contracts"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(_ORPHAN_BLUEPRINT, encoding="utf-8")
    # `orbit_a`/`orbit_b` form a cycle no goal reaches, so the orphan item shape
    # is exercised against the published schema.
    assert cli_main(["orphans", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["orphan_count"] >= 1
    _validate(data, "orphans")


def test_fact_coverage_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["fact-coverage", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # The blueprint references the Demo theory, so the TheoryStat shape is exercised.
    assert data["theory_count"] >= 1
    _validate(data, "fact-coverage")


def test_tag_cooccurrence_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["tag-cooccurrence", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # `mid` carries both `core` and `alg`, so the pair item shape is exercised.
    assert data["pair_count"] >= 1
    _validate(data, "tag-cooccurrence")


def test_proof_debt_json_conforms(tmp_path: Path, capsys) -> None:
    # A node with an assigned-but-unchecked Isabelle fact is a formal target
    # that is not yet proved, so it accrues debt and exercises the bucket shape.
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "contracts"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        "# contracts\n\n"
        "::: lemma {#a}\ntitle: A\nisabelle: Demo.a\neffort: 2\n"
        "status:\n  formal: named\n\nA.\n:::\n",
        encoding="utf-8",
    )
    assert cli_main(["proof-debt", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_debt"] >= 1
    assert set(data["buckets"]) >= {"named", "found", "problem", "missing"}
    _validate(data, "proof-debt")


def test_depends_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["depends", "mid", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # `mid` uses `base` and is used by `top`, so both neighbour shapes are exercised.
    assert [n["id"] for n in data["depends_on"]] == ["base"]
    assert [n["id"] for n in data["depended_on_by"]] == ["top"]
    _validate(data, "depends")


def test_kinds_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["kinds", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # The blueprint mixes definition/lemma/theorem, so the KindStat shape is exercised.
    assert data["kind_count"] >= 1
    _validate(data, "kinds")


def test_matrix_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["matrix", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # The blueprint mixes definition/lemma/theorem across formal states, so the
    # cell/marginal shapes are exercised against the published schema.
    assert data["total"] == 3
    assert data["cells"]
    _validate(data, "matrix")


def test_critical_path_json_conforms(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    assert cli_main(["critical-path", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # All three nodes are stubs forming base -> mid -> top, so the longest chain,
    # goals, and bottleneck item shapes are all exercised against the schema.
    assert data["longest"]["depth"] == 3
    assert data["goals"]
    assert any(b["leverage"] >= 1 for b in data["bottlenecks"])
    _validate(data, "critical-path")
