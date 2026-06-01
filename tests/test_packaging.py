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


def test_static_assets_are_packaged():
    """The renderer copies templates/static/* into the generated site, so
    those files must actually be shipped inside the wheel. Regression guard
    against silent drops of e.g. filters.js or style.css when the glob is
    narrowed."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]["isabelle_blueprint"]

    # Either the broad static glob, or each individual file listed explicitly.
    has_glob = any(entry == "render/templates/static/*" for entry in package_data)
    assert has_glob, (
        "expected 'render/templates/static/*' in pyproject.toml package-data; "
        f"got {package_data!r}"
    )

    # And the on-disk files the glob is meant to capture must actually exist.
    static_dir = root / "isabelle_blueprint" / "render" / "templates" / "static"
    assert (static_dir / "style.css").exists()
    assert (static_dir / "filters.js").exists()


def test_json_schemas_are_packaged():
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]["isabelle_blueprint"]

    assert "schemas/*.schema.json" in package_data
    assert (root / "isabelle_blueprint" / "schemas" / "tasks.schema.json").exists()
    assert (root / "isabelle_blueprint" / "schemas" / "status.schema.json").exists()


def test_pyproject_declares_changelog_url():
    """v1.0 prep: PyPI shows the Changelog link prominently, so make sure
    the URL is wired in pyproject.toml and not silently dropped."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    urls = data["project"].get("urls", {})
    assert "Changelog" in urls, f"missing Changelog URL in [project.urls]: {urls!r}"
    assert urls["Changelog"].startswith("https://"), urls["Changelog"]
