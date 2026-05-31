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
