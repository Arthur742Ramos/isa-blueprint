from __future__ import annotations

from isabelle_blueprint.report._markdown import md_cell, md_cell_multiline


def test_md_cell_flattens_all_newline_forms() -> None:
    assert md_cell("a\r\nb\nc\rd") == "a b c d"


def test_md_cell_escapes_pipe() -> None:
    assert md_cell("a|b") == r"a\|b"


def test_md_cell_leaves_plain_text_untouched() -> None:
    assert md_cell("plain text") == "plain text"


def test_md_cell_combines_flatten_and_escape() -> None:
    assert md_cell("a|b\nc|d") == r"a\|b c\|d"


def test_md_cell_multiline_preserves_newlines_as_breaks() -> None:
    assert md_cell_multiline("a\nb") == "a<br/>b"


def test_md_cell_multiline_leaves_carriage_returns_intact() -> None:
    # Only ``\n`` is converted; ``\r\n`` and bare ``\r`` are left untouched to
    # match the historical roadmap renderer.
    assert md_cell_multiline("a\r\nb") == "a\r<br/>b"
    assert md_cell_multiline("a\rb") == "a\rb"


def test_md_cell_multiline_escapes_backslash_before_pipe() -> None:
    # Backslash is doubled first so the pipe escape is not mistaken for an
    # existing one; this mirrors the roadmap renderer's historical output.
    assert md_cell_multiline(r"a\b|c") == r"a\\b\|c"


def test_md_cell_multiline_full_combination() -> None:
    assert md_cell_multiline("x\\|y\nz") == "x\\\\\\|y<br/>z"
