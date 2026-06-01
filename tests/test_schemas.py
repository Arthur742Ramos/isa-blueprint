from __future__ import annotations

import json
import tomllib
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.schemas import available_schemas, read_schema, write_schemas


def test_packaged_schemas_are_readable() -> None:
    for name in available_schemas():
        payload = json.loads(read_schema(name))
        assert payload["$schema"].startswith("https://json-schema.org/")
        assert payload["title"]


def test_schema_command_lists_names(capsys) -> None:
    rc = cli_main(["schema"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "project" in out
    assert "tasks" in out


def test_write_schemas_exports_files(tmp_path: Path) -> None:
    written = write_schemas(tmp_path, names=["tasks"])

    assert written["tasks"].exists()
    assert json.loads(written["tasks"].read_text(encoding="utf-8"))["title"]


def test_schema_package_data_declared() -> None:
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]["isabelle_blueprint"]

    assert "schemas/*.schema.json" in package_data

