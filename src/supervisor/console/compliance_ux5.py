"""UX5 view model of the compliance advisor pages (CONSOLE_UX5, group G3).

Pure functions over the plain matrix dict of ``compliance_view``. Nothing here changes how
duties are counted: counts come from ``matrix['summary']`` and from the rows as they are. Legal
text (summary, article, Vietnamese text) is passed through whole; only evidence sentences and
Decision 33 lines are shortened, and the raw text stays reachable (``raw`` / technical)."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from typing import Any

from supervisor.console.ux5 import PAGE_SIZE

OPEN_GROUPS = 3
TABS = ("summary", "d33", "all")
# tick order: worst first (the tick_strip macro draws in the order it is given)
TICK_OF = {"gap": "gap", "partial": "partial", "bank_process": "bank", "met": "closed"}
TICK_ORDER = ("gap", "partial", "bank", "closed")
STATUS_KIND = {
    "gap": "bad",
    "partial": "warn",
    "bank_process": "info",
    "met": "ok",
    "not_applicable": "na",
}
STATUS_FILTERS = ("gap", "partial", "bank_process", "met")
_SEVERITY = {"gap": 0, "partial": 1, "bank_process": 2, "met": 3, "not_applicable": 4}

_TAIL = re.compile(r"\s*\(if the obligation applies; product facts are incomplete\)\s*$")
_SOURCE = re.compile(r"\(source: ([^)]*)\)")
_IDS = re.compile(r"^\[([^\]]*)\]\s*(.*)$", re.S)


def words(identifier: str) -> str:
    """``agent_event_log`` -> ``agent event log`` (identifiers read as words)."""
    return re.sub(r"[_\s]+", " ", identifier or "").strip()


def _split_top(text: str) -> list[str]:
    """Split on commas that are not inside brackets."""
    out: list[str] = []
    depth = 0
    cur = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _item_name(item: str) -> str:
    return words(item.split(" (", 1)[0])


def evidence_label(row: dict[str, Any], t: Callable[..., str]) -> str:
    """Short, readable evidence line of one row; the raw ``status_reason`` stays in ``raw``."""
    reason = _TAIL.sub("", row.get("status_reason", "") or "")
    if reason.startswith("bank process"):
        ids = reason.split("process ids:", 1)[1] if "process ids:" in reason else ""
        names = ", ".join(_item_name(i) for i in _split_top(ids)) or "-"
        return t("g3_ev_bank", names=names)
    if reason.startswith("threshold"):
        return t("g3_ev_limit")
    m = re.match(r"^present: (.*?); missing: (.*)$", reason, re.S)
    if not m:
        return reason
    present, missing = m.group(1), m.group(2)
    have = [] if present.strip() == "none" else [_item_name(i) for i in _split_top(present)]
    lack = []
    if missing.strip() != "none":
        for item in _split_top(missing):
            name = _item_name(item)
            if re.search(r"\((catalogue|monitor|evidence) not on\)", item):
                name += " (" + t("g3_ev_off") + ")"
            lack.append(name)
    parts = []
    if have:
        parts.append(t("g3_ev_have", names=", ".join(have)))
    parts.append(t("g3_ev_missing", names=", ".join(lack)) if lack else t("g3_ev_nomissing"))
    return " ".join(parts)


def tick_counts(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    n = dict.fromkeys(TICK_ORDER, 0)
    for r in rows:
        tick = TICK_OF.get(r.get("status", ""))
        if tick:
            n[tick] += 1
    return [(k, n[k]) for k in TICK_ORDER if n[k]]


def short_question(q: dict[str, Any], lang: str) -> str:
    """Question text without its parenthesis and trailing hint; the full text is the tooltip."""
    text = (q.get("text_vi") if lang == "vi" else q.get("text_en")) or q.get("text_en") or ""
    text = re.sub(r"\s*\([^)]*\)", "", text)
    cut = text.find("?")
    return text[: cut + 1] if cut > 0 else text


def questions(m: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    out = []
    for q in sorted(m.get("questions", []), key=lambda q: -len(q.get("obligation_ids") or [])):
        out.append(
            {
                "id": q["id"],
                "short": short_question(q, lang),
                "full": (q.get("text_vi") if lang == "vi" else q.get("text_en")) or "",
                "n": len(q.get("obligation_ids") or []),
            }
        )
    return out


def _clean_line(line: str) -> dict[str, str]:
    m = _IDS.match(line)
    ids, body = (m.group(1), m.group(2)) if m else ("", line)

    def files(mo: re.Match[str]) -> str:
        n = len({s.strip() for s in mo.group(1).split(",") if s.strip()})
        return f"(source: {n} file{'s' if n != 1 else ''})"

    return {"ids": ids, "text": _SOURCE.sub(files, body), "raw": line}


def decision33(m: dict[str, Any]) -> dict[str, Any]:
    d = m.get("decision33", {})
    entries = []
    for e in d.get("entries", []):
        entries.append(
            {
                "entry": e.get("entry", ""),
                "triggered": e.get("triggered"),
                "lines": [_clean_line(ln) for ln in e.get("lines", [])],
            }
        )
    return {
        "classification": d.get("classification", "needs_answer"),
        "entries": entries,
        "caveat": d.get("caveat", ""),
        "raw_lines": list(d.get("lines", [])),
    }


def _vnd(n: Any) -> str:
    try:
        return f"{int(n):,} VND"
    except (TypeError, ValueError):
        return str(n)


def thresholds(m: dict[str, Any], t: Callable[..., str]) -> list[dict[str, Any]]:
    out = []
    for f in m.get("thresholds", []):
        per_txn = f.get("period") == "per_transaction"
        period = t("g3_th_txn") if per_txn else t("g3_th_day")
        verdict = f.get("verdict", "")
        key = {"exceeds": "g3_th_exceeds", "at_cap": "g3_th_atcap"}.get(verdict, "g3_th_within")
        raw_id = f.get("limit_id", "")
        lid = words(raw_id) if "_" in raw_id else raw_id
        out.append(
            {
                "id": f.get("id", ""),
                "label": f"{lid} · {period}",
                "limit": _vnd(f.get("limit_vnd")),
                "cap": _vnd(f.get("cap_vnd")),
                "verdict": verdict,
                "why": t(
                    key,
                    limit_id=lid,
                    limit=_vnd(f.get("limit_vnd")),
                    cap=_vnd(f.get("cap_vnd")),
                    period=period,
                ),
                "raw": f.get("reason", ""),
            }
        )
    return out


def _matches_q(r: dict[str, Any], needle: str) -> bool:
    hay = f"{r.get('obligation_id', '')} {r.get('article_ref', '')} {r.get('summary_en', '')}"
    return needle in hay.lower()


def filter_all(
    m: dict[str, Any], filtered: list[dict[str, Any]], *, q: str = "", question: str = ""
) -> list[dict[str, Any]]:
    """``filtered`` rows (from ``compliance_view.filter_rows``) narrowed by a text search and by
    one open question. Counting is not touched."""
    rows = filtered
    q = (q or "").strip().lower()[:64]
    if q:
        rows = [r for r in rows if _matches_q(r, q)]
    if question:
        ids = {
            oid
            for qq in m.get("questions", [])
            if qq.get("id") == question
            for oid in qq.get("obligation_ids", [])
        }
        rows = [r for r in rows if r.get("obligation_id") in ids]
    return rows


def groups(
    rows: list[dict[str, Any]],
    titles: dict[str, str],
    *,
    more: str = "",
) -> list[dict[str, Any]]:
    """Duties grouped by legal instrument, gaps first. A group is open when it has a gap (or
    when the reader asked for more of it). ``more`` is ``<instrument_id>:<n>``."""
    want_id, _, want_n = (more or "").partition(":")
    try:
        want = max(PAGE_SIZE, min(int(want_n), 10_000))
    except ValueError:
        want = PAGE_SIZE
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r.get("instrument_id", ""), []).append(r)
    out = []
    for iid, items in by.items():
        items = sorted(
            items, key=lambda r: (_SEVERITY.get(r.get("status", ""), 9), r.get("obligation_id", ""))
        )
        gaps = sum(1 for r in items if r.get("status") == "gap")
        waits = sum(1 for r in items if r.get("applies") == "needs_answer")
        limit = want if iid == want_id else PAGE_SIZE
        out.append(
            {
                "id": iid,
                "number": items[0].get("instrument_number", iid),
                "title": titles.get(iid, ""),
                "total": len(items),
                "gaps": gaps,
                "waits": waits,
                "ticks": tick_counts(items),
                "open": bool(gaps) or iid == want_id,
                "rows": items[:limit],
                "shown": min(limit, len(items)),
                "next_n": limit + PAGE_SIZE,
            }
        )
    out.sort(key=lambda g: (-g["gaps"], -g["waits"], g["number"]))
    # most instruments have a gap, so "open when it has a gap" would open nearly all of them:
    # open the OPEN_GROUPS with the most gaps; the others are one click away
    any_gap = any(g["gaps"] for g in out)
    for rank, g in enumerate(out):
        if g["id"] != want_id and ((any_gap and not g["gaps"]) or rank >= OPEN_GROUPS):
            g["open"] = False
    return out


def csv_text(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "obligation_id",
            "instrument",
            "article",
            "applies",
            "status",
            "summary_en",
            "status_reason",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.get("obligation_id", ""),
                r.get("instrument_number", ""),
                r.get("article_ref", ""),
                r.get("applies", ""),
                r.get("status", ""),
                r.get("summary_en", ""),
                r.get("status_reason", ""),
            ]
        )
    return buf.getvalue()


def build(
    m: dict[str, Any],
    f: dict[str, Any],
    titles: dict[str, str],
    query: Any,
    t: Callable[..., str],
    lang: str,
) -> dict[str, Any]:
    """Everything the UX5 agent template needs. ``f`` is the result of ``filter_rows``."""
    tab = query.get("tab", "summary")
    if tab not in TABS:
        tab = "summary"
    qtext = (query.get("q", "") or "")[:64]
    question = (query.get("question", "") or "")[:128]
    rows = filter_all(m, f["rows"], q=qtext, question=question)
    summ = m.get("summary", {})
    by = summ.get("by_status", {})
    gap_rows = sorted(
        (r for r in m.get("rows", []) if r.get("status") == "gap" and r.get("applies") == "yes"),
        key=lambda r: r.get("obligation_id", ""),
    )
    return {
        "tab": tab,
        "q": qtext,
        "question": question,
        "more": query.get("more", "") or "",
        "applies_n": summ.get("by_applies", {}).get("yes", 0),
        "needs_answer": summ.get("needs_answer", 0),
        "total": len(m.get("rows", [])),
        "by": {k: by.get(k, 0) for k in ("gap", "partial", "bank_process", "met")},
        "questions": questions(m, lang),
        "d33": decision33(m),
        "thresholds": thresholds(m, t),
        "gap_rows": gap_rows,
        "n_rows": len(rows),
        "groups": groups(rows, titles, more=query.get("more", "") or ""),
        "tech": technical_rows(m),
    }


def technical_rows(m: dict[str, Any]) -> list[tuple[str, str]]:
    """Admin-only raw ids: question ids, threshold ids and where each limit comes from."""
    rows: list[tuple[str, str]] = []
    for q in m.get("questions", []):
        rows.append((q["id"], f"{len(q.get('obligation_ids') or [])} duties"))
    for f in m.get("thresholds", []):
        ptr = f.get("pointer") or {}
        rows.append((f.get("id", ""), str(ptr.get("ref", ""))))
    return rows


def neighbours(m: dict[str, Any], obligation_id: str) -> tuple[str, str]:
    """Previous and next obligation id inside the same instrument (matrix order), or ''."""
    rows = m.get("rows", [])
    me = next((r for r in rows if r.get("obligation_id") == obligation_id), None)
    if me is None:
        return "", ""
    same = [r["obligation_id"] for r in rows if r.get("instrument_id") == me.get("instrument_id")]
    i = same.index(obligation_id)
    return (same[i - 1] if i > 0 else ""), (same[i + 1] if i + 1 < len(same) else "")


def instrument_titles(kb: Any) -> dict[str, str]:
    return {i.id: i.title_en for i in getattr(kb, "instruments", ())}
