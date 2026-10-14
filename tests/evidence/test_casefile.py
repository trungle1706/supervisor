from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import build_adapters
from supervisor.config import load_settings
from supervisor.core.models import Case, CaseEvent, ChainEntry, Signoff, Verdict
from supervisor.evidence.casefile import (
    CaseFile,
    CaseFileError,
    build_case_file,
    case_chain_refs,
    load_case_inputs,
    parse_json,
    record_case_file,
    render_html,
    render_json,
    render_pdf,
    write_case_file,
)
from supervisor.jobs.bootstrap_schema import run as bootstrap_run

render_pdf_mod = importlib.import_module("supervisor.evidence.casefile.render_pdf")
T0 = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
D33 = "Quyết định 33: hệ thống AI rủi ro cao (văn bản tổng hợp)"
REASON = "Đã xác minh với khách hàng Nguyễn Văn A, tài khoản ****1234 <ok>"
H = "a" * 64


def make_case(**kw: Any) -> Case:
    base: dict[str, Any] = {
        "case_id": "C-1",
        "agent_id": "agent-x",
        "severity": "high",
        "status": "open",
        "opened_at": T0 + timedelta(hours=2),
        "summary": "Chuyển tiền bất thường tài khoản ****1234",
        "regulation_refs": ["TT-09/2020 Điều 5"],
    }
    base.update(kw)
    return Case(**base)


def make_verdict(vid: str, ts: datetime, tier: int = 0, **kw: Any) -> Verdict:
    base: dict[str, Any] = {
        "verdict_id": vid,
        "ts": ts,
        "agent_id": "agent-x",
        "tier": tier,
        "checker_id": "rule-engine" if tier == 0 else "judge-1",
        "advisory": tier > 0,
        "label": "violation",
        "action": "block" if tier == 0 else "alert",
        "rule_id": "R-LIMIT" if tier == 0 else None,
    }
    base.update(kw)
    return Verdict(**base)


def make_chain(seq: int, ref: str, lane: str = "agent:agent-x") -> ChainEntry:
    return ChainEntry(
        lane=lane,
        seq=seq,
        ts=T0,
        record_type="verdict",
        record_ref=ref,
        payload_hash=H,
        prev_hash="b" * 64,
        entry_hash=f"{seq:064x}",
        writer="w",
        env="test",
    )


def make_signoff() -> Signoff:
    return Signoff(
        signoff_id="S-1",
        case_id="C-1",
        reviewer_id="reviewer-b",
        decision="approve",
        reason=REASON,
        ts=T0 + timedelta(hours=5),
        auth_method="dev_header",
    )


def build(**kw: Any) -> CaseFile:
    case = kw.pop("case", make_case())
    verdicts = kw.pop(
        "verdicts",
        [
            make_verdict("V-2", T0 + timedelta(hours=3)),
            make_verdict("V-1", T0, tier=0),
            make_verdict(
                "V-3",
                T0 + timedelta(hours=1),
                tier=1,
                score=0.12345,
                is_mock=True,
                model_id="mock-judge",
                rationale_masked="Nghi ngờ gian lận",
            ),
        ],
    )
    events = kw.pop(
        "events",
        [
            CaseEvent(
                case_id="C-1",
                seq=1,
                ts=T0 + timedelta(hours=2),
                actor="system",
                actor_kind="system",
                action="open",
                comment_masked="mở hồ sơ",
            )
        ],
    )
    signoffs = kw.pop("signoffs", [make_signoff()])
    chain = kw.pop("chain", [make_chain(3, "verdict:V-1"), make_chain(7, "signoff:S-1")])
    return build_case_file(
        case,
        events,
        verdicts,
        signoffs,
        chain,
        decision33_text=kw.pop("d33", D33),
        mask_version="mask/1",
        generated_at=kw.pop("generated_at", T0 + timedelta(hours=6)),
        **kw,
    )


class FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Any) -> str:
        self.calls.append((record_type, record_ref, dict(payload)))
        return "f" * 64


def test_sbv_clocks_exact_and_earliest_verdict() -> None:
    cf = build()
    assert cf.sbv.incident_detected_at == T0
    assert cf.sbv.report_due_at == T0 + timedelta(hours=24)
    assert cf.sbv.remediation_due_at == T0 + timedelta(days=5)
    assert cf.sbv.remediation_basis == "calendar_days"
    assert [t.ts for t in cf.timeline] == sorted(t.ts for t in cf.timeline)


def test_detection_falls_back_to_opened_at() -> None:
    cf = build(verdicts=[])
    assert cf.sbv.incident_detected_at == make_case().opened_at


def test_overdue_flags() -> None:
    assert not build().sbv.report_overdue
    late = build(generated_at=T0 + timedelta(hours=25))
    assert late.sbv.report_overdue and not late.sbv.remediation_overdue
    later = build(generated_at=T0 + timedelta(days=6))
    assert later.sbv.remediation_overdue
    closed = build(case=make_case(status="closed"), generated_at=T0 + timedelta(days=6))
    assert not closed.sbv.report_overdue and not closed.sbv.remediation_overdue


def test_rules_judges_and_refs() -> None:
    cf = build(rule_regulation_refs={"R-LIMIT": ["SBV-X"]})
    assert [r.verdict_id for r in cf.rules_broken] == ["V-1", "V-2"]
    assert cf.rules_broken[0].regulation_refs == ["SBV-X"]
    assert build().rules_broken[0].regulation_refs == ["TT-09/2020 Điều 5"]
    (j,) = cf.judge_findings
    assert j.is_mock and j.score_bp == 1234  # 0.12345 -> half-even 1234


def test_accepts_row_dicts() -> None:
    cf = build(case=make_case().row())
    assert cf.case_id == "C-1"


def test_chain_ref() -> None:
    cf = build()
    assert cf.chain is not None
    assert (cf.chain.lane, cf.chain.seq_from, cf.chain.seq_to) == ("agent:agent-x", 3, 7)
    assert cf.chain.head_hash == f"{7:064x}" and cf.chain.entry_count == 2
    assert build(chain=[]).chain is None


def test_two_lanes_rejected() -> None:
    with pytest.raises(ValueError, match="more than one lane"):
        build(chain=[make_chain(1, "case:C-1"), make_chain(2, "case:C-1", lane="root")])


def _walk(obj: Any) -> None:
    assert not isinstance(obj, float)
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v)


def test_json_round_trip_and_no_float() -> None:
    cf = build()
    data = render_json(cf)
    assert parse_json(data) == cf
    _walk(json.loads(data))


def test_html_content() -> None:
    cf = build(d33=D33)
    html = render_html(cf).decode("utf-8")
    for needle in (
        '<html lang="vi">',
        "Hồ sơ sự cố",
        "Case file",
        "Đồng hồ báo cáo NHNN (24 giờ)",
        "SBV reporting clocks",
        "Hạn khắc phục (5 ngày)",
        "Phê duyệt của con người",
        D33,
        "MOCK",
        f"{7:064x}",
    ):
        assert needle in html, needle
    assert "2026-10-01T08:00:00Z" in html and "ICT" in html
    assert "&lt;ok&gt;" in html  # sign-off reason escaped but otherwise verbatim
    assert "Đã xác minh với khách hàng Nguyễn Văn A, tài khoản ****1234" in html
    for bad in ("http://", "https://", "<script", "<link"):
        assert bad not in html


def test_html_escapes_summary() -> None:
    cf = build(case=make_case(summary="<b>x</b>"))
    html = render_html(cf).decode("utf-8")
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "<b>x</b>" not in html


def test_pdf_falls_back_without_font(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_pdf_mod, "FONT_CANDIDATES", ())
    res = render_pdf(build(), font_path=None)
    assert res.fmt == "html" and res.notice is not None and "HTML" in res.notice
    assert res.notice.isascii() and res.data.startswith(b"<!DOCTYPE html>")


def test_pdf_produced_when_possible() -> None:
    pytest.importorskip("fpdf")
    if render_pdf_mod.find_font(None) is None:
        pytest.skip("no local Unicode TTF font")
    res = render_pdf(build(), font_path=None)
    assert res.fmt == "pdf" and res.data.startswith(b"%PDF") and res.notice is None


def test_record_case_file() -> None:
    cf = build()
    sink = FakeSink()
    data = b"hello"
    assert record_case_file(sink, cf, "json", data) == "f" * 64
    rtype, ref, payload = sink.calls[0]
    assert rtype == "case_file" and ref == "case_file:C-1:json"
    assert payload["sha256"] == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert payload["size_bytes"] == 5 and payload["mask_version"] == "mask/1"
    assert not any(isinstance(v, float) for v in payload.values())


def test_write_case_file_refuses_overwrite(tmp_path: Path) -> None:
    cf = build()
    sink = FakeSink()
    path, notice = write_case_file(cf, tmp_path, "json", sink)
    assert path == tmp_path / "C-1.json" and notice is None and len(sink.calls) == 1
    with pytest.raises(CaseFileError):
        write_case_file(cf, tmp_path, "json", sink)
    assert len(sink.calls) == 1


def test_write_pdf_fallback_records_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_pdf_mod, "FONT_CANDIDATES", ())
    sink = FakeSink()
    path, notice = write_case_file(build(), tmp_path, "pdf", sink)
    assert path.suffix == ".html" and notice is not None
    assert sink.calls[0][1] == "case_file:C-1:html"


def test_load_case_inputs_sqlite(tmp_path: Path) -> None:
    settings = load_settings(sqlite_path=tmp_path / "t.db")
    a = build_adapters(settings)
    try:
        bootstrap_run(settings, a)
        with pytest.raises(CaseFileError):
            load_case_inputs(a.tables, a.state, "nope")
        case = make_case()
        row = case.row()
        row.pop("row_version")
        row.pop("updated_at")
        a.state.insert("cases", row)
        a.tables.append(
            "case_event",
            [
                CaseEvent(
                    case_id="C-1",
                    seq=1,
                    ts=T0 + timedelta(hours=2),
                    actor="system",
                    actor_kind="system",
                    action="open",
                ),
            ],
        )
        a.tables.append(
            "verdict",
            [
                make_verdict("V-1", T0),
                make_verdict("V-old", T0 - timedelta(days=3)),
                make_verdict("V-3", T0 + timedelta(hours=1), tier=1, score=0.5),
            ],
        )
        a.tables.append("signoff", [make_signoff()])
        refs = case_chain_refs("C-1", [], [make_verdict("V-1", T0)], [make_signoff()])
        assert refs == {"case:C-1", "verdict:V-1", "signoff:S-1"}
        a.tables.append(
            "chain_entry",
            [
                make_chain(0, "case:C-1"),
                make_chain(1, "verdict:V-1"),
                make_chain(2, "verdict:V-other"),
                make_chain(3, "signoff:S-1"),
            ],
        )
        inputs = load_case_inputs(a.tables, a.state, "C-1", now=T0 + timedelta(days=1))
        assert sorted(v.verdict_id for v in inputs["verdicts"]) == ["V-1", "V-3"]
        assert len(inputs["case_events"]) == 1 and len(inputs["signoffs"]) == 1
        assert [e.seq for e in inputs["chain_entries"]] == [0, 1, 3]
        cf = build_case_file(
            **inputs,
            decision33_text=D33,
            mask_version="mask/1",
            generated_at=T0 + timedelta(hours=6),
        )
        assert cf.chain is not None and (cf.chain.seq_from, cf.chain.seq_to) == (0, 3)
        assert parse_json(render_json(cf)) == cf
    finally:
        a.close()
