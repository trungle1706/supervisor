"""Every verbatim Vietnamese quote (text_vi) of a VERIFIED_PRIMARY obligation must appear in the
official text stored under regulations/sources/<instrument_id>/ when that text was fetched.

Whitespace is normalised; a quote may skip parts with '...' and each part must be found."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from supervisor.regkb import load_kb

REPO = Path(__file__).resolve().parents[2]
SOURCES = REPO / "regulations" / "sources"
_GAP = re.compile(r"\.\.\.|…|\[\.\.\.\]")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip().lower()


def _stored_text(instrument_id: str) -> str | None:
    folder = SOURCES / instrument_id
    if not folder.is_dir():
        return None
    parts = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(folder.glob("*.txt"))]
    return _norm("\n".join(parts)) if parts else None


def _cases() -> list[tuple[str, str, str]]:
    kb = load_kb()
    out = []
    for o in kb.obligations.values():
        if o.jurisdiction == "VN" and o.verification == "VERIFIED_PRIMARY" and o.text_vi:
            out.append((o.id, o.instrument_id, o.text_vi))
    return out


CASES = _cases()


@pytest.mark.skipif(not CASES, reason="no VERIFIED_PRIMARY Vietnamese quotes yet")
@pytest.mark.parametrize(("oid", "iid", "quote"), CASES, ids=[c[0] for c in CASES])
def test_quote_is_in_stored_primary_text(oid: str, iid: str, quote: str) -> None:
    stored = _stored_text(iid)
    if stored is None:
        pytest.skip(f"{iid}: no stored .txt primary text")
    missing = [
        frag
        for frag in (_norm(f).strip(" ;,.:\"'()") for f in _GAP.split(quote))
        if len(frag) >= 12 and frag not in stored
    ]
    assert not missing, f"{oid}: quote fragment not in stored text of {iid}: {missing[0][:120]!r}"
