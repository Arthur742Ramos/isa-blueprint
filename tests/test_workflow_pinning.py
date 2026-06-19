"""Supply-chain hardening guard for the GitHub Actions workflows.

These tests fail if anyone reintroduces a floating ``uses:`` tag (e.g.
``actions/checkout@v6``) instead of a 40-character commit SHA, or drops the
``github-actions`` Dependabot ecosystem that keeps those pins fresh.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"

# ``owner/repo@<ref>`` with an optional ``# comment``. Local actions (``./...``)
# and reusable workflows are intentionally excluded from the SHA requirement.
_USES_RE = re.compile(
    r"^\s*-?\s*uses:\s*(?P<ref>[^\s#]+)\s*(?:#\s*(?P<comment>.+?))?\s*$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_uses() -> list[tuple[Path, str, str | None]]:
    """Return ``(file, action_ref, trailing_comment)`` for every ``uses:`` line."""
    found: list[tuple[Path, str, str | None]] = []
    for wf in sorted(_WORKFLOW_DIR.glob("*.yml")):
        for line in wf.read_text(encoding="utf-8").splitlines():
            match = _USES_RE.match(line)
            if not match:
                continue
            found.append((wf, match.group("ref"), match.group("comment")))
    return found


def test_workflow_dir_has_uses_references():
    # Guards the regex itself: if this returns nothing the other tests are vacuous.
    assert _iter_uses(), "expected at least one `uses:` reference to validate"


def test_every_third_party_action_is_pinned_to_full_sha():
    offenders: list[str] = []
    for wf, ref, _comment in _iter_uses():
        if ref.startswith("./") or ref.startswith("."):
            continue  # local action, no pin required
        if "@" not in ref:
            offenders.append(f"{wf.name}: {ref} (no version/SHA at all)")
            continue
        _action, _, pin = ref.partition("@")
        if not _SHA_RE.match(pin):
            offenders.append(f"{wf.name}: {ref} (pin {pin!r} is not a 40-char SHA)")
    assert not offenders, "unpinned actions found:\n" + "\n".join(offenders)


def test_pinned_actions_keep_a_human_readable_version_comment():
    missing: list[str] = []
    for wf, ref, comment in _iter_uses():
        if ref.startswith("./") or ref.startswith("."):
            continue
        if not comment or not comment.strip():
            missing.append(f"{wf.name}: {ref}")
    assert not missing, "pinned actions missing a version comment:\n" + "\n".join(missing)


def test_dependabot_enables_github_actions_weekly():
    config = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    ecosystems = {
        update.get("package-ecosystem"): update for update in config.get("updates", [])
    }
    assert "github-actions" in ecosystems, "dependabot must update github-actions"
    schedule = ecosystems["github-actions"].get("schedule", {})
    assert schedule.get("interval") == "weekly"
