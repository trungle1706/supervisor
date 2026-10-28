"""Frozen data model of the regulation knowledge base.

``to_plain`` turns any of these objects back into the JSON-like dict the schema describes.
That dict is what the version hash and the export use, so the hash does not depend on file
layout, YAML formatting or dict order.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from supervisor.regkb.errors import UnknownObligationError

_KEEP_NONE = {"keep_none": True}


@dataclass(frozen=True)
class Source:
    url: str
    title: str
    fetched_at: str
    kind: str  # primary | secondary
    sha256: str | None = None
    local_path: str | None = None


@dataclass(frozen=True)
class DatedFact:
    """A date with its source and verification tag. ``date`` None = unknown."""

    date: str | None = field(metadata=_KEEP_NONE)
    source: str
    verification: str
    note: str | None = None
    label: str | None = None  # milestones only


@dataclass(frozen=True)
class Dates:
    issued: DatedFact | None = None
    effective: DatedFact | None = None
    compliance_deadline: DatedFact | None = None
    milestones: tuple[DatedFact, ...] | None = None


@dataclass(frozen=True)
class Control:
    kind: str  # catalogue | rule | monitor | console | evidence | process
    id: str
    coverage: str  # full | partial | none
    note: str | None = None


@dataclass(frozen=True)
class AppliesTo:
    """The applies_to predicate. None = no condition on that fact."""

    agent_class: tuple[str, ...] | None = None
    data_classes: tuple[str, ...] | None = None
    autonomy: tuple[str, ...] | None = None
    cross_border: bool | None = None
    model_hosting: tuple[str, ...] | None = None
    role: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ProductProfile:
    """Facts about a product. None = the fact is not known."""

    agent_classes: tuple[str, ...] | None = None
    data_classes: tuple[str, ...] | None = None
    autonomy: str | None = None
    cross_border: bool | None = None
    model_hosting: str | None = None
    roles: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Applicability:
    """Result of evaluating a predicate: applies | not_applicable | unknown."""

    status: str
    reasons: tuple[str, ...] = ()
    missing_facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Instrument:
    id: str
    jurisdiction: str
    kind: str
    issuer: str
    number: str
    title_en: str
    status: str
    binding: bool | str  # True | False | "internal" (WP-W3, internal documents)
    dates: Dates
    sources: tuple[Source, ...]
    verification: str
    primary_text_fetched: bool
    last_checked: str
    title_vi: str | None = None
    supersedes: tuple[str, ...] | None = None
    superseded_by: tuple[str, ...] | None = None
    related: tuple[str, ...] | None = None
    notes: str | None = None
    file: str = field(default="", metadata={"hash": False})


@dataclass(frozen=True)
class Obligation:
    """One obligation with the instrument header merged in."""

    id: str
    instrument_id: str
    jurisdiction: str
    instrument_kind: str
    issuer: str
    number: str
    title_en: str
    status: str
    binding: bool | str  # True | False | "internal" (WP-W3, internal documents)
    dates: Dates
    article_ref: str
    summary_en: str
    duties: tuple[str, ...]
    applies_to: AppliesTo
    control_mapping: tuple[Control, ...]
    evidence_needed: tuple[str, ...]
    verification: str
    sources: tuple[Source, ...]
    confidence: str
    title_vi: str | None = None
    text_vi: str | None = None
    text_en: str | None = None
    summary_vi: str | None = None
    addressee: str | None = None
    notes: str | None = None
    confirmed_by: str | None = None  # WP-L1: person who confirmed a law-agent draft
    file: str = field(default="", metadata={"hash": False})


def to_plain(obj: Any) -> Any:
    """Dataclass tree -> dict/list/str/bool. Drops None (except marked fields) and 'file'."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            if f.metadata.get("hash") is False:
                continue
            value = getattr(obj, f.name)
            if value is None and not f.metadata.get("keep_none"):
                continue
            out[f.name] = to_plain(value)
        return out
    if isinstance(obj, tuple | list):
        return [to_plain(v) for v in obj]
    return obj


@dataclass(frozen=True)
class KnowledgeBase:
    instruments: tuple[Instrument, ...]  # sorted by id
    obligations: dict[str, Obligation]  # sorted by id
    version: str  # sha256 hex over all instruments and obligations
    instrument_hashes: dict[str, str]
    warnings: tuple[str, ...] = ()

    def get(self, obligation_id: str) -> Obligation:
        try:
            return self.obligations[obligation_id]
        except KeyError:
            raise UnknownObligationError(f"unknown obligation id {obligation_id}") from None

    def instrument(self, instrument_id: str) -> Instrument:
        for inst in self.instruments:
            if inst.id == instrument_id:
                return inst
        raise UnknownObligationError(f"unknown instrument id {instrument_id}")

    def obligations_of(self, instrument_id: str) -> list[Obligation]:
        return [o for o in self.obligations.values() if o.instrument_id == instrument_id]

    def snapshot(self) -> dict[str, Any]:
        """Plain-dict form used by export and diff."""
        return {
            "version": self.version,
            "instrument_hashes": dict(self.instrument_hashes),
            "instruments": {i.id: to_plain(i) for i in self.instruments},
            "obligations": {k: to_plain(v) for k, v in self.obligations.items()},
        }
