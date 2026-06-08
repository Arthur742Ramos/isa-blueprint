from __future__ import annotations

from pathlib import Path

from isabelle_blueprint.cli import main as cli_main


def _write_project(tmp_path: Path, *, name: str = "hooks-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text("# hooks-test\n", encoding="utf-8")


def test_hooks_prints_config_by_default(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["hooks", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "repos:" in out
    assert "isabelle-blueprint fmt --check" in out
    assert "isabelle-blueprint lint --strict" in out
    # nothing written to disk in print mode.
    assert not (tmp_path / ".pre-commit-config.yaml").exists()


def test_hooks_write_creates_file(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["hooks", str(tmp_path), "--write"])

    assert rc == 0
    target = tmp_path / ".pre-commit-config.yaml"
    assert target.exists()
    assert "repos:" in target.read_text(encoding="utf-8")


def test_hooks_write_refuses_overwrite_without_force(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    target = tmp_path / ".pre-commit-config.yaml"
    target.write_text("# pre-existing\n", encoding="utf-8")

    rc = cli_main(["hooks", str(tmp_path), "--write"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert target.read_text(encoding="utf-8") == "# pre-existing\n"


def test_hooks_write_force_overwrites(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    target = tmp_path / ".pre-commit-config.yaml"
    target.write_text("# pre-existing\n", encoding="utf-8")

    rc = cli_main(["hooks", str(tmp_path), "--write", "--force"])

    assert rc == 0
    assert "repos:" in target.read_text(encoding="utf-8")
