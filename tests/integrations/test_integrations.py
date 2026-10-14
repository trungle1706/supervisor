"""WP11 bank-integration stubs: SIEM formatter + sinks, ITSM, pager, SCIM fakes. All off."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.integrations import (
    IntegrationError,
    RetryPolicy,
    load_integration_settings,
    with_retry,
)
from supervisor.adapters.integrations import siem as S
from supervisor.adapters.integrations.itsm import InMemoryItsm, ItsmSync, ticket_request
from supervisor.adapters.integrations.pager import FakePager, PagerBridge
from supervisor.adapters.integrations.scim import (
    FakeScimDirectory,
    load_role_groups,
    role_report,
)
from supervisor.cases.service import SystemActor
from supervisor.config import REPO_ROOT
from supervisor.demo import inject, seed
from supervisor.demo.session import DemoSession, build_session, demo_settings

REVIEWER = SystemActor("reviewer.an", "user", "dev_header", frozenset({"reviewer"}))
ONCALL = SystemActor("oncall.lan", "user", "pager", frozenset({"reviewer"}))


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DemoSession]:
    settings = demo_settings(tmp_path_factory.mktemp("integ") / "demo", llm_base_url="")
    assert seed.seed(settings, echo=lambda _l: None).ok
    s = build_session(settings)
    for n in (1, 4):
        assert inject.inject(s, n, echo=lambda _l: None, auto_resume=True).ok
    try:
        yield s
    finally:
        s.close()


def test_everything_is_off_by_default(tmp_path: Path) -> None:
    cfg = load_integration_settings(_env_file=None)
    assert not (cfg.siem_enabled or cfg.itsm_enabled or cfg.pager_enabled or cfg.scim_enabled)
    assert S.build_siem_sink(cfg, tmp_path) is None
    on = load_integration_settings(_env_file=None, siem_enabled=True)
    sink = S.build_siem_sink(on, tmp_path)
    assert isinstance(sink, S.LogSiemSink) and sink.path == tmp_path / "siem" / "events.log"
    hook = load_integration_settings(_env_file=None, siem_enabled=True, siem_sink="webhook")
    with pytest.raises(IntegrationError, match="FILL-ME"):
        S.build_siem_sink(hook, tmp_path)  # no URL: the webhook stays off


# ------------------------------------------------------------------ SIEM


def test_chain_feed_writes_schema_events_once(demo: DemoSession, tmp_path: Path) -> None:
    sink = S.LogSiemSink(tmp_path / "siem.log")
    feed = S.ChainEventFeed(demo.tables, sink)
    n = feed.poll()
    assert n > 0 and feed.poll() == 0  # cursor: nothing twice
    events = [json.loads(x) for x in (tmp_path / "siem.log").read_text("utf-8").splitlines()]
    assert len(events) == n and len({e["event_id"] for e in events}) == n
    assert {e["schema"] for e in events} == {S.SCHEMA}
    assert {e["event_type"] for e in events} <= set(S.EVENT_TYPES)
    blocks = [e for e in events if e["event_type"] == "gate_decision" and e["rule_id"] == "PAY-08"]
    assert blocks and blocks[0]["outcome"] == "block" and blocks[0]["severity"] == 7
    pause = [
        e for e in events if e["event_type"] == "gate_state_change" and e["outcome"] == "pause"
    ]
    assert pause and pause[0]["actor"] == "rule:PAY-07" and pause[0]["severity"] == 8
    assert any(e["event_type"] == "case_opened" and e["severity"] == 10 for e in events)
    assert any(e["event_type"] == "chain_root" for e in events)
    allowed = set(S.SiemEvent.__dataclass_fields__)
    assert all(set(e) == allowed for e in events)
    # no PII: no CCCD / phone / account-like digit runs anywhere in the SIEM stream
    text = json.dumps([{k: v for k, v in e.items() if k != "entry_hash"} for e in events])
    assert not re.search(r"(?<![0-9a-f])\d{9,12}(?![0-9a-f])", text)
    assert "ACC-" not in text and "CUS-" not in text


def test_anchor_event() -> None:
    ev = S.event_from_anchor(
        {
            "anchor_id": "a1",
            "lane": "root",
            "seq_to": 9,
            "root_hash": "ab" * 32,
            "anchored_at": "2026-10-14T00:00:00Z",
        },
        env="laptop",
    )
    assert ev.event_type == "chain_anchor" and ev.chain_seq == 9 and ev.outcome == "anchored"


def _event(**kw: Any) -> S.SiemEvent:
    base: dict[str, Any] = dict(
        event_id="agent:payments:3",
        event_type="gate_decision",
        ts="2026-10-14T01:02:03Z",
        severity=7,
        outcome="block",
        agent_id="payments",
        rule_id="PAY-08",
        case_id=None,
        actor=None,
        chain_lane="agent:payments",
        chain_seq=3,
        entry_hash="00" * 32,
        env="laptop",
    )
    base.update(kw)
    return S.SiemEvent(**base)


def test_cef_format_and_escaping() -> None:
    line = S.to_cef(_event())
    assert line.startswith("CEF:0|Supervisor|Supervisor|")
    assert "|supervisor.siem.v1:gate_decision|gate decision|7|" in line
    assert "cs2Label=ruleId cs2=PAY-08" in line and "cn1=3" in line
    assert "case_id" not in line and "cs3=" not in line  # empty fields are left out
    nasty = S.to_cef(_event(actor="a=b\\c\nd", event_type="gate|x"))
    assert "suser=a\\=b\\\\c\\nd" in nasty
    assert "gate\\|x" in nasty and "\n" not in nasty


def test_json_format_is_canonical() -> None:
    line = S.to_json(_event())
    assert json.loads(line)["rule_id"] == "PAY-08"
    assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"))


def test_webhook_retries_then_succeeds_or_fails() -> None:
    calls: list[dict[str, Any]] = []
    slept: list[float] = []
    failures = {"n": 2}

    def transport(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        calls.append(payload)
        if failures["n"]:
            failures["n"] -= 1
            raise ConnectionError("down")
        return {"ok": True}

    sink = S.WebhookSiemSink(
        "https://siem.example.invalid/hec", transport=transport, sleep=slept.append
    )
    assert sink.emit([_event()]) == 1
    assert len(calls) == 3 and slept == [1.0, 2.0]
    failures["n"] = 5
    with pytest.raises(IntegrationError, match="after 3 attempt"):
        sink.emit([_event()])
    with pytest.raises(IntegrationError):
        S.WebhookSiemSink("FILL-ME-hec-url")


def test_retry_policy_delays() -> None:
    assert RetryPolicy().delays() == [1.0, 2.0]
    assert RetryPolicy(attempts=5, base_delay_s=10, max_delay_s=30).delays() == [10, 20, 30, 30]
    assert with_retry(lambda: 3, RetryPolicy(), sleep=lambda _s: None) == 3


# ------------------------------------------------------------------ ITSM


def _case(demo: DemoSession, rule: str) -> dict[str, Any]:
    return next(c for c in demo.cases.list_cases() if rule in c["summary"])


def test_itsm_creates_once_writes_back_and_updates(demo: DemoSession) -> None:
    fake = InMemoryItsm(fail_next=1)
    sync = ItsmSync(fake, demo.cases, sleep=lambda _s: None)
    case = _case(demo, "PAY-08")
    with pytest.raises(IntegrationError, match="needs the reviewer"):
        sync.sync_case(case["case_id"])  # no background write-back without a person
    ref = sync.sync_case(case["case_id"], REVIEWER)
    assert ref.startswith("INC") and fake.calls == 2  # one retry
    assert demo.cases.get(case["case_id"])["itsm_ref"] == ref
    assert any(e["action"] == "itsm_ref" for e in demo.cases.events(case["case_id"]))
    t = fake.tickets[ref]
    assert t["priority"] == "P2" and t["rule_id"] == "PAY-08"
    assert t["console_url"].endswith(f"/console/cases/{case['case_id']}")
    assert case["summary"] not in json.dumps(t, default=str)  # no free text leaves
    assert sync.sync_case(case["case_id"]) == ref and len(fake.tickets) == 1
    # status change is pushed once
    reviewer = REVIEWER
    cur = demo.cases.get(case["case_id"])
    demo.cases.assign(case["case_id"], "reviewer.an", reviewer, cur["row_version"])
    cur = demo.cases.get(case["case_id"])
    demo.cases.transition(case["case_id"], "triaged", reviewer, cur["row_version"], note="seen")
    sync.sync_case(case["case_id"])
    sync.sync_case(case["case_id"])
    assert [h["status"] for h in t["history"]] == ["triaged"]


def test_ticket_request_maps_severity() -> None:
    req = ticket_request(
        {
            "case_id": "CASE-1",
            "severity": "critical",
            "agent_id": "payments",
            "status": "open",
            "opened_at": "2026-10-14T00:00:00Z",
        },
        rule_id="PAY-07",
        console_base_url="https://app.example.invalid/",
    )
    assert req.priority == "P1" and req.title.endswith("rule PAY-07")
    assert req.console_url == "https://app.example.invalid/console/cases/CASE-1"


# ------------------------------------------------------------------ pager


def test_pager_pages_critical_once_and_writes_ack(demo: DemoSession) -> None:
    pager = FakePager(fail_next=1)
    people = {"oncall.lan": ONCALL}
    bridge = PagerBridge(pager, demo.cases, people.get, sleep=lambda _s: None)
    critical = _case(demo, "PAY-07")
    high = _case(demo, "PAY-08")
    assert critical["severity"] == "critical" and high["severity"] == "high"
    assert bridge.maybe_page(critical["case_id"], "PAY-07") is True
    assert pager.triggers == 2  # one retry
    assert bridge.maybe_page(critical["case_id"]) is False  # dedup
    assert bridge.maybe_page(high["case_id"]) is False  # below page_severities
    ack = pager.ack(critical["case_id"], "oncall.lan", "2026-10-14T10:00:00Z")
    bridge.on_ack(ack)
    events = demo.cases.events(critical["case_id"])
    assert any(e["action"] == "comment" and e["actor"] == "oncall.lan" for e in events)
    stranger = pager.ack(critical["case_id"], "who.knows", "2026-10-14T10:01:00Z")
    with pytest.raises(IntegrationError, match="no console identity"):
        bridge.on_ack(stranger)
    with pytest.raises(IntegrationError):
        pager.ack("CASE-NOPE", "x", "y")


# ------------------------------------------------------------------ SCIM


def test_scim_role_report() -> None:
    groups = {
        "reviewer": ["sup-reviewers"],
        "approver": ["sup-approvers"],
        "owner": ["agent-owners"],
        "auditor": ["FILL-ME-internal-audit"],
        "admin": ["sup-admins", "missing-group"],
    }
    d = FakeScimDirectory(
        {
            "sup-reviewers": ["an@bank.example", "binh@bank.example"],
            "sup-approvers": ["em@bank.example", "an@bank.example"],
            "agent-owners": ["lead@bank.example"],
            "sup-admins": ["root@bank.example"],
        },
        fail_next=1,
    )
    rep = role_report(d, groups, sleep=lambda _s: None)
    assert rep.user_roles["an@bank.example"] == ["approver", "reviewer"]
    text = "\n".join(rep.findings)
    assert "role auditor: no group mapped" in text
    assert "'missing-group' not found" in text
    assert "an@bank.example holds reviewer and approver" in text
    assert "only one admin" in text and not rep.ok


def test_scim_committed_auth_yaml_is_all_placeholders() -> None:
    groups = load_role_groups(REPO_ROOT / "config" / "auth.yaml")
    rep = role_report(FakeScimDirectory({}), groups)
    assert rep.user_roles == {}
    assert sum("no group mapped" in f for f in rep.findings) == 5  # FILL-ME never matches
