"""Dev-host-only OCR of a scanned legal PDF (WP-L5).

NOT part of the app: nothing under src/ may import this module. It calls ``pdftoppm`` (poppler)
and ``tesseract`` through ``subprocess``; both are tools of the developer machine, not
dependencies of Supervisor. The result is a second text of the signed Circular 53/2026/TT-NHNN
that a test compares with the quotes (tests/regkb/test_quotes_ocr.py).

    python tools/regkb_ocr.py
    python tools/regkb_ocr.py --pdf <path to the pdf> --dpi 300

Writes next to the PDF:
    <pdf stem>.ocr.txt        the text; pages are separated by a line "=== page N ==="
    <pdf stem>.ocr.meta.json  sidecar: url (of the PDF), fetched_at, sha256 (of the .ocr.txt),
                              pdf_sha256, page count, tool versions, language, dpi, date

The sidecar keeps the keys of the other sidecars (``url``, ``fetched_at``, ``sha256``) so
``tests/regkb/test_sources.py`` and ``tools/regkb_fetch.py verify`` check the OCR file too.
OCR text is machine output and has noise; the text from vbpl stays the text of record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

TOOL = "regkb_ocr/1"
DEFAULT_PDF = Path("regulations/sources/VN-TT53-2026/53-2026-tt-nhnn-signed.pdf")
PAGE_MARK = "=== page {n} ==="


def out(msg: str) -> None:
    sys.stdout.write(msg + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)


def _first_line(cmd: list[str]) -> str:
    res = _run(cmd)
    text = (res.stdout + res.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def check_tools(lang: str) -> dict[str, str]:
    """Fail early when tesseract, pdftoppm or the language data is missing."""
    langs = _run(["tesseract", "--list-langs"])
    if langs.returncode != 0:
        raise SystemExit("[FAIL] tesseract is not installed or does not run")
    if lang not in {ln.strip() for ln in langs.stdout.splitlines()}:
        raise SystemExit(f"[FAIL] tesseract language data '{lang}' is missing")
    version = _run(["pdftoppm", "-v"])
    if version.returncode != 0:
        raise SystemExit("[FAIL] pdftoppm (poppler) is not installed or does not run")
    return {
        "tesseract": _first_line(["tesseract", "--version"]),
        "pdftoppm": _first_line(["pdftoppm", "-v"]),
    }


def ocr_pdf(pdf: Path, lang: str, dpi: int) -> list[str]:
    """Render the PDF page by page and OCR each page image. Returns one text per page."""
    pages: list[str] = []
    with tempfile.TemporaryDirectory(prefix="regkb-ocr-") as tmp:
        prefix = Path(tmp) / "page"
        res = _run(["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), str(prefix)])
        if res.returncode != 0:
            raise SystemExit(f"[FAIL] pdftoppm: {res.stderr.strip()[:200]}")
        images = sorted(Path(tmp).glob("page-*.png"))
        if not images:
            raise SystemExit("[FAIL] pdftoppm produced no page images")
        for n, image in enumerate(images, 1):
            res = _run(["tesseract", str(image), "stdout", "-l", lang, "--psm", "6"])
            if res.returncode != 0:
                raise SystemExit(f"[FAIL] tesseract page {n}: {res.stderr.strip()[:200]}")
            pages.append(res.stdout)
            out(f"[OK] page {n}/{len(images)}: {len(res.stdout)} characters")
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OCR a scanned PDF with tesseract (dev host only)")
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--lang", default="vie")
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args(argv)
    pdf: Path = args.pdf
    if not pdf.is_file():
        raise SystemExit(f"[FAIL] no such file: {pdf}")
    tools = check_tools(args.lang)
    pages = ocr_pdf(pdf, args.lang, args.dpi)
    body = "".join(
        f"{PAGE_MARK.format(n=n)}\n{text.rstrip()}\n\n" for n, text in enumerate(pages, 1)
    )
    txt = pdf.with_name(pdf.stem + ".ocr.txt")
    txt.write_text(body, encoding="utf-8", newline="\n")
    pdf_meta_path = pdf.with_name(pdf.stem + ".meta.json")
    pdf_meta = json.loads(pdf_meta_path.read_text("utf-8")) if pdf_meta_path.is_file() else {}
    meta = {
        "content_type": "text/plain; charset=utf-8",
        "dpi": args.dpi,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "language": args.lang,
        "note": (
            "Machine OCR of the signed scan. It has noise (diacritics, punctuation, line breaks). "
            "The vbpl text stays the text of record; this copy lets a test check the quotes "
            "against the signed copy."
        ),
        "pages": len(pages),
        "pdf_file": pdf.name,
        "pdf_sha256": sha256_file(pdf),
        "sha256": sha256_file(txt),
        "title": f"OCR text of {pdf.name}",
        "tool": TOOL,
        "tool_versions": tools,
        "url": pdf_meta.get("url", "https://invalid.example/ocr-of-local-pdf"),
    }
    txt.with_name(txt.stem + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    out(f"[OK] {txt} ({len(pages)} pages, sha256 {meta['sha256'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
