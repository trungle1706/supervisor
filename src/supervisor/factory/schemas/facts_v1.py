"""facts_v1: the frozen export of the facts card (WP-F1, owner decision 3).

``GET /v1/facts/{node_id}/export`` (flag ``ONBOARD_FACTS``, permission ``systems.view``) returns
a ``FactsExportV1``. The field names are frozen. The export carries every field of a card row
(``onboard.facts.row_view``) and every field of the card except the two display views
(``groups``, ``rows``); a test fails when the card gains a field that the export does not carry,
so the export is updated on purpose.

``confidence`` is not stored on a row. It is derived from ``source``: a rule fact is ``high``
(a fixed rule found it at a file and line), a model fact is ``medium`` (the gateway model
proposed it and ``validate_llm_claims`` kept it). ``low`` is reserved for a later reader.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The fact kinds of ``onboard.facts.KINDS`` (a test keeps the two in step).
FACT_KINDS = (
    "tool",
    "model",
    "endpoint",
    "dataset",
    "file",
    "secret_use",
    "external_url",
    "mcp_server",
    "approval_point",
    "autonomy",
    "decision33",
    "weak_spot",
    "claim",
)
FactKind = Literal[
    "tool",
    "model",
    "endpoint",
    "dataset",
    "file",
    "secret_use",
    "external_url",
    "mcp_server",
    "approval_point",
    "autonomy",
    "decision33",
    "weak_spot",
    "claim",
]
# Card keys that are display views of data the export already carries.
CARD_KEYS_NOT_EXPORTED = ("groups", "rows")
CONFIDENCE_BY_SOURCE = {"rule": "high", "model": "medium"}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactRecord(_M):
    fact_id: str = Field(min_length=1, max_length=64)
    node_id: str = Field(min_length=1, max_length=200)
    attempt_n: int = Field(ge=1)
    kind: FactKind
    name: str = Field(max_length=200)
    detail: str = Field(max_length=500)
    file: str = Field(min_length=1, max_length=300)
    line: int = Field(ge=1)
    quote: str | None = Field(default=None, max_length=200)
    source: Literal["rule", "model"]
    confidence: Literal["low", "medium", "high"]
    model_id: str | None = Field(default=None, max_length=120)
    dropped_claims: int | None = Field(default=None, ge=0)
    created_at: str | None = None


class SummaryRecord(_M):
    fact_id: str = Field(min_length=1, max_length=64)
    node_id: str = Field(min_length=1, max_length=200)
    attempt_n: int = Field(ge=1)
    kind: Literal["summary"]
    name: str
    detail: str = Field(max_length=500)
    file: None = None
    line: None = None
    quote: None = None
    source: Literal["rule", "model"]
    confidence: Literal["low", "medium", "high"]
    model_id: str | None = Field(default=None, max_length=120)
    dropped_claims: int = Field(ge=0)
    created_at: str | None = None


class FactsExportV1(_M):
    version: Literal[1]
    node_id: str = Field(min_length=1, max_length=200)
    attempt_n: int | None = Field(ge=1)
    latest_attempt: int | None = Field(ge=1)
    newer_attempt: bool
    total: int = Field(ge=0)
    dropped_claims: int = Field(ge=0)
    facts: list[FactRecord]
    summary: SummaryRecord | None


def confidence_for(source: str) -> str:
    return CONFIDENCE_BY_SOURCE.get(source, "low")


def _record(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["confidence"] = confidence_for(str(row.get("source")))
    return out


def export_card(card: dict[str, Any]) -> dict[str, Any]:
    """Turn ``FactsService.card()`` into the export dict (validated against ``FactsExportV1``)."""
    rows = list(card.get("rows") or [])
    facts = [_record(r) for r in rows if r["kind"] != "summary"]
    summary = card.get("summary")
    doc = {
        "version": 1,
        "node_id": card["node_id"],
        "attempt_n": card["attempt_n"],
        "latest_attempt": card["latest_attempt"],
        "newer_attempt": bool(card["newer_attempt"]),
        "total": int(card["total"]),
        "dropped_claims": int(card["dropped_claims"]),
        "facts": facts,
        "summary": _record(summary) if summary else None,
    }
    return FactsExportV1.model_validate(doc).model_dump(mode="json")
