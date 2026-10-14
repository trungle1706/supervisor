"""PDF rendering (optional extra ``pdf`` = fpdf2). Falls back to HTML. Never downloads fonts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from supervisor.evidence.casefile.builder import CaseFile
from supervisor.evidence.casefile.render_html import fmt_ict, fmt_utc, render_html

FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


@dataclass(frozen=True)
class RenderResult:
    fmt: Literal["pdf", "html"]
    data: bytes
    notice: str | None = None


def find_font(font_path: Path | None) -> Path | None:
    """Return the configured font if it exists, else the first local system font."""
    if font_path is not None and Path(font_path).is_file():
        return Path(font_path)
    for cand in FONT_CANDIDATES:
        if Path(cand).is_file():
            return Path(cand)
    return None


def _lines(cf: CaseFile) -> list[tuple[str, str]]:
    """(kind, text) pairs; kind is 'h1', 'h2' or 'p'."""
    s = cf.sbv
    out: list[tuple[str, str]] = [
        ("h1", f"Hồ sơ sự cố / Case file: {cf.case_id}"),
        ("p", f"Tác nhân / Agent: {cf.agent_id}"),
        ("p", f"Mức độ / Severity: {cf.severity} | Trạng thái / Status: {cf.status}"),
        ("p", f"Tóm tắt / Summary: {cf.summary}"),
        ("p", f"Mở lúc / Opened: {fmt_utc(cf.opened_at)} | Đóng / Closed: {fmt_utc(cf.closed_at)}"),
        ("p", f"Người phụ trách / Assignee: {cf.assignee or '-'} | ITSM: {cf.itsm_ref or '-'}"),
        ("p", f"Căn cứ quy định / Regulation refs: {', '.join(cf.regulation_refs) or '-'}"),
        ("h2", "Đồng hồ báo cáo NHNN (24 giờ) / SBV reporting clocks (24 h)"),
        ("p", f"Phát hiện / Detected: {fmt_utc(s.incident_detected_at)}"),
        ("p", f"   {fmt_ict(s.incident_detected_at)}"),
        (
            "p",
            f"Hạn báo cáo / Report due (24 h): {fmt_utc(s.report_due_at)}"
            + (" - QUÁ HẠN / OVERDUE" if s.report_overdue else ""),
        ),
        ("p", f"   {fmt_ict(s.report_due_at)}"),
        (
            "p",
            f"Hạn khắc phục (5 ngày) / Remediation due (5 days, {s.remediation_basis}): "
            f"{fmt_utc(s.remediation_due_at)}"
            + (" - QUÁ HẠN / OVERDUE" if s.remediation_overdue else ""),
        ),
        ("p", f"   {fmt_ict(s.remediation_due_at)}"),
        ("h2", "Phân loại theo Quyết định 33 / Decision 33 classification"),
        ("p", cf.decision33_classification),
        ("h2", "Dòng thời gian / Timeline"),
    ]
    out += [
        (
            "p",
            f"{fmt_utc(t.ts)} [{t.source}] {t.actor} ({t.actor_kind}): {t.action}"
            + (f" - {t.text}" if t.text else "")
            + f" ({t.ref})",
        )
        for t in cf.timeline
    ] or [("p", "Không có / None")]
    out.append(("h2", "Quy tắc bị vi phạm / Rules broken"))
    out += [
        (
            "p",
            f"{r.rule_id or '-'} | {r.verdict_id} | {fmt_utc(r.ts)} | {r.label}/{r.action} | "
            f"{', '.join(r.regulation_refs)}",
        )
        for r in cf.rules_broken
    ] or [("p", "Không có / None")]
    out.append(("h2", "Phát hiện của bộ đánh giá AI (chỉ tư vấn) / AI judge findings (advisory)"))
    out += [
        (
            "p",
            f"{j.verdict_id} | {fmt_utc(j.ts)} | {j.checker_id}/{j.model_id or '-'}"
            + (" [MOCK]" if j.is_mock else "")
            + f" | {j.label} | bp={j.score_bp if j.score_bp is not None else '-'}"
            + (f" | {j.rationale_masked}" if j.rationale_masked else ""),
        )
        for j in cf.judge_findings
    ] or [("p", "Không có / None")]
    out.append(("h2", "Phê duyệt của con người / Human sign-offs"))
    out += [
        (
            "p",
            f"{x.signoff_id} | {x.reviewer_id} | {x.decision} | {x.reason} | "
            f"{fmt_utc(x.ts)} | {x.auth_method}",
        )
        for x in cf.signoffs
    ] or [("p", "Không có / None")]
    out.append(("h2", "Tham chiếu chuỗi bằng chứng / Evidence chain reference"))
    if cf.chain:
        ch = cf.chain
        out += [
            ("p", f"Lane: {ch.lane} | seq {ch.seq_from}-{ch.seq_to} ({ch.entry_count})"),
            ("p", f"Head hash: {ch.head_hash}"),
        ]
    else:
        out.append(("p", "Chưa có bản ghi chuỗi / No chain entries yet"))
    out += [
        ("h2", "Chân trang / Footer"),
        ("p", f"Tạo lúc / Generated at: {fmt_utc(cf.generated_at)}"),
        ("p", f"mask_version: {cf.mask_version} | generator: {cf.generator_version}"),
        (
            "p",
            "SHA-256 của tệp được ghi vào chuỗi bằng chứng (record_type case_file) / "
            "The file sha256 is recorded in the evidence chain (record_type case_file).",
        ),
    ]
    return out


def _fallback(cf: CaseFile, reason: str) -> RenderResult:
    return RenderResult(
        fmt="html",
        data=render_html(cf),
        notice=f"PDF not produced: {reason}; HTML case file returned instead",
    )


def render_pdf(cf: CaseFile, *, font_path: Path | None = None) -> RenderResult:
    try:
        from fpdf import FPDF
    except ImportError:
        return _fallback(cf, "fpdf2 is not installed (pip install supervisor[pdf])")
    font = find_font(font_path)
    if font is None:
        return _fallback(cf, "no Unicode TTF font found (set CASEFILE_PDF_FONT)")

    pdf: Any = FPDF(format="A4")
    pdf.set_creation_date(cf.generated_at)
    pdf.set_title(f"Case file {cf.case_id}")
    pdf.add_font("cf", fname=str(font))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    for kind, text in _lines(cf):
        size = {"h1": 16, "h2": 12, "p": 9}[kind]
        pdf.set_font("cf", size=size)
        if kind != "p":
            pdf.ln(2)
        pdf.multi_cell(0, size * 0.5 + 2, text, new_x="LMARGIN", new_y="NEXT")
    return RenderResult(fmt="pdf", data=bytes(pdf.output()), notice=None)
