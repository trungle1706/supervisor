"""Circular 53/2026 quotes against BOTH stored texts (WP-L5).

* The vbpl text (``53-2026-tt-nhnn.txt``) is the text of record. Every ``text_vi`` quote of
  VN-TT53-2026 must match it as in ``test_quotes.py`` (white space folded, nothing else).
* The OCR text of the signed scan (``53-2026-tt-nhnn-signed.ocr.txt``, made by
  ``tools/regkb_ocr.py`` with tesseract ``-l vie``) is a second check that the quotes agree
  with the signed copy. OCR has noise, so the match is looser:

  1. Fold both sides: drop page numbers and page markers, drop diacritics, map ``d with stroke``
     to ``d``, keep only ``0-9a-z`` (white space and punctuation go), and treat the look-alike
     characters ``1 l j`` as ``i`` and ``0`` as ``o``.
  2. A quote matches when each of its fragments (the quote is cut at ``...``) is a substring of
     the folded OCR text (EXACT), or when at least 90 percent of the fragment's 12-character
     chunks are found inside one stretch of the folded OCR text, as long as the fragment plus a
     10 percent margin (NOISE-TOLERANT).

  THRESHOLD: the test fails when more than 10 percent of the quotes match in neither way.
  A quote that fails the OCR match is OCR noise or a real difference between the copies; the
  failure message lists them. The counts are in the test id and in the printed summary.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pytest

from supervisor.regkb import load_kb
from tests.regkb.test_quotes import _GAP, _norm, _stored_text

REPO = Path(__file__).resolve().parents[2]
FOLDER = REPO / "regulations" / "sources" / "VN-TT53-2026"
OCR_TXT = FOLDER / "53-2026-tt-nhnn-signed.ocr.txt"
OCR_META = FOLDER / "53-2026-tt-nhnn-signed.ocr.meta.json"
SIGNED_PDF = FOLDER / "53-2026-tt-nhnn-signed.pdf"
INSTRUMENT = "VN-TT53-2026"
MAX_FAIL_SHARE = 0.10  # more than 10 percent of the quotes without an OCR match fails the test
CHUNK = 12
MIN_CHUNK_SHARE = 0.90
MIN_FRAGMENT = 12  # shorter fragments are not checked (same rule as test_quotes.py)

_PAGE_HEAD = re.compile(r"=== page \d+ ===\n[^\w\n]*\d{1,2}[^\w\n]*\n")
_PAGE_MARK = re.compile(r"=== page \d+ ===")
_LOOKALIKE = str.maketrans("1lj0", "iiio")


def fold(text: str) -> str:
    """OCR-tolerant form of a text: no diacritics, no punctuation or spaces, look-alikes merged."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^0-9a-z]+", "", text.lower()).translate(_LOOKALIKE)


def folded_ocr() -> str:
    raw = OCR_TXT.read_text(encoding="utf-8")
    return fold(_PAGE_MARK.sub("", _PAGE_HEAD.sub("", raw)))


def fragments(quote: str) -> list[str]:
    return [f for f in (fold(x) for x in _GAP.split(quote)) if len(f) >= MIN_FRAGMENT]


def chunk_share(fragment: str, ocr: str) -> float:
    """Best share of the 12-character chunks of ``fragment`` found in one stretch of ``ocr``.

    Each chunk that occurs in ``ocr`` proposes a stretch (where the whole fragment would lie if
    that chunk is the anchor, plus a margin for noise); the share is counted inside the stretch
    only, so chunks that match far away in the document do not count."""
    chunks = [fragment[i : i + CHUNK] for i in range(0, len(fragment) - CHUNK + 1, CHUNK)]
    if not chunks:
        return 1.0
    margin = len(fragment) // 10 + 40
    best = 0
    for k, chunk in enumerate(chunks):
        at = ocr.find(chunk)
        while at >= 0:
            lo = max(0, at - k * CHUNK - margin)
            window = ocr[lo : at + (len(chunks) - k) * CHUNK + margin]
            best = max(best, sum(1 for c in chunks if c in window))
            if best / len(chunks) >= MIN_CHUNK_SHARE:
                return best / len(chunks)
            at = ocr.find(chunk, at + 1)
    return best / len(chunks)


def ocr_match(quote: str, ocr: str) -> str:
    """'exact', 'tolerant' or 'none'."""
    frags = fragments(quote)
    if all(f in ocr for f in frags):
        return "exact"
    if all(chunk_share(f, ocr) >= MIN_CHUNK_SHARE for f in frags):
        return "tolerant"
    return "none"


def _quotes() -> list[tuple[str, str]]:
    kb = load_kb()
    return [
        (o.id, o.text_vi)
        for o in kb.obligations_of(INSTRUMENT)
        if o.verification == "VERIFIED_PRIMARY" and o.text_vi
    ]


QUOTES = _quotes()


def _summary() -> tuple[str, dict[str, list[str]]]:
    if not OCR_TXT.is_file():
        return "ocr text missing", {"exact": [], "tolerant": [], "none": []}
    ocr = folded_ocr()
    got: dict[str, list[str]] = {"exact": [], "tolerant": [], "none": []}
    for oid, quote in QUOTES:
        got[ocr_match(quote, ocr)].append(oid)
    n = len(QUOTES)
    exact = len(got["exact"])
    tol = exact + len(got["tolerant"])
    return f"exact={exact}/{n} noise-tolerant={tol}/{n} fail={len(got['none'])}/{n}", got


SUMMARY_TEXT, RESULT = _summary()


def test_quotes_exist() -> None:
    assert len(QUOTES) >= 50, "Circular 53 should have its VERIFIED_PRIMARY quotes"


@pytest.mark.parametrize(("oid", "quote"), QUOTES, ids=[q[0] for q in QUOTES])
def test_quote_is_in_vbpl_text(oid: str, quote: str) -> None:
    stored = _stored_text(INSTRUMENT)
    assert stored is not None
    assert "=== page" not in stored, "the OCR text must not be part of the text of record"
    missing = [
        f
        for f in (_norm(x).strip(" ;,.:\"'()") for x in _GAP.split(quote))
        if len(f) >= 12 and f not in stored
    ]
    assert not missing, f"{oid}: quote fragment not in the vbpl text: {missing[0][:120]!r}"


def test_ocr_sidecar_matches_files() -> None:
    meta = json.loads(OCR_META.read_text(encoding="utf-8"))
    assert meta["pdf_sha256"] == hashlib.sha256(SIGNED_PDF.read_bytes()).hexdigest()
    assert meta["sha256"] == hashlib.sha256(OCR_TXT.read_bytes()).hexdigest()
    assert meta["language"] == "vie" and meta["pages"] == 23
    assert "tesseract" in meta["tool_versions"] and "pdftoppm" in meta["tool_versions"]


@pytest.mark.parametrize("summary", [SUMMARY_TEXT], ids=[f"ocr-match {SUMMARY_TEXT}"])
def test_quotes_match_the_ocr_text_of_the_signed_copy(summary: str) -> None:
    """THRESHOLD: more than 10 percent of the quotes without any OCR match fails the test."""
    assert OCR_TXT.is_file(), "run: python tools/regkb_ocr.py"
    print(f"[OCR] Circular 53 quotes vs signed scan: {summary}")
    failed = RESULT["none"]
    assert len(failed) <= MAX_FAIL_SHARE * len(QUOTES), f"{summary}; no OCR match: {failed}"


def test_fold_is_not_a_blank_check() -> None:
    """A sentence that is not in the signed text must not match (the fold is not too loose)."""
    ocr = folded_ocr()
    fake = "Đơn vị phải nộp báo cáo hằng ngày cho Ngân hàng Nhà nước về mọi giao dịch."
    assert ocr_match(fake, ocr) == "none"
    real = "Trí tuệ nhân tạo không thay thế thẩm quyền và trách nhiệm của con người."
    assert ocr_match(real, ocr) in ("exact", "tolerant")
