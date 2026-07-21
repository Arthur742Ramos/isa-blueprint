"""Exception hierarchy used across IsabelleBlueprint."""


class BlueprintError(Exception):
    """Base class for all IsabelleBlueprint errors."""


class ParseError(BlueprintError):
    """The blueprint source could not be parsed."""

    def __init__(self, message: str, *, source: str | None = None, line: int | None = None):
        self.source = source
        self.line = line
        location = ""
        if source and line is not None:
            location = f" ({source}:{line})"
        elif source:
            location = f" ({source})"
        elif line is not None:
            location = f" (line {line})"
        super().__init__(message + location)


class ValidationError(BlueprintError):
    """The parsed blueprint failed semantic validation (cycles, duplicates, missing deps)."""

    def __init__(self, message: str, issues: list[str] | None = None):
        self.issues = issues or []
        super().__init__(message)


class CheckerError(BlueprintError):
    """The Isabelle checker could not be invoked or produced unexpected output."""


class UnknownNodeError(BlueprintError, KeyError):
    """A referenced node id is not present in the project.

    This consolidates what were previously four independent (but identical)
    ``UnknownNodeError`` classes defined in
    :mod:`isabelle_blueprint.graph.dependency_graph`,
    :mod:`isabelle_blueprint.report.depends`, :mod:`isabelle_blueprint.report.path`,
    and :mod:`isabelle_blueprint.report.impact`. It still subclasses
    :class:`KeyError` (as each of those did) so existing ``except KeyError`` or
    ``except UnknownNodeError`` handling keeps working unchanged; those modules
    now import this class instead of defining their own.
    """
