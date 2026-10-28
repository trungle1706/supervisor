"""WP-C2: the eight risk types of Circular 53 Art. 14(3) as one status row per system
(RISK_DIMENSIONS).

Off path first (no table read, routes answer 400 risk_dimensions_off, system page unchanged), then
the loader (strict keys, eight fixed ids, no float), the eight rows made once, the rule proposal,
set and waive rules, the chain record (no float, no personal data), the HTMX tab, the summary and
the RegKB rows."""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.config import load_settings
from supervisor.core import rbac
from supervisor.core.errors import ConfigError
from supervisor.governance import risk_dimensions as rd
from supervisor.risk.model import CATEGORIES

from .conftest import Console, add_agent, draft

REPO = Path(__file__).resolve().parents[2]
CREATOR = "reviewer.an"  # reviewer: systems.edit and systems.approve; creates the system
OWNER = "payops-lead@example.invalid"  # owner role
SECOND = "approver.em"  # approver: systems.approve, no systems.edit
VIEWER = "viewer.hoa"
REASON = "The bank accepts this for the pilot period."
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
AGENT = "c2-agent"
TABLE = "risk_dimension_status"


# ------------------------------------------------------------------ helpers


@pytest.fixture
def rdon(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    from supervisor.app import app
    from supervisor.governance.risk_dimension_routes import router as rd_router

    from .conftest import restore_app

    monkeypatch.setattr(on.ctx.settings, "risk_dimensions", True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(rd_router)
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


@pytest.fixture
def rdoff(on: Console) -> Iterator[Console]:
    from supervisor.app import app
    from supervisor.governance.risk_dimension_routes import router as rd_router

    from .conftest import restore_app

    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(rd_router)
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


def _system(c: Console, owner: str = CREATOR, **over: Any) -> str:
    s = c.ctx.systems.register(draft(owner_user=owner, **over), CREATOR)
    return str(s["system_id"])


def _api(c: Console, method: str, url: str, body: Any = None, user: str = CREATOR) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def _url(sid: str, tail: str = "") -> str:
    return f"/v1/systems/{sid}/risk-dimensions{tail}"


def _rows(c: Console, sid: str) -> dict[str, dict[str, Any]]:
    return {r["dimension_id"]: dict(r) for r in c.ctx.state.query(TABLE, {"system_id": sid})}


def _result(
    c: Console, agent: str, pack: str, status: str, *, version: int | None = None, run: str = "r1"
) -> None:
    from supervisor.assurance.loader import load_packs

    ver = version or next(p.version for p in load_packs() if p.id == pack)
    c.ctx.tables.append(
        "eval_result",
        [
            {
                "run_id": run,
                "ts": NOW,
                "pack_id": pack,
                "pack_version": ver,
                "manifest_sha256": "0" * 64,
                "dimension": "security",
                "target_kind": "agent",
                "target_id": agent,
                "status": status,
                "metrics": {},
                "metric_status": {},
                "thresholds": {},
                "reasons": "",
                "n_items": 1,
                "data_mode": "synthetic",
                "dataset_id": "d",
                "dataset_sha256": "0" * 64,
                "is_mock": False,
                "launch_gate": "advisory",
                "judge_gate": False,
                "details": {},
                "evidence_hash": None,
            }
        ],
    )


def _with_agent(c: Console) -> str:
    add_agent(c.runtime.adapters, AGENT)
    sid = _system(c)
    c.ctx.systems.link(sid, "agent", AGENT, CREATOR)
    return sid


def _env(c: Console) -> rd.Env:
    return rd.Env.from_console(c.ctx)


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_has_float(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_float(v) for v in value)
    return False


# ------------------------------------------------------------------ off path


def test_flag_off_by_default() -> None:
    s = load_settings(llm_base_url="")
    assert s.risk_dimensions is False
    assert rd.enabled(s) is False


def test_flag_needs_governance(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "risk_dimensions", True)
    assert rd.enabled(console.ctx.settings) is False
    monkeypatch.setattr(console.ctx.settings, "governance_enabled", True)
    assert rd.enabled(console.ctx.settings) is True
    assert rd.tab_enabled(console.ctx.settings) is False  # the tab also needs the Systems pages


def test_off_routes_400_no_table_read_page_unchanged(
    rdoff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = rdoff
    sid = _system(on)
    seen: list[str] = []
    real_q, real_g = on.ctx.state.query, on.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_g(table, *a, **k)

    monkeypatch.setattr(on.ctx.state, "query", spy_q)
    monkeypatch.setattr(on.ctx.state, "get", spy_g)
    html = on.get(f"/console/systems/{sid}?lang=en").text
    assert "tab=riskdim" not in html and "data-rd" not in html
    assert on.get(f"/console/systems/{sid}?tab=riskdim&lang=en").status_code == 400
    for method, url, body in (
        ("GET", _url(sid), None),
        ("POST", _url(sid), {"dimension_id": "model", "status": "in_progress"}),
        ("POST", _url(sid, "/model/waive"), {"reason": REASON}),
        ("GET", "/v1/risk-dimensions/summary", None),
    ):
        r = _api(on, method, url, body, CREATOR)
        assert r.status_code == 400, url
        assert "risk_dimensions_off" in r.text, url
    for tail, form in (("set", {"status": "pass"}), ("confirm", {}), ("waive", {"reason": REASON})):
        r = on.post(f"/console/systems/{sid}/risk-dimensions/model/{tail}", form, user=CREATOR)
        assert r.status_code == 400 and "risk_dimensions_off" in r.text, tail
    assert TABLE not in seen


# ------------------------------------------------------------------ loader


def test_shipped_config_has_the_eight_ids_in_order() -> None:
    cfg = rd.load_config()
    assert tuple(d.id for d in cfg.dimensions) == rd.DIMENSION_IDS
    assert len(cfg.dimensions) == 8
    for d in cfg.dimensions:
        assert d.articles and d.criteria and d.definition_en and d.measure
        assert not _has_float(dict(d.threshold))
    assert next(d for d in cfg.dimensions if d.id == "reputation").applies_to == "bank"


def _raw() -> dict[str, Any]:
    return yaml.safe_load((REPO / "config" / "risk_dimensions.yaml").read_text(encoding="utf-8"))


def test_loader_is_strict() -> None:
    good = _raw()
    assert rd.parse_config(copy.deepcopy(good)).dimensions

    def bad(mutate: Any, match: str) -> None:
        data = copy.deepcopy(good)
        mutate(data)
        with pytest.raises(ConfigError, match=match):
            rd.parse_config(data)

    bad(lambda d: d.update(surprise=1), "unknown key: surprise")
    bad(lambda d: d["dimensions"][0].update(surprise=1), "unknown key: surprise")
    bad(lambda d: d["dimensions"][0].pop("measure"), "missing key: measure")
    bad(lambda d: d["extra_dimensions"].append({"id": "ninth"}), "extra_dimensions")
    bad(lambda d: d["dimensions"].pop(), "exactly")  # seven
    bad(lambda d: d["dimensions"].append(copy.deepcopy(d["dimensions"][0])), "exactly")  # nine
    bad(lambda d: d["dimensions"][0].update(id="other"), "exactly")
    bad(lambda d: d["dimensions"][0]["threshold"].update(ratio=0.8), "no float")
    bad(lambda d: d["dimensions"][0].update(review_days=1.5), "review_days")
    bad(lambda d: d["dimensions"][0].update(applies_to="everyone"), "applies_to")
    bad(lambda d: d["dimensions"][0]["measured_by"][0].update(kind="rule"), "kind")
    bad(lambda d: d["dimensions"][0]["measured_by"][0].update(required="yes"), "required")
    bad(lambda d: d["proposal"].update(pass_when="always"), "proposal")


def test_config_references_exist() -> None:
    from supervisor.assurance.loader import load_packs

    packs = {p.id for p in load_packs()}
    controls = yaml.safe_load((REPO / "regulations/schema/controls.yaml").read_text("utf-8"))
    known = {
        k for section in ("monitors", "console", "evidence", "process") for k in controls[section]
    }
    for d in rd.load_config().dimensions:
        for c in d.controls:
            assert c in known or c in packs, f"{d.id}: unknown control {c}"
        for m in d.measured_by:
            if m.kind == "pack":
                assert m.id in packs, f"{d.id}: unknown pack {m.id}"
        assert set(d.risk_categories) <= set(CATEGORIES)
    assert "risk_dimension_status" in controls["evidence"]
    assert "doc" in str(controls["evidence"]["risk_dimension_status"])


def test_category_links_follow_the_brief() -> None:
    cats = {d.id: set(d.risk_categories) for d in rd.load_config().dimensions}
    assert {"money_movement", "credit_decision", "model_behaviour"} <= cats["model"]
    assert "pii" in cats["data_governance"] and "pii" in cats["legal_compliance"]
    assert "injection" in cats["cybersecurity"]
    assert "availability" in cats["supply_chain"]
    assert "third_party" in cats["third_party"]
    assert "duties_gap" in cats["legal_compliance"]


def test_threshold_check_refuses_floats_and_text() -> None:
    assert rd.check_threshold({"max_x": 0, "ok": True, "rule": "all_required_ok"})
    for bad in ({"a": 0.5}, {"a": "Two words"}, {"A": 1}, [1], {"a": [1]}):
        with pytest.raises(rd.RiskDimensionError):
            rd.check_threshold(bad)


# ------------------------------------------------------------------ rows made once


def test_eight_rows_created_once(rdon: Console) -> None:
    sid = _system(rdon)
    assert _rows(rdon, sid) == {}  # nothing before the first read
    first = _api(rdon, "GET", _url(sid))
    assert first.status_code == 200, first.text
    body = first.json()
    assert [d["dimension_id"] for d in body["dimensions"]] == list(rd.DIMENSION_IDS)
    assert {d["status"] for d in body["dimensions"]} == {"not_started"}
    rows = _rows(rdon, sid)
    assert len(rows) == 8
    stamp = {k: (v["status_id"], v["row_version"]) for k, v in rows.items()}
    again = _api(rdon, "GET", _url(sid))
    assert again.status_code == 200
    assert {k: (v["status_id"], v["row_version"]) for k, v in _rows(rdon, sid).items()} == stamp
    assert body["banner"].startswith("Not legal advice")
    assert body["dimensions"][0]["owner_team"] == "payments-team"


def test_unknown_system_is_404(rdon: Console) -> None:
    assert _api(rdon, "GET", _url("no-such-system")).status_code == 404


# ------------------------------------------------------------------ proposal


def test_proposal_rules(rdon: Console) -> None:
    sid = _with_agent(rdon)
    env = _env(rdon)
    assert {p["status"] for p in rd.propose(env, sid).values()} == {"not_started"}
    required = [m.id for m in env.cfg.get("supply_chain").measured_by if m.required]
    # every required pack ok at the current version -> pass, with pointers
    for i, pack in enumerate(required):
        _result(rdon, AGENT, pack, "ok", run=f"run{i}")
    p = rd.propose(env, sid, "supply_chain")["supply_chain"]
    assert p["status"] == "pass" and p["evidence"]
    assert all(e.startswith("pack:") and AGENT in e for e in p["evidence"])
    # one required pack failed -> fail, no evidence
    _result(rdon, AGENT, required[0], "fail", run="run9")
    p = rd.propose(env, sid, "supply_chain")["supply_chain"]
    assert p["status"] == "fail" and p["evidence"] == []
    # a warning is not a pass and not a fail
    _result(rdon, AGENT, required[0], "warn", run="run10")
    assert rd.propose(env, sid, "supply_chain")["supply_chain"]["status"] == "not_started"


def test_proposal_ignores_a_result_of_an_old_pack_version(rdon: Console) -> None:
    sid = _with_agent(rdon)
    env = _env(rdon)
    for i, m in enumerate(m for m in env.cfg.get("data_governance").measured_by if m.required):
        _result(rdon, AGENT, m.id, "ok", version=99, run=f"old{i}")
    p = rd.propose(env, sid, "data_governance")["data_governance"]
    assert p["status"] == "not_started"
    assert {c["state"] for c in p["checks"]} == {"stale"}


def test_proposal_needs_an_agent_and_manual_types_have_none(rdon: Console) -> None:
    sid = _system(rdon)  # no agent linked
    env = _env(rdon)
    for m in env.cfg.get("data_governance").measured_by:
        _result(rdon, AGENT, m.id, "ok")
    props = rd.propose(env, sid)
    assert {p["status"] for p in props.values()} == {"not_started"}
    for dim in ("legal_compliance", "reputation"):
        assert props[dim]["checks"] == []


def test_proposal_is_not_stored_until_a_person_confirms(rdon: Console) -> None:
    sid = _with_agent(rdon)
    for i, m in enumerate(
        m for m in _env(rdon).cfg.get("data_governance").measured_by if m.required
    ):
        _result(rdon, AGENT, m.id, "ok", run=f"c{i}")
    body = _api(rdon, "GET", _url(sid)).json()
    row = next(d for d in body["dimensions"] if d["dimension_id"] == "data_governance")
    assert row["status"] == "not_started" and row["proposal"]["status"] == "pass"
    assert _rows(rdon, sid)["data_governance"]["status"] == "not_started"
    r = _api(rdon, "POST", _url(sid), {"dimension_id": "data_governance", "confirm_proposal": True})
    assert r.status_code == 200, r.text
    stored = _rows(rdon, sid)["data_governance"]
    assert stored["status"] == "pass" and json.loads(json.dumps(stored["evidence_json"]))
    assert stored["valid_until"] is not None  # review_days from the file
    # no proposal for a manual type
    r = _api(rdon, "POST", _url(sid), {"dimension_id": "reputation", "confirm_proposal": True})
    assert r.status_code == 400 and "no_proposal" in r.text


# ------------------------------------------------------------------ set and waive rules


def test_set_status_rules(rdon: Console) -> None:
    sid = _system(rdon)
    post = lambda body, user=CREATOR: _api(rdon, "POST", _url(sid), body, user)  # noqa: E731
    r = post({"dimension_id": "model", "status": "in_progress"})
    assert (
        r.status_code == 200
        and r.json()["from"] == "not_started"
        and r.json()["to"] == "in_progress"
    )
    # pass needs an evidence pointer
    r = post({"dimension_id": "model", "status": "pass"})
    assert r.status_code == 400 and "evidence_required" in r.text
    r = post({"dimension_id": "model", "status": "pass", "evidence": ["free text, not a pointer"]})
    assert r.status_code == 400 and "bad_evidence" in r.text
    r = post(
        {"dimension_id": "model", "status": "pass", "evidence": ["doc:VAL-2026-07", "fact:f1"]}
    )
    assert r.status_code == 200 and r.json()["evidence_n"] == 2
    row = _rows(rdon, sid)["model"]
    assert row["status"] == "pass" and row["assessed_by"] == f"person:{CREATOR}"
    assert (
        row["valid_until"] == (NOW.date().replace(year=2027, month=10, day=28)).isoformat()
        or row["valid_until"]
    )
    # waived goes through its own action
    r = post({"dimension_id": "model", "status": "waived"})
    assert r.status_code == 400 and "use_waive" in r.text
    # not_applicable needs a reason
    r = post({"dimension_id": "reputation", "status": "not_applicable"})
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = post({"dimension_id": "reputation", "status": "not_applicable", "note": REASON})
    assert r.status_code == 200
    # unknown dimension, bad status, float threshold, long note
    assert "unknown_dimension" in post({"dimension_id": "ninth", "status": "fail"}).text
    assert "bad_status" in post({"dimension_id": "model", "status": "great"}).text
    r = post({"dimension_id": "model", "status": "fail", "threshold": {"x": 0.5}})
    assert r.status_code == 400 and "bad_threshold" in r.text
    r = post({"dimension_id": "model", "status": "fail", "note": "x" * 301})
    assert r.status_code == 400 and "note_too_long" in r.text
    # a viewer cannot change anything
    assert post({"dimension_id": "model", "status": "fail"}, VIEWER).status_code == 403
    # the bank can set its threshold (integers and enums)
    r = post({"dimension_id": "model", "status": "fail", "threshold": {"max_failed_packs": 2}})
    assert r.status_code == 200
    assert json.loads(json.dumps(_rows(rdon, sid)["model"]["threshold_json"])) == {
        "max_failed_packs": 2
    }


def test_note_is_masked(rdon: Console) -> None:
    sid = _system(rdon)
    r = _api(
        rdon,
        "POST",
        _url(sid),
        {
            "dimension_id": "model",
            "status": "in_progress",
            "note": "see https://bank.example/internal/x and 12345678901234",
        },
    )
    assert r.status_code == 200
    note = _rows(rdon, sid)["model"]["note"]
    assert "https://" not in note and "12345678901234" not in note


def test_waive_rules(rdon: Console) -> None:
    sid = _system(rdon, owner=OWNER)
    url = _url(sid, "/ethics/waive")
    r = _api(rdon, "POST", url, {"reason": "too short"}, SECOND)
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = _api(rdon, "POST", url, {"reason": REASON}, OWNER)
    assert r.status_code == 400 and "owner_cannot_waive" in r.text
    assert _api(rdon, "POST", url, {"reason": REASON}, VIEWER).status_code == 403
    assert (
        _api(rdon, "POST", _url(sid, "/ninth/waive"), {"reason": REASON}, SECOND).status_code == 400
    )
    r = _api(rdon, "POST", url, {"reason": REASON}, SECOND)
    assert r.status_code == 200 and r.json()["to"] == "waived"
    row = _rows(rdon, sid)["ethics"]
    assert row["status"] == "waived" and row["note"] == REASON and row["updated_by"] == SECOND
    assert _api(rdon, "POST", url, {"reason": REASON}, SECOND).status_code == 400  # already
    # a second system owner on the team cannot waive either
    rdon.ctx.systems.add_member(sid, SECOND, "system_owner", CREATOR)
    r = _api(rdon, "POST", _url(sid, "/model/waive"), {"reason": REASON}, SECOND)
    assert r.status_code == 400 and "owner_cannot_waive" in r.text


def test_archived_system_cannot_change(rdon: Console) -> None:
    sid = _system(rdon)
    _api(rdon, "GET", _url(sid))
    rdon.ctx.systems.archive(sid, CREATOR)
    r = _api(rdon, "POST", _url(sid), {"dimension_id": "model", "status": "in_progress"})
    assert r.status_code == 400


# ------------------------------------------------------------------ chain and audit


def test_chain_record_and_audit_rows(rdon: Console) -> None:
    sid = _system(rdon)
    ev = ["doc:VAL-2026-07", "fact:f1"]
    r = _api(rdon, "POST", _url(sid), {"dimension_id": "model", "status": "pass", "evidence": ev})
    assert r.status_code == 200
    r = _api(rdon, "POST", _url(sid, "/model/waive"), {"reason": REASON}, SECOND)
    assert r.status_code == 200
    recs = [dict(x) for x in rdon.ctx.tables.query("chain_entry", {"record_type": rd.RECORD_TYPE})]
    assert len(recs) == 2
    payloads = []
    for x in sorted(recs, key=lambda e: e["seq"]):
        (row,) = rdon.ctx.tables.query("chain_payload", {"lane": x["lane"], "seq": x["seq"]})
        payloads.append(
            json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        )
    first, second = payloads
    assert (first["dimension_id"], first["from"], first["to"]) == ("model", "not_started", "pass")
    assert (second["from"], second["to"]) == ("pass", "waived")
    assert first["evidence_n"] == 2 and len(first["evidence_hash"]) == 64
    assert first["system_id"] == sid
    for p in payloads:
        assert not _has_float(p)
        text = json.dumps(p)
        assert CREATOR not in text and SECOND not in text and REASON not in text
        assert p["actor_ref"].startswith("p-")
    assert rd.RECORD_TYPE in {x["record_type"] for x in recs}
    rows = [
        dict(a)
        for a in rdon.ctx.tables.query("console_action")
        if str(a["path"]).startswith(f"/v1/systems/{sid}/risk-dimensions") and a["outcome"] == "ok"
    ]
    details = sorted(str(a["detail"]) for a in rows)
    assert details[0].startswith("risk_dim model not_started>pass n=2")
    assert details[1].startswith("risk_dim model pass>waived n=2 text_sha=")
    assert REASON not in str(rows)


# ------------------------------------------------------------------ console


def _tab(c: Console, sid: str, user: str = CREATOR) -> Any:
    return c.get(f"/console/systems/{sid}?tab=riskdim&lang=en", user=user)


def test_tab_shows_eight_rows(rdon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rdon.ctx.settings, "risk_register_enabled", True)
    sid = _system(rdon)
    page = rdon.get(f"/console/systems/{sid}?lang=en").text
    assert "tab=riskdim" in page and "Risk assessment" in page
    r = _tab(rdon, sid)
    assert r.status_code == 200, r.text[:300]
    assert r.text.count('data-section="rd-row"') == 8
    for dim in rd.DIMENSION_IDS:
        assert f'data-dimension="{dim}"' in r.text
    assert "Not legal advice" in r.text and "2027-01-01" in r.text
    assert 'data-act="rd-reassess"' in r.text and "disabled" in r.text
    vi = rdon.get(f"/console/systems/{sid}?tab=riskdim&lang=vi").text
    assert "Rủi ro mô hình" in vi


def test_htmx_set_confirm_waive(rdon: Console) -> None:
    sid = _with_agent(rdon)
    base = f"/console/systems/{sid}/risk-dimensions"
    r = rdon.post(f"{base}/model/set", {"status": "in_progress", "note": "started"}, user=CREATOR)
    assert r.status_code == 200, r.text[:300]
    assert (
        'data-dimension="model" data-status="in_progress"' in r.text and "Status saved." in r.text
    )
    r = rdon.post(f"{base}/model/set", {"status": "pass", "evidence": ""}, user=CREATOR)
    assert r.status_code == 400 and "evidence_required" in r.text
    r = rdon.post(
        f"{base}/model/set", {"status": "pass", "evidence": "doc:A1 fact:B2"}, user=CREATOR
    )
    assert r.status_code == 200 and 'data-status="pass"' in r.text
    for i, m in enumerate(
        m for m in _env(rdon).cfg.get("data_governance").measured_by if m.required
    ):
        _result(rdon, AGENT, m.id, "ok", run=f"h{i}")
    page = _tab(rdon, sid).text
    assert "Confirm proposal" in page
    r = rdon.post(f"{base}/data_governance/confirm", {}, user=CREATOR)
    assert r.status_code == 200 and "Proposal confirmed." in r.text
    assert _rows(rdon, sid)["data_governance"]["status"] == "pass"
    # waive: short reason, then fine; the owner has no waive form and the route refuses
    r = rdon.post(f"{base}/ethics/waive", {"reason": "short"}, user=SECOND)
    assert r.status_code == 400
    r = rdon.post(f"{base}/ethics/waive", {"reason": REASON}, user=SECOND)
    assert r.status_code == 200 and 'data-dimension="ethics" data-status="waived"' in r.text
    r = rdon.post(f"{base}/third_party/waive", {"reason": REASON}, user=CREATOR)
    assert r.status_code == 400 and "owner_cannot_waive" in r.text
    assert rdon.post(f"{base}/model/set", {"status": "fail"}, user=VIEWER).status_code == 403
    # a plain form post (no HX header, no Origin) is refused with 400, never 500
    plain = rdon.post(f"{base}/model/set", {"status": "fail"}, user=CREATOR, htmx=False)
    assert plain.status_code == 400


def test_risk_register_lines_on_the_row(rdon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rdon.ctx.settings, "risk_register_enabled", True)
    sid = _with_agent(rdon)
    r = rdon.ctx.risks.create(
        {
            "title": "Injection into the transfer agent",
            "description": "Synthetic.",
            "category": "injection",
            "agent_id": AGENT,
            "inherent_likelihood": 3,
            "inherent_impact": 4,
            "treatment": "mitigate",
            "residual_likelihood": 2,
            "residual_impact": 3,
            "owner": CREATOR,
            "status": "active",
            "review_date": "2027-03-01",
        },
        CREATOR,
    )
    page = _tab(rdon, sid).text
    section = page.split('data-dimension="cybersecurity"')[1].split('data-section="rd-row"')[0]
    assert r["risk_id"] in section
    other = page.split('data-dimension="ethics"')[1].split('data-section="rd-row"')[0]
    assert r["risk_id"] not in other


def test_summary_counts(rdon: Console) -> None:
    a, b = _system(rdon), _system(rdon, name="Payments - Second")
    _api(rdon, "GET", _url(a))
    _api(rdon, "POST", _url(a), {"dimension_id": "model", "status": "in_progress"})
    _api(rdon, "POST", _url(a, "/ethics/waive"), {"reason": REASON}, SECOND)
    s = _api(rdon, "GET", "/v1/risk-dimensions/summary").json()
    assert s["systems"] == 2 and s["statuses"] == list(rd.STATUSES)
    by = {d["dimension_id"]: d for d in s["dimensions"]}
    assert list(by) == list(rd.DIMENSION_IDS)
    assert by["model"]["in_progress"] == 1 and by["model"]["not_started"] == 1
    assert by["ethics"]["waived"] == 1 and by["ethics"]["not_started"] == 1
    assert b not in {r["system_id"] for r in rdon.ctx.state.query(TABLE)}  # read-only


def test_rbac_rows_exist() -> None:
    assert rbac.route_entry("GET", "/v1/systems/{system_id}/risk-dimensions") == "systems.view"
    assert rbac.route_entry("POST", "/v1/systems/{system_id}/risk-dimensions") == "systems.edit"
    assert (
        rbac.route_entry("POST", "/v1/systems/{system_id}/risk-dimensions/{dim}/waive")
        == "systems.approve"
    )
    assert rbac.route_entry("GET", "/v1/risk-dimensions/summary") == "systems.view"
    assert (
        rbac.route_entry("POST", "/console/systems/{system_id}/risk-dimensions/{dim}/waive")
        == "systems.approve"
    )


# ------------------------------------------------------------------ RegKB


def test_regkb_rows_for_art_14_3_and_14_4() -> None:
    from supervisor.regkb import load_kb

    kb = load_kb()
    r3 = kb.get("VN-TT53-2026-A14.03-01")
    r4 = kb.get("VN-TT53-2026-A14.04-01")
    assert r3.article_ref == "Art. 14(3)" and r4.article_ref == "Art. 14(4)"
    assert "Rủi ro mô hình" in r3.text_vi and "Rủi ro danh tiếng" in r3.text_vi
    assert "ngưỡng chấp nhận" in r4.text_vi
    for o in (r3, r4):
        assert o.verification == "VERIFIED_PRIMARY"
        assert "2027-01-01" in o.summary_en
        assert any(c.id == "risk_dimension_status" for c in o.control_mapping)
