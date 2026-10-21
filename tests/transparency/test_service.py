"""WP31 service: versions, files, hashes, the chain record, serving, allow-lists, PDF."""

from __future__ import annotations

import hashlib
import json

import pytest

from supervisor.core.errors import NotFoundError
from supervisor.transparency import allowlist, render
from supervisor.transparency.harness import Env
from supervisor.transparency.model import (
    SECTIONS,
    TransparencyError,
    TransparencyOff,
    UnknownAgent,
    assert_plain,
)


def _chain_rows(env: Env, agent: str) -> list[dict]:
    rows = env.adapters.tables.query("chain_entry", {"lane": f"agent:{agent}"}, order_by=("seq",))
    return [dict(r) for r in rows if r["record_type"] == "transparency_report"]


def test_generate_writes_files_rows_and_one_chain_record_per_variant(env: Env) -> None:
    out = env.svc.generate("payments", actor="reviewer.an", fresh_verify=True)
    assert [r["status"] for r in out] == ["made"] * 3
    assert len(_chain_rows(env, "payments")) == 3
    rows = env.svc.rows("payments")
    assert len(rows) == 6  # three variants x two languages
    for r in rows:
        folder = env.svc._dir("payments", r["variant"], r["version"])
        assert hashlib.sha256((folder / "report.json").read_bytes()).hexdigest() == r["json_hash"]
        html = (folder / f"report.{r['lang']}.html").read_bytes()
        assert hashlib.sha256(html).hexdigest() == r["html_hash"]
        assert r["chain_hash"] and r["verify_state"] == "ok"
        assert set(
            r["section_hashes"]
            if isinstance(r["section_hashes"], dict)
            else json.loads(r["section_hashes"])
        ) <= set(SECTIONS)


def test_chain_payload_holds_hashes_and_integers_only(env: Env) -> None:
    env.svc.generate("payments", ("regulator",), actor="reviewer.an", fresh_verify=False)
    payloads = env.adapters.tables.query("chain_payload", {"lane": "agent:payments"})
    docs = [
        json.loads(p["payload"]) if isinstance(p["payload"], str) else p["payload"]
        for p in payloads
    ]
    doc = next(d for d in docs if d.get("variant") == "regulator" and "json_sha256" in d)
    assert_plain(doc)  # no float
    assert len(doc["json_sha256"]) == 64 and len(doc["html_sha256_vi"]) == 64
    assert doc["diff_first"] is True and doc["version"] == 1
    text = json.dumps(doc)
    for banned in ("purpose", "summary", "title"):
        assert banned not in text


def test_second_run_is_unchanged_and_changes_make_a_diff(env: Env) -> None:
    env.svc.generate("credit_prequal", actor="u", fresh_verify=False)
    again = env.svc.generate("credit_prequal", actor="u", fresh_verify=False)
    assert {r["status"] for r in again} == {"unchanged"}
    env.add_case("credit_prequal", "new case")
    third = env.svc.generate("credit_prequal", ("regulator",), actor="u", fresh_verify=False)[0]
    assert third["version"] == 2 and "cases" in third["diff"]["changed"]
    assert "evidence" not in third["diff"]["changed"]  # the chain head is volatile by design


def test_serving_checks_the_stored_hash(env: Env) -> None:
    env.svc.generate("payments", ("customer",), actor="u", fresh_verify=False)
    data, ctype, info = env.svc.read("payments", "customer", "html", "vi")
    assert info["status"] == "signed" and ctype.startswith("text/html")
    path = env.svc._dir("payments", "customer", 1) / "report.vi.html"
    path.write_bytes(data + b"<!-- tampered -->")
    with pytest.raises(TransparencyError, match="does not match"):
        env.svc.read("payments", "customer", "html", "vi")
    path.unlink()
    with pytest.raises(NotFoundError):
        env.svc.read("payments", "customer", "html", "vi")


def test_unsigned_read_is_a_preview_and_live_ignores_the_stored_file(env: Env) -> None:
    _, _, info = env.svc.read("payments", "regulator", "json", "en")
    assert info == {"status": "preview", "version": 0, "hash": info["hash"]}
    env.svc.generate("payments", ("regulator",), actor="u", fresh_verify=False)
    assert env.svc.read("payments", "regulator", "json")[2]["status"] == "signed"
    assert env.svc.read("payments", "regulator", "json", live=True)[2]["status"] == "preview"


def test_off_flag_and_unknown_agent(env: Env) -> None:
    with pytest.raises(UnknownAgent):
        env.svc.generate("nobody", actor="u")
    env.settings.transparency_enabled = False
    with pytest.raises(TransparencyOff):
        env.svc.generate("payments", actor="u")


def test_variants_differ_by_allow_list_and_regulator_cites_obligations(env: Env) -> None:
    reg = env.svc.preview("payments", "regulator")
    cust = env.svc.preview("payments", "customer")
    internal = env.svc.preview("payments", "internal")
    assert "agent_id" in reg and "agent_id" not in cust
    assert "VN-QD33-2026-PL4.1-01" in json.dumps(reg)
    assert "owner_user" not in json.dumps(reg) and "owner_user" in json.dumps(internal)
    assert "backlog" in internal["sections"] and not reg["sections"]["backlog"]["available"]
    assert set(cust["sections"]["identity"]["data"]) == {"kind", "oversight"}
    for text in (env.texts(cust),):
        assert "payments" not in text.replace("executes_payments", "")


def test_unavailable_sections_say_why(env: Env) -> None:
    env.settings.risk_register_enabled = False
    r = env.svc.preview("payments", "regulator")
    s = r["sections"]["risks"]
    assert (s["available"], s["reason"], s["ref"]) == (False, "flag_off", "RISK_REGISTER_ENABLED")
    # WP30 is merged (integration wave 2): the package is present, CONTROLS_ENABLED is off
    c = r["sections"]["controls"]
    assert (c["reason"], c["ref"]) == ("flag_off", "CONTROLS_ENABLED")


def test_both_languages_use_their_own_words(env: Env) -> None:
    r = env.svc.preview("payments", "regulator")
    vi, en = render.plain_text(r, "vi"), render.plain_text(r, "en")
    assert "Phân loại" in vi and "Classification" in en
    assert "tp_" not in vi and "tp_" not in en  # no missing label key
    for variant in ("customer", "internal"):
        rr = env.svc.preview("payments", variant)
        assert "tp_" not in render.plain_text(rr, "vi") + render.plain_text(rr, "en")


def test_html_reuses_the_case_file_style_and_is_self_contained(env: Env) -> None:
    html = render.render_html(env.svc.preview("payments", "regulator"), "en").decode()
    assert render.case_file_style() in html
    assert "http://" not in html and "https://" not in html and "<script" not in html


def test_pdf_renders_with_a_local_font_only(env: Env) -> None:
    pytest.importorskip("fpdf")
    res = render.render_pdf(env.svc.preview("payments", "regulator"), "vi")
    if res.fmt == "html":
        pytest.skip(res.notice)  # no Unicode font on this machine
    assert res.data.startswith(b"%PDF") and res.notice is None
    again = render.render_pdf(env.svc.preview("payments", "regulator"), "vi")
    assert again.data[:5] == b"%PDF-"


def test_guard_rejects_leaks_directly() -> None:
    rep = {"sections": {"x": {"data": {"owner_user": "a"}, "ref": None}}}
    with pytest.raises(TransparencyError):
        allowlist.guard(rep, "customer", {"ids": set(), "people": set()})
    rep2 = {"sections": {"x": {"data": {"note": "see PAY-02 and " + "a" * 64}, "ref": None}}}
    with pytest.raises(TransparencyError):
        allowlist.guard(rep2, "customer", {"ids": set(), "people": set()})
    rep3 = {"sections": {"x": {"data": {"note": "Nguyen Van An"}, "ref": None}}}
    with pytest.raises(TransparencyError):
        allowlist.guard(
            rep3, "regulator", {"ids": set(), "people": {"Nguyen Van An"}, "team": set()}
        )
