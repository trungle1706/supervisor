"""WP8 Definition of Done: a reviewer completes the full incident flow in the console.

gate block (real gateway, DEMO-3 CRD-01) -> case (intake) -> assign + triage -> contain
(one-click pause of the agent) -> two sign-offs by two different people -> closed ->
two-person resume -> audit pack whose chain export verifies offline.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from supervisor.evidence.verify import verify_export

from .conftest import Console


def _version(html: str) -> int:
    return int(re.findall(r'name="row_version" value="(\d+)"', html)[0])


def _payloads(console: Console, record_type: str) -> list[dict[str, Any]]:
    tables = console.ctx.tables
    out = []
    for e in tables.query("chain_entry", {"record_type": record_type}, ["lane", "seq"]):
        p = tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})
        out.append(json.loads(p[0]["payload"]))
    return out


def test_full_incident_flow(console: Console, tmp_path: Path) -> None:
    # 1. the gate block is in the queue as a case
    q = console.get("/console/")
    case = next(c for c in console.ctx.cases.list_cases() if "CRD-01" in c["summary"])
    cid, agent = case["case_id"], case["agent_id"]
    assert agent == "credit_prequal" and case["severity"] == "high"
    assert f'data-case="{cid}"' in q.text
    url = f"/console/cases/{cid}"
    page = console.get(url)
    assert page.status_code == 200 and "CRD-01" in page.text

    # 2. assign + triage (reviewer.an)
    r = console.post(
        f"{url}/assign", {"assignee": "reviewer.an", "row_version": _version(page.text)}
    )
    assert r.status_code == 200, r.text
    r = console.post(
        f"{url}/transition",
        {"to": "triaged", "note": "Đã xem: chặn đúng quy tắc", "row_version": _version(r.text)},
    )
    assert r.status_code == 200 and 'data-status="triaged"' in r.text, r.text

    # 3. contain: one-click pause in the console (gateway state machine in-process)
    p = console.post(f"/console/agents/{agent}/pause", {"reason": f"case {cid}"})
    assert p.status_code == 200 and f'data-agent="{agent}" data-state="PAUSED"' in p.text
    assert console.runtime.gateway.states.get_state(agent) == "PAUSED"
    r = console.post(
        f"{url}/transition",
        {"to": "contained", "note": "Agent paused at the gate", "row_version": _version(r.text)},
    )
    assert r.status_code == 200 and 'data-status="contained"' in r.text, r.text
    v = _version(r.text)

    # closing a high case without two sign-offs is refused (400, not 500)
    r = console.post(
        f"{url}/transition",
        {"to": "closed", "resolution": "confirmed", "note": "x", "row_version": v},
    )
    assert r.status_code == 400 and "two sign-offs" in r.text

    # 4. two-person sign-off (reviewer + approver), statements stored verbatim
    first = "Tôi xác nhận vụ việc đã được ngăn chặn. -- reviewer.an"
    second = "Đồng ý đóng vụ việc. -- approver.em"
    s = console.post(
        f"{url}/signoff",
        {"decision": "approve", "reason": first, "affirm": "yes", "row_version": v},
    )
    assert s.status_code == 200, s.text
    s = console.post(
        f"{url}/signoff",
        {"decision": "approve", "reason": second, "affirm": "yes", "row_version": _version(s.text)},
        user="approver.em",
    )
    assert s.status_code == 200 and "(2/2)" in s.text, s.text

    # 5. close (reviewer.binh)
    page = console.get(url, user="reviewer.binh")
    r = console.post(
        f"{url}/transition",
        {
            "to": "closed",
            "resolution": "confirmed",
            "note": "Confirmed; rule worked",
            "row_version": _version(page.text),
        },
        user="reviewer.binh",
    )
    assert r.status_code == 200 and 'data-status="closed"' in r.text, r.text
    assert console.ctx.cases.get(cid)["status"] == "closed"

    # 6. two-person resume: reviewer alone stays paused; owner completes it
    r1 = console.post(f"/console/agents/{agent}/resume", {"reason": "case closed"})
    assert r1.status_code == 200 and "needs the owner" in r1.text
    assert console.runtime.gateway.states.get_state(agent) == "PAUSED"
    r2 = console.post(
        f"/console/agents/{agent}/resume",
        {"reason": "owner agrees"},
        user="lending-lead@example.invalid",
    )
    assert r2.status_code == 200 and 'data-state="RUNNING"' in r2.text, r2.text

    # evidence: every human action carries actor + auth_method
    events = [e for e in console.ctx.cases.events(cid) if e["actor_kind"] == "user"]
    assert {e["action"] for e in events} >= {"assign", "triage", "contain", "close:confirmed"}
    assert all(e["auth_method"] == "dev_header" for e in events)
    chain_events = [p for p in _payloads(console, "case_event") if p["case_id"] == cid]
    assert all(p["actor"] and p["auth_method"] for p in chain_events)
    gate_actions = [p for p in _payloads(console, "console_gate_action") if p["agent_id"] == agent]
    assert [(p["action"], p["actor"]) for p in gate_actions] == [
        ("pause", "reviewer.an"),
        ("resume", "reviewer.an"),
        ("resume", "lending-lead@example.invalid"),
    ]
    resumes = [
        p
        for p in _payloads(console, "gate_state_change")
        if p["event"] == "resume" and p["agent_id"] == agent
    ]
    assert resumes[-1]["approver_1"] == "reviewer.an"
    assert resumes[-1]["approver_2"] == "lending-lead@example.invalid"

    # 7. audit pack (auditor): download, unzip, verify offline
    e = console.post("/console/export", {}, user="auditor.dung")
    assert e.status_code == 200 and 'data-verify="ok"' in e.text, e.text
    name = re.findall(r"/console/exports/(audit-pack-[^\"]+\.zip)", e.text)[0]
    dl = console.get(f"/console/exports/{name}", user="auditor.dung")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    zpath = tmp_path / name
    zpath.write_bytes(dl.content)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(tmp_path / "pack")
    root = tmp_path / "pack" / name.removesuffix(".zip")
    report = verify_export(root / "chain")
    assert report.failures == 0, "\n".join(report.lines)
    assert "RESULT: OK" in (root / "verify_report.txt").read_text(encoding="ascii")
    cf = json.loads((root / "casefiles" / f"{cid}.json").read_text(encoding="utf-8"))
    assert cf["status"] == "closed"
    assert [s["reason"] for s in cf["signoffs"]] == [first, second]
    assert (root / "casefiles" / f"{cid}.html").is_file()
    assert (root / "eval_report.json").is_file() or (root / "eval_report_NOT_RUN.txt").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["verify_ok"] and cid in manifest["cases"]
    assert manifest["created_by"] == "auditor.dung" and manifest["auth_method"] == "dev_header"
    # the export left only the zip under data_dir (no scratch dirs)
    export_dir = Path(console.ctx.settings.console_export_dir)
    assert [p.name for p in export_dir.iterdir() if p.is_file()] == [name]
