"""facts_v1: the export carries every field of the facts card; the route and its flag."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from supervisor.factory.schemas import FactsExportV1
from supervisor.factory.schemas import facts_v1 as fv1
from supervisor.onboard import facts
from tests.console.test_o2_facts import MANIFEST, upload  # noqa: F401  (shared helpers)

from .conftest import DATA

HX = {"HX-Request": "true"}
H = {"X-Dev-User": "reviewer.an"}


# ------------------------------------------------------------------ drift


def sample_row() -> dict[str, Any]:
    return facts.row_view(
        {
            "fact_id": "fct_1",
            "node_id": "payments",
            "attempt_n": 1,
            "kind": "tool",
            "name": "t",
            "source": "rule",
        }
    )


def test_fact_kinds_match_the_facts_card() -> None:
    assert fv1.FACT_KINDS == facts.KINDS


def test_export_row_carries_every_field_of_a_card_row() -> None:
    """Fails when ``row_view`` gains a field that ``FactRecord`` does not carry."""
    card_fields = set(sample_row())
    exported = set(fv1.FactRecord.model_fields)
    assert card_fields <= exported, f"add to facts_v1: {sorted(card_fields - exported)}"
    assert exported - card_fields == {"confidence"}
    assert set(fv1.SummaryRecord.model_fields) == exported


def test_export_carries_every_field_of_the_card(console: Any) -> None:
    """Fails when ``FactsService.card`` gains a key that the export does not carry."""
    card = facts.FactsService(
        console.ctx.settings, console.ctx.state, console.ctx.clock, tables=console.ctx.tables
    ).card("payments")
    wanted = set(card) - set(fv1.CARD_KEYS_NOT_EXPORTED)
    assert wanted <= set(FactsExportV1.model_fields), (
        f"add to facts_v1: {sorted(wanted - set(FactsExportV1.model_fields))}"
    )
    assert set(FactsExportV1.model_fields) - wanted == {"version", "facts"}


def test_confidence_is_derived_from_the_source() -> None:
    assert fv1.confidence_for("rule") == "high"
    assert fv1.confidence_for("model") == "medium"


# ------------------------------------------------------------------ schema


def test_example_export_is_valid() -> None:
    FactsExportV1.model_validate(json.loads((DATA / "facts_export.json").read_text("utf-8")))


def test_export_refuses_an_unknown_field_and_a_float_line() -> None:
    doc = json.loads((DATA / "facts_export.json").read_text("utf-8"))
    doc["facts"][0]["extra"] = 1
    with pytest.raises(ValidationError):
        FactsExportV1.model_validate(doc)
    doc["facts"][0].pop("extra")
    doc["facts"][0]["confidence"] = 0.9
    with pytest.raises(ValidationError):
        FactsExportV1.model_validate(doc)


def test_export_version_is_frozen_at_one() -> None:
    doc = json.loads((DATA / "facts_export.json").read_text("utf-8"))
    doc["version"] = 2
    with pytest.raises(ValidationError):
        FactsExportV1.model_validate(doc)


# ------------------------------------------------------------------ route


def test_route_off_is_400_facts_off(console: Any) -> None:
    assert console.ctx.settings.onboard_facts is False
    r = console.client.get("/v1/facts/payments/export", headers=H)
    assert r.status_code == 400 and "facts_off" in r.json()["error"]


def test_route_is_open_to_a_viewer(console: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """systems.view is a viewer permission (the route declares needs("systems.view"))."""
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    r = console.client.get("/v1/facts/payments/export", headers={"X-Dev-User": "viewer.hoa"})
    assert r.status_code == 200, r.text


def test_route_on_empty_card(console: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    r = console.client.get("/v1/facts/payments/export", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    FactsExportV1.model_validate(body)
    assert body["version"] == 1 and body["facts"] == [] and body["attempt_n"] is None


def test_route_bad_node_id_is_400(console: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    r = console.client.get("/v1/facts/bad node!/export", headers=H)
    assert r.status_code == 400


def test_route_on_with_facts(console: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    upload(console)
    assert console.client.post("/console/facts/payments", headers={**H, **HX}).status_code == 200
    r = console.client.get("/v1/facts/payments/export", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    FactsExportV1.model_validate(body)
    assert body["total"] == len(body["facts"]) > 0
    assert body["summary"]["kind"] == "summary"
    card = console.client.get("/v1/facts/payments", headers=H).json()
    assert body["total"] == card["total"] and body["attempt_n"] == card["attempt_n"]
    sources = {f["source"]: f["confidence"] for f in body["facts"]}
    assert sources["rule"] == "high"
