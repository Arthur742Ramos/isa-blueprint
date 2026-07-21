"""Tests for the ``proof-debt`` weighted remaining-work command."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from isabelle_blueprint.cli import main as cli_main
from isabelle_blueprint.model.node import BlueprintNode, IsabelleRef, NodeKind, NodeStatus
from isabelle_blueprint.model.project import BlueprintProject
from isabelle_blueprint.model.status import FormalStatus
from isabelle_blueprint.report.proof_debt import (
    PROOF_DEBT_SCHEMA_VERSION,
    build_proof_debt_gate,
    build_proof_debt_report,
    render_proof_debt_report,
)

pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)

from isabelle_blueprint.schemas import read_schema  # noqa: E402


def _node(
    node_id: str,
    *,
    formal: FormalStatus = FormalStatus.NAMED,
    effort: int | None = None,
) -> BlueprintNode:
    return BlueprintNode(
        id=node_id,
        kind=NodeKind.LEMMA,
        title=node_id.upper(),
        isabelle=IsabelleRef(fact=f"Demo.{node_id}"),
        status=NodeStatus(formal=formal),
        effort=effort,
    )


def _project(*nodes: BlueprintNode, name: str = "debt") -> BlueprintProject:
    return BlueprintProject.from_nodes(name, list(nodes), sources=["demo.md"])


# ---- unit-level behaviour --------------------------------------------------


def test_total_debt_sums_weighted_unproved_targets() -> None:
    report = build_proof_debt_report(
        _project(
            _node("a", formal=FormalStatus.NAMED, effort=3),
            _node("b", formal=FormalStatus.FOUND, effort=2),
            _node("c", formal=FormalStatus.NOT_FOUND, effort=5),
            _node("done", formal=FormalStatus.PROVED, effort=10),
        )
    )
    # proved node carries no debt; remaining 3 + 2 + 5 = 10.
    assert report.total_debt == 10
    assert report.remaining_node_count == 3
    assert report.bucket("named").debt == 3
    assert report.bucket("found").debt == 2
    assert report.bucket("problem").debt == 5
    assert report.bucket("missing").debt == 0


def test_default_effort_used_when_no_explicit_effort() -> None:
    report = build_proof_debt_report(_project(_node("a", formal=FormalStatus.NAMED)))
    assert report.total_debt == 1  # DEFAULT_EFFORT
    assert report.default_effort_used is True


def test_stale_counts_as_found_bucket() -> None:
    report = build_proof_debt_report(_project(_node("a", formal=FormalStatus.STALE, effort=4)))
    assert report.bucket("found").debt == 4
    assert report.total_debt == 4


def test_missing_nodes_excluded_from_total() -> None:
    report = build_proof_debt_report(
        _project(
            _node("a", formal=FormalStatus.MISSING, effort=7),
            _node("b", formal=FormalStatus.NAMED, effort=2),
        )
    )
    assert report.bucket("missing").debt == 7
    assert report.bucket("missing").node_count == 1
    # The blueprint-only node has no formal target, so it is not debt.
    assert report.total_debt == 2
    assert report.remaining_node_count == 1


def test_default_effort_not_flagged_for_excluded_missing_node() -> None:
    # The only node without an explicit effort is a 'missing' (excluded) node,
    # so it never contributes to the counted debt: default_effort_used stays
    # False because no *counted* node fell back to the default effort.
    report = build_proof_debt_report(
        _project(
            _node("a", formal=FormalStatus.MISSING),
            _node("b", formal=FormalStatus.NAMED, effort=2),
        )
    )
    assert report.total_debt == 2
    assert report.remaining_node_count == 1
    assert report.default_effort_used is False


def test_fully_proved_project_has_zero_debt() -> None:
    report = build_proof_debt_report(_project(_node("a", formal=FormalStatus.PROVED, effort=9)))
    assert report.total_debt == 0
    assert report.remaining_node_count == 0
    assert report.default_effort_used is False


def test_gate_ceiling_is_inclusive() -> None:
    report = build_proof_debt_report(_project(_node("a", formal=FormalStatus.NAMED, effort=5)))
    assert build_proof_debt_gate(report, 5)["exceeds"] is False
    assert build_proof_debt_gate(report, 4)["exceeds"] is True


def test_render_lists_every_bucket() -> None:
    report = build_proof_debt_report(_project(_node("a", formal=FormalStatus.NAMED, effort=2)))
    text = render_proof_debt_report(report)
    assert "Proof debt: 2" in text
    for bucket in ("named", "found", "problem", "missing"):
        assert bucket in text


# ---- end-to-end CLI --------------------------------------------------------


def _write_debt_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "debt"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # debt

            ::: lemma {#a}
            title: A
            isabelle: Demo.a
            effort: 3
            status:
              formal: named

            A statement.
            :::

            ::: lemma {#b}
            title: B
            isabelle: Demo.b
            effort: 2
            status:
              formal: found

            B statement.
            :::

            ::: lemma {#c}
            title: C
            isabelle: Demo.c
            status:
              formal: not_found

            C statement.
            :::
            """
        ),
        encoding="utf-8",
    )


def _write_clean_project(tmp_path: Path) -> None:
    (tmp_path / "isabelle-blueprint.toml").write_text(
        '[project]\nname = "clean"\n', encoding="utf-8"
    )
    (tmp_path / "blueprint.md").write_text(
        textwrap.dedent(
            """\
            # clean

            ::: lemma {#a}
            title: A
            isabelle: Demo.a
            effort: 4
            status: proved

            A statement.
            :::
            """
        ),
        encoding="utf-8",
    )


def test_cli_unproved_project_reports_positive_debt(tmp_path, capsys):
    _write_debt_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == PROOF_DEBT_SCHEMA_VERSION
    assert data["project"] == "debt"
    # named 3 + found 2 + problem(not_found) 1(default) = 6.
    assert data["total_debt"] == 6
    assert data["remaining_node_count"] == 3
    assert data["buckets"]["named"] == 3
    assert data["buckets"]["found"] == 2
    assert data["buckets"]["problem"] == 1
    assert data["buckets"]["missing"] == 0
    assert data["default_effort_used"] is True


def test_cli_text_output_shows_bucket_table(tmp_path, capsys):
    _write_debt_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Proof debt: 6" in out
    assert "| named | 1 | 3 |" in out


def test_cli_fail_over_zero_exits_5_when_debt_positive(tmp_path, capsys):
    _write_debt_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path), "--fail-over", "0"])
    assert rc == 5
    err = capsys.readouterr().err
    assert "exceeds ceiling 0" in err


def test_cli_fail_over_gate_payload(tmp_path, capsys):
    _write_debt_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path), "--fail-over", "0", "--json"])
    assert rc == 5
    data = json.loads(capsys.readouterr().out)
    assert data["gate"] == {"fail_over": 0, "total_debt": 6, "exceeds": True}


def test_cli_fail_over_high_ceiling_passes(tmp_path, capsys):
    _write_debt_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path), "--fail-over", "100"])
    assert rc == 0


def test_cli_fail_over_negative_is_usage_error(tmp_path, capsys):
    _write_debt_project(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["proof-debt", str(tmp_path), "--fail-over", "-1"])
    assert excinfo.value.code == 2


def test_cli_clean_project_zero_debt_and_gate_passes(tmp_path, capsys):
    _write_clean_project(tmp_path)
    rc = cli_main(["proof-debt", str(tmp_path), "--fail-over", "0", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_debt"] == 0
    assert data["remaining_node_count"] == 0
    assert data["gate"]["exceeds"] is False


def test_cli_json_validates_against_schema(tmp_path, capsys):
    _write_debt_project(tmp_path)
    assert cli_main(["proof-debt", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    Draft202012Validator(json.loads(read_schema("proof-debt"))).validate(data)
