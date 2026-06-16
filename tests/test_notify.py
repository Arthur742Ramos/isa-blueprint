from __future__ import annotations

import json
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.errors import BlueprintError
from isabelle_blueprint.report import notify as notify_mod


def _write_project(tmp_path: Path, *, name: str = "notify-test") -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(
        """# notify-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: proved

A statement.

Proof sketch.
:::
""",
        encoding="utf-8",
    )


def test_notify_dry_run_slack_default(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["notify", str(tmp_path), "--no-burndown"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert set(payload) == {"text"}
    assert "notify-test" in payload["text"]
    assert "dry-run" in captured.err


def test_notify_dry_run_generic_shape(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["notify", str(tmp_path), "--no-burndown", "--format", "generic"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"title", "summary", "lines"}
    assert isinstance(payload["lines"], list)


def test_notify_send_requires_url(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["notify", str(tmp_path), "--no-burndown", "--send"])

    assert rc == 1
    assert "--url" in capsys.readouterr().err


def test_notify_send_http_rejected_without_allow(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(
        [
            "notify",
            str(tmp_path),
            "--no-burndown",
            "--send",
            "--url",
            "http://example.test/hook",
        ]
    )

    assert rc == 1
    assert "plaintext http" in capsys.readouterr().err


def test_notify_send_success(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    seen: dict[str, object] = {}

    class _FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _FakeOpener:
        def open(self, request, timeout=None):
            seen["url"] = request.full_url
            seen["body"] = request.data
            seen["timeout"] = timeout
            return _FakeResponse()

    monkeypatch.setattr(
        notify_mod.urllib.request, "build_opener", lambda *a, **k: _FakeOpener()
    )

    rc = cli_main(
        [
            "notify",
            str(tmp_path),
            "--no-burndown",
            "--send",
            "--url",
            "https://example.test/hook",
        ]
    )

    assert rc == 0
    assert seen["url"] == "https://example.test/hook"
    assert b"text" in seen["body"]
    assert "HTTP 204" in capsys.readouterr().out


def test_notify_markdown_preview(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["notify", str(tmp_path), "--no-burndown", "--format", "markdown"])

    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out
    # Heading carries the project name AND the coverage figure (advertised format).
    first_line = out.splitlines()[0]
    assert first_line.startswith("# IsabelleBlueprint status - notify-test")
    assert "Coverage: 100%" in first_line
    assert "Coverage: 100%" in out
    # Preview goes to stdout and is not valid JSON (it is Markdown text).
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    # No dry-run webhook hint for the local preview format.
    assert "dry-run" not in captured.err


def test_notify_markdown_send_is_rejected(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(
        [
            "notify",
            str(tmp_path),
            "--no-burndown",
            "--format",
            "markdown",
            "--send",
            "--url",
            "https://example.test/hook",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "preview-only" in err


def test_render_markdown_body() -> None:
    content = notify_mod.NotificationContent(
        title="T", summary="S", lines=["one", "two"]
    )
    body = notify_mod.render_markdown(content)
    assert body.startswith("# T\n")
    assert "S" in body
    assert "- one" in body
    assert "- two" in body
    assert body.endswith("\n")


def test_render_payload_formats() -> None:
    content = notify_mod.NotificationContent(
        title="T", summary="S", lines=["one", "two"]
    )
    assert notify_mod.render_payload(content, "slack") == {"text": content.text}
    assert notify_mod.render_payload(content, "discord") == {"content": content.text}
    teams = notify_mod.render_payload(content, "teams")
    assert teams["@type"] == "MessageCard"
    assert teams["title"] == "T"
    with pytest.raises(BlueprintError):
        notify_mod.render_payload(content, "nope")


def test_post_notification_rejects_non_http_scheme() -> None:
    with pytest.raises(BlueprintError):
        notify_mod.post_notification("ftp://example.test/hook", {"text": "hi"})
