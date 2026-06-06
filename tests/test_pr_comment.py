"""Tests for the PR status comment poster."""
from __future__ import annotations

import json
from pathlib import Path

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import BlueprintStatus, FormalStatus
from isabelle_blueprint.report import pr_comment as pr_mod
from isabelle_blueprint.report.pr_comment import (
    COMMENT_MARKER,
    build_comment_body,
    post_or_update_pr_comment,
    write_pr_comment_preview,
)

_GITHUB_ENV_VARS = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_REPOSITORY",
    "GITHUB_EVENT_PATH",
    "GITHUB_SHA",
    "GITHUB_REF",
)


def _clear_github_env(monkeypatch) -> None:
    for var in _GITHUB_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _write_cli_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "comment-cli"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        "# comment-cli\n\n"
        "::: lemma {#a}\ntitle: A\nisabelle: Demo.a\nstatus: stub\n\nA statement.\n:::\n",
        encoding="utf-8",
    )



def _project() -> BlueprintProject:
    a = BlueprintNode(
        id="def-a",
        kind=NodeKind.DEFINITION,
        title="A",
        statement="def of A",
        isabelle=IsabelleRef(fact="Demo.a_def"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.PROVED),
    )
    b = BlueprintNode(
        id="lem-b",
        kind=NodeKind.LEMMA,
        title="B",
        statement="thing about B",
        informal_proof="by induction",
        uses=["def-a"],
        isabelle=IsabelleRef(fact="Demo.b_lem"),
        status=NodeStatus(blueprint=BlueprintStatus.WRITTEN, formal=FormalStatus.PROVED),
    )
    return BlueprintProject.from_nodes("smoke", [a, b], sources=["smoke.md"])


def test_build_comment_body_contains_marker_and_metrics():
    body = build_comment_body(_project(), commit_sha="abcdef1234567890")
    assert body.startswith(COMMENT_MARKER)
    assert "IsabelleBlueprint status" in body
    assert "Nodes" in body and "Coverage" in body
    assert "abcdef12" in body


def test_build_comment_body_handles_no_coverage():
    project = BlueprintProject.from_nodes("empty", [], sources=["x.md"])
    body = build_comment_body(project)
    assert "Coverage | n/a" in body


def test_build_comment_body_inlines_multiline_check_error():
    bad = BlueprintNode(
        id="lem-bad",
        kind=NodeKind.LEMMA,
        title="Bad",
        statement="thing",
        isabelle=IsabelleRef(fact="Demo.bad"),
        status=NodeStatus(
            blueprint=BlueprintStatus.WRITTEN,
            formal=FormalStatus.NOT_FOUND,
            check_error="first line\nsecond line\nthird line",
        ),
    )
    project = BlueprintProject.from_nodes("multi", [bad], sources=["x.md"])

    body = build_comment_body(project)

    # The whole error stays on the node's bullet line; a stray newline would
    # break the surrounding Markdown list.
    assert "`lem-bad`: not_found — first line second line third line" in body
    assert "\nsecond line" not in body


def test_post_skips_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    result = post_or_update_pr_comment(_project(), pr_number=42)
    assert result.status == "skipped"
    assert "GITHUB_TOKEN" in result.reason


def test_post_skips_without_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    result = post_or_update_pr_comment(_project(), pr_number=42)
    assert result.status == "skipped"
    assert "GITHUB_REPOSITORY" in result.reason


def test_post_skips_without_pr(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    result = post_or_update_pr_comment(_project())
    assert result.status == "skipped"
    assert "pull request" in result.reason


def test_post_creates_new_comment_when_marker_missing(monkeypatch):
    calls: list[dict] = []

    def fake_opener(url, token, method="GET", body=None):
        calls.append({"url": url, "method": method, "body": body})
        if method == "GET":
            # No existing comments with our marker.
            return 200, []
        if method == "POST":
            return 201, {"html_url": "https://example/c/1"}
        raise AssertionError(f"unexpected {method}")

    result = post_or_update_pr_comment(
        _project(),
        repo="owner/repo",
        pr_number=7,
        token="x",
        commit_sha="deadbeef",
        opener=fake_opener,
    )
    assert result.status == "posted"
    assert result.url == "https://example/c/1"
    methods = [c["method"] for c in calls]
    assert methods == ["GET", "POST"]
    assert COMMENT_MARKER in calls[-1]["body"]["body"]


def test_post_updates_existing_comment_when_marker_present(monkeypatch):
    calls: list[dict] = []

    def fake_opener(url, token, method="GET", body=None):
        calls.append({"url": url, "method": method})
        if method == "GET":
            return 200, [
                {"id": 11, "body": "unrelated"},
                {"id": 22, "body": f"{COMMENT_MARKER}\n## old body"},
            ]
        if method == "PATCH":
            return 200, {"html_url": "https://example/c/22"}
        raise AssertionError(f"unexpected {method}")

    result = post_or_update_pr_comment(
        _project(),
        repo="owner/repo",
        pr_number=8,
        token="x",
        opener=fake_opener,
    )
    assert result.status == "updated"
    assert result.url == "https://example/c/22"
    # The PATCH must target the discovered comment id.
    assert "/issues/comments/22" in calls[-1]["url"]


def test_post_reports_failure_status(monkeypatch):
    def fake_opener(url, token, method="GET", body=None):
        if method == "GET":
            return 200, []
        return 403, "forbidden"

    result = post_or_update_pr_comment(
        _project(),
        repo="owner/repo",
        pr_number=9,
        token="x",
        opener=fake_opener,
    )
    assert result.status == "skipped"
    assert "403" in result.reason


def test_read_event_pr_number(tmp_path: Path):
    payload = {"pull_request": {"number": 314}}
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    assert pr_mod._read_event_pr_number(str(event)) == 314


def test_read_event_pr_number_handles_missing_file(tmp_path: Path):
    assert pr_mod._read_event_pr_number(str(tmp_path / "missing.json")) is None
    assert pr_mod._read_event_pr_number(None) is None


def test_read_event_pr_number_from_issue_comment(tmp_path: Path):
    payload = {"issue": {"number": 42, "pull_request": {"url": "..."}}}
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    assert pr_mod._read_event_pr_number(str(event)) == 42


def test_write_pr_comment_preview(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    out = tmp_path / "pr-comment.md"
    written = write_pr_comment_preview(_project(), out)
    assert written == out
    text = out.read_text(encoding="utf-8")
    assert text.startswith(COMMENT_MARKER)
    assert "IsabelleBlueprint status" in text


def test_cli_comment_without_github_context_skips_and_exits_zero(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _clear_github_env(monkeypatch)
    _write_cli_project(tmp_path)

    rc = cli_main(["comment", str(tmp_path)])

    assert rc == 0
    assert "skipped" in capsys.readouterr().out


def test_cli_comment_strict_without_github_context_exits_6(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # The frozen exit-code contract pins `comment --strict` to 6 when the PR
    # context (token/repo/PR number) cannot be resolved.
    _clear_github_env(monkeypatch)
    _write_cli_project(tmp_path)

    rc = cli_main(["comment", str(tmp_path), "--strict"])

    assert rc == 6


def test_cli_comment_preview_writes_body_and_exits_zero(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _clear_github_env(monkeypatch)
    _write_cli_project(tmp_path)

    rc = cli_main(["comment", str(tmp_path), "--preview"])

    assert rc == 0
    preview = tmp_path / "build" / "pr-comment.md"
    assert preview.exists()
    assert preview.read_text(encoding="utf-8").startswith(COMMENT_MARKER)
