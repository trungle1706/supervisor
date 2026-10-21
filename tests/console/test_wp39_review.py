"""WP39 review (Opus): ids that hold personal data, the one-time export link, the old rule
hashes, the alert link to the decision of its own agent, the coverage-gap scope and the read
path of the Analytics tabs. Synthetic data only."""

from __future__ import annotations

import csv
import io
import json
import os
import time
from datetime import timedelta
from typing import Any

import pytest

from supervisor.alerts.engine import evaluate
from supervisor.alerts.rules import load_rules
from supervisor.alerts.service import _corr
from supervisor.alerts.signals import load_signals
from supervisor.analytics.decisions import looks_personal, safe_id, shown_id
from supervisor.config import REPO_ROOT
from supervisor.console import decisions_v2
from supervisor.demo.activity_seed import export_href
from supervisor.jobs import alerts as alerts_job
from supervisor.jobs import decision_rollup
from supervisor.monitors.common import MonitorContext

from .conftest import Console
from .wp39_helpers import add_decision

NAME = "Nguyễn Văn Thắng"
PHONE = "0987654321"
EMAIL = "thang.nguyen@vidu.vn"
CCCD = "079203001234"
ACCOUNT = "19033456789012"
RAW = (NAME, PHONE, EMAIL, CCCD, ACCOUNT)


def _mctx(c: Console) -> MonitorContext:
    return MonitorContext.from_adapters(c.runtime.adapters, c.runtime.chain)


def _leaks(text: str) -> list[str]:
    forms = {v for raw in RAW for v in (raw, json.dumps(raw)[1:-1])}
    return sorted(f for f in forms if f in text)


def _export(c: Console, data: dict[str, str] | None = None, user: str = "auditor.dung") -> Any:
    return c.post("/console/decisions/export", data or {}, user=user)


# --------------------------------------------------------------------------- personal ids


def test_id_check_unit() -> None:
    for bad in (PHONE, EMAIL, CCCD, ACCOUNT, "+84987654321"):
        assert looks_personal(bad) and safe_id(bad) is None and shown_id(bad) == "<id-hidden>"
    for ok in ("corr-planted-0001", "req-1", "app-mobile", "4bf92f3577b34da6a3ce929d0e0e4736"):
        assert not looks_personal(ok) and safe_id(ok) == ok and shown_id(ok) == ok
    assert shown_id(None) is None and shown_id("<b>") == "<id-hidden>"
    assert _corr(PHONE) is None and _corr(EMAIL) is None and _corr("corr-1") == "corr-1"


def test_gate_replaces_personal_correlation_and_request_ids(v2console: Console) -> None:
    gw = v2console.runtime.gateway
    out = gw.check(
        "payments",
        "1.0.0",
        "get_balance",
        {"account_id": "A-1"},
        {"consumer_id": EMAIL, "trace_id": "tr-pid", "span_id": "sp-pid"},
        correlation_id=PHONE,
        request_id=EMAIL,
    )
    assert out["correlation_id"] != PHONE and safe_id(out["correlation_id"])
    e = v2console.ctx.tables.query("agent_event", {"event_id": out["decision_id"]})[0]
    assert e["correlation_id"] == out["correlation_id"] and e["request_id"] != EMAIL
    assert e["consumer_id"] is None  # an e-mail is not a consumer id
    chain = v2console.ctx.tables.query("chain_entry", {"record_ref": out["decision_id"]})[0]
    payload = v2console.ctx.tables.query(
        "chain_payload", {"lane": chain["lane"], "seq": chain["seq"]}
    )[0]["payload"]
    assert not _leaks(str(payload))  # R2: nothing personal on the evidence chain
    for f in v2console.ctx.tables.query("finding", {"event_id": out["decision_id"]}):
        assert f["correlation_id"] != PHONE and f["request_id"] != EMAIL


def test_http_gate_header_with_a_phone_is_not_echoed(v2console: Console) -> None:
    r = v2console.client.post(
        "/v1/gate/check",
        json={
            "agent_id": "payments",
            "agent_version": "1.0.0",
            "tool_name": "get_balance",
            "args": {"account_id": "A-1"},
            "context": {},
        },
        headers={"X-Supervisor-Correlation-Id": PHONE, "X-Request-ID": EMAIL},
    )
    assert r.status_code == 200
    assert PHONE not in r.text and EMAIL not in r.text
    assert r.headers.get("X-Supervisor-Correlation-Id") not in (None, PHONE)


def test_old_rows_with_personal_ids_are_hidden_on_every_surface(v2console: Console) -> None:
    """Rows written before the gate checked ids (or by another writer)."""
    eid = add_decision(
        v2console,
        corr=PHONE,
        request_id=EMAIL,
        consumer=EMAIL,
        trace="tr-old",
        span="sp-old",
        codes=("pii.phone",),
    )
    add_decision(v2console, corr=PHONE, consumer=EMAIL)
    now = v2console.ctx.clock.now()
    v2console.ctx.state.insert(
        "alert",
        {
            "alert_id": "e" * 32,
            "ts": now,
            "dedupe_key": "AL-PII-OUTPUT:payments",
            "rule_id": "AL-PII-OUTPUT",
            "rule_hash": "d" * 64,
            "severity": "high",
            "status": "open",
            "title": "old row",
            "agent_id": "payments",
            "group_value": "payments",
            "window_s": 600,
            "window_count": 3,
            "threshold": 3,
            "first_ts": now,
            "last_ts": now,
            "suppressed_count": 0,
            "refs": [],
            "routes": ["inbox"],
            "route_status": {"inbox": "sent"},
            "correlation_id": PHONE,
        },
    )
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    texts = [
        v2console.get(u).text
        for u in (
            "/console/decisions",
            "/console/decisions/rows",
            f"/console/decisions?drawer={eid}&dtab=metadata",
            "/console/traces/tr-old",
            "/console/traces/tr-old/span/sp-old",
            "/console/analytics?tab=gate",
            "/console/alerts?status=all",
            f"/console/alerts/{'e' * 32}/drawer",
        )
    ]
    for tab in decisions_v2.DRAWER_TABS:
        texts.append(v2console.get(f"/console/decisions/{eid}/drawer?tab={tab}").text)
    href = export_href(_export(v2console).text)
    texts.append(v2console.get(href, user="auditor.dung").text)
    for t in texts:
        assert not _leaks(t)
    rows = v2console.ctx.state.query("decision_daily", {"dimension": "consumer"})
    assert rows and all(r["dim_key"] == "<id-hidden>" for r in rows)


@pytest.mark.parametrize(
    "url",
    [
        f"/console/decisions?corr={PHONE}",
        f"/console/decisions?consumer={EMAIL}",
        f"/console/decisions?correlation={PHONE}",
        f"/console/decisions?event={CCCD}",
        f"/console/traces?corr={EMAIL}",
    ],
)
def test_personal_values_in_id_filters_are_refused(v2console: Console, url: str) -> None:
    r = v2console.get(url)
    assert r.status_code == 400 and not _leaks(r.text)


# --------------------------------------------------------------------------- export link


def test_export_link_is_bound_to_the_user_used_once_and_expires(
    v2console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_decision(v2console, corr="corr-exp", consumer="app-web")
    href = export_href(_export(v2console).text)
    assert href and "&t=" in href and "?exp=" in href
    name = href.split("/")[-1].split("?")[0]
    path = decisions_v2._export_root(v2console.ctx) / name
    assert path.is_file()
    # another auditor or admin, a reviewer, a bare name, a tampered token: never the file
    assert v2console.get(href, user="admin.chi").status_code == 400
    assert v2console.get(href, user="reviewer.an").status_code == 403
    assert v2console.get(href.split("?")[0], user="auditor.dung").status_code == 400
    tampered = href[:-1] + ("1" if href[-1] == "0" else "0")
    assert v2console.get(tampered, user="auditor.dung").status_code == 400
    ok = v2console.get(href, user="auditor.dung")
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    assert "attachment" in ok.headers["content-disposition"]
    assert not path.exists()  # served once, then deleted
    assert v2console.get(href, user="auditor.dung").status_code == 400  # no reuse
    # expired link
    href2 = export_href(_export(v2console).text)
    real = time.time
    monkeypatch.setattr(decisions_v2.time, "time", lambda: real() + decisions_v2.EXPORT_TTL_S + 5)
    assert v2console.get(href2, user="auditor.dung").status_code == 400
    # and the expired file was cleaned up on that request
    assert not list(decisions_v2._export_root(v2console.ctx).glob("*.csv"))


def test_old_export_files_are_removed_and_audit_packs_left_alone(v2console: Console) -> None:
    root = decisions_v2._export_root(v2console.ctx)
    root.mkdir(parents=True, exist_ok=True)
    old = root / "decisions-20260101T000000Z-0123456789abcdef.csv"
    old.write_text("x", encoding="utf-8")
    past = time.time() - decisions_v2.EXPORT_TTL_S - 60
    os.utime(old, (past, past))
    pack = root.parent / "audit-pack-20260101T000000Z-abcdef.zip"
    pack.write_bytes(b"zip")
    assert _export(v2console).status_code == 200
    assert not old.exists() and pack.exists()


def test_export_audit_row_has_the_filter_hash(v2console: Console) -> None:
    assert _export(v2console, {"status": "allow"}).status_code == 200
    assert _export(v2console, {"status": "block"}).status_code == 200
    acts = v2console.ctx.tables.query(
        "console_action", {"permission": "decisions.export", "outcome": "ok"}
    )
    hashes = {a["detail"].split("filters=")[1] for a in acts}
    assert len(hashes) == 2
    assert decisions_v2.filter_hash({"status": "allow"}) in hashes


def test_export_columns_are_pinned_a_new_one_must_be_added_here() -> None:
    assert decisions_v2.EXPORT_COLUMNS == (
        "time_utc",
        "decision_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "agent_id",
        "consumer_id",
        "tool",
        "direction",
        "status",
        "action",
        "rule_ids",
        "finding_codes",
        "not_evaluated_reasons",
        "latency_us",
        "latency_rules_us",
        "latency_detectors_us",
        "case_id",
    )


def test_export_rows_have_exactly_the_allow_listed_cells(v2console: Console) -> None:
    add_decision(v2console, consumer="app-web", codes=("pii.phone",))
    href = export_href(_export(v2console).text)
    rows = list(csv.reader(io.StringIO(v2console.get(href, user="auditor.dung").text)))
    assert all(len(r) == len(decisions_v2.EXPORT_COLUMNS) for r in rows)


def test_export_of_50000_rows_is_capped(v2console: Console) -> None:
    now = v2console.ctx.clock.now()
    v2console.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": f"big{i:029d}",
                "ts": now,
                "trace_id": f"tb{i}",
                "span_id": f"sb{i}",
                "agent_id": "payments",
                "event_type": "gate_decision",
                "tool_name": "get_balance",
                "status": "allowed",
                "env": "test",
                "classification": "allow",
                "source": "proxy",
                "capture_level": "digest",
                "verdict_status": "allow",
            }
            for i in range(50_000)
        ],
    )
    r = _export(v2console)
    assert r.status_code == 200 and "truncated: 5000 of " in r.text
    note = r.text.split('id="export-truncated">')[1].split("<")[0]
    assert note.isascii()
    rows = list(
        csv.reader(io.StringIO(v2console.get(export_href(r.text), user="auditor.dung").text))
    )
    assert len(rows) == 5001


# --------------------------------------------------------------------------- alerts


def test_old_rule_hashes_are_unchanged() -> None:
    """Hashes of the eight rules before WP39, computed with the WP37 loader (review)."""
    want = {
        "AL-BLOCK-BURST": "2ccc4e12dc29d615af692e5d0a2d1090e9845024f3f38fdb7f8825e76e9b1f97",
        "AL-QUARANTINE": "4cae9e54cf09a4323e15485e4b19c18f271ea88969b7a4a9839935c139254219",
        "AL-CHAIN-VERIFY-FAIL": "bf80e530ae4fd12f0dc7a84de919336defafb64f765d683520703a47784e7826",
        "AL-JUDGE-ESCALATION": "75b38fd27e3348083c43d8141fdd6b4a26bee7286af5be00e78da64db5e57373",
        "AL-INGRESS-REJECT-AGENT": (
            "07fd81ec4173a3bde0c67e301d70aa102b5d54cef8b744acc0387022c91a91f0"
        ),
        "AL-INGRESS-REJECT-BURST": (
            "0dcf9a962f054fcdc9af76c873eed9d2b013bad3517cba7e17e44c436d9cd96f"
        ),
        "AL-FAILCLOSED-DRILL-FAIL": (
            "c01d1ae034224309cd5fadc58da145e681651cba277033d9621fe3334ae6ea55"
        ),
        "AL-JOB-FAILURE": "d55695af3e40bd11d0359ac4ddbede6cf9b9a795c873f724c67c46057c668e9d",
    }
    got = {r.id: r.rule_hash for r in load_rules(REPO_ROOT / "config" / "alerts.yaml").rules}
    assert {k: got[k] for k in want} == want


def test_alert_links_to_the_decision_of_its_own_agent(v2console: Console) -> None:
    mine = add_decision(v2console, agent="payments", corr="corr-shared-1", age_s=300)
    other = add_decision(v2console, agent="customer_service", corr="corr-shared-1", age_s=10)
    assert decisions_v2.resolve_ref(v2console.ctx, correlation="corr-shared-1") == other
    got = decisions_v2.resolve_ref(v2console.ctx, correlation="corr-shared-1", agent="payments")
    assert got == mine
    r = v2console.get("/console/decisions?correlation=corr-shared-1&agent=payments")
    assert r.status_code == 200 and f'data-row="{mine}"' in r.text
    # the decision drawer does not list the alert of another agent with the same id
    now = v2console.ctx.clock.now()
    base = {
        "ts": now,
        "rule_hash": "d" * 64,
        "severity": "high",
        "status": "open",
        "title": "t",
        "window_s": 600,
        "window_count": 1,
        "threshold": 1,
        "first_ts": now,
        "last_ts": now,
        "suppressed_count": 0,
        "refs": [],
        "routes": ["inbox"],
        "route_status": {"inbox": "sent"},
        "correlation_id": "corr-shared-1",
    }
    for aid, agent, rule in (
        ("a" * 32, "payments", "AL-MINE"),
        ("b" * 32, "customer_service", "AL-OTHER"),
    ):
        v2console.ctx.state.insert(
            "alert",
            {**base, "alert_id": aid, "dedupe_key": f"{rule}:x", "rule_id": rule,
             "agent_id": agent, "group_value": agent},
        )  # fmt: skip
    meta = v2console.get(f"/console/decisions/{mine}/drawer?tab=metadata").text
    assert "AL-MINE" in meta and "AL-OTHER" not in meta
    drawer = v2console.get(f"/console/alerts/{'a' * 32}/drawer").text
    assert "correlation=corr-shared-1&amp;agent=payments" in drawer


def _event(agent: str, kind: str, ts: Any, n: int) -> dict[str, Any]:
    return {
        "event_id": f"{agent[:6]}{kind[:4]}{n:020d}",
        "ts": ts,
        "trace_id": f"tr-{agent}",
        "span_id": f"sp-{n}",
        "agent_id": agent,
        "event_type": kind,
        "tool_name": "x" if kind == "tool_call" else None,
        "env": "test",
        "source": "otel",
        "capture_level": "digest",
    }


def test_coverage_gap_scope(v2console: Console) -> None:
    """Decided in the review: tool calls only; inventory only for unregistered systems; a
    retired agent that still calls tools is a gap."""
    ctx = _mctx(v2console)
    now = v2console.ctx.clock.now() + timedelta(hours=3)  # clear of the demo decisions
    st = v2console.ctx.state
    agents = {a["agent_id"]: a for a in st.query("agent")}
    reg = sorted(agents)
    talker, retired = reg[0], reg[1]
    row = agents[retired]
    st.update("agent", {"agent_id": retired}, {"gate_state": "RETIRED"}, row["row_version"])
    v2console.ctx.tables.append(
        "agent_event",
        [
            _event(talker, "llm_call", now - timedelta(seconds=30), 1),  # talks only
            _event(talker, "message", now - timedelta(seconds=29), 2),
            _event(retired, "tool_call", now - timedelta(seconds=28), 3),  # retired, still acts
        ],
    )
    for name in (retired, "unknown-app"):  # inventory: retired agent and an unregistered app
        st.insert(
            "inventory_node",
            {
                "node_id": f"n-{name}",
                "kind": "system",
                "name": name,
                "display_name": name,
                "status": "active",
                "own_risk": None,
                "risk_source": "none",
                "decision33_class": None,
                "attrs": {},
                "evidence": [],
                "first_seen": now - timedelta(days=1),
                "last_seen": now - timedelta(seconds=10),
            },
        )
    sigs = load_signals(
        ctx, now - timedelta(hours=1), now + timedelta(seconds=1), gap_window_s=3600
    )
    gaps = {s.fields["agent_id"]: s.fields["seen_in"] for s in sigs if s.kind == "coverage_gap"}
    assert talker not in gaps  # LLM calls and messages never pass the gate
    assert gaps.get(retired) == "trace"  # a tool call around the gate
    assert gaps.get("unknown-app") == "inventory"
    # the retired agent seen ONLY in the inventory is not a gap
    sigs = load_signals(ctx, now - timedelta(hours=1), now + timedelta(seconds=1), gap_window_s=20)
    gaps = {s.fields["agent_id"] for s in sigs if s.kind == "coverage_gap"}
    assert retired not in gaps and "unknown-app" in gaps


def test_shadow_agent_1000_block_findings_in_a_minute_give_one_alert(v2console: Console) -> None:
    from supervisor.alerts.signals import Signal

    t0 = v2console.ctx.clock.now()
    sigs = [
        Signal(
            sid=f"finding:{i:06d}",
            kind="gate_finding",
            ts=t0 + timedelta(milliseconds=60 * i),
            derived=True,
            fields={
                "agent_id": "shadow-agent",
                "code": "injection.ignore_previous",
                "finding_class": "injection",
                "direction": "input",
                "detector_slug": "injection_regex",
                "action_hint": "block",
                "enforcement": "shadow",
                "is_mock": False,
                "correlation_id": f"c-{i}",
            },
        )
        for i in range(1000)
    ]
    rs = load_rules(REPO_ROOT / "config" / "alerts.yaml")
    res = evaluate(rs, sigs, only_rules={"AL-THREAT-NOT-ENFORCED"})
    assert len(res.fired) == 1 and res.fired[0].suppressed_count == 999


def test_analytics_tabs_never_read_the_raw_tables(
    v2console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_decision(v2console, codes=("pii.phone",))
    decision_rollup.run(_mctx(v2console), v2console.ctx.settings)
    from supervisor.console import analytics_v2

    seen: list[str] = []
    real_tables, real_state = v2console.ctx.tables.query, v2console.ctx.state.query

    def spy_tables(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_tables(table, *a, **k)

    def spy_state(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_state(table, *a, **k)

    monkeypatch.setattr(v2console.ctx.tables, "query", spy_tables)
    monkeypatch.setattr(v2console.ctx.state, "query", spy_state)
    gate = analytics_v2.gate_tables(v2console.ctx, 7, "")
    det = analytics_v2.detectors_data(v2console.ctx, 7, "")
    assert gate["dd_tables"]["agent"] and det["det_latency"]
    assert set(seen) == {"decision_daily"}


def test_alert_job_stores_no_personal_correlation_id(v2console: Console) -> None:
    for i in range(3):
        add_decision(v2console, corr=PHONE, direction="output", codes=("pii.phone",), age_s=30 + i)
    settings = v2console.ctx.settings.model_copy(update={"alerts_lag_s": 0})
    alerts_job.run(_mctx(v2console), settings)
    for a in v2console.ctx.state.query("alert"):
        assert a.get("correlation_id") != PHONE


def test_bootstrap_on_an_existing_wp37_sqlite_file_adds_the_wp39_columns(tmp_path: Any) -> None:
    from datetime import UTC, datetime

    from supervisor.adapters.clock import FixedClock
    from supervisor.adapters.factory import build_adapters
    from supervisor.adapters.sql.sqlite import SqliteExecutor
    from supervisor.config import load_settings
    from supervisor.core.schema import load_model, sqlite_statements
    from supervisor.core.schema_diff import live_columns, migrate
    from supervisor.jobs import bootstrap_schema
    from tests.databricks.test_schema_migration import _older

    model = load_model()
    wp39 = {"request_id", "consumer_id", "latency_rules_us", "latency_detectors_us"}
    wp39 |= {"detector_latency_json"}
    db = tmp_path / "wp37.db"
    x = SqliteExecutor(db)
    old = _older(model, {"agent_event": wp39, "alert": {"correlation_id"}})
    x.apply_ddl([s for s in sqlite_statements(old) if "decision_daily" not in s])
    assert not wp39 & set(live_columns(x, "agent_event") or {})
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", sqlite_path=db)
    adapters = build_adapters(
        settings, executor=x, clock=FixedClock(datetime(2026, 10, 20, tzinfo=UTC))
    )
    res = bootstrap_schema.run(settings, adapters)
    assert res["added_columns"] == 6
    assert wp39 <= set(live_columns(x, "agent_event") or {})
    assert "correlation_id" in (live_columns(x, "alert") or {})
    assert live_columns(x, "decision_daily")  # the new table is created
    assert migrate(x, model).statements == []
    x.close()
