"""Code clean-up batch B (audit N2, N7-N10, N15, N16): the statement count of each fixed reader
is constant in the number of rows, and the result equals what the old per-row code returned on
the same seed (the old loops are kept below as the reference)."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.cases.service import CaseService
from supervisor.config import load_settings
from supervisor.core.schema import load_model
from supervisor.evidence.chain import ChainWriter
from supervisor.evidence.signer import build_signer
from supervisor.governance import duty_evidence as de
from supervisor.governance import event_sources as src
from supervisor.governance import risk_dimensions as rd
from supervisor.governance.actions import ActionRunner
from supervisor.governance.actions_model import GovernanceEvent
from supervisor.jobs.bootstrap_schema import run as bootstrap_run
from supervisor.judge.mrm.agreement import agreement_pairs
from supervisor.mcp_server import tools_supervisor as ts_tools
from supervisor.monitors.common import MonitorContext, as_dt, median, read_range
from supervisor.monitors.oversight import OversightMetrics
from supervisor.risk.evidence import Window

T0 = dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.UTC)


class Counting(SqliteExecutor):
    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.reads = 0

    def query(self, *a: Any, **k: Any) -> Any:
        self.reads += 1
        return super().query(*a, **k)


class Rig:
    def __init__(self, tmp: Path) -> None:
        self.settings = load_settings(
            sql_backend="sqlite", data_dir=tmp / "d", llm_base_url="", governance_enabled=True
        )
        self.clock = FixedClock(T0)
        a = build_adapters(self.settings, clock=self.clock)
        bootstrap_run(self.settings, a)
        self.a = a
        self.x = Counting(a.executor.path)
        self.tables = SqlTableStore(self.x)
        self.state = SqlStateStore(self.x, self.clock)
        self.model = load_model()
        self.ctx = MonitorContext(
            tables=self.tables,
            state=self.state,
            executor=self.x,
            model=self.model,
            clock=self.clock,
            evidence=SimpleNamespace(record=lambda *a, **k: "h"),
        )

    def close(self) -> None:
        self.a.close()

    def row(self, table: str, state: bool = False, **vals: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for c in self.model.table(table).columns:
            if c.name in vals:
                out[c.name] = vals[c.name]
            elif state and c.name in ("row_version", "updated_at"):
                continue
            elif c.nullable:
                out[c.name] = None
            else:
                out[c.name] = {"string": "x", "text": "x", "int": 1, "bool": False, "json": {}}.get(
                    c.type, T0 if c.type == "timestamp" else "x"
                )
        return out

    def add(self, table: str, **vals: Any) -> None:
        self.tables.append(table, [self.row(table, **vals)])

    def put(self, table: str, **vals: Any) -> None:
        self.state.insert(table, self.row(table, state=True, **vals))

    def reads_of(self, fn: Any) -> tuple[Any, int]:
        before = self.x.reads
        out = fn()
        return out, self.x.reads - before


@pytest.fixture
def rig(tmp_path: Path):
    r = Rig(tmp_path)
    try:
        yield r
    finally:
        r.close()


# ------------------------------------------------------------------------------------ N2


def _seed_decisions(r: Rig, agent: str, n: int) -> None:
    for i in range(n):
        eid = f"e{agent}{i:04d}"
        ts = T0 - dt.timedelta(minutes=i)
        r.add(
            "agent_event", event_id=eid, ts=ts, agent_id=agent, event_type="gate_decision",
            tool_name="transfer", status="denied" if i % 2 else "allowed",
        )  # fmt: skip
        if i % 2:
            r.add(
                "verdict", verdict_id=f"v{eid}a", ts=ts, event_id=eid, agent_id=agent, tier=0,
                action="block", advisory=False, rule_id="R-1", rationale_masked="rule R-1",
            )  # fmt: skip
        r.add(
            "verdict", verdict_id=f"v{eid}b", ts=ts, event_id=eid, agent_id=agent, tier=1,
            action="log", advisory=True, is_mock=True, checker_id="judge.x", label="suspicious",
        )  # fmt: skip


def _old_decisions(tables: Any, agent: str, limit: int) -> list[dict[str, Any]]:
    """The loop as it was: one verdict query per gate event."""
    events = tables.query(
        "agent_event", {"agent_id": agent, "event_type": "gate_decision"}, order_by=("-ts",),
        limit=2000,
    )  # fmt: skip
    out = []
    for e in events:
        verdicts = tables.query("verdict", {"event_id": e["event_id"]})
        stops = [
            v for v in verdicts
            if int(v["tier"]) == 0 and v["action"] in ("block", "pause") and not v["advisory"]
        ]  # fmt: skip
        stop = min(stops, key=lambda v: v["action"] != "pause") if stops else None
        out.append(
            (
                e["event_id"],
                "blocked" if stop else ("allowed" if e["status"] == "allowed" else e["status"]),
                stop.get("rule_id") if stop else None,
                [v["checker_id"] for v in verdicts if v["advisory"]][:5],
            )
        )
        if len(out) >= limit:
            break
    return out


def _decisions(r: Rig, monkeypatch: pytest.MonkeyPatch, agent: str, limit: int):
    monkeypatch.setattr(ts_tools, "visible_agent", lambda call, a: a)
    call = SimpleNamespace(ctx=SimpleNamespace(tables=r.tables))
    return ts_tools.decisions(call, {"agent_id": agent, "limit": limit}, False)


@pytest.mark.parametrize("n", [5, 60])
def test_n2_decisions_use_a_constant_number_of_statements(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, n: int
) -> None:
    _seed_decisions(rig, "a1", n)
    res, reads = rig.reads_of(lambda: _decisions(rig, monkeypatch, "a1", 50))
    assert reads <= 3  # one event read, one verdict batch (not one query per event)
    got = [
        (i["event_id"], i["outcome"], i["rule_id"], [a["checker"] for a in i["advisory"]])
        for i in res["items"]
    ]
    assert got == [(a, "blocked" if b == "blocked" else b, c, d) for a, b, c, d in
                   _old_decisions(rig.tables, "a1", 50)]  # fmt: skip
    assert res["count"] == min(n, 50)


def test_n2_the_window_still_limits_the_batch(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_decisions(rig, "a1", 30)
    since = (T0 - dt.timedelta(minutes=9, seconds=30)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(ts_tools, "visible_agent", lambda call, a: a)
    call = SimpleNamespace(ctx=SimpleNamespace(tables=rig.tables))
    res = ts_tools.decisions(call, {"agent_id": "a1", "since": since, "limit": 100}, False)
    assert res["count"] == 10


# ------------------------------------------------------------------------------------ N7


def _case_service(r: Rig) -> CaseService:
    return CaseService(r.state, r.tables, SimpleNamespace(record=lambda *a, **k: "h"), r.clock)


def _seed_cases(r: Rig, n_cases: int, links: int, match_case: int) -> None:
    for c in range(n_cases):
        cid = f"CASE-{c:03d}"
        r.put(
            "cases", case_id=cid, agent_id="pay", severity="medium", status="open",
            opened_at=T0 - dt.timedelta(hours=c), regulation_refs=[], summary="s",
        )  # fmt: skip
        for k in range(links):
            ref = f"ev-{c}-{k}"
            rule = "R-HIT" if (c == match_case and k == links - 1) else f"R-{k}"
            r.add(
                "case_link", source_kind="gate", source_ref=ref, case_id=cid, agent_id="pay", ts=T0
            )
            r.add(
                "verdict", verdict_id=f"v-{c}-{k}", event_id=ref, agent_id="pay", tier=0,
                action="block", advisory=False, rule_id=rule, ts=T0,
            )  # fmt: skip


def _old_open_gate_case_for(svc: CaseService, agent_id: str, rule_id: str | None):
    if not rule_id:
        return None
    for case in svc.list_cases(agent_id=agent_id):
        if case["status"] == "closed":
            continue
        for link in svc.links(case["case_id"]):
            if link["source_kind"] != "gate":
                continue
            rows = svc.tables.query("verdict", {"event_id": link["source_ref"]})
            if any(r.get("rule_id") == rule_id for r in rows):
                return case
    return None


@pytest.mark.parametrize(("cases", "links"), [(2, 2), (12, 5)])
def test_n7_alert_grouping_is_constant_in_cases_and_links(rig: Rig, cases: int, links: int) -> None:
    _seed_cases(rig, cases, links, match_case=cases - 1)
    svc = _case_service(rig)
    new, reads = rig.reads_of(lambda: svc._open_gate_case_for("pay", "R-HIT"))
    old, old_reads = rig.reads_of(lambda: _old_open_gate_case_for(svc, "pay", "R-HIT"))
    assert reads <= 4 and old_reads > reads or cases == 2
    assert new is not None and new["case_id"] == old["case_id"] == f"CASE-{cases - 1:03d}"
    assert svc._open_gate_case_for("pay", "R-NONE") is None
    assert svc._open_gate_case_for("pay", None) is None
    assert svc._open_gate_case_for("other", "R-HIT") is None


def test_n7_closed_cases_do_not_group(rig: Rig) -> None:
    _seed_cases(rig, 3, 2, match_case=1)
    row = rig.state.get("cases", {"case_id": "CASE-001"})
    rig.state.update("cases", {"case_id": "CASE-001"}, {"status": "closed"}, row["row_version"])
    assert _case_service(rig)._open_gate_case_for("pay", "R-HIT") is None


def test_n7_linked_verdicts_use_batch_reads(rig: Rig) -> None:
    _seed_cases(rig, 1, 20, match_case=0)
    rig.add(
        "case_link",
        source_kind="judge",
        source_ref="vj1",
        case_id="CASE-000",
        agent_id="pay",
        ts=T0,
    )
    rig.add(
        "verdict", verdict_id="vj1", event_id=None, agent_id="pay", tier=1, advisory=True, ts=T0
    )
    svc = _case_service(rig)
    rows, reads = rig.reads_of(lambda: svc.linked_verdicts("CASE-000"))
    assert reads <= 3
    assert {r["verdict_id"] for r in rows} == {f"v-0-{k}" for k in range(20)} | {"vj1"}


# ------------------------------------------------------------------------------------ N8, N9


def _chain(r: Rig, n_verifies: int, ok_every: int = 2) -> ChainWriter:
    w = ChainWriter(r.tables, r.clock, build_signer(r.settings), root_every_n=100000)
    for i in range(n_verifies):
        r.clock.advance(1)
        w.record(
            "chain_verify",
            f"cv:{i}",
            {"ok": i % ok_every == 0, "failures": i % ok_every},
            lane="root",
        )
    return w


def _old_chain_breaks(ctx: MonitorContext, lo: dt.datetime, hi: dt.datetime) -> list[str]:
    out = []
    for rtype in src.CHAIN_VERIFY_TYPES:
        for e in read_range(ctx, "chain_entry", lo, hi, {"record_type": rtype}):
            rows = ctx.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
            p = json.loads(rows[0]["payload"]) if rows else {}
            ok = p["ok"] if "ok" in p else p.get("verify_ok")
            if ok is None or src._true(ok):
                continue
            out.append(src.safe_ref("chain", e["lane"], e["seq"]))
    return out


@pytest.mark.parametrize("n", [4, 40])
def test_n8_chain_breaks_read_payloads_in_one_batch(rig: Rig, n: int) -> None:
    _chain(rig, n)
    lo, hi = T0 - dt.timedelta(hours=1), T0 + dt.timedelta(hours=1)
    events, reads = rig.reads_of(lambda: src.chain_breaks(rig.ctx, lo, hi))
    assert reads <= 4  # two record types x (entries + one payload batch)
    assert [e.ref for e in events] == _old_chain_breaks(rig.ctx, lo, hi)
    assert len(events) == n // 2


def test_n8_chain_payloads_match_the_old_per_entry_reads(rig: Rig) -> None:
    _chain(rig, 12)
    entries = rig.tables.query("chain_entry", order_by=["lane", "seq"])
    got = src.chain_payloads(rig.tables, entries)
    for e in entries:
        old = [
            p["payload"]
            for p in rig.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        ]
        assert got.get((e["lane"], e["seq"]), []) == old  # byte-equal payload text


@pytest.mark.parametrize("n_agents", [2, 15])
def test_n8_model_changes_read_all_agent_histories_at_once(rig: Rig, n_agents: int) -> None:
    for i in range(n_agents):
        for v, (ep, at) in enumerate(
            [("m-a", T0 - dt.timedelta(days=3)), ("m-b", T0 - dt.timedelta(minutes=5))]
        ):
            rig.add(
                "agent_version", agent_id=f"ag{i}", version=f"1.{v}", deployed_at=at,
                model_endpoint=ep, model_family="fam",
            )  # fmt: skip
    lo, hi = T0 - dt.timedelta(hours=1), T0 + dt.timedelta(hours=1)
    events, reads = rig.reads_of(lambda: src.model_changes(rig.ctx, lo, hi))
    assert reads <= 3
    assert sorted(e.agent_id for e in events) == sorted(f"ag{i}" for i in range(n_agents))


def _event(sid: str, key: str) -> GovernanceEvent:
    return SimpleNamespace(system_id=sid, key=key)  # type: ignore[return-value]


@pytest.mark.parametrize("n", [5, 80])
def test_n9_raised_before_reads_the_payloads_in_one_batch(rig: Rig, n: int) -> None:
    w = ChainWriter(rig.tables, rig.clock, build_signer(rig.settings), root_every_n=100000)
    for i in range(n):
        rig.clock.advance(1)
        w.record(
            "system_change", "system:S1",
            {"action": "risk_raise" if i == 0 else "update", "event_key": f"k{i}", "i": i},
            lane="root",
        )  # fmt: skip
    me = SimpleNamespace(ctx=SimpleNamespace(tables=rig.tables))
    hit, reads = rig.reads_of(lambda: ActionRunner._raised_before(me, _event("S1", "k0")))
    assert hit is True and reads <= 2
    assert ActionRunner._raised_before(me, _event("S1", "k-none")) is False
    assert ActionRunner._raised_before(me, _event("S2", "k0")) is False


# ------------------------------------------------------------------------------------ N10


@pytest.mark.parametrize("n_cases", [1, 12])
def test_n10_oversight_reads_case_events_in_one_batch(rig: Rig, n_cases: int) -> None:
    day = T0.date()
    opened = dt.datetime.combine(day, dt.time(10), tzinfo=dt.UTC)
    for c in range(n_cases):
        cid = f"CASE-{c}"
        rig.put("cases", case_id=cid, agent_id="pay", severity="low", status="open",
                opened_at=opened, regulation_refs=[], summary="s")  # fmt: skip
        for seq, kind in enumerate(("system", "user", "user")):
            rig.add("case_event", case_id=cid, seq=seq,
                    ts=opened + dt.timedelta(seconds=60 * (c + 1) * (seq + 1)),
                    actor="x", actor_kind=kind, action="note")  # fmt: skip
    m = OversightMetrics(MonitorContext(
        tables=rig.tables, state=rig.state, executor=rig.x, model=rig.model,
        clock=rig.clock, evidence=rig.ctx.evidence))  # fmt: skip
    out, reads = rig.reads_of(lambda: m.compute("pay", day, True))
    assert out["cases_opened"] == n_cases
    # the first human event of case c is at +120 s * (c + 1): the median of 120*(1..n)
    firsts = sorted(120 * (c + 1) for c in range(n_cases))
    expect = median(firsts)
    assert out["tth_s"] == expect
    assert reads <= 12  # fixed set of reads; the same for 1 and 12 cases


def test_n10_statement_count_does_not_grow_with_cases(rig: Rig, tmp_path: Path) -> None:
    def run(n: int) -> int:
        r = Rig(tmp_path / f"r{n}")
        try:
            day = T0.date()
            opened = dt.datetime.combine(day, dt.time(10), tzinfo=dt.UTC)
            for c in range(n):
                r.put("cases", case_id=f"C{c}", agent_id="pay", severity="low", status="open",
                      opened_at=opened, regulation_refs=[], summary="s")  # fmt: skip
                r.add("case_event", case_id=f"C{c}", seq=0, ts=opened, actor="u", actor_kind="user",
                      action="note")  # fmt: skip
            m = OversightMetrics(r.ctx)
            return r.reads_of(lambda: m.compute("pay", day, True))[1]
        finally:
            r.close()

    assert run(1) == run(15)


# ------------------------------------------------------------------------------------ N15


def _seed_pack(r: Rig, agents: list[str]) -> None:
    for a in agents:
        for k in range(3):  # three results per agent: the newest one counts
            r.add(
                "eval_result", run_id=f"run-{a}-{k}", ts=T0 - dt.timedelta(hours=3 - k),
                pack_id="p1", pack_version=1, target_kind="agent", target_id=a,
                status="ok" if k == 2 else "fail",
            )  # fmt: skip


def _old_check_pack(
    env: Any, m: Any, agents: list[str], versions: dict[str, int]
) -> dict[str, Any]:
    out = []
    for agent in agents:
        rows = env.tables.query(
            "eval_result", {"target_kind": "agent", "target_id": agent, "pack_id": m.id},
            order_by=["-ts"], limit=1,
        )  # fmt: skip
        out.append(rows[0]["run_id"] if rows else None)
    return out  # type: ignore[return-value]


@pytest.mark.parametrize("n", [2, 20])
def test_n15_pack_check_reads_all_agents_at_once(rig: Rig, n: int) -> None:
    agents = [f"ag{i}" for i in range(n)]
    _seed_pack(rig, agents)
    env = SimpleNamespace(tables=rig.tables, state=rig.state)
    m = rd.Measure("pack", "p1", True)
    res, reads = rig.reads_of(lambda: rd._check_pack(env, m, agents, {"p1": 1}))
    assert reads == 1
    assert res["state"] == "ok"
    assert res["pointers"] == [f"pack:p1:run-{a}-2:{a}" for a in agents]
    assert [p.split(":")[2] for p in res["pointers"]] == _old_check_pack(env, m, agents, {})
    res_missing = rd._check_pack(env, m, [*agents, "ghost"], {"p1": 1})
    assert res_missing["state"] == "missing"


@pytest.mark.parametrize("n", [2, 20])
def test_n15_monitor_check_and_summary(rig: Rig, n: int) -> None:
    agents = [f"ag{i}" for i in range(n)]
    for a in agents:
        rig.put("oversight_metric", metric_date="2026-10-21", agent_id=a)
    env = SimpleNamespace(tables=rig.tables, state=rig.state)
    m = rd.Measure("monitor", "oversight", True)
    res, reads = rig.reads_of(lambda: rd._check_monitor(env, m, agents))
    assert reads == 1 and res["state"] == "ok" and len(res["pointers"]) == n
    assert rd._check_monitor(env, m, [*agents, "ghost"])["state"] == "missing"
    assert rd._check_monitor(env, m, [])["state"] == "missing"


@pytest.mark.parametrize("n", [3, 25])
def test_n15_summary_reads_all_systems_at_once(rig: Rig, n: int) -> None:
    cfg = rd.load_config()
    dims = [d.id for d in cfg.dimensions]
    ids = [f"S{i}" for i in range(n)]
    for i, sid in enumerate(ids[:-1]):  # the last system has no rows: not_started
        rig.put(
            "risk_dimension_status", status_id=f"{sid}:{dims[0]}", system_id=sid,
            dimension_id=dims[0], status="pass" if i % 2 else "not_started",
            evidence_json=[], threshold_json={}, updated_by="t",
        )  # fmt: skip
    env = SimpleNamespace(state=rig.state, cfg=cfg)
    out, reads = rig.reads_of(lambda: rd.summary(env, ids))
    assert reads == 1
    first = out["dimensions"][0]
    assert first["pass"] == (n - 1) // 2 and out["systems"] == n
    assert first["not_started"] == n - first["pass"]


@pytest.mark.parametrize("n", [2, 20])
def test_n15_duty_evidence_reader_is_constant_in_agents(rig: Rig, n: int) -> None:
    agents = [f"ag{i}" for i in range(n)]
    for a in agents:
        rig.add("agent_event", event_id=f"e-{a}", ts=T0, agent_id=a, event_type="gate_decision")
        rig.put("cases", case_id=f"C-{a}", agent_id=a, severity="low", status="open",
                opened_at=T0, regulation_refs=[], summary="s")  # fmt: skip
        rig.add("signoff", signoff_id=f"s-{a}", case_id=f"C-{a}", ts=T0)
        rig.put("oversight_metric", metric_date="2026-10-22", agent_id=a)
    env = SimpleNamespace(tables=rig.tables, state=rig.state)
    w = Window(T0 - dt.timedelta(days=1), T0 + dt.timedelta(days=1))
    reader = de.Reader(env, agents, w, None)
    counts = {}
    for counter in ("gate", "events", "cases", "signoff", "mon:oversight"):
        counts[counter], reads = rig.reads_of(lambda c=counter: reader.count(c))
        assert reads <= 2, (counter, reads)
    assert counts == {"gate": n, "events": n, "cases": n, "signoff": n, "mon:oversight": n}


# ------------------------------------------------------------------------------------ N16


@pytest.mark.parametrize("n", [3, 30])
def test_n16_agreement_pairs_do_not_query_per_link_or_case(rig: Rig, n: int) -> None:
    for c in range(n):
        cid = f"CASE-{c}"
        ref = f"ev{c}"
        rig.add(
            "case_link",
            source_kind="gate",
            source_ref=ref,
            case_id=cid,
            agent_id=f"ag{c % 3}",
            ts=T0,
        )
        rig.add("verdict", verdict_id=f"vj{c}", event_id=ref, agent_id=f"ag{c % 3}", tier=1,
                advisory=True, ts=T0)  # fmt: skip
        rig.add("verdict", verdict_id=f"vg{c}", event_id=ref, agent_id=f"ag{c % 3}", tier=0,
                advisory=False, ts=T0)  # fmt: skip
        rig.add("signoff", signoff_id=f"s{c}", case_id=cid, decision="close:confirmed", ts=T0)
    pairs, reads = rig.reads_of(lambda: agreement_pairs(rig.tables))
    assert reads <= 3  # case_link, verdict batch, signoff
    assert len(pairs) == n
    by_case = {p["case_id"]: p for p in pairs}
    assert all(
        by_case[f"CASE-{c}"]["agent_id"] == f"ag{c % 3}"
        and by_case[f"CASE-{c}"]["verdict_ids"] == [f"vj{c}"]
        for c in range(n)
    )


# ------------------------------------------------------------------------------------ misc


def test_as_dt_keeps_its_contract() -> None:
    assert as_dt("2026-10-22T12:00:00Z") == T0
    assert as_dt("2026-10-22T19:00:00+07:00") == T0
    assert as_dt("2026-10-22T12:00:00") == T0  # naive is UTC
    assert as_dt(T0.astimezone(dt.timezone(dt.timedelta(hours=7)))) == T0
    with pytest.raises(ValueError):
        as_dt("not a time")


_ = uuid
