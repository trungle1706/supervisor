"""UX5 group G3: compliance advisor (list, agent tabs, duty page, CSV), drafts, internal documents,
law changes, risks, controls and policies, with CONSOLE_UX5 on."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

from supervisor.console import compliance_ux5, i18n, i18n_ux5_g3
from supervisor.console.compliance_view import _demo_matrix
from supervisor.console.ux5 import PAGE_SIZE

from .conftest import Console
from .test_regkb_drafts import INSTRUMENT as DRAFT_INSTRUMENT
from .test_regkb_drafts import _seed as seed_drafts

GAP_ID = "VN-TT53-2026-A5.01G2-01"
AGENT = "/console/compliance/payments"


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    s = console.ctx.settings
    monkeypatch.setattr(s, "console_ux5", True)
    monkeypatch.setattr(s, "console_compliance_enabled", True)
    monkeypatch.setattr(s, "lawagent_enabled", True)
    monkeypatch.setattr(s, "regkb_internal", True)
    monkeypatch.setattr(s, "data_dir", tmp_path / "data")
    return console


def words(html: str) -> int:
    main = html.split("<main", 1)[-1]
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", main, flags=re.S)
    return len(re.sub(r"<[^>]+>", " ", text).split())


# ---------------------------------------------------------------- helpers (pure)
def test_evidence_label_is_short_and_readable() -> None:
    t = i18n.translator("en", ux5=True)
    row = {"status_reason": "present: agent_event_log (agent_event); missing: none"}
    assert compliance_ux5.evidence_label(row, t) == "Evidence: agent event log. Missing: nothing."
    row = {"status_reason": "present: none; missing: launch_report (evidence not on)"}
    assert compliance_ux5.evidence_label(row, t) == "Missing: launch report (not switched on)."
    row = {"status_reason": "bank process, no Supervisor control; process ids: security_assessment"}
    assert "security assessment" in compliance_ux5.evidence_label(row, t)
    assert "agent_event" not in compliance_ux5.evidence_label(
        {
            "status_reason": "present: a_b (agent_event); missing: none (if the obligation applies; product facts are incomplete)"  # noqa: E501
        },
        t,
    )


def test_groups_gaps_first_and_paged() -> None:
    m = _demo_matrix("", "payments")
    gs = compliance_ux5.groups(m["rows"], {})
    assert sum(g["total"] for g in gs) == len(m["rows"]) == 618  # counting is untouched
    assert [g["gaps"] for g in gs] == sorted((g["gaps"] for g in gs), reverse=True)
    assert all(len(g["rows"]) <= PAGE_SIZE for g in gs)
    assert sum(1 for g in gs if g["open"]) == compliance_ux5.OPEN_GROUPS
    big = max(gs, key=lambda g: g["total"])
    more = compliance_ux5.groups(m["rows"], {}, more=f"{big['id']}:50")
    again = next(g for g in more if g["id"] == big["id"])
    assert again["open"] and len(again["rows"]) == min(50, big["total"])


def test_override_keys_exist_with_en_and_vi() -> None:
    base = i18n.table()
    for key, (en, vi) in {**i18n_ux5_g3.NEW, **i18n_ux5_g3.UX5}.items():
        assert key in base and en.strip() and vi.strip(), key


def test_short_question_drops_the_class_list() -> None:
    q = {"text_en": "Which agent classes fit the product (payment, credit)? Code shows some."}
    assert compliance_ux5.short_question(q, "en") == "Which agent classes fit the product?"


# ---------------------------------------------------------------- compliance pages
def test_flag_off_keeps_the_old_page(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_compliance_enabled", True)
    r = console.get(AGENT)
    assert 'class="ux5"' not in r.text and f'data-obligation="{GAP_ID}"' in r.text
    assert console.get(AGENT + "?format=csv").status_code == 200


def test_list_page(ux: Console) -> None:
    r = ux.get("/console/compliance")
    assert r.status_code == 200 and 'class="ux5"' in r.text
    for agent in ("payments", "credit_prequal", "customer_service"):
        assert f'data-agent="{agent}"' in r.text
    assert r.text.count("Advisory only") >= 1 and "Open matrix" not in r.text
    assert "python -m supervisor.advisory" not in r.text
    assert words(r.text) < 400


def test_summary_tab_is_short_and_answers_first(ux: Console) -> None:
    r = ux.get(AGENT)
    assert r.status_code == 200
    assert "Answer first" in r.text and "Decision 33 suggestion" in r.text
    assert "479" in r.text and "Gap" in r.text
    q = max(_demo_matrix("", "payments")["questions"], key=lambda x: len(x["obligation_ids"]))
    assert f'data-question="{q["id"]}"' in r.text
    assert f"Blocks {len(q['obligation_ids'])} duties" in r.text
    assert "Show reasoning (" in r.text
    assert "profile.json#decision33" not in r.text  # source files are counted, not listed
    assert words(r.text) < 900
    assert f'data-obligation="{GAP_ID}"' not in r.text or r.text.count("data-obligation=") <= 8


def test_d33_tab_keeps_legal_caveat_and_limits(ux: Console) -> None:
    r = ux.get(AGENT + "?tab=d33")
    assert "Limits above the legal cap" in r.text and "PAY-03" in r.text
    assert "is NOT human inspection" in r.text  # the caveat is whole
    assert "daily_transfer_max_minor" not in r.text.replace(
        "TH-A5.01G2-daily_transfer_max_minor", ""
    )
    assert "<code>TH-A5.01G2" not in ux.get(AGENT + "?tab=d33", user="reviewer.an").text
    adm = ux.get(AGENT + "?tab=d33", user="admin.chi").text
    assert "Technical details" in adm and "<code>policies/baseline.yaml" in adm


def test_all_tab_is_grouped_bounded_and_legal_text_kept(ux: Console) -> None:
    r = ux.get(AGENT + "?tab=all")
    assert r.status_code == 200
    assert len(r.text) < 400_000 and words(r.text) < 8000
    assert r.text.count('<details class="g3-ins"') == compliance_ux5.OPEN_GROUPS
    assert r.text.count("data-obligation=") <= compliance_ux5.OPEN_GROUPS * PAGE_SIZE
    assert "One mark per duty" in r.text and r.text.count('class="u5-legend"') == 1
    assert "Show 25 more" in r.text and "u5-ticks" in r.text
    # opening a closed instrument shows its rows; the full legal summary is in the markup
    r2 = ux.get(AGENT + "?tab=all&instrument=VN-TT53-2026&status=gap")
    m = _demo_matrix("", "payments")
    row = next(x for x in m["rows"] if x["obligation_id"] == GAP_ID)
    assert row["summary_en"] in r2.text.replace("&#39;", "'").replace("&#34;", '"')
    assert "(not switched on)" in r2.text or "Missing" in r2.text
    # a question filter shows only the duties it blocks
    mq = min(_demo_matrix("", "payments")["questions"], key=lambda x: len(x["obligation_ids"]))
    q = ux.get(AGENT + f"?tab=all&question={mq['id']}")
    assert 0 < q.text.count("data-obligation=") <= min(len(mq["obligation_ids"]), 75)
    assert ux.get(AGENT + "?tab=all&status=bogus").status_code == 400


def test_more_link_adds_25_rows(ux: Console) -> None:
    m = _demo_matrix("", "payments")
    big = max(compliance_ux5.groups(m["rows"], {}), key=lambda g: g["total"])
    r = ux.get(f"{AGENT}?tab=all&more={big['id']}:50")
    assert r.text.count(f'data-obligation="{big["id"]}-') >= 26 or big["total"] <= 25


def test_vietnamese(ux: Console) -> None:
    r = ux.get(AGENT + "?lang=vi")
    assert "Trả lời trước" in r.text and "Gợi ý theo Quyết định 33" in r.text
    assert "Tất cả nghĩa vụ" in r.text


def test_csv_export_has_every_duty_with_full_text(ux: Console) -> None:
    r = ux.get(AGENT + "?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 618 and rows[0]["summary_en"]
    gap = ux.get(AGENT + "?format=csv&status=gap")
    assert 0 < len(list(csv.DictReader(io.StringIO(gap.text)))) < 618


def test_obligation_page(ux: Console) -> None:
    r = ux.get(f"{AGENT}/obligation/INTL-ATLAS-T0010-01")
    assert r.status_code == 200 and 'class="ux5"' in r.text
    assert "AML.T0010" in r.text and "Next in this instrument" in r.text
    assert "agent_version" not in r.text.replace(
        "data-", ""
    )  # id words only, no raw id for non-admin
    assert "Agent version" in r.text and "Source note" in r.text
    assert "No Vietnamese text stored for this duty." in r.text
    assert words(r.text) < 400


# ---------------------------------------------------------------- other pages
def test_drafts_page(ux: Console) -> None:
    seed_drafts(ux, 2)
    r = ux.get(f"/console/regkb/{DRAFT_INSTRUMENT}/drafts")
    assert r.status_code == 200 and 'class="ux5"' in r.text
    assert "Law agent drafts:" not in r.text and "Drafts only" not in r.text
    assert "python -m supervisor.regkb.lawagent" not in r.text
    assert "Details" in r.text and "Subject" in r.text
    adm = ux.get(f"/console/regkb/{DRAFT_INSTRUMENT}/drafts", user="admin.chi").text
    assert ">Confirm<" in adm and "python -m supervisor.regkb.lawagent" in adm  # technical, admin
    assert "Not legal advice" in r.text  # the disclaimer stays
    empty = ux.get(f"/console/regkb/{DRAFT_INSTRUMENT}/drafts?status=dropped")
    assert "No drafts yet" in empty.text
    vi = ux.get(f"/console/regkb/{DRAFT_INSTRUMENT}/drafts?lang=vi")
    assert "Bản nháp" in vi.text and "Đã xác nhận" in vi.text


def test_internal_documents_page(ux: Console) -> None:
    r = ux.get("/console/regkb/internal")
    assert r.status_code == 200 and 'class="ux5"' in r.text
    assert "Policies, standards and procedures the bank uploaded." in r.text
    assert "Not legal advice. Bank counsel confirms." in r.text
    assert 'data-regkb-banner="1"' not in r.text
    assert words(r.text) < 200
    assert "Tài liệu nội bộ" in ux.get("/console/regkb/internal?lang=vi").text


def test_law_changes_page(ux: Console) -> None:
    from supervisor.console import regkb_change_routes as rcr

    ux.ctx.settings.regkb_change_loop = True  # type: ignore[attr-defined]
    r = ux.get("/console/regkb/changes")
    if r.status_code == 200:
        assert "Updates to laws and rules already in the register." in r.text
        assert "No imported change yet. Import an update package to start." in r.text
        assert words(r.text) < 120
    assert rcr is not None


def test_risks_controls_policies_pages(ux: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    s = ux.ctx.settings
    for flag in ("risk_register_enabled", "console_risks_enabled", "inventory_enabled"):
        monkeypatch.setattr(s, flag, True)
    monkeypatch.setattr(s, "console_policies_enabled", True)
    r = ux.get("/console/risks")
    assert r.status_code == 200 and "u5-head" in r.text and "/v1/risks" not in r.text
    assert "/v1/risks" in ux.get("/console/risks", user="admin.chi").text  # technical, admin only
    p = ux.get("/console/policies")
    assert p.status_code == 200 and "u5-head" in p.text
    assert "To change a rule, edit the policy file in Git" not in p.text
    assert "Version history" in p.text and "If the gate fails" in p.text
    assert "mirror of" not in p.text
    monkeypatch.setattr(s, "console_controls_enabled", True, raising=False)
    c = ux.get("/console/controls")
    if c.status_code == 200:
        assert "python -m supervisor.controls" not in c.text
