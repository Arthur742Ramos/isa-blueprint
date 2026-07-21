"""Focused tests for the status/errors consolidation cleanup.

Covers two refactors:

* ``COMPLETE_FORMAL_STATUSES`` now lives solely in
  :mod:`isabelle_blueprint.model.status`; every report module that used it
  (and one that used to redefine an equivalent literal) imports the shared
  constant instead of duplicating it.
* The four independent (but identical) ``UnknownNodeError`` classes were
  consolidated into a single :class:`isabelle_blueprint.errors.UnknownNodeError`
  that the leaf modules now import rather than define.
"""

from __future__ import annotations

import isabelle_blueprint.errors as errors
import isabelle_blueprint.graph.dependency_graph as dependency_graph
import isabelle_blueprint.report.depends as depends
import isabelle_blueprint.report.impact as impact
import isabelle_blueprint.report.path as path
import isabelle_blueprint.report.roadmap as roadmap
import isabelle_blueprint.report.scorecard as scorecard
from isabelle_blueprint.model.status import COMPLETE_FORMAL_STATUSES, FormalStatus


def test_complete_formal_statuses_lives_in_model_status() -> None:
    assert COMPLETE_FORMAL_STATUSES == frozenset({FormalStatus.FOUND, FormalStatus.PROVED})


def test_report_modules_reexport_the_shared_constant() -> None:
    # roadmap/critical_path/staleness/impact all import (not redefine) the
    # constant, so they must be the exact same frozenset object as the
    # canonical one in model.status -- not merely an equal-by-value copy.
    assert roadmap.COMPLETE_FORMAL_STATUSES is COMPLETE_FORMAL_STATUSES


def test_scorecard_complete_formal_derives_from_shared_constant() -> None:
    # scorecard previously hardcoded its own frozenset of raw string values;
    # it must now be derived from (and stay in sync with) the shared enum
    # constant rather than duplicating the literal.
    assert scorecard._COMPLETE_FORMAL == frozenset(
        status.value for status in COMPLETE_FORMAL_STATUSES
    )


def test_unknown_node_error_is_single_shared_class() -> None:
    # All four call sites must resolve to the exact same class object after
    # consolidation into errors.py -- not merely four classes with matching
    # names/behaviour.
    assert dependency_graph.UnknownNodeError is errors.UnknownNodeError
    assert depends.UnknownNodeError is errors.UnknownNodeError
    assert path.UnknownNodeError is errors.UnknownNodeError
    assert impact.UnknownNodeError is errors.UnknownNodeError


def test_unknown_node_error_preserves_keyerror_compatibility() -> None:
    # Existing call sites (cli.py, mcp_server.py) catch `except KeyError` or
    # `except UnknownNodeError`; both must keep working after the class moved
    # into the shared BlueprintError hierarchy.
    assert issubclass(errors.UnknownNodeError, KeyError)
    assert issubclass(errors.UnknownNodeError, errors.BlueprintError)

    try:
        raise errors.UnknownNodeError("missing-node")
    except KeyError as exc:
        assert isinstance(exc, errors.UnknownNodeError)
    else:
        raise AssertionError("UnknownNodeError should be catchable as KeyError")
