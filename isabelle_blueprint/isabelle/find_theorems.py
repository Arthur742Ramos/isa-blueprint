"""Run Isabelle's ``find_theorems`` over the configured session.

This is the *running-Isabelle* counterpart to
:mod:`isabelle_blueprint.isabelle.fact_search`: where ``search-facts`` (default
mode) ranks declarations parsed from the ``.thy`` *sources*, the ``--isabelle``
mode driven by this module asks a real Isabelle process to evaluate
``find_theorems`` and return genuine candidate facts (name, theory, proposition)
for a query such as ``name: add_0`` or the pattern ``"_ + 0 = _"``.

It mirrors :mod:`isabelle_blueprint.isabelle.checker` and
:mod:`isabelle_blueprint.isabelle.sledgehammer`: it is tolerant of a missing
``isabelle`` binary or unconfigured session and never raises -- every failure
mode is folded into a :class:`FindTheoremsResult`.

Because batch ``isabelle build`` suppresses ``find_theorems``/``writeln`` stdout,
the generated wrapper theory writes the hits to a TSV file which we read back
here -- exactly the pattern the proof-status checker uses.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from isabelle_blueprint.isabelle._run import run_capture
from isabelle_blueprint.isabelle.theory_gen import (
    _comment_escape,
    _ml_string,
    generate_check_root,
    group_facts_by_theory,
)
from isabelle_blueprint.model.project import BlueprintProject

_THEORY_NAME = "Blueprint_Search"
_WRAPPER_SESSION = "Blueprint_Search_Wrapper"
_RESULT_FILE = "Blueprint_Search.tsv"

_DEFAULT_TIMEOUT = 120.0

# ``find_theorems`` criterion keywords. A query that opens with one of these (or
# already contains a quoted pattern) is a structured query and is passed to
# ``read_query`` verbatim; anything else is a bare term pattern that must be
# wrapped in double quotes so ``read_query`` parses it as a pattern criterion
# rather than choking on operators like ``+``.
_CRITERION_RE = re.compile(r"^-?\s*(name|intro|elim|dest|solves|simp)\b", re.IGNORECASE)


def normalize_query(query: str) -> str:
    """Return *query* shaped for ``Find_Theorems.read_query``.

    A structured query (``name: add_0``, ``intro``, ``simp: foo``) or one that
    already contains a quoted pattern is returned unchanged. A bare term such as
    ``_ + 0 = _`` is wrapped in double quotes so it is parsed as a *pattern*
    criterion -- without the quotes ``read_query`` reports an inner-syntax error
    on the first operator.
    """
    q = query.strip()
    if not q or '"' in q or _CRITERION_RE.match(q):
        return q
    return f'"{q}"'


@dataclass
class FindTheoremsResult:
    """Outcome of running ``find_theorems`` for one query."""

    ran: bool
    isabelle_available: bool = False
    return_code: int | None = None
    error: str | None = None
    query: str | None = None
    hits: list[dict] = field(default_factory=list)
    found_count: int = 0
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    generated_theory_path: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


def parse_find_theorems_tsv(text: str) -> list[dict]:
    """Parse the hits TSV written by the generated wrapper theory.

    Each non-blank line is ``"<name>\\t<theory>\\t<proposition>"``; trailing
    columns are tolerated (a hit whose proposition is empty still yields a
    record). Returns a list of ``{"name", "theory", "prop"}`` dicts in file
    order. Blank input yields an empty list.
    """
    hits: list[dict] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        name = parts[0].strip()
        if not name:
            continue
        theory = parts[1].strip() if len(parts) > 1 else ""
        # The proposition can legitimately contain leading/trailing spaces from
        # the term pretty-printer; collapse only the surrounding whitespace.
        prop = parts[2].strip() if len(parts) > 2 else ""
        hits.append({"name": name, "theory": theory, "prop": prop})
    return hits


def generate_find_theorems_theory(
    query: str,
    *,
    limit: int,
    result_file: str,
    theory_name: str = _THEORY_NAME,
    imports: list[str] | None = None,
    nonce: str | None = None,
) -> str:
    """Return the source of a wrapper theory that runs ``find_theorems``.

    The theory imports ``Main`` (within the configured session's heap, supplied
    by the wrapper ROOT) and evaluates ``Find_Theorems.find_theorems_cmd`` for
    *query*, writing ``name\\ttheory\\tproposition`` rows to *result_file*.
    """
    imp_list = list(imports) if imports else ["Main"]
    safe_limit = max(1, int(limit))

    lines: list[str] = []
    lines.append(f"theory {theory_name}")
    lines.append("  imports")
    for imp in imp_list:
        lines.append(f'    "{imp}"')
    lines.append("begin")
    lines.append("")
    lines.append("(* Auto-generated by IsabelleBlueprint. Do not edit by hand. *)")
    lines.append(f"(* find_theorems query: {_comment_escape(query)} *)")
    if nonce:
        # Force ``isabelle build`` to re-run the ML on every invocation: an
        # unchanged wrapper session is cached in the global heap and the ML (and
        # thus the result file) would never run again. A fresh nonce per run
        # perturbs the theory source so the session is always rebuilt.
        lines.append(f"(* Run nonce: {_comment_escape(nonce)} *)")
    lines.append("")
    lines.extend(_find_theorems_ml_block(query=query, limit=safe_limit, result_file=result_file))
    lines.append("")
    lines.append("end")
    return "\n".join(lines) + "\n"


def _query_ml_literal(query: str) -> str:
    """Return *query* as an ML double-quoted string literal for ``read_query``.

    The normalized query is inner syntax (a quoted pattern such as ``"_ + 0 = _"``
    or a structured criterion like ``name: add_0``) that Isabelle parses *after*
    its symbol layer has run. Exactly like the sledgehammer goal path's
    ``theory_gen._thy_inner_string``, only the double quote is escaped -- so an
    inner ``"`` cannot terminate the ML string literal early -- and control
    whitespace is collapsed. Backslashes are deliberately **not** doubled: an
    Isabelle symbol token such as ``\\<le>`` is rewritten to its Unicode glyph by
    the symbol layer before the SML lexer sees the string, so doubling the
    backslash would leave a stray ``\\`` in front of that glyph that SML rejects
    as a "bad escape character", breaking the build for any query that names a
    symbolic operator.
    """
    text = re.sub(r"[\r\n\t]+", " ", normalize_query(query))
    return '"' + text.replace('"', '\\"') + '"'


def _find_theorems_ml_block(*, query: str, limit: int, result_file: str) -> list[str]:
    """Render the ML block that runs ``find_theorems`` and writes a hits TSV."""
    query_lit = _query_ml_literal(query)
    result_lit = _ml_string(result_file)
    return [
        "ML \\<open>",
        "let",
        "  fun strip s = XML.content_of (YXML.parse_body s)",
        "  fun clean s = String.translate",
        '    (fn c => if c = #"\\n" orelse c = #"\\t" orelse c = #"\\r"',
        '             then " " else String.str c) s',
        "  val ctxt = @{context}",
        "  val ctxt' = ctxt |> Config.put show_markup false |> Config.put show_types false",
        f"  val criteria = Find_Theorems.read_query Position.none {query_lit}",
        "  val (_, results) =",
        f"    Find_Theorems.find_theorems_cmd ctxt NONE (SOME {limit}) true criteria",
        "  fun render (thm_name, thm) =",
        "    let",
        "      val name = Thm_Name.print thm_name",
        "      val thy = Thm.theory_name {long=false} thm",
        "      val prop = clean (strip (Syntax.string_of_term ctxt' (Thm.prop_of thm)))",
        '    in name ^ "\\t" ^ thy ^ "\\t" ^ prop end',
        "in",
        f'  File.write (Path.explode {result_lit}) (cat_lines (map render results) ^ "\\n")',
        "end",
        "\\<close>",
    ]


def run_find_theorems(
    project: BlueprintProject,
    *,
    query: str,
    limit: int = 20,
    build_dir: Path,
    session_name: str | None = None,
    isabelle_executable: str = "isabelle",
    extra_dirs: list[Path] | None = None,
    project_root: Path | None = None,
    timeout: float | None = None,
    jobs: int | None = None,
) -> FindTheoremsResult:
    """Generate a wrapper theory and run ``isabelle build`` to evaluate a query.

    As with the checker, a missing ``isabelle`` binary or unconfigured session
    short-circuits to ``ran=False`` with an explanatory ``error`` rather than
    raising. On success ``hits`` holds the parsed ``find_theorems`` candidates.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    result_path = build_dir / _RESULT_FILE
    # A stale TSV from a prior run would be misread as the current outcome.
    try:
        result_path.unlink()
    except FileNotFoundError:
        pass

    theory_text = generate_find_theorems_theory(
        query,
        limit=limit,
        result_file=result_path.name,
        theory_name=_THEORY_NAME,
        nonce=f"{datetime.now(UTC).isoformat()}-{uuid.uuid4().hex}",
    )
    theory_path = build_dir / f"{_THEORY_NAME}.thy"
    theory_path.write_text(theory_text, encoding="utf-8")

    resolved_isabelle = shutil.which(isabelle_executable)
    isabelle_available = resolved_isabelle is not None
    result = FindTheoremsResult(
        ran=False,
        isabelle_available=isabelle_available,
        query=query,
        generated_theory_path=str(theory_path),
    )

    if not isabelle_available:
        result.error = (
            f"Isabelle executable {isabelle_executable!r} not found on PATH; "
            "skipped find_theorems run."
        )
        return result

    if session_name is None:
        result.error = (
            "No Isabelle session configured (set [isabelle].session in "
            "isabelle-blueprint.toml); skipped find_theorems run."
        )
        return result

    grouped = group_facts_by_theory(project)
    session_deps = sorted(
        {
            ref.session
            for theory_refs in grouped.values()
            for ref in theory_refs
            if ref.session and ref.session != session_name
        }
    )
    (build_dir / "ROOT").write_text(
        generate_check_root(
            session_name,
            wrapper_name=_WRAPPER_SESSION,
            theory_name=_THEORY_NAME,
            session_deps=session_deps,
        ),
        encoding="utf-8",
    )

    cmd = [resolved_isabelle or isabelle_executable, "build", "-d", str(build_dir)]
    if project_root is not None:
        cmd.extend(["-d", str(project_root)])
    for d in extra_dirs or []:
        cmd.extend(["-d", str(d)])
    if jobs is not None and jobs > 0:
        cmd.extend(["-j", str(jobs)])
    cmd.append(_WRAPPER_SESSION)

    build_timeout = _DEFAULT_TIMEOUT if timeout is None else float(timeout)
    start = time.monotonic()
    try:
        proc = run_capture(cmd, cwd=str(build_dir), timeout=build_timeout)
    except subprocess.TimeoutExpired:
        result.error = (
            f"isabelle build timed out after {build_timeout:.0f}s; "
            "increase [isabelle].timeout in isabelle-blueprint.toml or pass --timeout"
        )
        return result
    except OSError as exc:
        result.error = f"failed to invoke {isabelle_executable!r}: {exc}"
        result.isabelle_available = False
        return result
    finally:
        result.duration_seconds = time.monotonic() - start

    result.ran = True
    result.return_code = proc.returncode
    result.stdout = proc.stdout
    result.stderr = proc.stderr

    if result_path.exists():
        tsv = result_path.read_text(encoding="utf-8", errors="ignore")
        result.hits = parse_find_theorems_tsv(tsv)
        result.found_count = len(result.hits)
        # A non-zero exit with no hits file is a build failure (e.g. an
        # unparseable query); surface it so the caller can treat it as a blocker.
        if not result.hits and proc.returncode != 0:
            result.error = f"isabelle build returned {proc.returncode} (find_theorems run failed)"
    else:
        result.error = (
            f"isabelle build returned {proc.returncode} without writing a find_theorems result file"
        )

    return result


def render_find_theorems(result: FindTheoremsResult) -> str:
    """Render a :class:`FindTheoremsResult` as human-facing text (trailing newline)."""
    query = result.query or ""
    if not result.ran:
        reason = result.error or "find_theorems did not run"
        return f"find_theorems for {query!r}: skipped ({reason})\n"
    if not result.hits:
        return f"no theorems match {query!r}\n"
    lines = [f"find_theorems matches for {query!r}:"]
    for hit in result.hits:
        lines.append(f"  {hit['name']}  [{hit['theory']}]  {hit['prop']}")
    return "\n".join(lines) + "\n"


__all__ = [
    "FindTheoremsResult",
    "generate_find_theorems_theory",
    "normalize_query",
    "parse_find_theorems_tsv",
    "render_find_theorems",
    "run_find_theorems",
]
