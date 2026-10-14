"""Fixed test vectors for canonical JSON + SHA-256 (spec in supervisor.core.canonical).

The hashes were cross-checked with `printf '%s' '<json>' | sha256sum`.
Changing any vector breaks every existing evidence chain: do not edit, add new ones.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from supervisor.core.canonical import (
    CanonicalError,
    canonical_bytes,
    canonical_json,
    format_ts,
    parse_ts,
    sha256_hex,
)
from supervisor.core.models import AgentEvent

ICT = timezone(timedelta(hours=7))

VECTORS = [
    ({}, "{}", "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"),
    (
        {
            "b": 1,
            "a": "Nguyễn Văn A",
            "amount_minor": 1500000,
            "ts": datetime(2026, 10, 14, 12, 0, 0, tzinfo=ICT),
            "n": None,
            "f": 0.1,
            "l": [True, False],
        },
        '{"a":"Nguyễn Văn A","amount_minor":1500000,"b":1,"f":0.1,"l":[true,false],"n":null,'
        '"ts":"2026-10-14T05:00:00.000000Z"}',
        "7c757023b4a485daabd335cd52a703f65976a1dff618b7e52fd097131b45d121",
    ),
    (
        {"chain": "root", "seq": 0, "prev_hash": "0" * 64},
        '{"chain":"root","prev_hash":"' + "0" * 64 + '","seq":0}',
        "1f8c09795ab3dabfdeac3d70bfc99313f2472a98020aeeeef7506948e5b0fd0a",
    ),
]


@pytest.mark.parametrize("value,text,digest", VECTORS)
def test_vectors(value: object, text: str, digest: str) -> None:
    assert canonical_json(value) == text
    assert canonical_bytes(value) == text.encode("utf-8")
    assert sha256_hex(value) == digest


def test_key_order_and_whitespace_do_not_matter() -> None:
    a = {"x": {"b": 2, "a": 1}, "y": [1, 2]}
    b = {"y": [1, 2], "x": {"a": 1, "b": 2}}
    assert sha256_hex(a) == sha256_hex(b)
    assert " " not in canonical_json(a)


def test_timestamps_utc_z_micro() -> None:
    t = datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC)
    assert format_ts(t) == "2026-01-02T03:04:05.000006Z"
    assert parse_ts("2026-01-02T03:04:05.000006Z") == t
    assert parse_ts("2026-01-02T10:04:05.000006+07:00") == t
    assert parse_ts("2026-01-02 03:04:05.000006") == t  # Databricks naive = UTC
    assert canonical_json({"d": date(2026, 1, 2)}) == '{"d":"2026-01-02"}'


@pytest.mark.parametrize(
    "bad",
    [
        {"ts": datetime(2026, 1, 1)},  # naive
        {"amount_minor": 1.5},  # float money
        {"amount_minor": "100"},  # string money
        {"amount_minor": True},  # bool money
        {"x": Decimal("1.0")},
        {"x": b"bytes"},
        {"x": math.nan},
        {"x": math.inf},
        {"x": 2**63},
        {1: "non-string key"},
        {"x": object()},
    ],
)
def test_rejects(bad: object) -> None:
    with pytest.raises(CanonicalError):
        canonical_json(bad)


def test_money_null_allowed_and_nested_money_checked() -> None:
    assert canonical_json({"fee_minor": None}) == '{"fee_minor":null}'
    with pytest.raises(CanonicalError):
        canonical_json({"items": [{"amount_minor": 1.0}]})


def test_model_hash_is_stable() -> None:
    ev = AgentEvent(
        event_id="e1",
        ts=datetime(2026, 10, 14, 12, 0, tzinfo=ICT),
        trace_id="t1",
        span_id="s1",
        agent_id="payments",
        event_type="tool_call",
        tool_name="transfer",
        amount_minor=250_000_000,
        currency="VND",
        env="dev",
        source="otel",
    )
    assert canonical_json(ev) == canonical_json(ev.model_dump())
    assert '"ts":"2026-10-14T05:00:00.000000Z"' in canonical_json(ev)
    assert sha256_hex(ev) == sha256_hex(AgentEvent.model_validate(ev.model_dump()))
