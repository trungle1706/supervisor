"""WP-G1 review fixes: H1 register bypass, M2 register band, M3 initiation floor, M4 stub, L5."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.governance import events
from supervisor.governance.lifecycle import LifecycleService
from supervisor.governance.model import SystemsError
from supervisor.governance.systems import SystemService
from supervisor.tasks.service import TaskService

from .conftest import Console, ListSink, add_agent, draft, person

# ------------------------------------------------------------------ H1


def test_h1_register_over_the_api_starts_in_initiation(on: Console) -> None:
    hdr = {"X-Dev-User": "reviewer.an"}
    r = on.client.post("/v1/systems", json=draft(lifecycle_stage="operation"), headers=hdr)
    assert r.status_code == 400
    assert "approvals" in r.json()["error"] and "stage" in r.json()["error"]
    assert on.ctx.state.query("ai_system") == []
    r = on.client.post("/v1/systems", json=draft(lifecycle_stage="launch"), headers=hdr)
    assert r.status_code == 400 and "lifecycle_stage" in r.json()["error"]
    r = on.client.post("/v1/systems", json=draft(lifecycle_stage="initiation"), headers=hdr)
    assert r.status_code == 201 and r.json()["lifecycle_stage"] == "initiation"


def test_h1_console_form_cannot_set_the_stage(on: Console) -> None:
    form = {k: v for k, v in draft().items() if k != "owner_user"}
    r = on.post("/console/systems", {**form, "lifecycle_stage": "operation"})
    assert r.status_code == 200, r.text[:200]
    (row,) = on.ctx.state.query("ai_system")
    assert row["lifecycle_stage"] == "initiation"


# ------------------------------------------------------------------ M2 and M3


def _tasks(adapters: Adapters, sink: ListSink) -> TaskService:
    adapters.settings.governance_enabled = True
    return TaskService.from_adapters(adapters, evidence=sink)


def _link(adapters: Adapters, svc: SystemService, agent: str, **agent_over: Any) -> str:
    add_agent(adapters, agent, **agent_over)
    s = svc.register(draft(), "owner.lan")
    svc.link(s["system_id"], "agent", agent, "owner.lan")
    return str(s["system_id"])


class _Level:
    inherent_level = "high"


class _Register:
    def agent_levels(self) -> dict[str, Any]:
        return {"a1": _Level()}


def test_m2_register_band_counts_for_a_linked_agent(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    _link(adapters, svc, "a1", risk_tier="unknown", decision33_class="not_high_risk")
    tasks = _tasks(adapters, sink)
    tasks._risks = _Register()  # the WP29 register says high
    inp = tasks.agent_inputs("a1")
    assert inp["band"] == "high" and inp["band_source"] == "risk_register"
    assert inp["level"] == "high" and inp["system_level"] == "unspecified"
    # a system band that is higher still wins
    sid = inp["system_ids"]
    svc.update_fields(sid, {"risk_level": "prohibited"}, "owner.lan")
    inp = tasks.agent_inputs("a1")
    assert inp["band"] == "critical" and inp["band_source"] == "system"


def test_m3_initiation_only_needs_a_low_final_level(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    # high-risk class: floor is high, so the move task exists
    _link(adapters, svc, "hr", risk_tier="unknown", decision33_class="high_risk")
    tasks = _tasks(adapters, sink)
    inp = tasks.agent_inputs("hr")
    assert inp["level"] == "high" and "initiation_only" not in inp
    from supervisor.cases.service import SystemActor

    tasks.generate("hr", SystemActor())
    assert [t for t in tasks.agent_summary("hr")["tasks"] if t["kind"] == "move"]


def test_m3_register_band_high_gives_a_move_task(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    from supervisor.cases.service import SystemActor

    _link(adapters, svc, "a1", risk_tier="unknown", decision33_class="not_high_risk")
    tasks = _tasks(adapters, sink)
    tasks._risks = _Register()
    assert "initiation_only" not in tasks.agent_inputs("a1")
    tasks.generate("a1", SystemActor())
    assert [t for t in tasks.agent_summary("a1")["tasks"] if t["kind"] == "move"]


def test_m3_still_low_stays_initiation_only(
    adapters: Adapters, svc: SystemService, sink: ListSink
) -> None:
    _link(adapters, svc, "lo", risk_tier="unknown", decision33_class="not_high_risk")
    inp = _tasks(adapters, sink).agent_inputs("lo")
    assert inp["level"] == "low" and inp["initiation_only"] == "1"


# ------------------------------------------------------------------ M4


def test_m4_a_raising_stub_does_not_fail_the_request(
    adapters: Adapters, svc: SystemService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.adapters.notify import outbound_webhook

    def boom(self: Any, event: Any) -> bool:
        raise RuntimeError("sender down")

    monkeypatch.setattr(outbound_webhook.OutboundWebhookStub, "send", boom)
    adapters.settings.webhooks_enabled = True
    s = svc.register(draft(), "owner.lan")  # does not raise
    (e,) = events.list_events(adapters.state, s["system_id"])
    assert e["delivered"] in (False, 0)
    # and deliver_pending itself never raises
    assert events.deliver_pending(adapters.state, adapters.clock, adapters.settings) == 0


def test_m4_emit_reads_one_row_not_the_table(
    adapters: Adapters, svc: SystemService, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapters.settings.webhooks_enabled = True
    svc.register(draft(name="First"), "owner.lan")
    calls: list[Any] = []
    real = adapters.state.query

    def spy(table: str, where: Any = None, *a: Any, **k: Any) -> Any:
        calls.append((table, where))
        return real(table, where, *a, **k)

    monkeypatch.setattr(adapters.state, "query", spy)
    events.emit(adapters.state, adapters.clock, adapters.settings, "system_archived", "sys_x", {})
    # no read of the whole table (get may filter by key)
    assert ("outbound_event", None) not in calls


# ------------------------------------------------------------------ L5


def test_l5_the_approval_is_claimed_before_the_system_moves(
    adapters: Adapters, svc: SystemService, monkeypatch: pytest.MonkeyPatch
) -> None:
    life = LifecycleService(svc)
    sid = str(svc.register(draft(), "owner.lan")["system_id"])
    aid = life.request(sid, "deployment", "owner.lan")["approval_id"]
    life.decide(sid, aid, "approve", person("approver.em", "approver"))
    order: list[str] = []
    real = adapters.state.update

    def spy(table: str, *a: Any, **k: Any) -> Any:
        order.append(table)
        return real(table, *a, **k)

    monkeypatch.setattr(adapters.state, "update", spy)
    life.move(sid, "deployment", "owner.lan")
    assert order.index("stage_approval") < order.index("ai_system")


def test_l5_a_lost_claim_leaves_the_system_untouched(
    adapters: Adapters, svc: SystemService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.core.errors import ConcurrencyError

    life = LifecycleService(svc)
    sid = str(svc.register(draft(), "owner.lan")["system_id"])
    aid = life.request(sid, "deployment", "owner.lan")["approval_id"]
    life.decide(sid, aid, "approve", person("approver.em", "approver"))
    real = adapters.state.update

    def fail(table: str, *a: Any, **k: Any) -> Any:
        if table == "stage_approval":
            raise ConcurrencyError("lost")
        return real(table, *a, **k)

    monkeypatch.setattr(adapters.state, "update", fail)
    with pytest.raises(SystemsError, match="used by someone else"):
        life.move(sid, "deployment", "owner.lan")
    assert svc.get(sid)["lifecycle_stage"] == "initiation"
