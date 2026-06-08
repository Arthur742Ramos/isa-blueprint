"""Generate a ``.pre-commit-config.yaml`` for a blueprint project.

The generated config wires two cheap, offline IsabelleBlueprint gates as local
hooks so they run on every commit:

* ``fmt --check`` - the blueprint Markdown is in canonical interchange form.
* ``lint --strict`` - no structural ``error`` findings (cycles, duplicate ids,
  missing dependencies, broken formal statuses).

Both run via the installed ``isabelle-blueprint`` console script (``language:
system``) and pass ``pass_filenames: false`` because the commands discover their
own inputs from ``isabelle-blueprint.toml``.
"""
from __future__ import annotations

PRECOMMIT_CONFIG_FILENAME = ".pre-commit-config.yaml"


def render_precommit_config() -> str:
    """Return the canonical ``.pre-commit-config.yaml`` text (trailing newline)."""
    return (
        "# Managed by `isabelle-blueprint hooks`.\n"
        "# See https://pre-commit.com for the runner.\n"
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: isabelle-blueprint-fmt\n"
        "        name: isabelle-blueprint fmt --check\n"
        "        entry: isabelle-blueprint fmt --check\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "        files: \\.md$\n"
        "      - id: isabelle-blueprint-lint\n"
        "        name: isabelle-blueprint lint --strict\n"
        "        entry: isabelle-blueprint lint --strict\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "        files: \\.(md|tex|toml)$\n"
    )
