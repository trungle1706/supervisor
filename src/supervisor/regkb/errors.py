"""Typed errors of the regulation knowledge base. Messages name the file and the id."""

from __future__ import annotations

from supervisor.core.errors import SupervisorError


class RegKBError(SupervisorError):
    """Base error. ``errors`` holds every problem found (one line each)."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = list(errors) if errors else [message]


class SchemaError(RegKBError):
    """A file does not follow the JSON Schema (or is not valid YAML)."""


class SemanticError(RegKBError):
    """A file is valid against the schema but breaks a RegKB rule."""


class UnknownObligationError(RegKBError):
    """No obligation or instrument has this id."""


class UnsupportedKeywordError(RegKBError):
    """The schema uses a keyword the in-repo validator does not implement."""
