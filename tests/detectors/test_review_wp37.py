"""WP37 review tests (Opus reviewer): R1 matrix, bounded detector time, R2 on every write path,
additive SQLite migration, ASCII start-up errors."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.integrations import siem
from supervisor.adapters.integrations.ocsf import to_ocsf_dict
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.sqlite import SqliteExecutor
from supervisor.adapters.sql.store import SqlTableStore
from supervisor.config import load_settings
from supervisor.core import detectors as D
from supervisor.core.detectors import Finding, derive_status
from supervisor.core.schema import SchemaModel, load_model, sqlite_statements
from supervisor.core.schema_diff import live_columns
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import load_policy_texts
from supervisor.jobs import bootstrap_schema
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import GatewayFactory, make_gate
from tests.detectors.fakes import FakeDetector, boom, hint
from tests.detectors.fingerprint import PII_ARGS
from tests.gateway.conftest import MemoryEvidence

NAME = "NGUYEN VAN THU"
PHONE = "0912345678"
CCCD = "001203004567"
EMAIL = "thu.nguyen@example.com"
RAW = (NAME, PHONE, CCCD, EMAIL, "Nguyen Van Thu")
MONEY = {"amount_minor": 1000, "from_account_id": "ACC-1", "payee_id": "P-1", "customer_id": "C-1"}


def _cfg(*slugs: str, fail_closed: bool = True, limits: Mapping[str, Any] | None = None) -> str:
    doc = yaml.safe_load((REPO_ROOT / "config" / "detectors.yaml").read_text(encoding="utf-8"))
    for s in slugs:
        doc["detectors"][s] = {"enabled": True, "fail_closed": fail_closed, "settings": {}}
    doc["limits"].update(limits or {})
    return yaml.safe_dump(doc)


class _DownJudge:
    def judge(self, *a: Any, **k: Any) -> Any:
        from supervisor.judge.runner import JudgeCall

        return JudgeCall(
            tier=1, role="primary", checker_id="x", model_id="m", model_family="f",
            family_source="mock", model_version="1", region="local", mask_version="v",
            prompt_hash="h", is_mock=True, status="unavailable", suspicion_bp=None,
            label="judge_unavailable", rationale_masked="",
        )  # fmt: skip


# ---------------------------------------------------------------------------- R1


def test_judge_advisory_never_fails_closed_even_if_the_yaml_says_so(
    make_gateway: GatewayFactory, masker: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from supervisor.detectors import build_registry

    reg = build_registry(masker, judge=_DownJudge())
    assert reg.may_fail_closed("judge_advisory") is False
    assert reg.may_fail_closed("dlp_vn") and reg.may_fail_closed("injection_regex")
    with caplog.at_level(logging.WARNING, logger="supervisor.detectors.config"):
        gate = make_gate(masker, registry=reg, config_text=_cfg("judge_advisory"))
    assert "judge_advisory.fail_closed: ignored" in caplog.text
    run_cfg, _ = gate.resolved.for_agent(None)
    assert run_cfg.detectors["judge_advisory"].fail_closed is False
    gw = make_gateway(gate=gate)
    for agent, tool, args in (
        ("payments", "transfer", MONEY),
        ("credit_prequal", "decide_prequal", {"application_id": "A-1"}),
        ("payments", "add_payee", {"payee_name": "P"}),
    ):
        r = gw.check(agent, "1", tool, args)
        assert r["rule_id"] != "GATE-DETECTOR-FAILED", tool
        assert ("judge_advisory", "execution_failed") in [
            (n["detector_slug"], n["reason"]) for n in r["not_executed"]
        ]


def test_registry_refuses_fail_closed_for_an_advisory_detector_built_by_hand() -> None:
    """Defence in depth: a RunConfig made without the config loader cannot do it either."""
    det = FakeDetector("adv", boom)
    det.category = "advisory"  # type: ignore[misc]
    reg = D.DetectorRegistry([det])
    cfg = D.RunConfig(detectors={"adv": D.DetectorSetting(True, {"preset": "balanced"}, True)})
    res = reg.run({"args": {"a": "x"}, "meta": {}}, "input", cfg, risk_class="money")
    assert [n.not_executed_reason for n in res.not_executed] == ["execution_failed"]
    assert res.failed_closed == []
    # and the "*" (content_uninspectable) path does not count an advisory detector
    res = reg.run({"args": {"a": b"\x00"}, "meta": {}}, "input", cfg, risk_class="money")
    assert res.failed_closed == []


CALLS: list[tuple[str, str, dict[str, Any]]] = [
    ("customer_service", "read_ticket", {"ticket_id": "T1"}),
    ("customer_service", "waive_fee", {"amount_minor": 1, "customer_id": "C-1"}),
    ("payments", "get_balance", {"account_id": "A-1"}),
    ("payments", "add_payee", {"payee_name": "P"}),
    ("payments", "transfer", {**MONEY, "amount_minor": 0}),  # a deterministic block
    ("credit_prequal", "decide_prequal", {"application_id": "A-1"}),
    ("nobody", "read_ticket", {}),
]
KEEP = ("allow", "action", "rule_id", "agent_state", "risk_class", "policy_hash")


@pytest.mark.parametrize("action", ["report", "transform", "pause", "block"])
def test_no_finding_hint_changes_any_decision(
    make_gateway: GatewayFactory, masker: Any, action: str
) -> None:
    """R1 matrix: a detector that fires at score 10000 with every hint on every risk class
    leaves allow / action / rule_id exactly as the flag-off gate decides."""
    gw = make_gateway(
        gate=make_gate(masker, extra=[hint(action, 10_000)], config_text=_cfg("hinter"))
    )
    on = [gw.check(a, "1", t, dict(x)) for a, t, x in CALLS]
    gate, gw.detector_gate = gw.detector_gate, None
    try:
        off = [gw.check(a, "1", t, dict(x)) for a, t, x in CALLS]
    finally:
        gw.detector_gate = gate
    for (agent, tool, _), x, y in zip(CALLS, on, off, strict=True):
        assert {k: x[k] for k in KEEP} == {k: y[k] for k in KEEP}, (agent, tool)
        assert x["status"] in ("block", "pause") if not y["allow"] else x["status"] == "report"
        assert x["agent_paused"] is False or y["agent_paused"] is True


def test_detector_failure_blocks_only_money_credit_and_pii_export(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    gw = make_gateway(
        gate=make_gate(masker, extra=[FakeDetector("bad", boom)], config_text=_cfg("bad"))
    )
    calls = [
        *CALLS,
        ("payments", "transfer", dict(MONEY)),
        ("payments", "add_payee", dict(PII_ARGS)),
        ("credit_prequal", "fetch_application", {"application_id": "APP-1"}),
        ("credit_prequal", "decide_prequal", {"application_id": "APP-1", "decision": "refer"}),
    ]
    # flag off first: its allowed fetch_application is the prior that CRD-02 needs later
    gate, gw.detector_gate = gw.detector_gate, None
    try:
        off = [gw.check(a, "1", t, dict(x)) for a, t, x in calls]
    finally:
        gw.detector_gate = gate
    on = [gw.check(a, "1", t, dict(x)) for a, t, x in calls]
    blocked_by_failure = set()
    for (_agent, tool, _), x, y in zip(calls, on, off, strict=True):
        if not y["allow"]:  # a deterministic block keeps its own rule id
            assert x["rule_id"] == y["rule_id"] and x["status"] in ("block", "pause"), tool
        elif y["risk_class"] in ("money", "credit", "pii_export"):
            assert x["rule_id"] == "GATE-DETECTOR-FAILED", tool
            assert x["status"] == "block" and "transformed_args" not in x
            blocked_by_failure.add(y["risk_class"])
        else:  # read_only: listed only
            assert x["allow"] is True and x["not_executed"], tool
    assert blocked_by_failure == {"money", "credit", "pii_export"}


def test_precedence_with_skip_and_transform() -> None:
    rep = [Finding("a", "a@1", "c", score_bp=9000, threshold_bp=5000)]
    skip = {"findings": [], "skipped": True}
    # skip never hides a deterministic block or pause
    assert derive_status(allow=False, action="block", has_transform=False, **skip) == "block"
    assert derive_status(allow=False, action="pause", has_transform=False, **skip) == "pause"
    assert (
        derive_status(
            allow=False, action="pause", has_transform=True, matched_actions=["block"], **skip
        )
        == "block"
    )
    # a transform (WP24b on a skipped call) stays visible
    assert derive_status(allow=True, action="allow", has_transform=True, **skip) == "transform"
    assert derive_status(allow=True, action="allow", has_transform=False, **skip) == "skip"
    # full order on an allowed call
    base = {"allow": True, "action": "allow"}
    assert derive_status(**base, findings=rep, has_transform=True) == "transform"
    assert derive_status(**base, findings=rep, has_transform=False) == "report"
    assert derive_status(**base, findings=[], has_transform=False) == "allow"


# ---------------------------------------------------------------------------- bounded time


def _hang(release: threading.Event) -> Any:
    def run(payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str) -> list:
        release.wait(30)
        return []

    return run


def test_a_hung_detector_cannot_hold_the_gate_past_its_timeout(
    make_gateway: GatewayFactory, masker: Any
) -> None:
    """A detector that never returns: the money decision comes back well inside the gate's
    2 s budget, as GATE-DETECTOR-FAILED (timed_out), and the gate workers stay free."""
    release = threading.Event()
    gate = make_gate(
        masker,
        extra=[FakeDetector("hang", _hang(release))],
        config_text=_cfg("hang", limits={"timeout_ms": 50}),
    )
    gw = make_gateway(gate=gate, workers=2)
    try:
        t0 = time.monotonic()
        answers = [gw.check("payments", "1", "transfer", dict(MONEY)) for _ in range(6)]
        took = time.monotonic() - t0
        # 6 calls on 2 workers: without the bound, calls 3+ would wait for the 2 s gate timeout
        assert took < 6 * 1.0, took
        for r in answers:
            assert r["rule_id"] == "GATE-DETECTOR-FAILED" and r["fail_mode"] == "closed"
            assert ("hang", "timed_out") in [
                (n["detector_slug"], n["reason"]) for n in r["not_executed"]
            ]
        ok = gw.check("customer_service", "1", "read_ticket", {"ticket_id": "T1"})
        assert ok["allow"] is True and ok["rule_id"] is None  # read_only: listed, not blocked
    finally:
        release.set()


def test_no_free_detector_slot_is_timed_out_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "_SLOTS", threading.BoundedSemaphore(1))
    release = threading.Event()
    reg = D.DetectorRegistry([FakeDetector("hang", _hang(release))])
    cfg = D.RunConfig(detectors={"hang": D.DetectorSetting(True, {"preset": "balanced"})})
    cfg = D.RunConfig(detectors=cfg.detectors, timeout_ms=20)
    try:
        first = reg.run({"args": {"a": "x"}, "meta": {}}, "input", cfg, risk_class="money")
        t0 = time.monotonic()
        second = reg.run({"args": {"a": "x"}, "meta": {}}, "input", cfg, risk_class="money")
        assert time.monotonic() - t0 < 0.5
        assert first.not_executed[0].detail == "deadline"
        assert second.not_executed[0].detail == "no free detector slot"
        assert [f.not_executed_reason for f in second.failed_closed] == ["timed_out"]
    finally:
        release.set()


# ---------------------------------------------------------------------------- R2


NESTED = {
    "customer_id": "C-1",
    "beneficiaries": [{"profile": {"full_name": NAME, "ids": [{"cccd": CCCD}]}}],
    "contact": {"lines": [f"goi {PHONE}", f"mail {EMAIL}"]},
}


def _blob(*parts: Any) -> str:
    return json.dumps(parts, ensure_ascii=False, default=str)


def test_no_raw_pii_on_any_write_path_nested_and_output(
    gw_on: Gateway, evidence: MemoryEvidence, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        a = gw_on.check(
            "payments",
            "1",
            "get_balance",
            {"account_id": "A-1", "memo": NESTED},
            {"tool_results": [{"rows": [NESTED]}], "trace_id": "t-r2"},
        )
        b = gw_on.check(
            "payments",
            "1",
            "add_payee",
            {"payee_name": "P"},
            {"output": {"result": NESTED, "text": f"{NAME} {CCCD}"}},
            direction="output",
        )
        gw_on.drain()
    assert {f["code"] for f in a["findings"]} >= {"pii.person", "pii.cccd", "pii.phone"}
    assert b["direction"] == "output" and b["status"] == "transform"
    frags = [x for r in (a, b) for f in r["findings"] for x in f["fragments"]]
    assert frags and all(x["text"].startswith("<") for x in frags)  # tokens on masked text
    tables = gw_on.tables
    rows = {t: tables.query(t, {}) for t in ("finding", "agent_event", "verdict")}
    chain = [p for _, _, p in evidence.entries]
    entry = {
        "lane": "agent:payments",
        "seq": 1,
        "ts": "2026-10-20T00:00:00Z",
        "env": "laptop",
        "entry_hash": "a" * 64,
    }
    events = [siem.event_from_chain({**entry, "record_type": t}, p) for t, _, p in evidence.entries]
    ocsf = [to_ocsf_dict(e) for e in events if e is not None]
    answers_minus_transform = [
        {k: v for k, v in r.items() if k != "transformed_payload"} for r in (a, b)
    ]
    stored = _blob(rows, chain, ocsf, caplog.text)
    for raw in RAW:
        assert raw not in stored, raw
        assert raw not in _blob(answers_minus_transform), raw
    for raw in RAW:  # the output the caller may pass on
        assert raw not in _blob(b["transformed_payload"]), raw

    # the same rows through the Delta executor: values travel as parameters, check those too
    fake = FakeStatementExecution()
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    delta = SqlTableStore(ex, load_model())
    for t, rs in rows.items():
        for r in rs:
            fake.add(dml_result(1))
            delta.append(t, [{k: v for k, v in r.items() if not k.startswith("_")}])
    sent = _blob([c.kwargs for c in fake.calls])
    assert "MERGE INTO" in sent or "INSERT" in sent
    for raw in RAW:
        assert raw not in sent, raw


def test_a_dict_key_holding_a_name_is_masked_in_the_path(gw_on: Gateway) -> None:
    r = gw_on.check("payments", "1", "get_balance", {"by_name": {NAME: PHONE}})
    assert NAME not in json.dumps(r, ensure_ascii=False)
    paths = [x["path"] for f in r["findings"] for x in f["fragments"]]
    assert paths and all("*" in p for p in paths)


def test_a_name_used_as_a_key_is_masked_in_the_transformed_payload(gw_on: Gateway) -> None:
    r = gw_on.check("payments", "1", "add_payee", {**PII_ARGS, "by_name": {NAME: PHONE}})
    assert r["status"] == "transform"
    for field in ("transformed_payload", "transformed_args"):
        assert NAME not in json.dumps(r[field], ensure_ascii=False), field
        assert PHONE not in json.dumps(r[field], ensure_ascii=False), field


# ---------------------------------------------------------------------------- settings


def test_policy_hash_unchanged_when_the_override_is_unset_and_changes_when_set() -> None:
    text = (REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8")
    plain = load_policy_texts([("p.yaml", text)])
    doc = yaml.safe_load(text)
    explicit_none = load_policy_texts([("p.yaml", yaml.safe_dump(doc))])
    assert plain.policy_hash == explicit_none.policy_hash
    doc["agents"]["payments"]["detectors"] = {"preset": "strict"}
    assert load_policy_texts([("p.yaml", yaml.safe_dump(doc))]).policy_hash != plain.policy_hash


def test_bad_detector_config_message_is_one_ascii_line(tmp_path: Path) -> None:
    from supervisor.core.errors import ConfigError
    from supervisor.preflight import format_check, run_checks
    from supervisor.wiring import build_runtime

    bad = tmp_path / "detectors.yaml"
    bad.write_text("detectors:\n  dlp_vn: {settings: {mode: ngang}}\n  bí: {}\n", encoding="utf-8")
    kw: dict[str, Any] = {
        "sql_backend": "sqlite",
        "data_dir": tmp_path / "data",
        "llm_base_url": "",
        "detectors_enabled": True,
        "detectors_config": bad,
    }
    with pytest.raises(ConfigError) as info:
        build_runtime(load_settings(**kw))
    msg = str(info.value)
    assert msg.isascii() and "\n" not in msg and "DETECTORS_CONFIG=" in msg and "mode" in msg
    assert info.value.__cause__ is None and info.value.__suppress_context__
    checks = run_checks(lambda: load_settings(**kw))
    (det,) = [c for c in checks if c.name == "detectors"]
    assert det.status == "FAIL" and format_check(det).isascii()
    kw["detectors_enabled"] = False
    assert not [c for c in run_checks(lambda: load_settings(**kw)) if c.name == "detectors"]


# ---------------------------------------------------------------------------- migration


def _older(model: SchemaModel) -> SchemaModel:
    from dataclasses import replace

    drop = {"verdict_status", "correlation_id", "coverage_json"}
    tables = {}
    for name, t in model.tables.items():
        if name == "finding":
            continue
        cols = (
            t.columns
            if name != "agent_event"
            else tuple(c for c in t.columns if c.name not in drop)
        )
        tables[name] = replace(t, columns=cols)
    return SchemaModel(model.version, tables, "v0.3.0-like")


def test_bootstrap_migrates_a_v030_sqlite_file_without_data_loss(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    model = load_model()
    db = tmp_path / "old.db"
    x = SqliteExecutor(db)
    x.apply_ddl(sqlite_statements(_older(model)))
    assert "verdict_status" not in (live_columns(x, "agent_event") or {})
    assert live_columns(x, "finding") is None
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", sqlite_path=db)
    t0 = datetime(2026, 10, 20, tzinfo=UTC)
    adapters = build_adapters(settings, executor=x, clock=FixedClock(t0))
    old = _older(model).table("agent_event")
    row: dict[str, Any] = {
        c.name: None if c.nullable else (0 if c.type in ("int", "bigint") else "x")
        for c in old.columns
    }
    row.update(
        {
            "event_id": "e" * 32,
            "ts": t0,
            "trace_id": "t-old",
            "agent_id": "payments",
            "event_type": "gate_decision",
            "status": "allowed",
        }
    )
    x.execute(
        f"INSERT INTO agent_event ({', '.join(row)}) VALUES ({', '.join(':' + c for c in row)})",
        row,
    )
    result = bootstrap_schema.run(settings, adapters)
    assert result["added_columns"] == 3
    cols = set(live_columns(x, "agent_event") or {})
    assert {"verdict_status", "correlation_id", "coverage_json"} <= cols
    assert "finding_id" in (live_columns(x, "finding") or {})
    (kept,) = x.query("SELECT trace_id, status, verdict_status FROM agent_event")
    assert tuple(kept.values() if isinstance(kept, dict) else kept) == ("t-old", "allowed", None)
    assert bootstrap_schema.run(settings, adapters)["added_columns"] == 0  # idempotent
    x.close()
