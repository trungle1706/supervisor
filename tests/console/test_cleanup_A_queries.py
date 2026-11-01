"""Code clean-up batch A (N3-N6): the console read models read the append-only tables in a few
statements, whatever the number of events. A statement counter on the SQL executor proves it
(the same idea as the ``Counting`` executor in ``tests/test_store_read_cache.py``)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from supervisor.console import readmodels, traces

from .conftest import Console
from .test_ux3_more import _event, _verdict

_FROM = re.compile(r'\bFROM\s+"?(\w+)"?', re.I)


@contextmanager
def count_reads(console: Console) -> Iterator[Counter[str]]:
    """Statements the console store sends while the block runs, by table."""
    x = console.ctx.tables.x
    seen: Counter[str] = Counter()
    original = x.query

    def counting(sql: str, *a: Any, **k: Any) -> Any:
        found = _FROM.search(sql)
        seen[found.group(1) if found else "?"] += 1
        return original(sql, *a, **k)

    x.query = counting
    try:
        yield seen
    finally:
        del x.query  # back to the class method


def _user(name: str = "reviewer.an") -> Any:
    from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
    from supervisor.config import REPO_ROOT

    return DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users[name]


# ---------------------------------------------------------------- N3: landing page decisions


@pytest.mark.parametrize("newer", [1, 10, 100])
def test_latest_decisions_reads_two_tables_once_each(console: Console, newer: int) -> None:
    # three old stops (their verdicts are the newest) and `newer` allowed calls after them
    for i in range(3):
        e = _event(
            console, f"t-old-{i}", f"s{i}", None, "gate_decision", tool="pay/send",
            offset=-3 * 86_400_000 - i, status="blocked", classification="block",
        )  # fmt: skip
        _verdict(console, f"t-old-{i}", e, action="pause" if i == 1 else "block")
    for i in range(newer):
        _event(console, f"t-new-{i}", f"n{i}", None, "gate_decision", tool="x/y", offset=i)
    with count_reads(console) as reads:
        out = readmodels.latest_decisions(console.ctx)
    assert len(out) == 6
    assert sorted(o["outcome"] for o in out).count("blocked") >= 2
    assert any(o["outcome"] == "paused" for o in out)
    # agent_event: the newest events + the stop events that are not among them (one statement)
    # verdict: block + pause scan, plus the verdicts of the shown events (one statement)
    assert reads["agent_event"] == 2, reads
    assert reads["verdict"] == 3, reads


# ---------------------------------------------------------------- N5, N6: trace page


@pytest.mark.parametrize("gates", [1, 10, 50])
def test_trace_detail_reads_event_verdicts_in_one_statement(console: Console, gates: int) -> None:
    for i in range(gates):
        e = _event(
            console, "t-many", f"sp{i}", None, "gate_decision", tool="pay/send",
            offset=i, status="blocked", classification="block",
        )  # fmt: skip
        _verdict(console, "t-elsewhere", e, action="block")  # keyed by the event, not the trace
    with count_reads(console) as reads:
        detail = traces.trace_detail(console.ctx, "t-many")
    assert reads["verdict"] == 2, reads  # by trace id, then all events at once
    assert sum(len(n["verdicts"]) for n in detail["nodes"]) == gates
    assert all(n["stop"] == "block" for n in detail["nodes"])


@pytest.mark.parametrize("events", [1, 4, 12])
def test_span_detail_reads_chain_entries_in_one_statement(console: Console, events: int) -> None:
    for i in range(events):
        _event(console, "t-span", "sp-one", None, "gate_decision", tool="pay/send", offset=i)
    with count_reads(console) as reads:
        detail = traces.trace_detail(console.ctx, "t-span")
    assert reads["chain_entry"] == 1, reads
    assert len(detail["selected"]["evs"]) == events


def test_span_detail_chain_position_is_the_stored_one(console: Console) -> None:
    ctx = console.ctx
    entry = ctx.tables.query("chain_entry", {"record_type": "gate_decision"}, limit=1)[0]
    event = ctx.tables.query("agent_event", {"event_id": entry["record_ref"]}, limit=1)[0]
    detail = traces.trace_detail(ctx, event["trace_id"], event["span_id"])
    item = next(i for i in detail["selected"]["evs"] if i["e"]["event_id"] == event["event_id"])
    assert item["chain"] == {"lane": entry["lane"], "seq": int(entry["seq"])}
    # a gate decision without a chain entry shows no position
    lone = _event(console, "t-lone", "sp-lone", None, "gate_decision", tool="a/b")
    alone = traces.trace_detail(ctx, "t-lone")["selected"]["evs"]
    assert alone[0]["e"]["event_id"] == lone and alone[0]["chain"] is None


# ---------------------------------------------------------------- N4: agent cards


def test_agent_cards_read_pending_resumes_only_for_paused_agents(console: Console) -> None:
    ctx = console.ctx
    with count_reads(console) as base:
        cards = readmodels.agent_cards(ctx, _user())
    assert not any(c["state"] == "PAUSED" for c in cards)
    assert base["gate_control"] == 0, base
    row = ctx.state.get("agent", {"agent_id": cards[0]["agent_id"]})
    ctx.state.update(
        "agent",
        {"agent_id": row["agent_id"]},
        {"gate_state": "PAUSED", "status": "paused"},
        int(row["row_version"]),
    )
    ctx.gateway.states.invalidate()
    with count_reads(console) as paused:
        cards = readmodels.agent_cards(ctx, _user())
    assert [c["state"] for c in cards if c["agent_id"] == row["agent_id"]] == ["PAUSED"]
    assert paused["gate_control"] == 2, paused  # pending resumes + stop cause, paused agent only
