"""Packaging metadata smoke tests."""
from __future__ import annotations

import tomllib
from pathlib import Path


def test_py_typed_marker_is_packaged():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert (root / "isabelle_blueprint" / "py.typed").exists()
    assert "Typing :: Typed" in data["project"]["classifiers"]
    assert data["tool"]["setuptools"]["include-package-data"] is True
    assert "py.typed" in data["tool"]["setuptools"]["package-data"]["isabelle_blueprint"]
