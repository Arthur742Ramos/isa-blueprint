"""Terminal colour helpers for human-facing CLI output.

Colour is *opt-in* and conservative:

* Output is only ever coloured after :func:`configure` enables it for the
  current process.  Until then (and inside unit tests that call render helpers
  directly) :func:`is_enabled` is ``False`` so every helper returns plain text.
* ``configure("auto", ...)`` enables colour only when the target stream is a
  TTY and the ``NO_COLOR`` environment variable is unset (see
  https://no-color.org).  ``"always"`` forces colour on; ``"never"`` forces it
  off.
* Only short *semantic tokens* (a severity word, a health label) are ever
  coloured.  Machine-readable output (JSON, SARIF, completion scripts) must
  never be routed through these helpers.
"""

from __future__ import annotations

import os
from typing import IO

_RESET = "\033[0m"
_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}

# Disabled until configure() runs, so importing this module never changes the
# output of code that forgets to (or deliberately does not) configure it.
_enabled = False


def configure(mode: str = "auto", *, stream: IO[str] | None = None) -> bool:
    """Enable or disable colour for subsequent helper calls.

    ``mode`` is one of ``"auto"``, ``"always"``, ``"never"``.  Returns the
    resulting enabled state.  Called once per CLI invocation from ``main`` so
    state never leaks between in-process test runs.
    """

    global _enabled
    if mode == "always":
        _enabled = True
    elif mode == "never":
        _enabled = False
    else:  # auto
        if os.environ.get("NO_COLOR") is not None:
            _enabled = False
        else:
            target = stream if stream is not None else _default_stream()
            _enabled = _stream_is_tty(target)
    return _enabled


def set_enabled(value: bool) -> None:
    """Force the enabled state directly (used by tests)."""

    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    return _enabled


def paint(text: str, *styles: str) -> str:
    """Wrap ``text`` in the given ANSI styles when colour is enabled."""

    if not _enabled or not styles:
        return text
    prefix = "".join(_CODES[s] for s in styles if s in _CODES)
    if not prefix:
        return text
    return f"{prefix}{text}{_RESET}"


def error(text: str) -> str:
    return paint(text, "red")


def warning(text: str) -> str:
    return paint(text, "yellow")


def info(text: str) -> str:
    return paint(text, "cyan")


def success(text: str) -> str:
    return paint(text, "green")


def bold(text: str) -> str:
    return paint(text, "bold")


def dim(text: str) -> str:
    return paint(text, "dim")


def _default_stream() -> IO[str]:
    import sys

    return sys.stdout


def _stream_is_tty(stream: IO[str] | None) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (ValueError, OSError):  # closed/detached stream
        return False
