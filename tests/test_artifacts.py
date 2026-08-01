"""Tests for generated-artifact staging and reconciliation."""
from __future__ import annotations

from pathlib import Path

import pytest

from isabelle_blueprint.artifacts import (
    atomic_write_text,
    create_staging_dir,
    discard_staging_dir,
    publish_staged,
    remove_generated_file,
)


def test_publish_reconciles_managed_files_and_preserves_unmanaged(tmp_path: Path):
    output = tmp_path / "site"
    output.mkdir()
    (output / "CNAME").write_text("example.test\n", encoding="utf-8")
    staging = create_staging_dir(output)
    try:
        (staging / "index.html").write_text("new", encoding="utf-8")
        (staging / "nodes").mkdir()
        (staging / "nodes" / "new.html").write_text("node", encoding="utf-8")
        publish_staged(output, staging, [Path("index.html"), Path("nodes/new.html")])
    finally:
        discard_staging_dir(staging)

    assert (output / "CNAME").exists()
    assert (output / "index.html").read_text(encoding="utf-8") == "new"

    staging = create_staging_dir(output)
    try:
        (staging / "index.html").write_text("updated", encoding="utf-8")
        publish_staged(output, staging, [Path("index.html")])
    finally:
        discard_staging_dir(staging)

    assert not (output / "nodes" / "new.html").exists()
    assert (output / "CNAME").exists()


def test_publish_uses_legacy_paths_when_manifest_is_missing(tmp_path: Path):
    output = tmp_path / "site"
    output.mkdir()
    (output / "old.json").write_text("old", encoding="utf-8")
    staging = create_staging_dir(output)
    try:
        (staging / "new.json").write_text("new", encoding="utf-8")
        publish_staged(output, staging, [Path("new.json")], legacy_paths=[Path("old.json")])
    finally:
        discard_staging_dir(staging)
    assert not (output / "old.json").exists()
    assert (output / "new.json").exists()


def test_publish_rejects_unsafe_paths(tmp_path: Path):
    output = tmp_path / "site"
    staging = create_staging_dir(output)
    try:
        with pytest.raises(ValueError, match="relative path"):
            publish_staged(output, staging, [Path("../escape.txt")])
    finally:
        discard_staging_dir(staging)


def test_atomic_write_and_remove_generated_file(tmp_path: Path):
    path = tmp_path / "nested" / "artifact.txt"
    atomic_write_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"
    remove_generated_file(path)
    remove_generated_file(path)
    assert not path.exists()


def test_publish_refuses_symlinked_output_subdirectory(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "site"
    output.mkdir()
    try:
        (output / "nodes").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    staging = create_staging_dir(output)
    try:
        (staging / "nodes").mkdir()
        (staging / "nodes" / "node.html").write_text("node", encoding="utf-8")
        with pytest.raises(ValueError, match="symlink|escapes"):
            publish_staged(output, staging, [Path("nodes/node.html")])
    finally:
        discard_staging_dir(staging)
    assert not (outside / "node.html").exists()
