"""WP31 review (data protection officer): planted identifying values in every source the builder
reads must not reach the outer variants, in any language or format; the allow-list review gate;
the chain actor; the second check on the preview path."""

from __future__ import annotations

import copy
import html as htmllib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from supervisor.risk.model import CATEGORIES
from supervisor.risk.service import RiskService
from supervisor.transparency import allowlist, render
from supervisor.transparency.builder import ok
from supervisor.transparency.harness import AGENT_IDS, Env
from supervisor.transparency.model import TransparencyError

from .pdftext import pdf_text

NAME = "Nguyễn Thị Hồng Nhung"  # registered (owner, MRM role)
NAME2 = "Trần Văn Bảo"  # registered (business owner)
NAME3 = "Lê Minh Khôi"  # nobody registered it: only in free text and config fields
CCCD = "079203001234"
PHONE = "0912345678"
EMAIL = "nhung.nguyen@bank.example.vn"
EMAIL2 = "khoi.le@other.example.vn"
ACCOUNT = "19031234567890"
RULE = "PAY-03"
HASH = "deadbeef" * 8
TEAM = "Khoi Ban Le Team Alpha"
BACKLOG_TXT = "BKLG-SECRET-ROW"
PII = f"{NAME3} CCCD {CCCD} tel {PHONE} mail {EMAIL2} acct {ACCOUNT} credit_prequal {RULE} {HASH}"

TOKENS: dict[str, list[str]] = {
    "person": [NAME, NAME2, NAME3],
    "email": [EMAIL, EMAIL2],
    "phone": [PHONE],
    "cccd": [CCCD],
    "account": [ACCOUNT],
    "agent_id": ["payments", "credit_prequal"],
    "rule_id": [RULE],
    "hash": [HASH],
    "owner_team": [TEAM],
    "backlog": [BACKLOG_TXT],
}
FORBID = {
    "customer": list(TOKENS),
    "regulator": ["person", "email", "phone", "cccd", "account"],
}


def _hits(text: str, variant: str) -> list[str]:
    low = text.lower().replace("executes_payments", "")
    out = []
    for cat in FORBID[variant]:
        for tok in TOKENS[cat]:
            t = tok.lower()
            found = (
                re.search(rf"(?<![a-z0-9_]){re.escape(t)}(?![a-z0-9_])", low)
                if cat == "agent_id"
                else t in low
            )
            if found:
                out.append(f"{cat}:{tok}")
    return out


def _seed(env: Env, *, masker: bool = True) -> None:
    s = env.settings
    s.mrm_model_owner = NAME
    s.mrm_validator = f"{NAME2} {EMAIL}"
    if not masker:
        env.svc.facts._masker = None
        env.svc.src.masker = None
    backlog = Path(env._tmp.name) / "BACKLOG.md"
    backlog.write_text(
        "| Item | Returns when |\n|---|---|\n"
        f"| payments: {BACKLOG_TXT} for {NAME} {EMAIL} {PHONE} | when {CCCD} {ACCOUNT} |\n",
        encoding="utf-8",
    )
    s.transparency_backlog_file = backlog
    db = sqlite3.connect(str(s.sqlite_path))
    try:
        db.execute(
            "UPDATE agent SET name=?, owner_team=?, owner_user=?, business_owner=? "
            "WHERE agent_id='payments'",
            (f"Tro ly {NAME} {PHONE}", TEAM, EMAIL, NAME2),
        )
        root = db.execute(
            "SELECT e.src_id FROM inventory_edge e JOIN inventory_node n ON n.node_id=e.dst_id "
            "WHERE n.name='payments/transfer'"
        ).fetchone()
        assert root is not None
        for (dst,) in db.execute("SELECT dst_id FROM inventory_edge WHERE src_id=?", root):
            db.execute(
                "UPDATE inventory_node SET display_name=? WHERE node_id=?", (f"tool {PII}", dst)
            )
        db.execute(
            "UPDATE inventory_edge SET evidence_ref=? WHERE src_id=?", (f"x.py:1 {PII}", root[0])
        )
        db.commit()
    finally:
        db.close()
    real = env.svc.facts.matrix

    def matrix(agent_id: str) -> dict[str, Any]:
        m = copy.deepcopy(real(agent_id))
        p = m.setdefault("product", {})
        p["purpose"] = f"Purpose {PII}"
        for lim in p.get("limits") or []:
            lim["id"] = f"lim {PHONE}"
            lim["scope"] = f"scope {NAME3}"
            lim.setdefault("pointer", {})["ref"] = f"f.py:2 {NAME3} {EMAIL2} {CCCD}"
        for r in m.get("rows") or []:
            r["article_ref"] = f"Art 1 {NAME3} {EMAIL2} {ACCOUNT}"
            r["instrument_id"] = f"inst {CCCD}"
        return m

    env.svc.facts.matrix = matrix  # type: ignore[method-assign]
    RiskService(
        env.adapters.state, env.adapters.tables, env.adapters.clock, s, evidence=env.rt.chain
    ).create(
        {
            "title": f"Risk {PII}",
            "description": PII,
            "category": "pii" if "pii" in CATEGORIES else CATEGORIES[0],
            "agent_id": "payments",
            "inherent_likelihood": 4,
            "inherent_impact": 5,
            "treatment": "accept",
            "treatment_note": f"note {PII}",
            "residual_likelihood": 4,
            "residual_impact": 5,
            "owner": EMAIL,
            "review_date": "2027-01-31",
            "status": "active",
        },
        EMAIL,
    )
    env.add_case("payments", f"Case {PII}")
    env.rt.chain.record("note", "probe", {"agent_id": "payments", "text": PII, "who": NAME})
    env.add_eval("payments", "pii_canary", mock=True)


def _texts(env: Env, variant: str, live: bool) -> dict[tuple[str, str], str]:
    out = {}
    pdf_ok = render.render_pdf(env.svc.preview("payments", variant), "en").fmt == "pdf"
    for lang in ("vi", "en"):
        for fmt in ("json", "html", "pdf"):
            if fmt == "pdf" and not pdf_ok:
                continue
            data, _, _ = env.svc.read("payments", variant, fmt, lang, live=live)
            out[(lang, fmt)] = (
                pdf_text(data)
                if fmt == "pdf"
                else htmllib.unescape(data.decode("utf-8"))
                if fmt == "html"
                else data.decode("utf-8")
            )
    return out


@pytest.mark.parametrize("masker", [True, False], ids=["masker", "no_masker"])
def test_planted_values_never_reach_the_outer_variants(env: Env, masker: bool) -> None:
    _seed(env, masker=masker)
    env.set_verify(False)
    seen = 0
    for variant in ("regulator", "customer"):
        for live in (True, False):
            if not live:
                env.svc.generate("payments", (variant,), actor=EMAIL, fresh_verify=True)
            for (lang, fmt), text in _texts(env, variant, live).items():
                assert _hits(text, variant) == [], (variant, live, lang, fmt)
                seen += 1
    assert seen >= 16
    internal = json.dumps(env.svc.preview("payments", "internal"), ensure_ascii=False)
    # the bank sees its rows (masked); with no masker the free text is dropped there too
    assert (BACKLOG_TXT in internal) is masker


def test_the_failed_chain_check_is_stated_in_every_variant_and_format(env: Env) -> None:
    _seed(env)
    env.set_verify(False)
    env.svc.generate("payments", actor="system:test", fresh_verify=True)
    for variant in ("regulator", "customer", "internal"):
        for (lang, fmt), text in _texts(env, variant, live=False).items():
            if fmt == "json":
                assert "chain_verify_failed" in text, (variant, lang)
            elif lang == "en":
                assert "did not pass" in text or "FAILED" in text, (variant, fmt)
            else:
                assert "KHÔNG ĐẠT" in text or "không đạt" in text, (variant, fmt)


def test_chain_record_names_no_person(env: Env) -> None:
    env.svc.generate("payments", ("regulator",), actor=EMAIL, fresh_verify=False)
    env.svc.generate("customer_service", ("regulator",), actor="system:job", fresh_verify=False)
    docs = []
    for lane in ("agent:payments", "agent:customer_service"):
        for p in env.adapters.tables.query("chain_payload", {"lane": lane}):
            d = json.loads(p["payload"]) if isinstance(p["payload"], str) else p["payload"]
            if "json_sha256" in d:
                docs.append(d)
    by = {d["agent_id"]: d["generated_by"] for d in docs}
    assert by["customer_service"] == "system:job"  # a product role stays readable
    assert by["payments"].startswith("act_") and EMAIL not in json.dumps(docs)
    # the append-only row holds the same ref (the console_action audit row keeps the person)
    assert env.svc.latest("payments", "regulator")["generated_by"] == by["payments"]


def test_live_and_lang_cannot_skip_the_text_check(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label that would print a contact detail is refused on the preview path too."""
    real = render.plain_text

    def leaky(report: dict[str, Any], lang: str) -> str:
        return real(report, lang) + ("\nmail " + EMAIL2 if lang == "vi" else "")

    monkeypatch.setattr(render, "plain_text", leaky)
    for variant in ("regulator", "customer"):
        for lang in ("en", "vi"):
            for fmt in ("json", "html"):
                with pytest.raises(TransparencyError, match="allow-list leak"):
                    env.svc.read("payments", variant, fmt, lang, live=True)
    env.svc.read("payments", "internal", "html", "en", live=True)  # internal: no outer check


def test_live_read_writes_nothing(env: Env) -> None:
    before = (
        len(env.svc.rows("payments")),
        len(env.adapters.tables.query("chain_entry", {"lane": "agent:payments"})),
    )
    for variant in ("regulator", "customer", "internal"):
        env.svc.read("payments", variant, "html", "vi", live=True)
        env.svc.read("payments", variant, "json", "en", live=True)
    after = (
        len(env.svc.rows("payments")),
        len(env.adapters.tables.query("chain_entry", {"lane": "agent:payments"})),
    )
    assert before == after
    assert not Path(env.settings.transparency_dir).exists()


# --------------------------------------------------------------------------- allow-list review


def _covered(path: str) -> bool:
    return path in allowlist.REVIEWED or any(
        r.startswith(path + ".") or r.startswith(path + "[]") for r in allowlist.REVIEWED
    )


def test_every_field_the_builder_makes_was_reviewed(env: Env) -> None:
    env.add_case("payments", "x")
    env.add_eval("payments", "pii_canary")
    paths: set[str] = set()
    for agent in AGENT_IDS:
        paths |= allowlist.field_paths(env.svc.builder.build_full(agent)["sections"])
    missing = sorted(p for p in paths if not _covered(p))
    assert missing == [], (
        "new report fields: add them to allowlist.REVIEWED and decide per variant who sees them"
    )


def test_a_new_field_without_review_fails(env: Env) -> None:
    """The regulator spec copies some sections whole (``True``): a new field there would go out
    without anybody deciding. The review list catches it."""
    from supervisor.transparency.builder import c_inventory

    def more(c: Any) -> dict[str, Any]:
        sec = c_inventory(c)
        return ok({**sec["data"], "operator_note": "new"})

    env.svc.builder.register("inventory", more)
    paths = allowlist.field_paths(env.svc.builder.build_full("payments")["sections"])
    assert [p for p in paths if not _covered(p)] == ["inventory.operator_note"]
    reg = env.svc.preview("payments", "regulator")
    assert "operator_note" in reg["sections"]["inventory"]["data"]  # why the gate is needed


def test_outer_variants_scrub_raw_fields_but_leave_clean_text_alone(env: Env) -> None:
    for agent in AGENT_IDS:
        for variant in ("regulator", "customer"):
            report, _ = env.svc.builder.build_pair(agent, variant)
            full = allowlist.project_sections(
                env.svc.builder.build_full(agent)["sections"], variant
            )
            for sid, sec in full.items():
                assert report["sections"][sid]["data"] == sec["data"], (agent, variant, sid)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mail a.b@bank.example.vn", "email"),
        ("CCCD 079203001234", "digits"),
        ("so 079 203 001 234", "digits"),
        ("acct 1903 1234 5678 90", "digits"),
        ("goi 0912 345 678", "digits"),
        ("goi 091-234-5678", "phone"),
    ],
)
def test_guard_refuses_contact_and_account_data(text: str, kind: str) -> None:
    for variant in ("regulator", "customer"):
        assert kind in allowlist.text_leaks(text, variant, {}), (text, variant)
    assert allowlist.text_leaks(text, "internal", {}) == []
    assert allowlist.REMOVED in allowlist.scrub_text(text)


@pytest.mark.parametrize(
    "text",
    ["2026-10-20T21:57:38.973474Z", "VN-QD33-2026-PL4.1-01", "x.py:123", "deadbeef" * 8, "9035"],
)
def test_guard_leaves_dates_ids_and_hashes(text: str) -> None:
    assert allowlist.scrub_text(text) == text
    assert "digits" not in allowlist.text_leaks(text, "regulator", {})
