"""WP39: the additive facts the gate records (consumer id, request id, latency split)."""

from __future__ import annotations

import json

from supervisor.alerts.service import _corr

from .conftest import Console
from .wp39_fixtures import plant


def _event(c: Console, eid: str) -> dict:
    return c.ctx.tables.query("agent_event", {"event_id": eid})[0]


def test_gate_records_consumer_request_and_latency_facts(v2console: Console) -> None:
    ids = plant(v2console)
    e = _event(v2console, ids["a"])
    assert e["consumer_id"] == "app-mobile" and e["request_id"] == "req-planted-01"
    assert e["latency_rules_us"] is not None and e["latency_detectors_us"] is not None
    per = e["detector_latency_json"]
    per = per if isinstance(per, dict) else json.loads(per)
    assert set(per) <= {"dlp_vn", "injection_regex", "judge_advisory"} and per
    assert e["latency_us"] >= e["latency_rules_us"] + 0  # the split is part of the whole
    # the detector time is the sum of the per-detector times, to the microsecond or two
    assert abs(e["latency_detectors_us"] - sum(per.values())) <= 2000


def test_consumer_id_must_be_a_plain_id(v2console: Console) -> None:
    gw = v2console.runtime.gateway
    out = {}
    for name, cid in (("ok", "app-web"), ("nl", "app-web\n"), ("html", "<b>x</b>"), ("num", 7)):
        out[name] = gw.check(
            "payments", "1.0.0", "get_balance", {"account_id": "A-1"}, {"consumer_id": cid}
        )["decision_id"]
    assert _event(v2console, out["ok"])["consumer_id"] == "app-web"
    for k in ("nl", "html", "num"):
        assert _event(v2console, out[k])["consumer_id"] is None


def test_alert_correlation_id_is_kept_only_when_it_is_an_id() -> None:
    assert _corr("corr-1_a.b:c@d") == "corr-1_a.b:c@d"
    assert _corr("x\n") is None and _corr("<i>") is None and _corr("") is None and _corr(5) is None
