from __future__ import annotations

import urllib.request
from pathlib import Path

import isabelle_blueprint.cli as cli
from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.config import load_config

_PROJECT = """# watch-test

::: lemma {#a}
title: A
isabelle: Demo.a
status: stub

A statement.

Sketch.
:::
"""


def _write_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "watch-test"\n',
        encoding="utf-8",
    )
    (tmp_path / "blueprint.md").write_text(_PROJECT, encoding="utf-8")


def _stop_after_first(monkeypatch) -> None:
    # The watch loop calls time.sleep between polls; raising there exits the
    # loop deterministically after the initial run, exactly like Ctrl-C.
    def _raise(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", _raise)


def test_report_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["report", str(tmp_path), "--watch", "--interval", "0.01"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err
    assert "stopped" in err


def test_status_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["status", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err


def test_tasks_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["tasks", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err


def test_report_without_watch_is_single_shot(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)
    rc = cli_main(["report", str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" not in err


def test_web_watch_paths_include_assignments(tmp_path: Path) -> None:
    # The static site now renders owner data from assignments.json, so the web
    # watch loop must re-render when that file changes.
    _write_project(tmp_path)
    config = load_config(tmp_path)
    assert config.assignments_path in cli._watch_paths(tmp_path)


def test_web_single_shot_renders_site(tmp_path: Path, capsys) -> None:
    # `web` without --watch/--serve renders the static site once and reports the
    # written index path. This pins the common (non-watch) code path.
    _write_project(tmp_path)

    rc = cli_main(["web", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("site -> ")
    site_dir = tmp_path / "site"
    assert (site_dir / "index.html").exists()
    assert (site_dir / "status.html").exists()


def test_start_site_server_serves_files_then_shuts_down(tmp_path: Path) -> None:
    # `_start_site_server` binds a real ThreadingHTTPServer in a background
    # thread. We bind to 127.0.0.1 on an ephemeral port (0), make a single
    # request with a hard timeout, then shut it down -- so the test is hermetic
    # and cannot hang.
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<html>hello-serve</html>", encoding="utf-8")

    server = cli._start_site_server(site_dir, "127.0.0.1", 0)
    try:
        host, port = server.server_address[0], server.server_address[1]
        with urllib.request.urlopen(f"http://{host}:{port}/index.html", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "hello-serve" in body
    finally:
        server.shutdown()
        server.server_close()


def test_serve_refuses_in_ci_with_exit_code_8(tmp_path: Path, capsys, monkeypatch) -> None:
    # The `serve` subcommand refuses to run under CI (CI=true) and returns exit
    # code 8 -- before rendering or binding anything. `--allow-ci` overrides it.
    _write_project(tmp_path)
    monkeypatch.setenv("CI", "true")

    rc = cli_main(["serve", str(tmp_path)])

    assert rc == 8
    err = capsys.readouterr().err
    assert "refusing to serve in CI" in err
    # The refusal happens before any rendering, so no site is written.
    assert not (tmp_path / "site").exists()


def test_web_serve_refuses_in_ci_with_exit_code_8(tmp_path: Path, capsys, monkeypatch) -> None:
    # `web --serve` shares the same CI refusal guard as the `serve` subcommand.
    _write_project(tmp_path)
    monkeypatch.setenv("CI", "true")

    rc = cli_main(["web", str(tmp_path), "--serve"])

    assert rc == 8
    assert "refusing to serve in CI" in capsys.readouterr().err


def test_web_watch_without_serve_is_allowed_in_ci(tmp_path: Path, capsys, monkeypatch) -> None:
    # The CI guard only blocks --serve; plain --watch must still work under CI.
    _write_project(tmp_path)
    monkeypatch.setenv("CI", "true")
    _stop_after_first(monkeypatch)

    rc = cli_main(["web", str(tmp_path), "--watch"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert "refusing to serve in CI" not in err
    assert "site -> " in out


def test_serve_starts_server_and_shuts_down(tmp_path: Path, capsys, monkeypatch) -> None:
    # End-to-end wiring of the `serve` subcommand: it renders the site once,
    # starts the HTTP server (ephemeral port 0 -> never collides), then the
    # watch loop is broken on the first poll (KeyboardInterrupt), driving the
    # finally-block that shuts the server down. We assert the server is closed.
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)

    started: list[object] = []
    real_start = cli._start_site_server

    def _tracking_start(site_dir: Path, host: str, port: int):  # type: ignore[no-untyped-def]
        server = real_start(site_dir, host, port)
        started.append(server)
        return server

    monkeypatch.setattr(cli, "_start_site_server", _tracking_start)

    rc = cli_main(["serve", str(tmp_path), "--host", "127.0.0.1", "--port", "0"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "site -> " in out
    assert "serving -> http://127.0.0.1:0/" in out
    # The server was started and then closed in the finally-block; a closed
    # ThreadingHTTPServer has a negative fileno.
    assert len(started) == 1
    assert started[0].fileno() == -1  # type: ignore[attr-defined]


def test_serve_allows_ci_with_allow_ci_flag(tmp_path: Path, capsys, monkeypatch) -> None:
    # `--allow-ci` overrides the CI refusal guard, so serving proceeds even when
    # CI=true. We still break the watch loop immediately to avoid hanging.
    _write_project(tmp_path)
    monkeypatch.setenv("CI", "true")
    _stop_after_first(monkeypatch)
    monkeypatch.setattr(cli, "_start_site_server", lambda *a, **k: None)

    rc = cli_main(["serve", str(tmp_path), "--port", "0", "--allow-ci"])

    assert rc == 0
    out, err = capsys.readouterr()
    assert "refusing to serve in CI" not in err
    assert "site -> " in out
