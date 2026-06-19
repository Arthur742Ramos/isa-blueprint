"""Shared Markdown table-cell escaping helpers.

A literal ``|`` would start a new table column and a newline would terminate the
row, so user-controlled cell text has to be neutralised before it is dropped
into a Markdown table. Centralising the logic here keeps the ~dozen report
renderers that build Markdown tables in lock-step rather than each carrying its
own copy of the same ``str.replace`` chain.
"""
from __future__ import annotations


def md_cell(text: str) -> str:
    """Escape a value for safe inclusion in a Markdown table cell.

    Newlines (in all three ``\\r\\n`` / ``\\n`` / ``\\r`` forms) are flattened to
    spaces so the value cannot break out of its row, and a literal ``|`` is
    escaped so it cannot start a new column.
    """

    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", r"\|")


def md_cell_multiline(text: str) -> str:
    """Escape a cell, converting ``\\n`` newlines to ``<br/>`` line breaks.

    Unlike :func:`md_cell`, this keeps multi-line cell content visible by
    rendering ``\\n`` as an HTML ``<br/>`` break rather than flattening it to a
    space. Only ``\\n`` is converted: ``\\r\\n`` and bare ``\\r`` are left
    intact, matching the historical roadmap renderer. A literal backslash is
    escaped first so the escape introduced for ``|`` is not mistaken for a
    pre-existing one.
    """

    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br/>")
