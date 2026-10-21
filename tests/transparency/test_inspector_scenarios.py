"""WP31 review: five scenarios written by the reviewer as an SBV inspector (not by the author).

Expected values were read by hand from the sources, not from the builder: the Decision 33 class
and the six PL4 obligation ids of the payments matrix (``regkb`` demo matrix, entries
"transactions" and "credit"), the owner team of the payments manifest, the default flags in
``config.py`` (five monitors off), a real offline verifier run on a chain row changed in SQLite
(no ``verify_fn`` fake), and the hashes the chain record carries against the served bytes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from supervisor.core.errors import NotFoundError
from supervisor.transparency import render
from supervisor.transparency.harness import Env
from supervisor.transparency.model import TransparencyError

PL4 = [
    "VN-QD33-2026-PL4.1-01",
    "VN-QD33-2026-PL4.1-02",
    "VN-QD33-2026-PL4.1-03",
    "VN-QD33-2026-PL4.2-01",
    "VN-QD33-2026-PL4.2-02",
    "VN-QD33-2026-PL4.2-03",
]


def _codes(report: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for i in report["sections"]["not_shown"]["data"]["items"]:
        out.setdefault(i["code"], []).append(i.get("ref"))
    return out


def _payloads(env: Env, agent: str) -> list[dict]:
    rows = env.adapters.tables.query("chain_payload", {"lane": f"agent:{agent}"})
    docs = [
        json.loads(p["payload"]) if isinstance(p["payload"], str) else p["payload"] for p in rows
    ]
    return sorted(
        (d for d in docs if "json_sha256" in d), key=lambda d: (d["variant"], d["version"])
    )


def test_s1_class_and_every_cited_obligation_traceable(env: Env) -> None:
    """Inspector: 'which class, under which obligations, and do they exist in your matrix?'"""
    r = env.svc.preview("payments", "regulator")
    cls = r["sections"]["classification"]["data"]
    comp = r["sections"]["compliance"]["data"]
    ident = r["sections"]["identity"]["data"]
    assert cls["decision33_class"] == "high_risk"
    assert cls["d33_obligation_ids"] == PL4
    in_matrix = {x["obligation_id"] for x in comp["d33_rows"]}
    assert set(PL4) <= in_matrix and comp["d33_ids_missing"] == []
    assert ident["owner_team"] == "Payments Ops" and ident["risk_tier"] == "critical"
    assert "owner_user" not in ident and "business_owner" not in ident  # persons left out
    en = render.plain_text(r, "en")
    for oid in PL4:
        assert oid in en  # cited in the words the inspector reads, not only in the JSON


def test_s2_every_source_that_is_off_or_mock_is_stated(env: Env) -> None:
    """Inspector: 'what are you not showing me?' with the register and inventory off."""
    env.settings.risk_register_enabled = False
    env.settings.inventory_enabled = False
    r = env.svc.preview("credit_prequal", "regulator")
    c = _codes(r)
    # CONTROLS_ENABLED: WP30 is merged (integration wave 2) and its flag is off here
    assert set(c["section_flag_off"]) == {
        "RISK_REGISTER_ENABLED",
        "INVENTORY_ENABLED",
        "CONTROLS_ENABLED",
    }
    assert c["monitors_off"] == ["drift,fairness,metrics,multiagent,quality"]
    assert "mock_judge" in c and "judge_not_validated" in c
    assert "chain_not_verified" in c  # nobody ran the offline check for this build
    assert "advisory_only" in c and "illustrative" in c
    cust = _codes(env.svc.preview("credit_prequal", "customer"))
    assert "monitors_off" in cust and "chain_not_verified" in cust
    vi = render.plain_text(env.svc.preview("credit_prequal", "customer"), "vi")
    assert "Một số giám sát đang tắt" in vi


def test_s3_a_changed_chain_row_is_reported_by_the_real_verifier(env: Env) -> None:
    """Inspector: 'show me the check fails when a record was changed after the fact.'"""
    first = env.svc.generate("payments", ("regulator",), actor="system:test")[0]
    assert first["verify_state"] == "ok"
    db = sqlite3.connect(str(env.settings.sqlite_path))
    try:
        row = db.execute(
            "SELECT rowid, payload FROM chain_payload WHERE lane='agent:payments' "
            "ORDER BY seq LIMIT 1"
        ).fetchone()
        doc = json.loads(row[1])
        doc["ts"] = "2020-01-01T00:00:00Z"  # someone with file access edits history
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='chain_payload'"
        ).fetchall():
            db.execute(f'DROP TRIGGER "{name}"')  # the append-only guard is a trigger
        db.execute("UPDATE chain_payload SET payload=? WHERE rowid=?", (json.dumps(doc), row[0]))
        db.commit()
    finally:
        db.close()
    out = {
        r["variant"]: r
        for r in env.svc.generate("payments", actor="system:test", fresh_verify=True)
    }
    assert {r["verify_state"] for r in out.values()} == {"failed"}
    assert out["regulator"]["version"] == 2 and "evidence" in out["regulator"]["diff"]["changed"]
    for variant in ("regulator", "customer", "internal"):
        rep, _ = env.svc.report("payments", variant)
        assert "chain_verify_failed" in _codes(rep), variant
    cust, _ = env.svc.report("payments", "customer")
    assert "did not pass" in render.plain_text(cust, "en")
    assert "KHÔNG ĐẠT" in render.plain_text(env.svc.report("payments", "regulator")[0], "vi")


def test_s4_retired_agent_with_no_inventory_node_and_no_matrix(env: Env) -> None:
    """Inspector: 'an agent you switched off: what do you still know about it?'"""
    env.add_agent("old_bot", status="retired", gate_state="QUARANTINED")
    r = env.svc.preview("old_bot", "regulator")
    s, c = r["sections"], _codes(r)
    assert s["identity"]["available"] and s["identity"]["data"]["status"] == "retired"
    assert (s["inventory"]["reason"], s["compliance"]["reason"]) == (
        "not_in_inventory",
        "no_matrix",
    )
    assert s["classification"]["reason"] == "no_data"
    for code in ("agent_retired", "section_not_in_inventory", "section_no_matrix"):
        assert code in c, code
    assert "classification" in c["section_no_data"]
    assert "old_bot" not in env.svc.facts.running_agents()  # the daily job leaves it alone


def test_s5_the_chain_hashes_match_the_served_files_and_tamper_is_refused(env: Env) -> None:
    """Inspector: 'prove that the file you hand me is the one you signed.'"""
    env.svc.generate("payments", ("regulator",), actor="reviewer.an", fresh_verify=False)
    env.add_case("payments", "A new incident")
    env.svc.generate("payments", ("regulator",), actor="reviewer.an", fresh_verify=False)
    v1, v2 = _payloads(env, "payments")
    assert (v1["version"], v2["version"], v2["prev_version"]) == (1, 2, 1)
    assert v2["diff_changed"] == ["cases"] and v2["diff_changed_n"] == 1
    for lang in ("vi", "en"):
        html, _, info = env.svc.read("payments", "regulator", "html", lang)
        assert info["version"] == 2
        assert hashlib.sha256(html).hexdigest() == v2[f"html_sha256_{lang}"]
        if f"pdf_sha256_{lang}" in v2:
            pdf, _, _ = env.svc.read("payments", "regulator", "pdf", lang)
            assert hashlib.sha256(pdf).hexdigest() == v2[f"pdf_sha256_{lang}"]
    js, _, _ = env.svc.read("payments", "regulator", "json")
    assert hashlib.sha256(js).hexdigest() == v2["json_sha256"]
    path = env.svc._dir("payments", "regulator", 2) / "report.en.html"
    path.write_bytes(path.read_bytes().replace(b"</body>", b"<p>edited</p></body>"))
    with pytest.raises(TransparencyError, match="does not match"):
        env.svc.read("payments", "regulator", "html", "en")
    assert len({r["version"] for r in env.svc.rows("payments", "regulator")}) == 2  # v1 kept
    (env.svc._dir("payments", "regulator", 2) / "report.json").unlink()
    with pytest.raises(NotFoundError):
        env.svc.read("payments", "regulator", "json")
