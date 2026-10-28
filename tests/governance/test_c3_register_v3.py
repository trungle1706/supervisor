# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-C3 (phase 12, REGISTER_V3): the nine-step register workflow and its compliance strip.

Off path, step order, the facts prefill with its markers, the AI type flags by rule, the strip
mapping and statuses, go back and re-run, the duties prefill, the submit with the stage approval
request, the HTMX panels and the role checks."""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from supervisor.governance.register_v2 import model as rm
from supervisor.governance.register_v2 import service as rs
from supervisor.governance.register_v3 import flags as fl
from supervisor.governance.register_v3 import service as v3s
from supervisor.governance.register_v3 import strip

from .conftest import Console, mounted, on  # noqa: F401  (fixtures)
from .test_n3_register import ME, S1, S2, new, rows, step, submit

HX = {"HX-Request": "true"}
APPROVER = "reviewer.binh"
VIEWER = "viewer.hoa"


@pytest.fixture
def v3(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in (
        "console_register_v2",
        "console_nav_v3",
        "agents_api_enabled",
        "classification_v2",
        "risk_dimensions",
        "register_v3",
    ):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    return on


def fact(kind: str, name: str, detail: str = "", n: int = 1, line: int = 3) -> dict[str, Any]:
    return {
        "fact_id": f"f_{kind}_{name}"[:60],
        "node_id": "x",
        "attempt_n": n,
        "kind": kind,
        "name": name,
        "detail": detail,
        "file": "agent.py",
        "line": line,
        "quote": None,
        "source": "rule",
        "model_id": None,
        "dropped_claims": None,
        "created_at": None,
    }


def card_of(rows_: list[dict[str, Any]], n: int = 1) -> dict[str, Any]:
    return {
        "node_id": "x",
        "attempt_n": n,
        "latest_attempt": n,
        "newer_attempt": False,
        "total": len(rows_),
        "dropped_claims": 0,
        "rows": rows_,
        "groups": [],
        "summary": None,
    }


FACT_ROWS = [
    fact("model", "gpt-synthetic", "family=openai"),
    fact("tool", "lookup_account", "risk_class=read"),
    fact("autonomy", "L3"),
    fact("dataset", "main.synthetic.accounts"),
    fact("claim", "purpose", "Answers staff questions about transfers."),
    fact("claim", "pii", "category=personal_data"),
]


def use_card(monkeypatch: pytest.MonkeyPatch, rows_: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(v3s, "facts_card", lambda ctx, draft: card_of(rows_))


S3 = {**S1, **S2, "autonomy_level": "l1_assistive"}


def to_step3(c: Console, form: dict[str, Any] | None = None) -> str:
    did = new(c)
    assert step(c, did, 1).status_code == 200  # source: nothing live, go on
    assert step(c, did, 2).status_code == 200  # facts
    r = step(c, did, 3, {**S3, **(form or {})})
    assert r.status_code == 200, r.text[:400]
    return did


def draft_of(c: Console, did: str) -> dict[str, Any]:
    return rs.store_of(c.ctx).get(did, ME)


# ------------------------------------------------------------------ off path


def test_off_path_is_the_seven_step_flow(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    assert on.ctx.settings.register_v3 is False and rs.v3_on(on.ctx) is False
    assert rs.total_steps(on.ctx) == 6
    did = new(on)
    html = on.get(f"/console/register/{did}/step/1?lang=en", user=ME).text
    assert 'data-register="strip"' not in html and 'data-register="step1"' in html
    assert on.get(f"/console/register/{did}/step/7", user=ME).status_code == 400
    assert rm.step_keys(False) == rm.STEP_KEYS and rm.step_keys(True) == rm.STEP_KEYS_DUTIES


def test_flag_without_its_needs_is_400(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("console_register_v2", "register_v3"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    r = on.get("/console/register", user=ME)
    assert r.status_code == 400 and "CLASSIFICATION_V2" in r.text and "RISK_DIMENSIONS" in r.text


# ------------------------------------------------------------------ steps


def test_nine_steps_in_order(v3: Console) -> None:
    assert rm.STEP_KEYS_V3 == (
        "source",
        "facts",
        "identify",
        "classify",
        "assess",
        "duties",
        "guardians",
        "review",
        "done",
    )
    assert rs.total_steps(v3.ctx) == 9
    did = new(v3)
    html = v3.get(f"/console/register/{did}/step/1?lang=en", user=ME).text
    assert html.count("<li") >= 9 and 'data-register="strip"' in html
    for n, marker in ((1, "source"), (2, "facts"), (3, "identify")):
        page = v3.get(f"/console/register/{did}/step/{n}?lang=en", user=ME)
        assert page.status_code == 200 and f'data-register="{marker}"' in page.text, n


# ------------------------------------------------------------------ facts prefill and AI type


def test_prefill_from_facts_with_markers(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "onboard_facts", True)
    use_card(monkeypatch, FACT_ROWS)
    did = new(v3)
    assert step(v3, did, 1).status_code == 200
    assert step(v3, did, 2).status_code == 200  # the facts are taken in on Continue
    d = draft_of(v3, did)
    vals = d["data"]["v"]
    assert vals["model_family"] == "openai" and vals["autonomy_level"] == "l3_tool_using_supervised"
    assert vals["personal_data"] == "identifiable"
    assert "main.synthetic.accounts" in vals["data_sources"]
    assert {"model_family", "autonomy_level", "personal_data", "data_sources", "purpose"} <= set(
        d["data"]["ai_from"]
    )
    assert d["data"]["ai_from_attempt"] == 1
    html = v3.get(f"/console/register/{did}/step/3?lang=en", user=ME).text
    assert html.count('data-mark="facts"') >= 5 and "from facts" in html
    # a field the person changes loses its marker; a second pass does not overwrite it
    assert step(v3, did, 3, {**S3, "model_family": "mine"}, save=True).status_code == 200
    assert "model_family" not in draft_of(v3, did)["data"]["ai_from"]
    assert step(v3, did, 2).status_code == 200
    assert draft_of(v3, did)["data"]["v"]["model_family"] == "mine"


def test_prefill_needs_the_flag_and_a_card(v3: Console) -> None:
    did = new(v3)
    step(v3, did, 1)
    step(v3, did, 2)
    assert draft_of(v3, did)["data"].get("ai_from") in (None, {})
    html = v3.get(f"/console/register/{did}/step/2?lang=en", user=ME).text
    assert 'data-register="turn-on"' in html and "ONBOARD_FACTS" in html


def test_ai_type_flags_by_rule() -> None:
    f = fl.derive({"user_segment": "internal", "human_control": "pre_approval"}, FACT_ROWS)
    assert f == {"generative": True, "agentic": True, "customer_facing": False, "decides": False}
    assert fl.derive({}, []) == dict.fromkeys(fl.FLAGS, False)
    assert fl.derive({"model_family": "x"}, [])["generative"] is True
    assert fl.derive({"autonomy_level": "l2_workflow_step"}, [])["agentic"] is True
    assert fl.derive({"user_segment": "customer"}, [])["customer_facing"] is True
    assert fl.derive({"credit_decision": True}, [])["decides"] is True
    assert fl.derive({"system_type": "decision"}, [])["decides"] is True
    ag = fl.derive({"autonomy_level": "l3_tool_using_supervised", "human_control": "none"}, [])
    assert ag["decides"] is True
    assert fl.propose_type({"decides": True}) == "decision"
    assert fl.propose_type({"agentic": True}) == "automation"
    assert fl.propose_type({"agentic": True, "customer_facing": True}) == "assistant"
    assert fl.settle({"agentic": True}, None)[1]["agentic"] == "rule"
    flags, src = fl.settle({"agentic": True}, {"agentic": False})
    assert flags["agentic"] is False and src["agentic"] == "person" and src["decides"] == "rule"
    assert set(fl.tags_of(flags)) == {
        "ai_generative",
        "ai_agentic",
        "ai_customer_facing",
        "ai_decides",
    }


def test_flags_are_stored_on_draft_and_system(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "onboard_facts", True)
    use_card(monkeypatch, FACT_ROWS)
    did = new(v3)
    step(v3, did, 1)
    step(v3, did, 2)
    form = {**S3, "flags_form": "1", "flag_generative": "1", "flag_customer_facing": "1"}
    assert step(v3, did, 3, form).status_code == 200
    d = draft_of(v3, did)
    assert d["data"]["ai_flags"] == {
        "generative": True,
        "agentic": False,
        "customer_facing": True,
        "decides": False,
    }
    assert d["data"]["ai_flag_src"]["agentic"] == "person"  # the rule said yes (tool fact)
    assert d["data"]["ai_flag_src"]["generative"] == "rule"
    sysrow = rows(v3, "ai_system")[0]
    tags = yaml.safe_load(sysrow["tags"]) if isinstance(sysrow["tags"], str) else sysrow["tags"]
    assert tags["ai_agentic"] == "0" and tags["ai_generative"] == "1"
    assert tags["ai_customer_facing"] == "1" and tags["source"] == "register_v2"
    assert sysrow["status"] == "draft" and sysrow["lifecycle_stage"] == "initiation"


def test_step3_makes_one_system_and_updates_it(v3: Console) -> None:
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    assert [r["system_id"] for r in rows(v3, "ai_system")] == [sid]
    # go back, change, continue: the same record changes, no second one
    changed = {**S3, "purpose": "A changed purpose for the synthetic helper."}
    assert step(v3, did, 3, changed).status_code == 200
    assert [r["system_id"] for r in rows(v3, "ai_system")] == [sid]
    assert rows(v3, "ai_system")[0]["purpose"].startswith("A changed purpose")
    # a bad value: HTTP 400 naming the field, nothing else written
    bad = step(v3, did, 3, {**S3, "kind": "nonsense"})
    assert bad.status_code == 400 and "kind" in bad.text
    miss = step(v3, did, 3, {**S3, "purpose": ""})
    assert miss.status_code == 400 and "purpose" in miss.text


def test_save_for_later_does_not_make_the_system(v3: Console) -> None:
    did = new(v3)
    assert step(v3, did, 3, {"name": "Later"}, save=True).status_code == 200
    assert rows(v3, "ai_system") == [] and "sys" not in draft_of(v3, did)["data"]


# ------------------------------------------------------------------ the strip


def strip_rows(c: Console, did: str, key: str) -> dict[str, dict[str, Any]]:
    out = strip.evaluate(c.ctx, draft_of(c, did), key)
    return {r["id"]: r for r in out["rows"]}


def test_every_strip_id_exists_in_regkb() -> None:
    from supervisor.regkb.loader import load_kb

    kb = load_kb()
    cfg = strip.load()
    assert set(cfg) == set(rm.STEP_KEYS_V3)
    for key, entries in cfg.items():
        assert entries, key
        for e in entries:
            assert e.id in kb.obligations, (key, e.id)
            assert e.rule in strip.RULES


def test_strip_mapping_has_the_articles_of_the_brief() -> None:
    cfg = strip.load()
    ids = {k: {e.id for e in v} for k, v in cfg.items()}
    for oid in (
        "VN-AI-2025-A9.01-01",
        "VN-AI-2025-A10.01-01",
        "VN-DEC142-2026-A6.02-01",
        "VN-DEC142-2026-A8.01-01",
        "VN-DEC142-2026-A9.01-01",
        "VN-TT53-2026-A4.03-01",
    ):
        assert oid in ids["classify"], oid
    assert {"VN-TT53-2026-A14.03-01", "VN-TT53-2026-A14.04-01", "VN-TT53-2026-A13.01-01"} <= ids[
        "assess"
    ]
    assert {"VN-TT53-2026-A5.01-01", "VN-TT53-2026-A6.01-01", "VN-TT53-2026-A7.04-01"} <= ids[
        "guardians"
    ]
    assert {"VN-TT53-2026-A12.03-01", "VN-TT53-2026-A4.03-01"} <= ids["review"]
    assert {"VN-AI-2025-A13.01-01", "VN-AI-2025-A10.03-01", "VN-DEC142-2026-A12.02-01"} <= ids[
        "duties"
    ]


def test_strip_parse_refuses_bad_files() -> None:
    good = yaml.safe_load(open(strip.DEFAULT_CONFIG, encoding="utf-8"))
    strip.parse(good)
    for bad in (
        {**good, "extra": 1},
        {**good, "steps": {k: v for k, v in good["steps"].items() if k != "done"}},
        {**good, "steps": {**good["steps"], "done": [{"id": "X", "rule": "nope"}]}},
        {
            **good,
            "steps": {**good["steps"], "done": [{"id": "X", "rule": "submitted", "when": "low"}]},
        },
        {**good, "steps": {**good["steps"], "done": []}},
    ):
        with pytest.raises(strip.StripError):
            strip.parse(bad)


def test_strip_is_on_every_step_page(v3: Console) -> None:
    did = to_step3(v3)
    for n, key in enumerate(rm.STEP_KEYS_V3[:8], 1):
        html = v3.get(f"/console/register/{did}/step/{n}?lang=en", user=ME).text
        assert f'data-register="strip" data-step="{key}"' in html, key
        want = {e.id for e in strip.load()[key]}
        got = set(re.findall(r'data-strip-article="([^"]+)"', html))
        assert got == want, key
    vi = v3.get(f"/console/register/{did}/step/3?lang=vi", user=ME).text
    assert "Dải tuân thủ" in vi and "Nhận diện và loại AI" in vi


def test_strip_statuses_and_attempts(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    did = new(v3)
    r = strip_rows(v3, did, "identify")
    assert {x["status"] for x in r.values()} == {"open"}
    assert strip.evaluate(v3.ctx, draft_of(v3, did), "identify")["attempt"] == 0
    assert step(v3, did, 1).status_code == 200
    assert step(v3, did, 3, S3).status_code == 200
    sid = draft_of(v3, did)["data"]["sys"]
    rows3 = strip_rows(v3, did, "identify")
    assert {x["status"] for x in rows3.values()} == {"met"}
    assert rows3["VN-TT53-2026-A4.05-01"]["evidence"] == f"ai_system:{sid}"
    assert strip.evaluate(v3.ctx, draft_of(v3, did), "identify")["attempt"] == 1
    assert step(v3, did, 3, S3).status_code == 200  # a second pass of the step
    assert strip.evaluate(v3.ctx, draft_of(v3, did), "identify")["attempt"] == 2
    # the classification rules: nothing yet, then a record waiting, then an approved one
    c = strip_rows(v3, did, "classify")
    assert {x["status"] for x in c.values()} == {"open"}
    cid = classify(v3, sid)
    c = strip_rows(v3, did, "classify")
    assert c["VN-AI-2025-A9.01-01"]["status"] == "met"
    assert c["VN-AI-2025-A9.01-01"]["evidence"] == f"classification_v2:{cid}"
    assert c["VN-TT53-2026-A4.03-01"]["status"] == "open"  # not approved yet
    approve(v3, sid)
    c = strip_rows(v3, did, "classify")
    assert c["VN-TT53-2026-A4.03-01"]["status"] == "met"
    # the level decides the "when" entries: a medium system has no board approval duty
    rv = strip_rows(v3, did, "review")
    assert rv["VN-TT53-2026-A12.03-01"]["status"] == "not_applicable"
    assert rv["VN-TT53-2026-A4.03-01"]["status"] == "met"


def test_strip_assess_all_pass_or_waived_means_met(v3: Console) -> None:
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    a = strip_rows(v3, did, "assess")
    assert a["VN-TT53-2026-A14.03-01"]["status"] == "open"
    assert a["VN-TT53-2026-A14.04-01"]["status"] == "open"
    assert (
        v3.get(f"/console/register/{did}/step/5?lang=en", user=ME).status_code == 200
    )  # rows made
    dims = [r["dimension_id"] for r in rows(v3, "risk_dimension_status", system_id=sid)]
    assert len(dims) == 8
    for i, dim in enumerate(dims):
        r = v3.post(
            f"/console/systems/{sid}/risk-dimensions/{dim}/waive",
            {"reason": "Synthetic waiver for the strip test."},
            user=APPROVER,
        )
        assert r.status_code == 200, r.text[:300]
        a = strip_rows(v3, did, "assess")
        want = "met" if i == 7 else "open"
        assert a["VN-TT53-2026-A14.03-01"]["status"] == want, i
    assert strip_rows(v3, did, "assess")["VN-TT53-2026-A14.04-01"]["status"] == "met"
    assert strip_rows(v3, did, "assess")["VN-TT53-2026-A14.03-01"]["evidence"] == (
        f"risk_dimension_status:{sid}"
    )


# ------------------------------------------------------------------ helpers for the records

HIGH = {
    "answers": {
        "N-SYSTEM": {"answer": "yes"},
        "N-PROHIBITED": {"answer": "no"},
        "N-THRESHOLD": {"answer": "yes", "evidence": "doc:limits-v2"},
        "N-CERT": {"answer": "no"},
        "N-CONFUSE": {"answer": "no"},
    },
    "decision33": {"Q-OTHER": {"answer": "no", "justification": "Checked against the product."}},
}
LOW = {
    "answers": {
        "N-SYSTEM": {"answer": "yes"},
        "N-PROHIBITED": {"answer": "no"},
        "N-THRESHOLD": {"answer": "no"},
        "N-CONFUSE": {"answer": "no"},
    },
    "decision33": HIGH["decision33"],
}


def classify(c: Console, sid: str, body: dict[str, Any] | None = None) -> str:
    r = c.client.request(
        "POST",
        f"/v1/systems/{sid}/classification-v2",
        json=body or HIGH,
        headers={"X-Dev-User": ME},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["classification_id"])


def approve(c: Console, sid: str) -> None:
    r = c.client.request(
        "POST", f"/v1/systems/{sid}/classification-v2/approve", headers={"X-Dev-User": APPROVER}
    )
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ go back and re-run

S_HIGH = {**S3, "money_movement": "1", "credit_decision": "1"}


def test_go_back_change_and_rerun_every_step(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v3.ctx.settings, "onboard_facts", True)
    use_card(monkeypatch, FACT_ROWS)
    did = to_step3(v3, S_HIGH)
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    for n in (4, 5, 6, 7):  # forward through the middle steps
        assert step(v3, did, n, {"bind_form": "1"} if n == 7 else None).status_code == 200, n
    d = draft_of(v3, did)
    assert d["step"] == 8
    att = d["data"]["step_attempts"]
    assert att["identify"] == 1 and all(
        att[k] == 1 for k in ("classify", "assess", "duties", "guardians")
    )
    # every step can be opened again and run again; the attempt number goes up by one each time
    for n, key in ((1, "source"), (2, "facts"), (3, "identify"), (4, "classify"), (5, "assess")):
        page = v3.get(f"/console/register/{did}/step/{n}?lang=en", user=ME)
        assert page.status_code == 200, key
        body = S_HIGH if n == 3 else (None if n != 1 else {"skip_reason": "No code to give yet."})
        assert step(v3, did, n, body).status_code == 200, key
        assert draft_of(v3, did)["step"] == 8  # going back never lowers the furthest step
        assert draft_of(v3, did)["data"]["step_attempts"][key] == att.get(key, 0) + 1, key
    assert step(v3, did, 7, {"bind_form": "1"}, save=True).status_code == 200
    assert draft_of(v3, did)["data"]["step_attempts"]["guardians"] == 2
    assert [r["system_id"] for r in rows(v3, "ai_system")] == [sid]  # still one record


def test_source_step_needs_a_source_or_a_reason_when_intake_is_on(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "onboard_intake", True)
    did = new(v3)
    bad = step(v3, did, 1)
    assert bad.status_code == 400 and "source" in bad.text
    short = step(v3, did, 1, {"skip": "1", "skip_reason": "no"})
    assert short.status_code == 400 and "skip_reason" in short.text
    ok = step(v3, did, 1, {"skip": "1", "skip_reason": "The code is not ready to share."})
    assert ok.status_code == 200
    assert draft_of(v3, did)["data"]["skip_source"].startswith("The code")
    r = strip_rows(v3, did, "source")
    assert {x["status"] for x in r.values()} == {"not_applicable"}


def test_source_and_facts_panels_are_the_intake_and_facts_panels(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import zipfile

    for flag in ("onboard_intake", "onboard_facts"):
        monkeypatch.setattr(v3.ctx.settings, flag, True)
    did = new(v3)
    page = v3.get(f"/console/register/{did}/step/1?lang=en", user=ME).text
    assert 'id="intake-panel"' in page and f'data-node="{did}"' in page
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("agent.py", "import os\n\ndef run():\n    return 1\n")
    up = v3.client.post(
        f"/console/intake/{did}",
        files={"file": ("agent.zip", buf.getvalue(), "application/zip")},
        headers={"X-Dev-User": ME, "HX-Request": "true"},
    )
    assert up.status_code == 200, up.text[:300]
    assert 'data-attempt="1"' in up.text
    assert step(v3, did, 1).status_code == 200  # a stored attempt lets the step go on
    r = strip_rows(v3, did, "source")
    assert {x["status"] for x in r.values()} == {"met"}
    assert r["VN-TT53-2026-A19.02-01"]["evidence"] == f"intake_attempt:{did}#1"
    assert strip.evaluate(v3.ctx, draft_of(v3, did), "source")["attempt"] == 1
    facts_page = v3.get(f"/console/register/{did}/step/2?lang=en", user=ME).text
    assert 'id="facts-panel"' in facts_page and 'data-action="reread"' in facts_page
    again = v3.post(f"/console/facts/{did}", {}, user=ME)
    assert again.status_code == 200, again.text[:300]
    assert strip.evaluate(v3.ctx, draft_of(v3, did), "facts")["attempt"] == 1


def test_step_pages_embed_the_panels(v3: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("onboard_predeploy", "onboard_orchestrator"):
        monkeypatch.setattr(v3.ctx.settings, flag, True)
    did = to_step3(v3, S_HIGH)
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    cls = v3.get(f"/console/register/{did}/step/4?lang=en", user=ME).text
    assert 'id="classify-panel"' in cls and f'data-system="{sid}"' in cls
    assess = v3.get(f"/console/register/{did}/step/5?lang=en", user=ME).text
    assert 'id="tab-body"' in assess and assess.count('data-section="rd-row"') == 8
    assert 'data-orch="panel"' in assess and 'data-act="orch-run"' in assess
    guard = v3.get(f"/console/register/{did}/step/7?lang=en", user=ME).text
    assert 'id="predeploy-panel"' in guard and 'data-action="run-again"' in guard
    assert 'data-register="step5"' in guard  # the guardian table is still there
    # the panels answer as htmx fragments too
    for url in (
        f"/console/systems/{sid}/classify",
        f"/console/predeploy/{did}",
    ):
        r = v3.get(url + ("&" if "?" in url else "?") + "lang=en", user=ME, headers=HX)
        assert r.status_code == 200 and "<html" not in r.text.lower(), url


def test_panels_say_turn_on_and_let_the_person_continue(v3: Console) -> None:
    did = to_step3(v3)
    for n, flag in ((1, "ONBOARD_INTAKE"), (2, "ONBOARD_FACTS"), (7, "ONBOARD_PREDEPLOY")):
        html = v3.get(f"/console/register/{did}/step/{n}?lang=en", user=ME).text
        assert 'data-register="turn-on"' in html and flag in html, n
        assert f'action="/console/register/{did}/step/{n}?lang=en"' in html, n
    html = v3.get(f"/console/register/{did}/step/5?lang=en", user=ME).text
    assert "ONBOARD_ORCHESTRATOR" in html and 'data-act="rd-reassess"' in html


# ------------------------------------------------------------------ duties


def test_duties_prefill_from_classification_and_ai_type(v3: Console) -> None:
    did = to_step3(v3, {**S_HIGH, "flags_form": "1", "flag_customer_facing": "1"})
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    assert step(v3, did, 5).status_code == 200  # Continue on the assessment step applies it
    d = draft_of(v3, did)
    assert d["data"]["duties_answers"] == {
        "Q-customer_facing": True,
        "Q-decisions_affecting_customers": False,
    }
    assert d["data"]["duty_from"] == {
        "Q-customer_facing": "ai_type",
        "Q-decisions_affecting_customers": "ai_type",
    }
    view = v3s.step_view(v3.ctx, _me(v3), d, "duties", {}, None)
    marks = {m["obligation_id"]: m for m in view["marks_duty"]}
    assert marks["VN-TT53-2026-A13.01-01"]["from"] == "classification"
    assert marks["VN-TT53-2026-A12.03-01"]["from"] == "classification"
    assert marks["VN-AI-2025-A13.01-01"]["from"] == "classification"
    assert marks["VN-DEC142-2026-A12.02-01"]["from"] == "classification"
    assert marks["VN-AI-2025-A10.03-01"]["from"] == "classification"
    assert view["level"]["level"] == "high"
    html = v3.get(f"/console/register/{did}/step/6?lang=en", user=ME).text
    assert html.count('data-mark="ai_type"') == 2 and "from classification" in html
    assert 'data-prefill="VN-TT53-2026-A13.01-01"' in html
    # the person changes a pre-filled answer: it is the person's now
    assert step(v3, did, 6, {"Q-customer_facing": "no"}).status_code == 200
    d = draft_of(v3, did)
    assert d["data"]["duties_answers"]["Q-customer_facing"] is False
    assert "Q-customer_facing" not in d["data"]["duty_from"]
    assert "Q-decisions_affecting_customers" in d["data"]["duty_from"]
    # Re-apply does not take the person's answer back
    assert step(v3, did, 6, {"prefill": "1", "run": "1"}).status_code == 200
    assert draft_of(v3, did)["data"]["duties_answers"]["Q-customer_facing"] is False


def test_duties_prefill_from_a_low_level_has_no_level_rows(v3: Console) -> None:
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    d = draft_of(v3, did)
    view = v3s.step_view(v3.ctx, _me(v3), d, "duties", {}, None)
    assert view["level"]["level"] == "low" and view["marks_duty"] == []
    s = strip_rows(v3, did, "duties")
    assert {x["status"] for x in s.values()} == {"not_applicable"}


def test_duties_prefill_from_the_orchestrator_file(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from pathlib import Path

    monkeypatch.setattr(v3.ctx.settings, "onboard_orchestrator", True)
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    folder = Path(v3.ctx.settings.data_dir) / "assessments" / sid / "1"
    folder.mkdir(parents=True)
    (folder / "duties_prefill.json").write_text(
        json.dumps(
            {
                "version": 1,
                "system_id": sid,
                "covered": [
                    {
                        "dimension_id": "model",
                        "articles": ["Art. 14(3)(a)", "Art. 16(3)"],
                        "controls": [],
                        "report_ref": "report:model-1",
                        "report_sha256": "0" * 64,
                        "confirmed": False,
                    }
                ],
                "open": [],
            }
        ),
        encoding="utf-8",
    )
    view = v3s.step_view(v3.ctx, _me(v3), draft_of(v3, did), "duties", {}, None)
    got = {m["obligation_id"]: m for m in view["marks_duty"] if m["from"] == "assessment"}
    assert "VN-TT53-2026-A16.03-01" in got and "VN-TT53-2026-A14.03-01" in got
    assert got["VN-TT53-2026-A16.03-01"]["confirmed"] is False
    assert got["VN-TT53-2026-A16.03-01"]["ref"] == "report:model-1"
    html = v3.get(f"/console/register/{did}/step/6?lang=en", user=ME).text
    assert "from assessment" in html and "proposal" in html
    # the flag off: the file is not read
    monkeypatch.setattr(v3.ctx.settings, "onboard_orchestrator", False)
    view = v3s.step_view(v3.ctx, _me(v3), draft_of(v3, did), "duties", {}, None)
    assert not [m for m in view["marks_duty"] if m["from"] == "assessment"]


def _me(c: Console) -> Any:
    from supervisor.adapters.auth.base import AuthPrincipal

    return AuthPrincipal(ME, "user", "dev_header", frozenset({"reviewer"}), ME)


# ------------------------------------------------------------------ submit and done


def walk_to_review(c: Console) -> tuple[str, str]:
    did = to_step3(c, S_HIGH)
    sid = draft_of(c, did)["data"]["sys"]
    classify(c, sid)
    for n in (4, 5, 6):
        assert step(c, did, n).status_code == 200
    assert step(c, did, 7, {"bind_form": "1"}).status_code == 200
    return did, sid


def test_review_page_and_submit_creates_the_stage_approval_request(v3: Console) -> None:
    did, sid = walk_to_review(v3)
    page = v3.get(f"/console/register/{did}/step/8?lang=en", user=ME).text
    assert 'data-register="review"' in page and 'data-register="stage-request"' in page
    assert "deployment" in page and "Submit and ask for approval" in page
    assert 'data-register="review-flags"' in page
    assert rows(v3, "stage_approval") == []
    r = submit(v3, did)
    assert r.status_code == 200, r.text[:300]
    d = draft_of(v3, did)
    assert d["status"] == "submitted"
    ap = rows(v3, "stage_approval", system_id=sid)
    assert len(ap) == 1 and ap[0]["status"] == "pending" and ap[0]["to_stage"] == "deployment"
    assert ap[0]["requested_by"] == ME
    res = d["data"]["result"]
    assert res["system_id"] == sid and res["v3"] is True
    stage = next(s for s in res["steps"] if s["key"] == "rg3_w_stage")
    assert stage["status"] == "ok" and ap[0]["approval_id"] in stage["detail"]
    # one system record, still in status draft and stage initiation; nothing applied
    sysrows = rows(v3, "ai_system")
    assert [x["system_id"] for x in sysrows] == [sid]
    assert sysrows[0]["status"] == "draft" and sysrows[0]["lifecycle_stage"] == "initiation"
    assert rows(v3, "obligation_status", system_id=sid)
    # a second submit writes nothing
    assert submit(v3, did).status_code == 400
    assert len(rows(v3, "stage_approval", system_id=sid)) == 1


def test_done_step_links(v3: Console) -> None:
    did, sid = walk_to_review(v3)
    assert submit(v3, did).status_code == 200
    page = v3.get(f"/console/register/{did}/result?lang=en", user=ME).text
    assert 'data-register="v3-links"' in page
    for link in ("system", "system-classification", "system-riskdim", "system-tasks"):
        assert f'data-link="{link}"' in page, link
    assert f"/console/systems/{sid}?tab=riskdim" in page
    r = v3.get(f"/console/register/{did}/step/9?lang=en", user=ME, follow_redirects=False)
    assert r.status_code in (302, 303, 307) and "/result" in r.headers["location"]
    # the strip of the last step: met after the submit
    last = strip_rows(v3, did, "done")
    assert last["VN-TT53-2026-A22.01-01"]["status"] == "met"
    assert last["VN-TT53-2026-A4.05-01"]["status"] == "met"
    rv = strip_rows(v3, did, "review")
    assert rv["VN-TT53-2026-A12.03-01"]["status"] == "met"  # high risk, request waiting


def test_submit_without_step3_is_400_and_a_not_yet_step_9_goes_back(v3: Console) -> None:
    did = new(v3)
    r = submit(v3, did)
    assert r.status_code == 400
    assert rows(v3, "stage_approval") == [] and rows(v3, "ai_system") == []
    assert draft_of(v3, did)["status"] == "draft"
    back = v3.get(f"/console/register/{did}/step/9?lang=en", user=ME, follow_redirects=False)
    assert back.status_code in (302, 303, 307) and "/step/8" in back.headers["location"]


def test_abandon_archives_the_system_record(v3: Console) -> None:
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    assert v3.post(f"/console/register/{did}/abandon", {}, user=ME).status_code == 200
    assert draft_of_any(v3, did)["status"] == "abandoned"
    assert rows(v3, "ai_system", system_id=sid)[0]["status"] == "archived"


def draft_of_any(c: Console, did: str) -> dict[str, Any]:
    return rs.store_of(c.ctx).get(did, ME)


# ------------------------------------------------------------------ roles


def test_roles_and_other_people_drafts(v3: Console) -> None:
    did = to_step3(v3)
    for n in (1, 3, 8):
        assert v3.get(f"/console/register/{did}/step/{n}", user=VIEWER).status_code == 403
        assert v3.post(f"/console/register/{did}/step/{n}", {}, user=VIEWER).status_code == 403
    assert v3.post(f"/console/register/{did}/submit", {}, user=VIEWER).status_code == 403
    other = v3.get(f"/console/register/{did}/step/3", user="admin.chi")
    assert other.status_code == 400 and "does not exist" in other.text


def test_bad_step_numbers_are_400(v3: Console) -> None:
    did = new(v3)
    for n in ("0", "10", "x", "-1"):
        assert v3.get(f"/console/register/{did}/step/{n}", user=ME).status_code == 400, n


def test_vi_pages_render(v3: Console) -> None:
    did, _ = walk_to_review(v3)
    for n in range(1, 9):
        r = v3.get(f"/console/register/{did}/step/{n}?lang=vi", user=ME)
        assert r.status_code == 200, n
        assert "rg3_" not in r.text and "rg2_" not in r.text, n
