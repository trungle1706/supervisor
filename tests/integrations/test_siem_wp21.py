"""WP21: SIEM production sinks (file rotation, http retry + dead letter + idempotency, delta),
OCSF output, per-lane cursors. Offline: fake transports, SQLite, databricks_fake."""

# ruff: noqa: F401, F811, E501 (the evidence conftest fixture ``env`` is imported)

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from supervisor.adapters.integrations import (
    IntegrationError,
    RetryPolicy,
    load_integration_settings,
)
from supervisor.adapters.integrations import siem as S
from supervisor.adapters.integrations.deadletter import DeadLetter
from supervisor.adapters.integrations.ocsf import CLASSES, EVENT_CLASS, OCSF_VERSION, to_ocsf_dict
from supervisor.adapters.integrations.transport import HttpTransport, idempotency_key
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlStateStore, SqlTableStore
from supervisor.core.errors import DuplicateKeyError
from supervisor.core.schema import load_model
from tests.evidence.conftest import T0, Env, env, make_writer

ENTRY = {
    "lane": "agent:a1",
    "seq": 7,
    "ts": "2026-10-19T08:00:00.000000Z",
    "record_type": "gate_decision",
    "entry_hash": "ab" * 32,
    "env": "laptop",
}


def _ev(event_type: str = "gate_decision", n: int = 1, **kw: Any) -> S.SiemEvent:
    base: dict[str, Any] = {
        "event_id": f"agent:a1:{n}",
        "event_type": event_type,
        "ts": "2026-10-19T08:00:00.000000Z",
        "severity": 7,
        "outcome": "block",
        "agent_id": "a1",
        "rule_id": "PAY-08",
        "case_id": None,
        "actor": None,
        "chain_lane": "agent:a1",
        "chain_seq": n,
        "entry_hash": "ab" * 32,
        "env": "laptop",
    }
    base.update(kw)
    return S.SiemEvent(**base)


# --------------------------------------------------------------------------- OCSF

CHAIN_CASES: list[tuple[str, dict[str, Any], str, int]] = [
    ("gate_decision", {"agent_id": "a1", "action": "block", "rule_id": "PAY-08"}, "gate_decision", 6003),
    ("gate_state_change", {"agent_id": "a1", "event": "quarantine", "principal": "u1"}, "gate_state_change", 6003),
    ("case", {"agent_id": "a1", "case_id": "C1", "severity": "high", "opened_by": "u"}, "case_opened", 2004),
    ("case_event", {"agent_id": "a1", "case_id": "C1", "action": "triage", "actor": "u"}, "case_event", 2004),
    ("chain_verify", {"ok": False, "failures": 2}, "chain_anomaly", 2004),
    ("audit_pack_built", {"verify_ok": False}, "chain_anomaly", 2004),
    ("ingress_reject", {"agent_id": "a1", "reason_code": "bad_signature"}, "ingress_reject", 3002),
    ("root_commit", {}, "chain_root", 6003),
]  # fmt: skip

REQUIRED = (
    "activity_id",
    "category_uid",
    "class_uid",
    "severity_id",
    "time",
    "type_uid",
    "metadata",
)


@pytest.mark.parametrize("rtype, payload, etype, class_uid", CHAIN_CASES)
def test_ocsf_required_fields_and_class_consistency(
    rtype: str, payload: dict[str, Any], etype: str, class_uid: int
) -> None:
    ev = S.event_from_chain({**ENTRY, "record_type": rtype}, payload)
    assert ev is not None and ev.event_type == etype
    doc = to_ocsf_dict(ev)
    for k in REQUIRED:
        assert k in doc, k
    assert doc["class_uid"] == class_uid == EVENT_CLASS[etype]
    assert doc["category_uid"] == CLASSES[class_uid][0] == class_uid // 1000
    assert doc["type_uid"] == class_uid * 100 + doc["activity_id"]
    assert doc["class_name"] == CLASSES[class_uid][1]
    assert 0 <= doc["severity_id"] <= 5 and isinstance(doc["time"], int) and doc["time"] > 0
    assert doc["metadata"]["version"] == OCSF_VERSION
    assert doc["metadata"]["product"]["vendor_name"] == "Supervisor"
    assert doc["metadata"]["uid"] == ev.event_id
    json.dumps(doc)  # serialisable
    if class_uid == 2004:
        assert doc["finding_info"]["uid"] and doc["finding_info"]["title"]
    if class_uid == 3002:
        assert doc["status_id"] == 2 and doc["user"]["uid"] == "a1"
    if class_uid == 6003:
        assert doc["api"]["operation"] and doc["actor"]["user"]["uid"]


def test_ocsf_alert_event_and_block_dispositions() -> None:
    alert = S.event_from_alert(
        {
            "alert_id": "f" * 32, "ts": "2026-10-19T08:00:00.000000Z", "dedupe_key": "R:a",
            "rule_id": "AL-BLOCK-BURST", "severity": "high", "agent_id": "a1", "case_id": "C9",
            "chain_lane": "agent:a1", "chain_seq": 4, "entry_hash": "cd" * 32, "window_s": 600,
            "window_count": 5, "threshold": 5, "suppressed_count": 2,
        }
    )  # fmt: skip
    doc = to_ocsf_dict(alert)
    assert doc["class_uid"] == 2004 and doc["severity_id"] == 4
    assert doc["unmapped"]["attrs"]["window_count"] == 5
    assert doc["resources"] == [{"type": "AI Agent", "uid": "a1"}]
    block = to_ocsf_dict(_ev(outcome="block"))
    assert (block["disposition_id"], block["action_id"], block["status_id"]) == (2, 2, 2)
    allow = to_ocsf_dict(_ev(outcome="allow", severity=1))
    assert (allow["disposition_id"], allow["action_id"], allow["status_id"]) == (1, 1, 1)


def test_good_audit_pack_is_not_an_anomaly() -> None:
    assert (
        S.event_from_chain({**ENTRY, "record_type": "audit_pack_built"}, {"verify_ok": True})
        is None
    )
    ok = S.event_from_chain({**ENTRY, "record_type": "chain_verify"}, {"ok": True})
    assert ok is not None and ok.outcome == "verify_ok" and ok.severity == 1


FREE_TEXT = "chuyen khoan cho Nguyen Van A so dien thoai 0912345678"


@pytest.mark.parametrize("fmt", ["jsonl", "cef", "ocsf"])
def test_no_free_text_or_pii_in_any_format(fmt: str) -> None:
    payload = {
        "agent_id": "a1",
        "action": "block",
        "rule_id": "PAY-08",
        "reason": FREE_TEXT,
        "args_masked": FREE_TEXT,
        "comment": FREE_TEXT,
    }
    ev = S.event_from_chain(ENTRY, payload)
    assert ev is not None
    out = S.FORMATTERS[fmt](ev)
    assert "Nguyen" not in out and "0912345678" not in out and "chuyen" not in out


def test_unknown_format_is_refused_and_json_is_an_alias() -> None:
    with pytest.raises(IntegrationError, match="jsonl, cef or ocsf"):
        S.LogSiemSink(Path("x"), "xml")
    assert S.FORMATTERS["json"] is S.FORMATTERS["jsonl"]


def test_cef_labels_only_with_values() -> None:
    line = S.to_cef(_ev())
    assert "cs3Label" not in line and "cn2Label" not in line and "cs1Label=agentId" in line
    alert = S.event_from_alert(
        {
            "alert_id": "a" * 32, "ts": "2026-10-19T08:00:00.000000Z", "dedupe_key": "R:a",
            "rule_id": "AL-X", "severity": "low", "agent_id": "a", "window_s": 60,
            "window_count": 3, "threshold": 3, "suppressed_count": 4,
        }
    )  # fmt: skip
    cef = S.to_cef(alert)
    assert "cn2=3" in cef and "cn3=4" in cef and "cn2Label=windowCount" in cef


# --------------------------------------------------------------------------- file sink


def test_file_sink_rotates_by_size_and_never_splits_a_batch(tmp_path: Path) -> None:
    path = tmp_path / "siem" / "events.log"
    one = len(S.to_json(_ev()) + "\n")
    sink = S.LogSiemSink(path, "jsonl", max_bytes=one * 3, backups=2)
    for i in range(12):
        sink.emit([_ev(n=i)])
    files = sorted(p.name for p in path.parent.iterdir())
    assert files == ["events.log", "events.log.1", "events.log.2"]
    seen = []
    for name in ("events.log.2", "events.log.1", "events.log"):
        lines = (path.parent / name).read_text("utf-8").splitlines()
        assert 1 <= len(lines) <= 3
        seen += [json.loads(x)["event_id"] for x in lines]  # every line is whole JSON
    assert seen == sorted(seen, key=lambda s: int(s.rsplit(":", 1)[1]))
    assert seen[-1] == "agent:a1:11"  # the newest event is in the live file
    assert path.stat().st_size <= one * 3


def test_file_sink_without_limit_never_rotates(tmp_path: Path) -> None:
    sink = S.LogSiemSink(tmp_path / "e.log")
    for i in range(20):
        sink.emit([_ev(n=i)])
    assert [p.name for p in tmp_path.iterdir()] == ["e.log"]


def test_file_sink_writes_ocsf_lines(tmp_path: Path) -> None:
    sink = S.LogSiemSink(tmp_path / "e.log", "ocsf")
    sink.emit([_ev(), _ev("ingress_reject", n=2, outcome="reject")])
    docs = [json.loads(x) for x in (tmp_path / "e.log").read_text("utf-8").splitlines()]
    assert [d["class_uid"] for d in docs] == [6003, 3002]


# --------------------------------------------------------------------------- http sink


class FlakyTransport:
    def __init__(self, fail: int) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls.append(payload)
        if self.fail:
            self.fail -= 1
            raise ConnectionError("down")
        return {"ok": True}


def test_http_sink_backoff_dead_letter_and_replay(tmp_path: Path) -> None:
    dl = DeadLetter(tmp_path / "dead.jsonl")
    slept: list[float] = []
    tr = FlakyTransport(fail=3)
    sink = S.WebhookSiemSink(
        "https://siem.example.invalid/hec",
        transport=tr,
        sleep=slept.append,
        fmt="ocsf",
        dead_letter=dl,
    )
    events = [_ev(n=1), _ev(n=2)]
    assert sink.emit(events) == 0  # parked, not raised: the feed can move on
    assert len(tr.calls) == 3 and slept == [1.0, 2.0] and sink.dead_lettered == 1
    entries = dl.entries()
    assert len(entries) == 1 and entries[0]["kind"] == "siem" and entries[0]["attempts"] == 3
    key = entries[0]["key"]
    assert key == idempotency_key(e.event_id for e in events) == tr.calls[0]["idempotency_key"]
    assert [d["class_uid"] for d in entries[0]["payload"]["events"]] == [6003, 6003]
    # the receiver is back: replay sends the SAME key, the file empties
    assert sink.replay_dead_letter() == (1, 0)
    assert tr.calls[-1]["idempotency_key"] == key and dl.count() == 0


def test_http_sink_without_dead_letter_raises_after_retries() -> None:
    sink = S.WebhookSiemSink(
        "https://x.invalid/h", transport=FlakyTransport(9), sleep=lambda _s: None
    )
    with pytest.raises(IntegrationError, match="after 3 attempt"):
        sink.emit([_ev()])


def test_http_sink_replay_keeps_entries_that_still_fail(tmp_path: Path) -> None:
    dl = DeadLetter(tmp_path / "d.jsonl")
    tr = FlakyTransport(fail=99)
    sink = S.WebhookSiemSink(
        "https://x.invalid/h", transport=tr, sleep=lambda _s: None, dead_letter=dl
    )
    sink.emit([_ev()])
    assert sink.replay_dead_letter() == (0, 1) and dl.count() == 1


def test_idempotency_key_is_stable_and_order_sensitive() -> None:
    assert idempotency_key(["a", "b"]) == idempotency_key(["a", "b"])
    assert idempotency_key(["a", "b"]) != idempotency_key(["b", "a"])
    assert len(idempotency_key(["a"])) == 32


def test_transport_headers_status_mapping_and_no_token_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    reply: dict[str, Any] = {"status": 200}

    def fake_post(url: str, **kw: Any) -> httpx.Response:
        seen.update(kw, url=url)
        if reply.get("raise"):
            raise reply["raise"]
        return httpx.Response(reply["status"], request=httpx.Request("POST", url), content=b"")

    monkeypatch.setattr(httpx, "post", fake_post)
    tr = HttpTransport("s3cret-token", "Splunk")
    assert tr("https://h.invalid/x", {"idempotency_key": "k1"}, 5.0) == {}
    assert seen["headers"] == {"Authorization": "Splunk s3cret-token", "Idempotency-Key": "k1"}
    assert "s3cret" not in repr(tr)
    reply["status"] = 503  # retried class
    with pytest.raises(ConnectionError, match="HTTP 503"):
        tr("https://h.invalid/x", {}, 5.0)
    reply["status"] = 401  # permanent: no retry
    with pytest.raises(IntegrationError, match="HTTP 401"):
        tr("https://h.invalid/x", {}, 5.0)
    reply.update(raise_=None, raise_error=None)
    reply["raise"] = httpx.ConnectError("boom")
    with pytest.raises(ConnectionError):
        tr("https://h.invalid/x", {}, 5.0)
    # end to end through the sink: a 401 is parked at once (one attempt), the token stays out
    reply.pop("raise")
    dl = DeadLetter(tmp_path / "d.jsonl")
    sink = S.WebhookSiemSink(
        "https://h.invalid/x", transport=tr, sleep=lambda _s: None, dead_letter=dl
    )
    assert sink.emit([_ev()]) == 0
    assert "s3cret" not in (tmp_path / "d.jsonl").read_text("utf-8")


def test_build_siem_sink_kinds(tmp_path: Path) -> None:
    mk = lambda **kw: load_integration_settings(_env_file=None, siem_enabled=True, **kw)  # noqa: E731
    assert S.build_siem_sink(load_integration_settings(_env_file=None), tmp_path) is None
    f = S.build_siem_sink(mk(siem_format="ocsf", siem_file_max_bytes=1000), tmp_path)
    assert isinstance(f, S.LogSiemSink) and f.fmt == "ocsf" and f.max_bytes == 1000
    h = S.build_siem_sink(mk(siem_sink="http", siem_webhook_url="https://h.invalid/x"), tmp_path)
    assert isinstance(h, S.WebhookSiemSink) and h.dead_letter is not None
    assert h.dead_letter.path == tmp_path / "siem" / "dead_letter.jsonl"
    with pytest.raises(IntegrationError, match="FILL-ME"):
        S.build_siem_sink(mk(siem_sink="http"), tmp_path)
    with pytest.raises(IntegrationError, match="needs the SQL store"):
        S.build_siem_sink(mk(siem_sink="delta"), tmp_path)


# --------------------------------------------------------------------------- delta sink


def test_delta_sink_on_sqlite_is_idempotent(env: Env) -> None:
    sink = S.DeltaSiemSink(env.adapters.tables)
    evs = [_ev(n=1), _ev("ingress_reject", n=2, outcome="reject", severity=6)]
    assert sink.emit(evs) == 2
    assert sink.emit(evs) == 0  # the same events again add nothing
    assert sink.emit(evs + [_ev(n=3)]) == 1  # a partial overlap adds only the new one
    rows = env.adapters.tables.query("siem_event", order_by=["event_id"])
    assert [r["event_id"] for r in rows] == ["agent:a1:1", "agent:a1:2", "agent:a1:3"]
    r2 = rows[1]
    assert r2["ocsf_class_uid"] == 3002 and r2["event_schema"] == S.SCHEMA
    assert json.loads(r2["ocsf_json"])["class_uid"] == 3002
    assert r2["agent_id"] == "a1" and r2["chain_seq"] == 2


def test_delta_sink_with_databricks_fake_issues_an_insert_only_merge() -> None:
    fake = FakeStatementExecution()
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    model = load_model()
    tables = SqlTableStore(ex, model)
    sink = S.DeltaSiemSink(tables)
    fake.add(dml_result(2), match="MERGE INTO")
    assert sink.emit([_ev(n=1), _ev(n=2)]) == 2
    stmt = fake.statements[0]
    assert "MERGE INTO" in stmt and "siem_event" in stmt and "WHEN NOT MATCHED THEN INSERT" in stmt
    assert "tgt.event_id = src.event_id" in stmt  # the primary key is the idempotency key
    assert "UPDATE" not in stmt and "DELETE" not in stmt  # append-only table
    # a restart sends the same batch: Delta says 1 of 2 existed -> row by row, only the new one counts
    fake.add(dml_result(1), match="MERGE INTO")  # batch: one row was new
    fake.add(dml_result(0), match="MERGE INTO")  # row 1 alone: already there
    fake.add(dml_result(1), match="MERGE INTO")  # row 2 alone: new
    assert sink.emit([_ev(n=1), _ev(n=2)]) == 1
    assert fake.remaining() == 0 and len(fake.statements) == 4


# --------------------------------------------------------------------------- feed cursors


class ListSink:
    def __init__(self) -> None:
        self.batches: list[list[S.SiemEvent]] = []
        self.fail = False

    def emit(self, events: Any) -> int:
        evs = list(events)
        if self.fail:
            raise IntegrationError("sink down")
        self.batches.append(evs)
        return len(evs)


def _decisions(w: Any, env: Env, agent: str, n: int, action: str = "block") -> None:
    for i in range(n):
        env.clock.advance(1)
        w.record(
            "gate_decision",
            f"d:{agent}:{i}:{env.clock.now().timestamp()}",
            {"agent_id": agent, "action": action, "rule_id": "PAY-08", "allow": False},
        )


def test_cursor_per_lane_survives_a_restart_without_duplicates(env: Env) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 3)
    _decisions(w, env, "a2", 2)
    sink = ListSink()
    feed = S.ChainEventFeed(env.adapters.tables, sink, env.adapters.state)
    first = feed.poll()
    ids = [e.event_id for b in sink.batches for e in b]
    assert first == len(ids) and len(set(ids)) == len(ids) >= 5
    cursors = {
        r["state_key"] for r in env.adapters.state.query("monitor_state", {"monitor": "siem"})
    }
    assert {"cursor:agent:a1", "cursor:agent:a2"} <= cursors
    # "restart": a brand new feed object on the same store
    feed2 = S.ChainEventFeed(env.adapters.tables, sink, env.adapters.state)
    assert feed2.poll() == 0
    _decisions(w, env, "a1", 2)
    n = feed2.poll()
    new_ids = [e.event_id for e in sink.batches[-1]]
    assert n == len(new_ids) >= 2 and not set(new_ids) & set(ids)
    assert all(i.startswith("agent:a1:") or i.startswith("root:") for i in new_ids)


def test_cursor_does_not_advance_when_the_sink_fails(env: Env) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 2)
    sink = ListSink()
    sink.fail = True
    feed = S.ChainEventFeed(env.adapters.tables, sink, env.adapters.state)
    with pytest.raises(IntegrationError):
        feed.poll()
    assert env.adapters.state.query("monitor_state", {"monitor": "siem"}) == []
    sink.fail = False
    assert feed.poll() >= 2  # nothing was lost


def test_feed_batch_cap_continues_next_poll(env: Env) -> None:
    w = make_writer(env)
    _decisions(w, env, "a1", 6)
    sink = ListSink()
    feed = S.ChainEventFeed(env.adapters.tables, sink, env.adapters.state, max_events=3)
    total, ids = 0, []
    for _ in range(10):
        n = feed.poll()
        total += n
        if n == 0:
            break
    ids = [e.event_id for b in sink.batches for e in b]
    assert len(ids) == len(set(ids)) and sum(1 for i in ids if i.startswith("agent:a1:")) == 6


def test_ingress_reject_and_chain_verify_records_reach_the_siem(env: Env) -> None:
    w = make_writer(env)
    w.record("ingress_reject", "ir:1", {"agent_id": "a1", "reason_code": "bad_signature"})
    w.record("chain_verify", "cv:1", {"ok": False, "failures": 3})
    sink = ListSink()
    S.ChainEventFeed(env.adapters.tables, sink, env.adapters.state).poll()
    kinds = {e.event_type: e for b in sink.batches for e in b}
    assert kinds["ingress_reject"].attrs == {"reason_code": "bad_signature"}
    assert (
        kinds["chain_anomaly"].outcome == "verify_failed" and kinds["chain_anomaly"].severity == 10
    )


def test_env_names_and_secret_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIEM_ENABLED", "1")
    monkeypatch.setenv("SIEM_SINK", "http")
    monkeypatch.setenv("SIEM_FORMAT", "ocsf")
    monkeypatch.setenv("SIEM_HTTP_URL", "https://h.invalid/x")  # alias of SIEM_WEBHOOK_URL
    monkeypatch.setenv("SIEM_HTTP_TOKEN", "tok-xyz")
    monkeypatch.setenv("SIEM_HTTP_AUTH_SCHEME", "Splunk")
    cfg = load_integration_settings(_env_file=None)
    assert cfg.siem_webhook_url == "https://h.invalid/x" and cfg.siem_http_auth_scheme == "Splunk"
    assert "tok-xyz" not in repr(cfg)
    sink = S.build_siem_sink(cfg, tmp_path)
    assert isinstance(sink, S.WebhookSiemSink) and sink.fmt == "ocsf"
    assert "tok-xyz" not in repr(sink.transport)


def test_file_sink_keeps_writing_when_rotation_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "e.log"
    sink = S.LogSiemSink(path, max_bytes=50, backups=2)
    sink.emit([_ev(n=1)])

    def blocked(*_a: Any, **_k: Any) -> None:
        raise PermissionError("file in use")  # Windows forwarder without share-delete

    monkeypatch.setattr(S.os, "replace", blocked)
    assert sink.emit([_ev(n=2)]) == 1  # no exception, the event is not lost
    assert len(path.read_text("utf-8").splitlines()) == 2
