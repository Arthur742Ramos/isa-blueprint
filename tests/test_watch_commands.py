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


def _is_server_closed(server: object) -> bool:
    # A closed ThreadingHTTPServer usually reports fileno() == -1, but that is
    # brittle across CPython versions. Treat the server as closed if fileno()
    # is -1, raises (the fd was already released), or the underlying socket is
    # closed/None.
    try:
        if server.fileno() == -1:  # type: ignore[attr-defined]
            return True
    except OSError:
        return True
    sock = getattr(server, "socket", None)
    if sock is None:
        return True
    fileno = getattr(sock, "fileno", None)
    if fileno is None:
        return True
    try:
        return fileno() == -1
    except OSError:
        return True


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


def _stop_after_one_change(monkeypatch) -> None:
    # Let the first poll observe a changed snapshot (triggering one re-run),
    # then raise on the second sleep to exit deterministically, exactly like
    # Ctrl-C after a single re-run cycle.
    calls = {"n": 0}

    def _sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", _sleep)

    snapshots = iter([{"a": 1}, {"a": 2}, {"a": 2}])

    def _fake_snapshot(_paths):
        return next(snapshots, {"a": 2})

    monkeypatch.setattr(cli, "_snapshot", _fake_snapshot)


def test_check_watch_runs_once_then_stops(tmp_path: Path, capsys, monkeypatch) -> None:
    # `check --watch` is implemented by `_watch_check` delegating to the
    # shared `_run_watch` loop (label="checked"); this pins that the watch
    # loop still starts, prints the banner, and stops cleanly on Ctrl-C.
    _write_project(tmp_path)
    _stop_after_first(monkeypatch)
    rc = cli_main(["check", str(tmp_path), "--watch", "--interval", "0.01"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "watching for changes" in err
    assert "stopped" in err


def test_check_watch_rerun_uses_checked_label(tmp_path: Path, capsys, monkeypatch) -> None:
    # After the `_watch_check`/`_run_watch` merge, `check --watch` must still
    # report re-runs as "re-checked" (not the generic "re-ran" used by
    # report/status/tasks), preserving the pre-refactor wording exactly.
    _write_project(tmp_path)
    _stop_after_one_change(monkeypatch)
    rc = cli_main(["check", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "re-checked (exit code 0)" in err
    assert "re-ran" not in err


def test_report_watch_rerun_uses_ran_label(tmp_path: Path, capsys, monkeypatch) -> None:
    # The other `_run_watch` consumers (report/status/tasks) must keep using
    # the default "re-ran" wording after the merge with `_watch_check`.
    _write_project(tmp_path)
    _stop_after_one_change(monkeypatch)
    rc = cli_main(["report", str(tmp_path), "--watch"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "re-ran (exit code 0)" in err
    assert "re-checked" not in err


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


def test_web_offline_embeds_runtime_data_and_omits_mathjax(tmp_path: Path, capsys) -> None:
    _write_project(tmp_path)

    rc = cli_main(["web", str(tmp_path), "--offline"])

    assert rc == 0
    capsys.readouterr()
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    graph = (tmp_path / "site" / "graph.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/npm/mathjax" not in index
    assert 'id="graph-data"' in graph
    assert "data-offline" in index


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
    # Exercise the normal serve path: clear any ambient CI marker (GitHub
    # Actions sets CI=true) so the in-CI refusal guard does not trip here.
    monkeypatch.delenv("CI", raising=False)
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
    # Port 0 is only the *requested* port; the OS binds an ephemeral one, so the
    # advertised URL carries the real port. Assert the host:port prefix rather
    # than the literal ":0/".
    assert "serving -> http://127.0.0.1:" in out
    # The server was started and then closed in the finally-block. A closed
    # ThreadingHTTPServer reports a negative fileno on most CPython versions,
    # but that detail is brittle across versions, so also accept the underlying
    # socket being closed/None (and treat a raising fileno() as closed).
    assert len(started) == 1
    assert _is_server_closed(started[0])


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
