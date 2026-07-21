"""Parse Isabelle ``ROOT`` files to enumerate the theories of a session.

This is the *single source of truth* for "which ``.thy`` files belong to a
build". Callers must not glob ``**/*.thy`` independently, because that silently
pulls in work-in-progress / orphaned / archived theories and breaks the moment a
project adds a new theory subdirectory.

The ROOT/session parsing here is a faithful port of the ``common.py`` module of
`ott2/isabelle-query <https://github.com/ott2/isabelle-query>`_ (MIT, by
Andras Salamon). It is vendored rather than depended upon so IsabelleBlueprint
keeps a single, light dependency footprint. The build-trajectory ``run_guarded``
helper and the ``.isabelle-query`` marker-file mechanism are intentionally
omitted; session discovery here uses an explicit directory, then
``$ISABELLE_BLUEPRINT_ROOT``, then the nearest ancestor that holds a ``ROOT``
file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from isabelle_blueprint.isabelle.theory_import import strip_isabelle_comments

ROOT_ENV_VAR = "ISABELLE_BLUEPRINT_ROOT"


def default_session_dir(start: Path | None = None) -> Path:
    """Resolve the Isabelle session directory to index.

    Resolution order:

    1. ``$ISABELLE_BLUEPRINT_ROOT``, if set (``~`` expanded, resolved absolute).
    2. The nearest ancestor directory (including ``start``) that holds a
       ``ROOT`` file directly -- an unambiguous single session, so most
       projects need no configuration.
    3. Fall back to ``start`` itself.
    """
    env = os.environ.get(ROOT_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / "ROOT").is_file():
            return directory
    return here


# Keywords that terminate a ``theories`` or ``directories`` block in a ROOT
# file (i.e. names of sibling clauses at the same nesting level).
_ROOT_BLOCK_TERMINATORS = (
    "theories",
    "document_files",
    "document_theories",
    "sessions",
    "options",
    "description",
    "chapter",
    "session",
    "directories",
)

# A directory name inside a ``directories`` clause: either a double-quoted
# string (which may contain spaces) or a bare path-like identifier.
_DIRECTORY_TOKEN_RE = re.compile(r'"(?P<quoted>[^"]*)"|(?P<bare>[^\s"]+)')


def _is_terminator(stripped: str, *, exclude: str) -> bool:
    """True iff ``stripped`` starts with a ROOT block terminator other than
    ``exclude`` (the block currently being parsed)."""
    for keyword in _ROOT_BLOCK_TERMINATORS:
        if keyword == exclude:
            continue
        if re.match(rf"{keyword}\b", stripped):
            return True
    return False


def parse_root_theories(root_path: Path) -> list[str]:
    """Return the ordered theory names from a ROOT's ``theories`` block.

    Returns ``[]`` if the file does not exist or has no such block.
    """
    if not root_path.exists():
        return []
    theories: list[str] = []
    in_theories = False
    cleaned = strip_isabelle_comments(root_path.read_text(encoding="utf-8", errors="replace"))
    for line in cleaned.splitlines():
        stripped = line.strip()
        if re.match(r"theories\b", stripped):
            in_theories = True
            continue
        if _is_terminator(stripped, exclude="theories"):
            in_theories = False
            continue
        # Theory entries are bare identifiers (one per line). Skip blanks,
        # comments, and option-decorated forms ("Foo (in Bar)").
        if in_theories and re.match(r"[A-Za-z_][A-Za-z0-9_]*$", stripped):
            theories.append(stripped)
    return theories


def parse_root_directories(root_path: Path) -> list[str]:
    """Return the ordered subdirectory names from a ROOT's ``directories``
    clause. Accepts single-line and multi-line forms; ``[]`` if absent."""
    if not root_path.exists():
        return []
    subdirs: list[str] = []
    in_dirs = False
    cleaned = strip_isabelle_comments(root_path.read_text(encoding="utf-8", errors="replace"))
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith("directories"):
            in_dirs = True
            stripped = stripped[len("directories") :].strip()
        elif _is_terminator(stripped, exclude="directories"):
            in_dirs = False
            continue
        if in_dirs:
            # Directory names may be quoted ("src") or bare (src); collect both.
            # Comments are already stripped and terminator lines have exited the
            # block above, so every remaining token on the line is a directory.
            for match in _DIRECTORY_TOKEN_RE.finditer(stripped):
                name = match.group("quoted")
                if name is None:
                    name = match.group("bare")
                if name:
                    subdirs.append(name)
    return subdirs


def resolve_thy_file(name: str, t_dir: Path | None = None) -> Path | None:
    """Resolve a declared theory ``name`` to its ``.thy`` file on disk.

    Searches the session root first, then each subdirectory declared under the
    ROOT's ``directories`` clause. Returns ``None`` if not found. ``t_dir``
    defaults to :func:`default_session_dir`.
    """
    if t_dir is None:
        t_dir = default_session_dir()
    candidate = t_dir / f"{name}.thy"
    if candidate.exists():
        return candidate
    root_path = t_dir / "ROOT"
    for sub in parse_root_directories(root_path):
        candidate = t_dir / sub / f"{name}.thy"
        if candidate.exists():
            return candidate
    return None


_IMPORTS_RE = re.compile(r"\bimports\b(.*?)\bbegin\b", re.DOTALL)


def parse_thy_imports(thy_path: Path) -> list[str]:
    """Return the ordered theory names from a ``.thy`` file's
    ``imports ... begin`` clause.

    Handles plain names (``Main``) and quoted qualified names
    (``"HOL-Library.FuncSet"``). The source is comment-stripped first, so a
    licence header or a commented-out ``imports ... begin`` line cannot hide the
    real clause or inject phantom imports. Returns the raw import names; callers
    decide whether each is in-project or external by cross-referencing a
    session's in-project theory list. Returns ``[]`` if the file is missing or
    has no imports clause.
    """
    if not thy_path.exists():
        return []
    cleaned = strip_isabelle_comments(thy_path.read_text(encoding="utf-8", errors="replace"))
    match = _IMPORTS_RE.search(cleaned)
    if not match:
        return []
    raw = match.group(1)
    tokens = re.findall(r'"([^"]+)"|(\S+)', raw)
    return [a or b for a, b in tokens]


def iter_thy_files(t_dir: Path | None = None) -> list[Path]:
    """Return the ordered ``.thy`` files declared by ROOT(s) under ``t_dir``.

    Two layouts are supported transparently:

    * **Single ROOT** (``t_dir/ROOT`` exists): order matches that ROOT's
      ``theories`` block; each theory is resolved at the session root first,
      then in declared subdirectories.
    * **Multi-ROOT** (no ``t_dir/ROOT``, but ROOTs in subdirectories): every
      session declared by every ROOT under ``t_dir`` is enumerated and its
      theories resolved against the declaring session's directory. Results are
      deduplicated by resolved path.

    Theory names with no matching file on disk are silently skipped, so callers
    can run against partial trees during a refactor.
    """
    if t_dir is None:
        t_dir = default_session_dir()
    out: list[Path] = []
    root_path = t_dir / "ROOT"
    if root_path.exists():
        for name in parse_root_theories(root_path):
            resolved = resolve_thy_file(name, t_dir=t_dir)
            if resolved is not None:
                out.append(resolved)
        return out
    seen: set[Path] = set()
    for session in iter_sessions(t_dir):
        for theory_entry in session.theories:
            resolved = resolve_session_theory(session, theory_entry)
            if resolved is not None and resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


# ---------------------------------------------------------------------------
# Multi-root / multi-session API
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """One ``session ...`` declaration parsed from a ROOT file.

    A ROOT may declare multiple sessions; each is captured separately so tools
    can enumerate theories and follow cross-session references accurately (e.g.
    resolving a theory under the session's ``in <subdir>`` clause rather than
    alongside the ROOT file).
    """

    name: str
    root_path: Path
    in_subdir: str | None
    parent: str | None
    used_sessions: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    theories: list[tuple[str, str | None]] = field(default_factory=list)

    @property
    def session_dir(self) -> Path:
        """Directory containing this session's ``.thy`` files."""
        if self.in_subdir:
            return self.root_path.parent / self.in_subdir
        return self.root_path.parent


# Keywords recognised by the ROOT tokeniser. Encountering one closes the
# previous stanza and opens a new one.
_ROOT_KEYWORDS = {
    "chapter",
    "session",
    "options",
    "sessions",
    "directories",
    "theories",
    "document_files",
    "document_theories",
    "export_files",
    "export_classpath",
    "global",
    "description",
    "in",
}

_OLD_DESC_RE = re.compile(r"\{\*.*?\*\}", re.DOTALL)
_ID_RE = re.compile(r"[A-Za-z0-9_./\-]+")
_OPEN_CARTOUCHE, _CLOSE_CARTOUCHE = r"\<open>", r"\<close>"
_TAG_RE = re.compile(r"\\<[A-Za-z_^]+>")


def _strip_cartouches(text: str) -> str:
    """Remove Isabelle cartouches ``\\<open>...\\<close>`` (nestable).

    Content inside a cartouche is descriptive text, not ROOT syntax, so it must
    not be tokenised -- otherwise prose inside a ``\\<comment> \\<open>...
    \\<close>`` spawns phantom sessions.
    """
    out: list[str] = []
    i, n = 0, len(text)
    depth = 0
    while i < n:
        if text.startswith(_OPEN_CARTOUCHE, i):
            depth += 1
            i += len(_OPEN_CARTOUCHE)
            continue
        if text.startswith(_CLOSE_CARTOUCHE, i):
            if depth > 0:
                depth -= 1
            i += len(_CLOSE_CARTOUCHE)
            continue
        if depth == 0:
            out.append(text[i])
        i += 1
    return "".join(out)


def _strip_root_comments(text: str) -> str:
    text = strip_isabelle_comments(text)  # nesting-aware (* ... *) removal
    text = _strip_cartouches(text)
    text = _OLD_DESC_RE.sub(" ", text)  # legacy {* ... *} description
    text = _TAG_RE.sub(" ", text)  # lone \<comment> etc. (after cartouches)
    return text


def _tokenize_root(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(kind, value)`` tokens from a ROOT file source.

    ``kind`` is one of ``"kw"``, ``"id"``, ``"str"``. Both ``[...]`` and
    ``(...)`` are skipped wholesale -- they hold options (``[document =
    false]``) and theory annotations (``Main (global)``) that should not leak
    their internal identifiers. ``=`` and ``+`` are dropped (structural
    session-header punctuation).
    """
    text = _strip_root_comments(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = text.find('"', i + 1)
            if j < 0:
                return
            yield ("str", text[i + 1 : j])
            i = j + 1
            continue
        if c in "[(":
            close = "]" if c == "[" else ")"
            opener = c
            depth = 1
            j = i + 1
            while j < n and depth:
                if text[j] == opener:
                    depth += 1
                elif text[j] == close:
                    depth -= 1
                j += 1
            i = j
            continue
        if c in "=+)]":
            i += 1
            continue
        m = _ID_RE.match(text, i)
        if not m:
            i += 1
            continue
        tok = m.group()
        i = m.end()
        yield ("kw" if tok in _ROOT_KEYWORDS else "id", tok)


def parse_root_sessions(root_path: Path) -> list[SessionInfo]:
    """Parse every ``session ...`` declaration from a ROOT file.

    Returns sessions in declaration order; ``[]`` if the file is missing or
    declares no sessions. Handles session-level ``in <subdir>`` and parent
    (after ``=``), per-theory ``in <subdir>`` overrides, ``(...)``-wrapped
    options, ``(* comments *)``, ``\\<open>...\\<close>`` cartouches, and
    ``{* legacy descriptions *}``.
    """
    if not root_path.exists():
        return []
    text = root_path.read_text(encoding="utf-8", errors="replace")
    toks = list(_tokenize_root(text))
    out: list[SessionInfo] = []
    abs_root = root_path.resolve()

    cur: SessionInfo | None = None
    state: str | None = None
    pending_theory: tuple[str, str | None] | None = None

    def flush_pending() -> None:
        nonlocal pending_theory
        if pending_theory is not None and cur is not None:
            cur.theories.append(pending_theory)
            pending_theory = None

    i = 0
    while i < len(toks):
        kind, val = toks[i]
        if kind == "kw":
            # ``in`` modifies the current session header or the pending theory,
            # so it must not flush the pending theory before being handled.
            if val != "in":
                flush_pending()
            if val == "session":
                if cur is not None:
                    out.append(cur)
                cur = SessionInfo(name="<anon>", root_path=abs_root, in_subdir=None, parent=None)
                if i + 1 < len(toks) and toks[i + 1][0] in ("id", "str"):
                    cur.name = toks[i + 1][1]
                    i += 2
                else:
                    i += 1
                state = "session_header"
                continue
            if val == "in":
                target_arg = i + 1 < len(toks) and toks[i + 1][0] in ("id", "str")
                if state == "session_header" and target_arg and cur is not None:
                    cur.in_subdir = toks[i + 1][1]
                    i += 2
                    continue
                if pending_theory is not None and target_arg:
                    pending_theory = (pending_theory[0], toks[i + 1][1])
                    i += 2
                    continue
                i += 1
                continue
            state = val
            i += 1
            continue
        # id / str token
        if cur is not None:
            if state == "session_header":
                cur.parent = val
                state = None
            elif state == "theories":
                flush_pending()
                pending_theory = (val, None)
            elif state == "directories":
                cur.directories.append(val)
            elif state == "sessions":
                cur.used_sessions.append(val)
        i += 1
    flush_pending()
    if cur is not None:
        out.append(cur)
    return out


def resolve_session_theory(
    session: SessionInfo,
    theory_entry: tuple[str, str | None] | str,
) -> Path | None:
    """Resolve a session-owned theory to its ``.thy`` file on disk.

    ``theory_entry`` is either a ``(name, dir_override)`` tuple (the shape
    :attr:`SessionInfo.theories` produces) or a bare ``name`` string. Search
    order: per-theory ``dir_override``, the session directory, each declared
    ``directories`` subdir, then a unique ``rglob`` fallback.
    """
    if isinstance(theory_entry, tuple):
        name, dir_override = theory_entry
    else:
        name, dir_override = theory_entry, None
    base = session.session_dir
    candidates: list[Path] = []
    if dir_override is not None:
        candidates.append(base / dir_override / f"{name}.thy")
    candidates.append(base / f"{name}.thy")
    for sub in session.directories:
        candidates.append(base / sub / f"{name}.thy")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    leaf = Path(name).name + ".thy"
    matches = list(base.rglob(leaf)) if base.exists() else []
    return matches[0] if len(matches) == 1 else None


def discover_roots(root_dir: Path) -> list[Path]:
    """Find every ``ROOT`` file under ``root_dir`` (recursive, sorted).

    Skips hidden directories. ROOT files that declare no sessions are still
    returned; :func:`parse_root_sessions` yields ``[]`` for them.
    """
    if not root_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(root_dir.rglob("ROOT")):
        # Only skip ROOTs nested under a hidden directory *within* root_dir;
        # checking path.parts would also match a dotted ancestor of root_dir
        # itself (e.g. /home/user/.local/proj), wrongly skipping everything.
        if any(part.startswith(".") for part in path.relative_to(root_dir).parts):
            continue
        if path.is_file():
            out.append(path.resolve())
    return out


def iter_sessions(root_dir: Path) -> list[SessionInfo]:
    """Return every session declared by any ROOT under ``root_dir``."""
    out: list[SessionInfo] = []
    for root_path in discover_roots(root_dir):
        out.extend(parse_root_sessions(root_path))
    return out
