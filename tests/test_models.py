from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from supervisor.core.models import ALL_RECORDS, AgentEvent, StateRecord, Verdict
from supervisor.core.schema import STATE_COLUMNS, load_model

NOW = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)


def test_models_match_schema_model_yaml() -> None:
    model = load_model()
    for cls in ALL_RECORDS:
        table = model.table(cls.__table__)
        assert set(cls.model_fields) == set(table.column_names), cls.__name__
        is_state = issubclass(cls, StateRecord)
        assert is_state == (table.kind == "state"), cls.__name__
        for col in table.columns:
            field = cls.model_fields[col.name]
            if col.name in dict(STATE_COLUMNS):
                continue
            assert (not field.is_required()) or not col.nullable or col.name in table.primary_key, (
                f"{cls.__name__}.{col.name}: nullable column must have a default"
            )


def test_timestamps_become_utc_and_naive_is_rejected() -> None:
    ict = timezone(timedelta(hours=7))
    ev = AgentEvent(
        event_id="e",
        ts=datetime(2026, 10, 14, 12, 0, tzinfo=ict),
        trace_id="t",
        span_id="s",
        agent_id="a",
        event_type="message",
        env="dev",
        source="otel",
    )
    assert ev.ts == NOW and ev.ts.tzinfo == UTC
    with pytest.raises(ValidationError):
        AgentEvent(**{**ev.model_dump(), "ts": datetime(2026, 10, 14)})


def test_money_is_strict_int() -> None:
    base = dict(
        event_id="e",
        ts=NOW,
        trace_id="t",
        span_id="s",
        agent_id="a",
        event_type="tool_call",
        env="dev",
        source="otel",
        currency="VND",
    )
    assert AgentEvent(**base, amount_minor=5_000_000).amount_minor == 5_000_000
    for bad in (1.5, "100", 100.0):
        with pytest.raises(ValidationError):
            AgentEvent(**base, amount_minor=bad)


def _verdict(**kw: object) -> Verdict:
    base: dict[str, object] = dict(
        verdict_id="v",
        ts=NOW,
        agent_id="a",
        tier=1,
        checker_id="judge-t1",
        advisory=True,
        label="suspicious",
        action="open_case",
    )
    base.update(kw)
    return Verdict(**base)  # type: ignore[arg-type]


def test_judges_only_advise() -> None:
    assert _verdict().advisory
    with pytest.raises(ValidationError):
        _verdict(action="block")
    with pytest.raises(ValidationError):
        _verdict(action="pause")
    with pytest.raises(ValidationError):
        _verdict(advisory=False)
    # Tier 0 rules may block.
    assert _verdict(tier=0, advisory=False, action="block", rule_id="r1").action == "block"


def test_mock_verdict_is_labelled() -> None:
    assert _verdict(is_mock=True, model_id="mock-judge").is_mock
    with pytest.raises(ValidationError):
        _verdict(is_mock=True, model_id="qwen3:4b")
