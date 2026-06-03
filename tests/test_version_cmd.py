from __future__ import annotations

import json

from isabelle_blueprint import __version__
from isabelle_blueprint.cli import main as cli_main


def test_version_json_shape(capsys) -> None:
    rc = cli_main(["version", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "isabelle-blueprint"
    assert data["version"] == __version__
    assert isinstance(data["python"], str) and data["python"]
    assert "project" in data["schemas"]
    assert "agent-memory" in data["schemas"]


def test_version_text(capsys) -> None:
    rc = cli_main(["version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "python" in out
    assert "schemas" in out
