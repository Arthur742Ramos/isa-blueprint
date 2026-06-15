"""Source-only theory index: entries, call graph, imports, and ``sorry``s.

This module computes a best-effort index of an Isabelle session **directly from
its ``.thy`` sources**, with no dependency on the ``isabelle`` binary. It powers
the offline analyses inspired by `ott2/isabelle-query
<https://github.com/ott2/isabelle-query>`_ (MIT): a cross-theory reference
("call") graph, the theory import graph, ``sorry`` / ``oops`` detection, and
unreferenced-entry analysis.

Everything here is *textual and best-effort*. Identifier matching honours
Isabelle primes (``'``) and dotted qualified names, but does not model symbolic
operators, mixfix syntax, locale qualification, or generated facts
(``foo.simps``). Treat references as a strong hint, not ground truth -- the
authoritative dependency/proof data still comes from ``isabelle`` via
``check`` / ``dump``.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from isabelle_blueprint.isabelle.root import parse_thy_imports
from isabelle_blueprint.isabelle.theory_import import (
    ImportedTheoryFact,
    make_node_id,
    strip_isabelle_comments,
)

# Blueprint-ready facts reuse the importer's fact type so the existing renderers
# (`render_imported_blueprint` / `imported_theory_review`) consume them directly.
ImportedFact = ImportedTheoryFact

# Source declaration kinds the index understands. Broader than the blueprint
# importer's set so references to functions/datatypes/etc. resolve.
_FACT_KINDS = (
    "definition",
    "abbreviation",
    "fun",
    "primrec",
    "inductive_set",
    "inductive",
    "lemma",
    "corollary",
    "theorem",
    "proposition",
)
_TYPE_KINDS = ("datatype", "type_synonym", "record")
DECL_KINDS = _FACT_KINDS + _TYPE_KINDS

# Map a source declaration kind onto the closest blueprint node kind. Used when
# bootstrapping a blueprint from a whole session.
KIND_TO_BLUEPRINT_KIND = {
    "definition": "definition",
    "abbreviation": "definition",
    "fun": "definition",
    "primrec": "definition",
    "inductive": "definition",
    "inductive_set": "definition",
    "datatype": "definition",
    "type_synonym": "definition",
    "record": "definition",
    "lemma": "lemma",
    "corollary": "corollary",
    "theorem": "theorem",
    "proposition": "proposition",
}

_THEORY_RE = re.compile(r"(?m)^\s*theory\s+([A-Za-z_][\w'.]*)\b")
_KIND_RE = re.compile(r"(?m)^[ \t]*(?P<kind>" + "|".join(DECL_KINDS) + r")\b")
_NAME_TOK_RE = re.compile(r'"(?P<q>[^"]+)"|(?P<id>[A-Za-z_][\w\'.]*)')
_TYPE_ARG_RE = re.compile(r"'[\w']+\s+")
_SORRY_RE = re.compile(r"(?<![\w'])(?P<tok>sorry|oops)(?![\w'])")

_OPEN_CARTOUCHE, _CLOSE_CARTOUCHE = r"\<open>", r"\<close>"


def _blank_cartouches(text: str) -> str:
    """Replace the contents of Isabelle cartouches ``\\<open>...\\<close>`` with
    spaces, preserving length and newlines.

    Cartouches hold descriptive prose (for example ``text \\<open>... sorry
    ...\\<close>``), not proof commands, so scanning their text for ``sorry`` /
    ``oops`` yields false proof-gap markers. Blanking keeps every offset and line
    number aligned with the source while removing the prose from the scan.
    """
    out = list(text)
    depth = 0
    i, n = 0, len(text)
    olen, clen = len(_OPEN_CARTOUCHE), len(_CLOSE_CARTOUCHE)
    while i < n:
        if text.startswith(_OPEN_CARTOUCHE, i):
            for j in range(i, i + olen):
                if out[j] != "\n":
                    out[j] = " "
            depth += 1
            i += olen
            continue
        if depth > 0 and text.startswith(_CLOSE_CARTOUCHE, i):
            for j in range(i, i + clen):
                if out[j] != "\n":
                    out[j] = " "
            depth -= 1
            i += clen
            continue
        if depth > 0 and out[i] != "\n":
            out[i] = " "
        i += 1
    return "".join(out)

# Isar lemma/definition keywords that may sit where a name would and must never
# be captured as one.
_RESERVED_NAMES = frozenset(
    {
        "assumes",
        "shows",
        "fixes",
        "obtains",
        "notes",
        "includes",
        "and",
        "where",
        "for",
        "if",
        "by",
        "using",
        "unfolding",
        "qualified",
    }
)


@dataclass(frozen=True)
class SourceEntry:
    """A top-level declaration parsed from a ``.thy`` source."""

    kind: str
    name: str
    theory: str
    line: int
    path: str

    @property
    def key(self) -> str:
        return f"{self.theory}.{self.name}"


@dataclass(frozen=True)
class SorryMarker:
    """A ``sorry`` / ``oops`` occurrence located in the sources."""

    theory: str
    line: int
    token: str
    entry: str | None
    path: str


def _balanced_parens_end(text: str, start: int) -> int:
    """Return the index just past the ``)`` matching ``text[start] == '('``."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _strip_leading_parens(text: str) -> str:
    """Drop leading ``(...)`` groups -- locale specs, options, paren type-args."""
    s = text.lstrip()
    while s.startswith("("):
        end = _balanced_parens_end(s, 0)
        s = s[end:].lstrip()
    return s


def _parse_entry_name(kind: str, after: str) -> str | None:
    """Parse a declaration's name from the text following its keyword.

    Returns ``None`` for anonymous declarations (``lemma "stmt"``) or when no
    plausible name is found.
    """
    s = _strip_leading_parens(after)
    if kind in _TYPE_KINDS:
        while True:
            m = _TYPE_ARG_RE.match(s)
            if not m:
                break
            s = s[m.end() :]
        token = _NAME_TOK_RE.match(s)
        if not token:
            return None
        name = token.group("q") or token.group("id")
        return name
    # Fact / definition-like: a name is followed (after optional [attrs]) by one
    # of :: / : / where / = .
    token = _NAME_TOK_RE.match(s)
    if not token:
        return None
    name = token.group("q") or token.group("id")
    if name is None or name in _RESERVED_NAMES:
        return None
    rest = s[token.end() :].lstrip()
    if rest.startswith("["):
        close = rest.find("]")
        if close >= 0:
            rest = rest[close + 1 :].lstrip()
    if token.group("q") is not None:
        # A quoted spelling is a name only when it labels the statement.
        return name if rest.startswith(":") else None
    if rest.startswith(("::", ":", "=")) or rest.startswith("where"):
        return name
    return None


@dataclass
class _ParsedEntry:
    entry: SourceEntry
    start: int
    end: int
    body: str


def _parse_file(path: Path) -> tuple[str, list[_ParsedEntry], list[str], str]:
    """Parse one ``.thy`` file into (theory_name, entries, raw_imports, cleaned)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_isabelle_comments(text)
    theory_match = _THEORY_RE.search(cleaned)
    theory = theory_match.group(1) if theory_match else path.stem
    matches = list(_KIND_RE.finditer(cleaned))
    parsed: list[_ParsedEntry] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        kind = match.group("kind")
        name = _parse_entry_name(kind, cleaned[match.end() : match.end() + 400])
        if name is None:
            continue
        line = cleaned.count("\n", 0, start) + 1
        entry = SourceEntry(kind=kind, name=name, theory=theory, line=line, path=str(path))
        parsed.append(_ParsedEntry(entry=entry, start=start, end=end, body=cleaned[start:end]))
    imports = parse_thy_imports(path)
    return theory, parsed, imports, cleaned


def _topo_order(
    theories: list[str], in_proj_imports: dict[str, list[str]]
) -> tuple[list[str], bool]:
    """Kahn topological sort: imported theories before importers.

    Returns ``(ordered, has_cycle)``. On a cycle the leftover theories are
    appended in declaration order so callers still get a total order.
    """
    indegree = {t: 0 for t in theories}
    children: dict[str, list[str]] = {t: [] for t in theories}
    for theory in theories:
        for imp in in_proj_imports.get(theory, []):
            if imp in indegree:
                children[imp].append(theory)
                indegree[theory] += 1
    queue = deque(t for t in theories if indegree[t] == 0)
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    has_cycle = len(ordered) < len(theories)
    if has_cycle:
        remaining = [t for t in theories if t not in set(ordered)]
        ordered.extend(remaining)
    return ordered, has_cycle


class SourceIndex:
    """A best-effort, source-only index over a set of ``.thy`` files."""

    def __init__(self, paths: list[Path]):
        self.entries: list[SourceEntry] = []
        self.theory_order: list[str] = []
        self.theory_paths: dict[str, str] = {}
        self.theory_imports: dict[str, list[str]] = {}
        self.sorries: list[SorryMarker] = []
        self._entry_by_key: dict[str, SourceEntry] = {}
        self._body_by_key: dict[str, str] = {}

        for path in paths:
            theory, parsed, imports, cleaned = _parse_file(path)
            if theory not in self.theory_paths:
                self.theory_order.append(theory)
                self.theory_paths[theory] = str(path)
                self.theory_imports[theory] = imports
            for item in parsed:
                self.entries.append(item.entry)
                if item.entry.key not in self._entry_by_key:
                    self._entry_by_key[item.entry.key] = item.entry
                    self._body_by_key[item.entry.key] = item.body
            self._collect_sorries(theory, str(path), cleaned, parsed)

        self.theory_set = set(self.theory_order)
        self.in_project_imports: dict[str, list[str]] = {
            theory: [imp for imp in imports if imp in self.theory_set]
            for theory, imports in self.theory_imports.items()
        }
        self.external_imports: dict[str, list[str]] = {
            theory: [imp for imp in imports if imp not in self.theory_set]
            for theory, imports in self.theory_imports.items()
        }
        self.theory_topo_order, self.has_import_cycle = _topo_order(
            self.theory_order, self.in_project_imports
        )
        self.reference_graph = self._build_reference_graph()
        self._reverse_graph = self._build_reverse_graph()
        self._order_index = self._build_order_index()

    # -- construction helpers ------------------------------------------------

    def _collect_sorries(
        self, theory: str, path: str, cleaned: str, parsed: list[_ParsedEntry]
    ) -> None:
        scan_source = _blank_cartouches(cleaned)
        for match in _SORRY_RE.finditer(scan_source):
            offset = match.start()
            line = scan_source.count("\n", 0, offset) + 1
            enclosing = next(
                (p.entry.name for p in parsed if p.start <= offset < p.end), None
            )
            self.sorries.append(
                SorryMarker(
                    theory=theory,
                    line=line,
                    token=match.group("tok"),
                    entry=enclosing,
                    path=path,
                )
            )

    def _build_reference_graph(self) -> dict[str, set[str]]:
        keys = set(self._entry_by_key)
        by_short: dict[str, list[str]] = {}
        for key, entry in self._entry_by_key.items():
            by_short.setdefault(entry.name, []).append(key)

        short_names = sorted(
            {name for name in by_short if len(name) >= 2}, key=len, reverse=True
        )
        qualified = sorted(keys, key=len, reverse=True)
        short_re = (
            re.compile(
                r"(?<![\w'.])(?:" + "|".join(re.escape(n) for n in short_names) + r")(?![\w'.])"
            )
            if short_names
            else None
        )
        qual_re = (
            re.compile(
                r"(?<![\w'])(?:" + "|".join(re.escape(k) for k in qualified) + r")(?![\w'.])"
            )
            if qualified
            else None
        )

        graph: dict[str, set[str]] = {}
        for key, entry in self._entry_by_key.items():
            body = self._body_by_key[key]
            refs: set[str] = set()
            if qual_re is not None:
                for match in qual_re.finditer(body):
                    refs.add(match.group())
            if short_re is not None:
                for match in short_re.finditer(body):
                    short = match.group()
                    same_theory = f"{entry.theory}.{short}"
                    if same_theory in keys:
                        refs.add(same_theory)
                    else:
                        candidates = by_short.get(short, [])
                        if len(candidates) == 1:
                            refs.add(candidates[0])
            refs.discard(key)
            graph[key] = refs
        return graph

    def _build_reverse_graph(self) -> dict[str, set[str]]:
        reverse: dict[str, set[str]] = {key: set() for key in self._entry_by_key}
        for caller, callees in self.reference_graph.items():
            for callee in callees:
                reverse.setdefault(callee, set()).add(caller)
        return reverse

    def _build_order_index(self) -> dict[str, int]:
        theory_rank = {theory: rank for rank, theory in enumerate(self.theory_topo_order)}
        ordered_keys = sorted(
            self._entry_by_key.values(),
            key=lambda e: (theory_rank.get(e.theory, len(theory_rank)), e.line, e.name),
        )
        return {entry.key: index for index, entry in enumerate(ordered_keys)}

    # -- public queries ------------------------------------------------------

    def resolve(self, name: str) -> list[str]:
        """Resolve a short or qualified name to matching entry keys."""
        if name in self._entry_by_key:
            return [name]
        return sorted(key for key, entry in self._entry_by_key.items() if entry.name == name)

    def callees(self, name: str, *, transitive: bool = False) -> list[str]:
        return self._walk(name, self.reference_graph, transitive)

    def callers(self, name: str, *, transitive: bool = False) -> list[str]:
        return self._walk(name, self._reverse_graph, transitive)

    def _walk(self, name: str, graph: dict[str, set[str]], transitive: bool) -> list[str]:
        seeds = self.resolve(name)
        result: set[str] = set()
        queue: deque[str] = deque()
        for seed in seeds:
            for nxt in graph.get(seed, set()):
                if nxt not in result:
                    result.add(nxt)
                    queue.append(nxt)
        if transitive:
            while queue:
                node = queue.popleft()
                for nxt in graph.get(node, set()):
                    if nxt not in result:
                        result.add(nxt)
                        queue.append(nxt)
        result.difference_update(seeds)
        return sorted(result, key=lambda k: self._order_index.get(k, 0))

    def theory_deps(self, theory: str) -> tuple[list[str], list[str]]:
        """Return ``(imports_in_project, imported_by)`` for ``theory``."""
        imports = sorted(self.in_project_imports.get(theory, []))
        imported_by = sorted(
            other
            for other, deps in self.in_project_imports.items()
            if theory in deps
        )
        return imports, imported_by

    def unreferenced_entries(self) -> list[str]:
        """Entry keys not referenced by any other indexed entry.

        This is *not* dead-code analysis: Isabelle exports facts and constants
        for downstream sessions, automation, code generation, and locales that
        this single-tree textual scan cannot see.
        """
        return sorted(
            (key for key in self._entry_by_key if not self._reverse_graph.get(key)),
            key=lambda k: self._order_index.get(k, 0),
        )

    def imported_facts(self) -> list[ImportedFact]:
        """Build blueprint-ready facts in global acyclic order.

        ``uses`` for each fact lists the node ids of referenced facts that come
        *earlier* in the global order, which guarantees an acyclic dependency
        graph (the blueprint validator rejects cycles).
        """
        ordered = sorted(
            self._entry_by_key.values(), key=lambda e: self._order_index[e.key]
        )
        used_ids: set[str] = set()
        node_id_by_key: dict[str, str] = {}
        for entry in ordered:
            node_id_by_key[entry.key] = make_node_id(entry.theory, entry.name, used_ids)
        facts: list[ImportedFact] = []
        for entry in ordered:
            earlier = [
                ref
                for ref in self.reference_graph.get(entry.key, set())
                if ref in self._order_index
                and self._order_index[ref] < self._order_index[entry.key]
            ]
            earlier.sort(key=lambda k: self._order_index[k])
            facts.append(
                ImportedFact(
                    kind=KIND_TO_BLUEPRINT_KIND.get(entry.kind, "other"),
                    name=entry.name,
                    theory=entry.theory,
                    line=entry.line,
                    node_id=node_id_by_key[entry.key],
                    uses=tuple(node_id_by_key[ref] for ref in earlier),
                )
            )
        return facts

    def counts(self) -> dict[str, int]:
        """Compact numeric summary of the index (source-only, no Isabelle)."""
        entries_with_sorry = {
            f"{m.theory}.{m.entry}" for m in self.sorries if m.entry is not None
        }
        import_edges = sum(
            len(set(deps)) for deps in self.in_project_imports.values()
        )
        return {
            "theories": len(self.theory_order),
            "entries": len(self.entries),
            "sorry_entries": len(entries_with_sorry),
            "unreferenced": len(self.unreferenced_entries()),
            "import_edges": import_edges,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "theories": [
                {
                    "name": theory,
                    "path": self.theory_paths[theory],
                    "imports": sorted(self.in_project_imports.get(theory, [])),
                    "external_imports": sorted(self.external_imports.get(theory, [])),
                    "imported_by": self.theory_deps(theory)[1],
                    "entry_count": sum(1 for e in self.entries if e.theory == theory),
                }
                for theory in self.theory_order
            ],
            "entries": [
                {
                    "key": entry.key,
                    "kind": entry.kind,
                    "name": entry.name,
                    "theory": entry.theory,
                    "line": entry.line,
                    "references": sorted(self.reference_graph.get(entry.key, set())),
                }
                for entry in sorted(
                    self._entry_by_key.values(), key=lambda e: self._order_index[e.key]
                )
            ],
            "sorries": [
                {
                    "theory": marker.theory,
                    "line": marker.line,
                    "token": marker.token,
                    "entry": marker.entry,
                }
                for marker in self.sorries
            ],
            "unreferenced": self.unreferenced_entries(),
            "has_import_cycle": self.has_import_cycle,
        }


def build_index(paths: list[Path]) -> SourceIndex:
    """Build a :class:`SourceIndex` from the given ``.thy`` paths."""
    return SourceIndex(paths)


def session_theory_files(session_dir: Path, session_name: str | None = None) -> list[Path]:
    """Resolve the ``.thy`` files of a session directory.

    Prefers ``session ...`` declarations in ``session_dir/ROOT``. When
    ``session_name`` is given it is honoured strictly: an unknown name, or one
    that resolves no theory files, raises :class:`ValueError` (never a silent
    fallback). Without a name, a single session is used and an ambiguous tree
    raises :class:`ValueError`. Falls back to a plain ``theories`` block or
    multi-ROOT discovery only when no ``session`` declaration provides theories.
    """
    from isabelle_blueprint.isabelle import root as root_mod

    def _resolve(sessions: list[root_mod.SessionInfo]) -> list[Path]:
        files: list[Path] = []
        seen: set[Path] = set()
        for session in sessions:
            for theory_entry in session.theories:
                resolved = root_mod.resolve_session_theory(session, theory_entry)
                if resolved is not None and resolved not in seen:
                    seen.add(resolved)
                    files.append(resolved)
        return files

    root_path = session_dir / "ROOT"
    sessions = (
        root_mod.parse_root_sessions(root_path)
        if root_path.exists()
        else root_mod.iter_sessions(session_dir)
    )

    if session_name is not None:
        selected = [s for s in sessions if s.name == session_name]
        if not selected:
            available = ", ".join(sorted(s.name for s in sessions)) or "none"
            raise ValueError(
                f"session {session_name!r} not found in {session_dir} (available: {available})"
            )
        files = _resolve(selected)
        if not files:
            raise ValueError(
                f"session {session_name!r} declares no resolvable theory files under {session_dir}"
            )
        return files

    with_theories = [s for s in sessions if s.theories]
    if len(with_theories) > 1:
        available = ", ".join(sorted(s.name for s in with_theories))
        raise ValueError(
            f"multiple sessions under {session_dir}; pass --session NAME (available: {available})"
        )
    if with_theories:
        files = _resolve(with_theories)
        if files:
            return files
    return root_mod.iter_thy_files(session_dir)
