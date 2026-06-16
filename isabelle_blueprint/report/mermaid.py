"""Shared Mermaid rendering helpers for the report renderers.

These small helpers are used by the several ``report`` renderers that emit
Mermaid ``flowchart`` diagrams so the node-id escaping and label escaping stay
identical across diagrams.
"""
from __future__ import annotations


def mermaid_node_id(node_id: str) -> str:
    """Return a Mermaid-safe identifier for ``node_id`` (injective escaping).

    Every character that is not ASCII alphanumeric is escaped by codepoint, so
    distinct blueprint ids that differ only in their separators never collapse
    onto the same Mermaid node. A leading ``n_`` keeps ids that start with a
    digit valid.
    """

    safe = "".join(ch if (ch.isascii() and ch.isalnum()) else f"_{ord(ch)}_" for ch in node_id)
    return f"n_{safe}"


def mermaid_label(text: str) -> str:
    """Escape ``text`` for use inside a quoted Mermaid node label."""

    return (
        text.replace("\\", "\\\\")
        .replace('"', "&quot;")
        .replace("|", "&#124;")
        .replace("\n", "<br/>")
    )
