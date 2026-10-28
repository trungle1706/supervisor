"""WP-L4: the regulator pack (REGULATOR_PACK).

HTML and JSON contents, no floats, no personal data in a synthetic system with Vietnamese names
planted in free-text fields, the signature checked offline by the existing verifier (which still
accepts a chain export), routes and roles, and the CLI."""

from __future__ import annotations

import html as htmllib
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.core.canonical import format_ts
from supervisor.evidence import verify as vf
from supervisor.governance import duty_evidence as de
from supervisor.governance import regulator_pack as rp

from .conftest import Console
from .l4_support import (
    AGENT,
    BANNER,
    CREATOR,
    NOW,
    OB_CHAIN,
    OB_GATE2,
    OB_JUDGE,
    OB_MASK,
    OB_RULE,
    env,
    gate_events,
    kb,
    put_row,
    system_with_agent,
    verdicts,
)
from .test_l3_duties import _audit
from .test_l4_evidence import l4  # noqa: F401  (fixture)

# Vietnamese personal names and ids planted in free text; none may reach the pack
NAMES = ("Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Cường", "Phạm Minh Đức")
ASCII_NAMES = ("Nguyen Van An", "Tran Thi Binh", "Le Hoang Cuong", "Pham Minh Duc")
IDS = (
    "nguyen.van.an@example.invalid",
    "tran.thi.binh@example.invalid",
    "le.hoang.cuong@example.invalid",
)


def _no_float(text: str) -> Any:
    def boom(v: str) -> Any:
        raise AssertionError(f"float in the pack: {v}")

    return json.loads(text, parse_float=boom, parse_constant=boom)


def _planted(c: Console) -> str:
    """A system whose free-text fields, team and row notes hold names and ids."""
    sid = system_with_agent(
        c,
        owner_user=IDS[0],
        business_owner=IDS[2],
        purpose=f"Hỗ trợ khách hàng {NAMES[0]} và {NAMES[1]} về chuyển khoản trong nước.",
    )
    svc = c.ctx.systems
    svc.update_fields(
        sid, {"risk_justification": f"Do {NAMES[2]} đề xuất; {NAMES[3]} duyệt."}, IDS[0]
    )
    svc.add_member(sid, IDS[1], "reviewer", IDS[0])
    gate_events(c, 3)
    verdicts(c, 2)
    note = f"{BANNER} closed by {IDS[1]} on 2026-10-20 with CTL-X; evidence: Hồ sơ của {NAMES[3]}"
    put_row(c, sid, OB_GATE2)  # works
    put_row(c, sid, OB_CHAIN)  # no evidence
    put_row(c, sid, OB_RULE, coverage="partial", status="closed", control="CTL-X", note=note)
    put_row(
        c,
        sid,
        OB_JUDGE,
        coverage="none",
        status="waived",
        note=f"{BANNER} waived by {IDS[0]}: {NAMES[2]}",
    )
    put_row(c, sid, OB_MASK, coverage="unknown", applies="needs_answer")
    return sid


def _pack(c: Console, sid: str) -> dict[str, Any]:
    return rp.generate_for_console(c.ctx, sid)


def _find(pack: dict[str, Any], oid: str) -> dict[str, Any]:
    for inst in pack["instruments"]:
        for d in inst["duties"]:
            if d["obligation_id"] == oid:
                return d
    raise AssertionError(oid)


# ------------------------------------------------------------------ contents


def test_json_header_summary_and_sections(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    h, s = pack["header"], pack["summary"]
    assert pack["format"] == "supervisor.regulator_pack" and pack["pack_version"] == 1
    assert pack["banner"] == BANNER
    assert h["system_id"] == sid and h["name"] == "Payments - Assistant"
    assert h["lifecycle_stage"] and h["autonomy_level"] == "l1_assistive"
    assert h["decision33_class"] in ("unclassified", "high_risk", "not_high_risk")
    assert h["regkb_version"] == kb(l4).version and len(h["regkb_version"]) == 64
    assert h["generated_at"].endswith("Z") and h["window"]["days"] == 30
    assert {o["role"] for o in h["owners"]} >= {"system_owner", "reviewer"}
    assert all(set(o) == {"role", "n"} for o in h["owners"])  # role names only, no person
    assert s["rows"] == 5
    assert s["by_status"] == {"open": 3, "closed": 1, "waived": 1}
    assert s["by_coverage"] == {"full": 2, "partial": 1, "none": 1, "unknown": 1}
    assert s["by_applies"] == {"yes": 4, "needs_answer": 1, "no": 0}
    assert s["gap_closure_pct"] == 33  # 1 closed of 3 applying rows that are open or closed
    assert s["coverage_by_status"]["full"] == {"open": 2, "closed": 0, "waived": 0}
    instruments = {i["instrument_id"]: i for i in pack["instruments"]}
    assert instruments  # one section per instrument
    assert sum(len(i["duties"]) for i in pack["instruments"]) == 5
    for inst in instruments.values():
        assert inst["number"] and inst["duties"]


def test_duty_entry_fields(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    d = _find(pack, OB_GATE2)
    ob = kb(l4).get(OB_GATE2)
    assert d["article"] == ob.article_ref and d["duty"] == ob.summary_en
    assert d["text_vi"] == (ob.text_vi or "")  # verbatim quote from RegKB
    assert (d["applies"], d["coverage"], d["status"]) == ("yes", "full", "open")
    assert d["works"] == "works" and d["closing_control"] == ""
    assert {e["control_id"]: e["count"] for e in d["evidence"]} == {
        "approved_tools": 3,
        "single_limit": 3,
    }
    assert d["pointers"]["status_id"].startswith("os_") and d["pointers"]["gap_task_id"] == ""
    assert d["confirmed_by"] == rp.DEFAULT_CONFIRMED == "RegKB data 2026-10-15"
    assert _find(pack, OB_CHAIN)["works"] == "no_evidence"
    closed = _find(pack, OB_RULE)
    assert closed["status"] == "closed" and closed["closing_control"] == "CTL-X"
    assert closed["closed_by"] == "person" and len(closed["note_sha256"]) == 16
    assert closed["pointers"]["gap_task_id"].startswith("tsk_") or closed["pointers"]["gap_task_id"]
    assert _find(pack, OB_JUDGE)["closed_by"] == "waived"
    judge = _find(pack, OB_JUDGE)["evidence"][0]
    assert judge["advisory"] is True and judge["works"] is False


def test_confirmed_by_comes_from_the_law_agent_draft(l4: Console) -> None:  # noqa: F811
    sid = system_with_agent(l4)
    ob = next(o for o in kb(l4).obligations.values() if o.text_vi and o.id == OB_MASK)
    put_row(l4, sid, OB_MASK, coverage="partial")
    l4.ctx.state.insert(
        "regkb_draft",
        {
            "draft_id": "dr_l4_1",
            "instrument_id": ob.instrument_id,
            "article": "Điều 1",
            "duty_id": "D-X",
            "subject": "bank",
            "trigger": "always",
            "evidence_asked": "log",
            "text_vi": ob.text_vi,
            "summary_en": "x",
            "source": "model",
            "status": "confirmed",
            "confirmed_by": IDS[0],
            "confirmed_at": NOW,
            "run_id": "run_1",
            "created_at": NOW,
        },
    )
    d = _find(_pack(l4, sid), OB_MASK)
    assert d["confirmed_by"].startswith("act_") and d["confirmed_on"] == "2026-10-28"
    assert IDS[0] not in json.dumps(d)  # a keyed reference, not the id


def test_no_floats_anywhere(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    text = rp.to_json_bytes(pack).decode("utf-8")
    _no_float(text)
    stack: list[Any] = [pack]
    while stack:
        v = stack.pop()
        assert not isinstance(v, float)
        if isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


def test_no_personal_data_in_json_or_html(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    blobs = [
        rp.to_json_bytes(pack).decode("utf-8"),
        json.dumps(pack, ensure_ascii=True),
        rp.render_html(pack),
    ]
    for blob in blobs:
        for needle in (*NAMES, *ASCII_NAMES, *IDS, "Hồ sơ của", "Hỗ trợ khách hàng"):
            assert needle not in blob, needle
        assert "owner_user" not in blob and "user_id" not in blob  # role names are fine
    assert "Payments - Assistant" in blobs[0]  # the system name is part of the header


def test_html_has_the_banner_and_every_duty(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    page = rp.render_html(pack)
    assert (
        page.count(BANNER) >= 2 and 'data-banner="top"' in page and 'data-banner="bottom"' in page
    )
    assert "<script" not in page.lower() and "http://" not in page and "https://" not in page
    for oid in (OB_GATE2, OB_CHAIN, OB_RULE, OB_JUDGE, OB_MASK):
        assert f'data-obligation="{oid}"' in page
    quote = kb(l4).get(OB_GATE2).text_vi
    if quote:
        assert htmllib.escape(quote) in page
    assert "Gap closure score" in page and "33%" in page
    assert pack["content_sha256"] in page and "Payments - Assistant" in page
    assert "approved_tools" in page and "RegKB data 2026-10-15" in page


def test_pack_of_an_empty_system(l4: Console) -> None:  # noqa: F811
    sid = system_with_agent(l4)
    pack = _pack(l4, sid)
    assert pack["instruments"] == [] and pack["summary"]["rows"] == 0
    assert pack["summary"]["gap_closure_pct"] is None
    assert "Gap closure score" in rp.render_html(pack)


def test_evidence_is_the_same_as_the_tab_and_the_closed_row(l4: Console) -> None:  # noqa: F811
    sid = system_with_agent(l4)
    gate_events(l4, 2)
    put_row(l4, sid, OB_MASK)
    de.refresh(env(l4), l4.ctx.systems.get(sid))
    d = _find(_pack(l4, sid), OB_MASK)
    assert d["status"] == "closed" and d["closed_by"] == "evidence"
    assert d["closing_control"] == "pii_masking"
    assert _pack(l4, sid)["summary"]["closed_by_evidence"] == 1


# ------------------------------------------------------------------ the signature


def _write(tmp_path: Path, pack: dict[str, Any]) -> Path:
    p = tmp_path / "regulator-pack.json"
    p.write_bytes(rp.to_json_bytes(pack))
    return p


def test_signature_verifies_offline(l4: Console, tmp_path: Path, capsys: Any) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    assert pack["signature"]["algorithm"] == "ed25519"
    assert pack["content_sha256"] == rp.content_hash(pack)
    path = _write(tmp_path, pack)
    report = vf.verify_signed_doc(path)
    assert report.failures == 0 and report.lines[-1] == "RESULT: OK", report.lines
    assert vf.main([str(path)]) == 0
    assert "[OK]" in capsys.readouterr().out
    # a copy of the verifier needs only the file: pin the key from the pack
    pem = tmp_path / "pub.pem"
    pem.write_text(pack["signature"]["public_key"], encoding="ascii")
    assert vf.main([str(path), "--pubkey", str(pem)]) == 0


def test_a_changed_pack_does_not_verify(l4: Console, tmp_path: Path, capsys: Any) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    pack["summary"]["gap_closure_pct"] = 100
    path = _write(tmp_path, pack)
    assert vf.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] content" in out and "RESULT: FAIL" in out
    # content fixed up but the signature kept: the signature fails
    pack["content_sha256"] = rp.content_hash(pack)
    assert vf.main([str(_write(tmp_path, pack))]) == 1
    assert "[FAIL] signature" in capsys.readouterr().out


def test_a_foreign_key_is_refused_when_pinned(l4: Console, tmp_path: Path) -> None:  # noqa: F811
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from supervisor.evidence.signer import public_key_pem

    sid = _planted(l4)
    pack = _pack(l4, sid)
    other = tmp_path / "other.pem"
    other.write_text(public_key_pem(Ed25519PrivateKey.generate().public_key()), encoding="ascii")
    report = vf.verify_signed_doc(_write(tmp_path, pack), pubkey=other)
    assert report.failures == 1 and "not the pinned key" in "\n".join(report.lines)


def test_verifier_reads_a_float_or_a_foreign_file_as_unreadable(
    tmp_path: Path, capsys: Any
) -> None:
    bad = tmp_path / "x.json"
    bad.write_text('{"format": "supervisor.regulator_pack", "n": 1.5}', encoding="utf-8")
    assert vf.main([str(bad)]) == 2
    other = tmp_path / "y.json"
    other.write_text('{"format": "something-else"}', encoding="utf-8")
    assert vf.main([str(other)]) == 2
    assert vf.main([str(tmp_path / "missing")]) == 2  # a path that is neither file nor dir
    assert "[FAIL]" in capsys.readouterr().out


def test_the_chain_records_the_pack_hash(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    pack = _pack(l4, sid)
    chain = l4.ctx.runtime.chain
    chain.commit_root(force=True)
    rows = [r for r in l4.ctx.tables.query("chain_entry") if r["record_type"] == "regulator_pack"]
    assert rows and rows[-1]["record_ref"].endswith(pack["content_sha256"][:16])
    payloads = [
        json.loads(p["payload"])
        for p in l4.ctx.tables.query("chain_payload")
        if p["payload_hash"] in {r["payload_hash"] for r in rows}
    ]
    assert payloads[-1]["content_sha256"] == pack["content_sha256"]
    assert payloads[-1]["rows"] == 5 and NAMES[0] not in json.dumps(payloads)


def test_old_chain_export_still_verifies(l4: Console, tmp_path: Path, capsys: Any) -> None:  # noqa: F811
    from supervisor.console import auditpack
    from supervisor.evidence.export import export_chain

    sid = _planted(l4)
    _pack(l4, sid)  # a regulator_pack record is on the chain now
    res = auditpack.verify_chain(l4.ctx)
    assert res["ok"] is True, res["lines"]
    l4.ctx.runtime.chain.commit_root(force=True)
    export_chain(l4.ctx.tables, tmp_path / "chain", created_at=l4.ctx.clock.now())
    assert vf.verify_export(tmp_path / "chain").failures == 0
    assert vf.main([str(tmp_path / "chain")]) == 0  # a directory is verified as before
    assert "RESULT: OK" in capsys.readouterr().out


def test_old_audit_pack_still_verifies(l4: Console) -> None:  # noqa: F811
    from supervisor.console import auditpack

    class _Actor:
        user_id, kind, auth_method = CREATOR, "user", "dev_header"

    sid = _planted(l4)
    _pack(l4, sid)
    built = auditpack.build_audit_pack(l4.ctx, _Actor())
    assert built.verify_ok is True, built.verify_lines


# ------------------------------------------------------------------ routes and roles


def _url(sid: str, ext: str) -> str:
    return f"/v1/systems/{sid}/regulator-pack.{ext}"


def test_json_route_returns_the_signed_pack(l4: Console, tmp_path: Path) -> None:  # noqa: F811
    sid = _planted(l4)
    r = l4.get(_url(sid, "json"), user="auditor.dung")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    pack = _no_float(r.text)
    assert pack["format"] == "supervisor.regulator_pack" and pack["header"]["system_id"] == sid
    path = tmp_path / "from-route.json"
    path.write_bytes(r.content)
    assert vf.verify_signed_doc(path).failures == 0
    for needle in (*NAMES, *IDS):
        assert needle not in r.text


def test_html_route_returns_the_page(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    r = l4.get(_url(sid, "html"), user="auditor.dung")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.text.count(BANNER) >= 2 and OB_GATE2 in r.text
    for needle in (*NAMES, *IDS):
        assert needle not in r.text


@pytest.mark.parametrize("user", ["auditor.dung", "reviewer.an", "admin.chi"])
def test_roles_that_see_every_system_can_read(l4: Console, user: str) -> None:  # noqa: F811
    sid = _planted(l4)
    for ext in ("json", "html"):
        assert l4.get(_url(sid, ext), user=user).status_code == 200, (user, ext)


def test_a_scoped_viewer_gets_404_for_a_system_outside_the_scope(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    for ext in ("json", "html"):  # viewer.hoa holds systems.view but sees only the own scope
        r = l4.get(_url(sid, ext), user="viewer.hoa")
        assert r.status_code == 404 and "regulator" not in r.text.lower()


def test_unknown_systems_are_404(l4: Console) -> None:  # noqa: F811
    _planted(l4)
    for ext in ("json", "html"):
        assert l4.get(_url("sys_unknown1", ext), user="auditor.dung").status_code == 404
        assert l4.get(_url("bad id!", ext), user="auditor.dung").status_code in (400, 404)


def test_flag_off_routes_are_400(l4: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    sid = _planted(l4)
    monkeypatch.setattr(l4.ctx.settings, "regulator_pack", False)
    for ext in ("json", "html"):
        r = l4.get(_url(sid, ext), user="auditor.dung")
        assert r.status_code == 400 and "regulator_pack_off" in r.text
    assert not [
        r for r in l4.ctx.tables.query("chain_entry") if r["record_type"] == "regulator_pack"
    ]


def test_buttons_on_the_tab_and_the_header(l4: Console) -> None:  # noqa: F811
    sid = _planted(l4)
    tab = l4.get(f"/console/systems/{sid}?tab=duties&lang=en&f=all", user="auditor.dung").text
    assert f'href="{_url(sid, "html")}"' in tab and f'href="{_url(sid, "json")}"' in tab
    head = l4.get(f"/console/systems/{sid}?lang=en", user="auditor.dung").text
    assert 'data-act="regulator-pack"' in head and _url(sid, "html") in head
    assert len(_audit(l4)) == 0  # reading a pack is not a mutating console action


# ------------------------------------------------------------------ the CLI


def test_cli_writes_the_pack_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.governance.systems import SystemService
    from supervisor.jobs import bootstrap_schema

    from .conftest import draft

    for key, val in (
        ("SQL_BACKEND", "sqlite"),
        ("DATA_DIR", str(tmp_path / "cli")),
        ("LLM_BASE_URL", ""),
        ("GOVERNANCE_ENABLED", "1"),
        ("CONSOLE_SYSTEMS_ENABLED", "1"),
        ("RISK_DUTIES", "1"),
    ):
        monkeypatch.setenv(key, val)
    settings = load_settings()
    adapters = build_adapters(settings)
    bootstrap_schema.run(settings, adapters)
    try:
        sid = str(SystemService.from_adapters(adapters).register(draft(), CREATOR)["system_id"])
        ob = kb_for(settings).get(OB_MASK)
        from supervisor.governance.register_v2 import duties as dut

        adapters.state.insert(
            "obligation_status",
            {
                "status_id": dut.status_id(sid, OB_MASK),
                "system_id": sid,
                "obligation_id": OB_MASK,
                "instrument_id": ob.instrument_id,
                "applies": "yes",
                "coverage": "partial",
                "status": "open",
                "owner_user": CREATOR,
                "due_date": None,
                "closing_control": None,
                "note": f"{BANNER} seeded",
                "created_at": NOW,
            },
        )
    finally:
        adapters.close()
    out = tmp_path / "pack"
    # flag off: a no-op
    assert rp.main(["--system", sid, "--out", str(out)]) == 0
    assert "[SKIP]" in capsys.readouterr().out and not out.exists()
    monkeypatch.setenv("REGULATOR_PACK", "1")
    assert rp.main(["--system", sid, "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert text.startswith("[OK] regulator_pack:") and text.isascii()
    assert sorted(p.name for p in out.iterdir()) == [
        "public_key.pem",
        "regulator-pack.html",
        "regulator-pack.json",
    ]
    pack = _no_float((out / "regulator-pack.json").read_text(encoding="utf-8"))
    assert pack["header"]["system_id"] == sid and pack["summary"]["rows"] == 1
    assert BANNER in (out / "regulator-pack.html").read_text(encoding="utf-8")
    assert vf.main([str(out / "regulator-pack.json"), "--pubkey", str(out / "public_key.pem")]) == 0
    # an unknown system is a clean failure
    assert rp.main(["--system", "sys_nope0000", "--out", str(tmp_path / "x")]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def kb_for(settings: Any) -> Any:
    from supervisor.console.compliance_view import kb_for as _kb

    return _kb(settings)


def test_time_format_helper_is_utc_z() -> None:
    assert format_ts(NOW).endswith("Z") and AGENT
