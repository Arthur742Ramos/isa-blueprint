"""Tests for multi-blueprint project support (v0.7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.config import load_config
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.parser import parse_blueprint

_BP_A = """# Part A

::: lemma {#lem-alpha}
title: Alpha lemma
isabelle: A.alpha
status:
  blueprint: written
:::

Statement A.
:::
"""

_BP_B = """# Part B

::: lemma {#lem-beta}
title: Beta lemma
isabelle: B.beta
status:
  blueprint: written
:::

Statement B.
:::
"""

_BP_B_DUP = """# Part B (duplicate id)

::: lemma {#lem-alpha}
title: Alpha lemma (duplicate)
isabelle: B.alpha
status:
  blueprint: written
:::

Statement.
:::
"""


def _write_project(
    tmp_path: Path,
    *,
    blueprints: list[str] | str | None,
    files: dict[str, str],
) -> Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    toml = ["[project]", 'name = "Multi"']
    if isinstance(blueprints, list):
        formatted = ", ".join(f'"{b}"' for b in blueprints)
        toml.append(f"blueprints = [{formatted}]")
    elif isinstance(blueprints, str):
        toml.append(f'blueprint = "{blueprints}"')
    (tmp_path / "isabelle-blueprint.toml").write_text("\n".join(toml) + "\n", encoding="utf-8")
    return tmp_path


def test_config_legacy_single_blueprint(tmp_path: Path) -> None:
    _write_project(tmp_path, blueprints="blueprint.md", files={"blueprint.md": _BP_A})
    config = load_config(tmp_path)
    assert config.blueprint_paths == [config.blueprint_path]
    assert config.extra_blueprint_paths == []
    assert config.blueprint_path.name == "blueprint.md"


def test_config_blueprints_list_populates_all(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B},
    )
    config = load_config(tmp_path)
    assert len(config.blueprint_paths) == 2
    assert config.blueprint_path.name == "a.md"
    assert config.extra_blueprint_paths[0].name == "b.md"


def test_config_blueprints_as_string_normalises_to_list(tmp_path: Path) -> None:
    _write_project(tmp_path, blueprints=["only.md"], files={"only.md": _BP_A})
    config = load_config(tmp_path)
    assert config.blueprint_paths == [config.blueprint_path]


def test_config_blueprints_empty_list_raises(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        "[project]\nblueprints = []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="non-empty list"):
        load_config(tmp_path)


def test_parse_blueprint_merges_nodes(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text(_BP_A, encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text(_BP_B, encoding="utf-8")
    project = parse_blueprint([a, b], project_name="merged")
    ids = [n.id for n in project.nodes]
    assert ids == ["lem-alpha", "lem-beta"]


def test_parse_blueprint_raises_on_duplicate_id(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text(_BP_A, encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text(_BP_B_DUP, encoding="utf-8")
    with pytest.raises(BlueprintError) as exc:
        parse_blueprint([a, b], project_name="merged")
    msg = str(exc.value)
    assert "lem-alpha" in msg
    assert str(a) in msg
    assert str(b) in msg


def test_cli_check_loads_multi_blueprint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B},
    )
    rc = cli_main(["check", str(tmp_path)])
    assert rc == 0


def test_cli_check_reports_dup_ids_as_blueprint_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B_DUP},
    )
    rc = cli_main(["check", str(tmp_path)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "lem-alpha" in err
    assert "duplicate node id" in err


def test_cli_new_append_requires_blueprint_flag_when_multi(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B},
    )
    rc = cli_main(
        [
            "new",
            "lemma",
            "lem-gamma",
            str(tmp_path),
            "--append",
            "--no-fact",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "multiple blueprints" in err


def test_cli_new_append_writes_to_chosen_blueprint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B},
    )
    rc = cli_main(
        [
            "new",
            "lemma",
            "lem-gamma",
            str(tmp_path),
            "--append",
            "--blueprint",
            "b.md",
            "--no-fact",
        ]
    )
    assert rc == 0
    assert "lem-gamma" in (tmp_path / "b.md").read_text(encoding="utf-8")
    assert "lem-gamma" not in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_cli_new_append_rejects_unknown_blueprint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(
        tmp_path,
        blueprints=["a.md", "b.md"],
        files={"a.md": _BP_A, "b.md": _BP_B},
    )
    rc = cli_main(
        [
            "new",
            "lemma",
            "lem-gamma",
            str(tmp_path),
            "--append",
            "--blueprint",
            "nope.md",
            "--no-fact",
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "not one of the configured" in err


def test_cli_new_append_single_blueprint_still_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project(tmp_path, blueprints="blueprint.md", files={"blueprint.md": _BP_A})
    rc = cli_main(
        [
            "new",
            "lemma",
            "lem-beta",
            str(tmp_path),
            "--append",
            "--no-fact",
        ]
    )
    assert rc == 0
    assert "lem-beta" in (tmp_path / "blueprint.md").read_text(encoding="utf-8")
