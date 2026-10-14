"""Facts from a system of record for deterministic rules (``fact.<source>.<field>``).

Some controls depend on data the agent does not put in the tool arguments, for example
"approve a loan only when the required documents are on file". A rule reads such a
value with the predicate path ``fact.<source>.<field>``; the gateway looks the record
up in its ``FactSource`` with the key taken from the tool argument ``<source>_id``
(``fact.application.documents_complete`` -> argument ``application_id``).

Fail closed: no fact source, no key argument, no record, or no such field raise a
rule error, so the rule's own fail mode applies (closed for money, credit, PII export).
Feature default: no fact source (rules that need one fail closed).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol


class FactSource(Protocol):
    def get(self, source: str, key: str) -> Mapping[str, Any] | None:
        """The record ``key`` of ``source`` (for example application APP-00003), or None."""
        ...


class MappingFactSource:
    """FactSource over plain callables, one per source (tests, demo, bank adapters)."""

    def __init__(self, sources: Mapping[str, Callable[[str], Mapping[str, Any] | None]]) -> None:
        self.sources = dict(sources)

    def get(self, source: str, key: str) -> Mapping[str, Any] | None:
        fn = self.sources.get(source)
        return fn(key) if fn is not None else None


__all__ = ["FactSource", "MappingFactSource"]
