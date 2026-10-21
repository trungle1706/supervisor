"""WP41 review (Opus, data protection officer view): the keep_args leak matrix.

Three kept arguments (a tax code, a CCCD and a phone number) go through the REAL runtime
(detectors, session monitor and inventory on). The tool answer carries them as sent (that is
the feature); nothing else may: no stored row, no chain entry, no SIEM / OCSF line, no console
page, no CSV export, no session sketch and no log line. Synthetic data only.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

TAX = "0108765432"
CCCD = "079203001234"
PHONE = "0987654321"
RAW = (TAX, CCCD, PHONE)
TOOL = "lookup_customer_basic_info"
AGENT = "payments"
APPROVERS = ["dpo.lan", "sec.minh"]


def _leaks(blob: str) -> list[str]:
    forms = {v for raw in RAW for v in (raw, json.dumps(raw)[1:-1], " ".join(raw))}
    return sorted(f for f in forms if f in blob)


def _policy_dir(data_dir: Path) -> Path:
    from supervisor.demo.activity_seed import demo_policy_dir

    out = demo_policy_dir(data_dir)
    path = out / "baseline.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["tools"][TOOL] = "pii_export"
    ag = doc["agents"][AGENT]
    ag["detectors"] = {"settings": {"dlp_vn": {"keep_args": {TOOL: ["tax_code", "cccd", "phone"]}}}}
    ag["keep_args_approvals"] = list(APPROVERS)
    for rule in doc["rules"]:  # PAY-07: the payments agent may call approved tools only
        if rule["id"] == "PAY-07":
            rule["when"]["tool"]["not_in"].append(TOOL)
    ag["monitors"] = {"session": {"k": 3, "case_threshold_bp": 2500}}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return out


class Kit:
    def __init__(self, client: Any, runtime: Any, ctx: Any, data_dir: Path) -> None:
        self.client, self.runtime, self.ctx, self.data_dir = client, runtime, ctx, data_dir

    def get(self, url: str, user: str = "reviewer.an") -> Any:
        return self.client.get(url, headers={"X-Dev-User": user})

    def post(self, url: str, data: dict[str, str], user: str) -> Any:
        return self.client.post(url, data=data, headers={"X-Dev-User": user, "HX-Request": "true"})


@pytest.fixture
def kit(tmp_path: Path) -> Iterator[Kit]:
    from fastapi.testclient import TestClient

    from supervisor.adapters.auth import set_provider
    from supervisor.adapters.factory import build_adapters
    from supervisor.app import app
    from supervisor.config import load_settings
    from supervisor.console.context import build_context, set_context
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.jobs import bootstrap_schema
    from supervisor.wiring import build_runtime

    data_dir = tmp_path / "data"
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=data_dir,
        llm_base_url="",
        detectors_enabled=True,
        session_monitor_enabled=True,
        inventory_enabled=True,
        console_decisions_v2=True,
        console_decisions_enabled=True,
        console_traces_enabled=True,
        policy_dir=_policy_dir(data_dir),
    )
    adapters = build_adapters(settings)
    bootstrap_schema.run(adapters.settings, adapters)
    runtime = build_runtime(adapters.settings, adapters=adapters, policy_refresh_s=0.0)
    ctx = build_context(runtime)
    set_context(ctx)
    gate_wiring.set_gateway(runtime.gateway)
    try:
        yield Kit(TestClient(app, raise_server_exceptions=False), runtime, ctx, data_dir)
    finally:
        set_context(None)
        gate_wiring.set_gateway(None)
        set_provider(None)
        runtime.close()
        adapters.close()


def _all_rows(kit: Kit) -> str:
    """Every row of every table of the store, as one text."""
    ex = kit.runtime.adapters.executor
    names = [r["name"] for r in ex.query("SELECT name FROM sqlite_master WHERE type='table'")]
    out = []
    for n in names:
        out.append(json.dumps(ex.query(f'SELECT * FROM "{n}"'), default=str, ensure_ascii=False))
    return "\n".join(out)


def _chain(kit: Kit) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(chain entry, its payload) pairs; the payload sits in ``chain_payload``."""
    tables = kit.runtime.adapters.tables
    pay = {
        (p["lane"], p["seq"]): p["payload"] for p in tables.query("chain_payload", {}, limit=10_000)
    }
    out = []
    for e in tables.query("chain_entry", {}, limit=10_000):
        p = pay.get((e["lane"], e["seq"])) or {}
        out.append((e, json.loads(p) if isinstance(p, str) else p))
    return out


def _files(root: Path) -> str:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(p.read_bytes().decode("utf-8", "replace"))
    return "\n".join(out)


def test_kept_arguments_reach_the_tool_and_nothing_else(
    kit: Kit, caplog: pytest.LogCaptureFixture
) -> None:
    from supervisor.adapters.integrations.siem import event_from_chain, format_line

    gw = kit.runtime.gateway
    args = {"tax_code": TAX, "cccd": CCCD, "phone": PHONE, "customer_id": "C-1"}
    ctx = {"session_id": "conv-kept-1", "consumer_id": "app-mobile", "trace_id": "tr-kept-1"}
    sg = gw.session_gate
    assert sg is not None
    seen: list[Any] = []
    real_finalize = sg.finalize

    def spy(call: Any, a: Any, risk: Any) -> Any:  # what the session sketch is built on
        seen.append(json.dumps(a, ensure_ascii=False))
        return real_finalize(call, a, risk)

    sg.finalize = spy  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG):
        r = gw.check(AGENT, "1.0.0", TOOL, args, ctx, correlation_id="corr-kept-1")
        # the same values as a NESTED key, in a tool result and in an output check: never kept
        nested = gw.check(AGENT, "1.0.0", TOOL, {"customer": {"tax_code": TAX}}, ctx)
        res = gw.check(
            AGENT,
            "1.0.0",
            TOOL,
            {"customer_id": "C-2"},
            {**ctx, "tool_results": [{"phone": PHONE}]},
        )
        out = gw.check(
            AGENT, "1.0.0", TOOL, dict(args), {**ctx, "output": f"So {PHONE}, MST {TAX}"},
            direction="output",
        )  # fmt: skip
        gw.drain()
    # 1. the tool gets the values as sent (the feature) and the answer names them
    assert r["allow"] is True and r["status"] == "transform", (r["rule_id"], r["reason"])
    assert {k: r["transformed_args"][k] for k in ("tax_code", "cccd", "phone")} == {
        "tax_code": TAX,
        "cccd": CCCD,
        "phone": PHONE,
    }
    assert r["kept_args"] == ["cccd", "phone", "tax_code"]
    assert seen and not _leaks("\n".join(seen))  # the sketch input is the masked copy
    # 2. not a nested key of the same name, not a tool result, not the output direction
    assert "kept_args" not in nested and TAX not in json.dumps(nested["transformed_args"])
    assert "kept_args" not in res and "kept_args" not in out
    assert not _leaks(json.dumps(out.get("transformed_payload") or {}, ensure_ascii=False))
    # 3. stores: every table (agent_event, finding, verdict, chain_entry, session json,
    #    inventory, ...) and every file under the data folder (chain lanes, logs)
    assert not _leaks(_all_rows(kit))
    ev = kit.runtime.adapters.tables.query("agent_event", {"event_id": r["decision_id"]})[0]
    cov = ev["coverage_json"]
    assert (json.loads(cov) if isinstance(cov, str) else cov)["kept_args"] == [
        "cccd",
        "phone",
        "tax_code",
    ]
    assert ev["session_json"]  # the sketch exists and was built on the masked copy
    # 4. chain entries rendered as SIEM lines in every format (jsonl, cef, ocsf)
    chain = _chain(kit)
    gate = [p for e, p in chain if e["record_type"] == "gate_decision" and p.get("kept_args")]
    assert gate and gate[0]["kept_args"] == ["cccd", "phone", "tax_code"]  # names only
    lines = []
    for e, payload in chain:
        siem = event_from_chain(e, payload)
        if siem is not None:
            lines += [format_line(siem, f) for f in ("jsonl", "cef", "ocsf")]
    assert lines and not _leaks("\n".join(lines))
    # 5. console: list, drawer (every tab), export
    eid = r["decision_id"]
    pages = [kit.get("/console/decisions").text, kit.get("/console/decisions/rows").text]
    for tab in ("request", "response", "detections", "metadata"):
        resp = kit.get(f"/console/decisions/{eid}/drawer?tab={tab}")
        assert resp.status_code == 200, tab
        pages.append(resp.text)
    from supervisor.demo.activity_seed import export_href

    href = export_href(kit.post("/console/decisions/export", {}, user="auditor.dung").text)
    assert href
    csv_text = kit.get(href, user="auditor.dung").text
    pages.append(csv_text)
    assert not _leaks("\n".join(pages))
    rows = list(csv.reader(io.StringIO(csv_text)))
    col = rows[0].index("kept_arguments")
    assert any(row[col] == "cccd;phone;tax_code" for row in rows[1:])
    # 6. the session sketch and the agent page of the gate-registered agent
    pages2 = [kit.get(f"/console/agents/{AGENT}"), kit.get("/console/inventory")]
    assert all(p.status_code < 500 for p in pages2)
    assert not _leaks("\n".join(p.text for p in pages2))
    # 7. logs: no record holds a value (the audit line names tools and arguments only)
    assert not _leaks("\n".join(rec.getMessage() for rec in caplog.records))
    audit = [m.getMessage() for m in caplog.records if "keep_args loaded" in m.getMessage()]
    assert audit and TOOL in audit[0] and "dpo.lan" in audit[0]
    # 8. files under the data folder (SQLite file and its WAL, chain lanes, exports)
    assert not _leaks(_files(kit.data_dir))


def test_the_policy_load_writes_the_chain_record_with_the_approvers(kit: Kit) -> None:
    kit.runtime.gateway.check(AGENT, "1.0.0", "get_balance", {"account_id": "A-1"}, {})
    rows = [p for e, p in _chain(kit) if e["record_type"] == "policy_keep_args"]
    assert len(rows) == 1
    assert rows[0]["tools"] == {TOOL: ["cccd", "phone", "tax_code"]}
    assert rows[0]["approvals"] == APPROVERS and rows[0]["agent_id"] == AGENT
