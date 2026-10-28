"""Law agent drafts page (WP-L1): read model for ``/console/regkb/<instrument>/drafts``.

The page lists the drafts of ``regkb_draft`` grouped by article, with the verbatim quote marked
inside the stored article text. A person with ``regkb.confirm`` confirms or drops a draft. A draft
is never an obligation; a confirmed draft is exported by the CLI into the YAML files by a pull
request. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core import rbac
from supervisor.core.errors import SupervisorError
from supervisor.regkb import internal
from supervisor.regkb.drafts import STATUSES, DraftStore
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.lawagent import (
    BANNER,
    Article,
    normalise_ws,
    parse_article_ref,
    split_articles,
    stored_text,
)
from supervisor.regkb.loader import _load_yaml, load_kb

CONTEXT_CHARS = 220
_OFF = (
    "The law agent page is off (LAWAGENT_ENABLED=1 turns it on); the drafts are made with "
    "python -m supervisor.regkb.lawagent --instrument <id>"
)


class RegkbInputError(SupervisorError):
    """Bad input on the drafts page (HTTP 400 with the message)."""


def ensure_on(settings: Any) -> None:
    if not settings.lawagent_enabled:
        raise RegkbInputError(_OFF)


@functools.lru_cache(maxsize=1)
def _kb() -> Any:
    return load_kb()


@functools.lru_cache(maxsize=1)
def _duty_labels() -> dict[str, str]:
    data = _load_yaml(REPO_ROOT / "regulations" / "schema" / "duties.yaml") or {}
    return {k: str(v.get("label_en", "")) for k, v in (data.get("duties") or {}).items()}


@functools.lru_cache(maxsize=8)
def _articles(instrument_id: str) -> dict[int, Article]:
    try:
        text, _sha, _rel = stored_text(_kb(), instrument_id, Path(REPO_ROOT))
    except RegKBError:
        return {}
    return {a.number: a for a in split_articles(text)}


def check_instrument(instrument_id: str, ctx: Any = None) -> None:
    if internal.is_internal_instrument(instrument_id):  # WP-W3: an uploaded internal document
        if ctx is None:
            raise RegkbInputError("unknown instrument id")
        try:
            internal.require_on(ctx.settings)
            internal.service(ctx)._row(internal.doc_id_of(instrument_id))
        except internal.InternalError as exc:
            raise RegkbInputError(str(exc)) from None
        return
    try:
        _kb().instrument(instrument_id)
    except RegKBError:
        raise RegkbInputError("unknown instrument id") from None


def _item(row: dict[str, Any], articles: dict[int, Article]) -> dict[str, Any]:
    number, clause = parse_article_ref(row["article"])
    art = articles.get(number)
    quote = normalise_ws(str(row["text_vi"]))
    before = after = ""
    found = False
    if art is not None:
        i = art.text.find(quote)
        if i >= 0:
            found = True
            before = art.text[max(0, i - CONTEXT_CHARS) : i]
            after = art.text[i + len(quote) : i + len(quote) + CONTEXT_CHARS]
    return {
        **row,
        "number": number,
        "clause": clause,
        "duty_label": _duty_labels().get(row["duty_id"], ""),
        "quote": quote,
        "before": before,
        "after": after,
        "in_text": found,
        "is_mock": "mock" in str(row.get("model_id") or "").lower(),
        "dimensions": [],
        "section_ref": "",
    }


def _internal_groups(
    ctx: Any, instrument_id: str, rows: list[dict[str, Any]], status: str
) -> list[dict[str, Any]]:
    """Drafts of an internal document grouped by section; the quote is marked in the section."""
    svc = internal.service(ctx)
    doc_id = internal.doc_id_of(instrument_id)
    sections = {s.ref: s for s in svc.sections(doc_id)}
    extra = svc.draft_meta(doc_id)
    groups: dict[int, dict[str, Any]] = {}
    for r in rows:
        if status != "all" and r["status"] != status:
            continue
        sec = sections.get(r["article"])
        quote = normalise_ws(str(r["text_vi"]))
        before = after = ""
        found = False
        if sec is not None:
            i = sec.text.find(quote)
            if i >= 0:
                found = True
                before = sec.text[max(0, i - CONTEXT_CHARS) : i]
                after = sec.text[i + len(quote) : i + len(quote) + CONTEXT_CHARS]
        ids = [d for d in str(r["duty_id"]).split(",") if d]
        meta = extra.get(r["draft_id"], {})
        it = {
            **r,
            "number": sec.n if sec else 0,
            "clause": "",
            "duty_label": "; ".join(_duty_labels().get(d, "") for d in ids),
            "quote": quote,
            "before": before,
            "after": after,
            "in_text": found,
            "is_mock": "mock" in str(r.get("model_id") or "").lower(),
            "dimensions": list(meta.get("dimensions") or []),
            "section_ref": r["article"],
        }
        g = groups.setdefault(
            it["number"],
            {
                "number": it["number"],
                "label": (sec.label if sec else r["article"]),
                "heading": sec.heading if sec else "",
                "drafts": [],
            },
        )
        g["drafts"].append(it)
    return [groups[n] for n in sorted(groups)]


def drafts_view(ctx: Any, me: Any, instrument_id: str, status: str = "draft") -> dict[str, Any]:
    check_instrument(instrument_id, ctx)
    if status not in (*STATUSES, "all"):
        raise RegkbInputError("status must be draft, confirmed, dropped or all")
    rows = DraftStore(ctx.state, ctx.clock).list(instrument_id)
    if internal.is_internal_instrument(instrument_id):
        doc = internal.service(ctx)._row(internal.doc_id_of(instrument_id))
        return {
            "instrument": instrument_id,
            "instrument_title": doc["title"],
            "banner": BANNER,
            "status": status,
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
            "groups": _internal_groups(ctx, instrument_id, rows, status),
            "can_confirm": rbac.allowed(me.roles, "regkb.confirm"),
            "has_text": True,
            "is_internal": True,
            "doc": doc,
        }
    articles = _articles(instrument_id)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    groups: dict[int, dict[str, Any]] = {}
    for r in rows:
        if status != "all" and r["status"] != status:
            continue
        it = _item(r, articles)
        g = groups.setdefault(
            it["number"],
            {
                "number": it["number"],
                "label": f"Điều {it['number']}",
                "heading": articles[it["number"]].heading if it["number"] in articles else "",
                "drafts": [],
            },
        )
        g["drafts"].append(it)
    return {
        "instrument": instrument_id,
        "instrument_title": _kb().instrument(instrument_id).title_en,
        "banner": BANNER,
        "status": status,
        "counts": counts,
        "groups": [groups[n] for n in sorted(groups)],
        "can_confirm": rbac.allowed(me.roles, "regkb.confirm"),
        "has_text": bool(articles),
        "is_internal": False,
    }


def draft_view(ctx: Any, me: Any, instrument_id: str, draft_id: str) -> dict[str, Any]:
    row = DraftStore(ctx.state, ctx.clock).get(draft_id)
    if row is None or row["instrument_id"] != instrument_id:
        raise RegkbInputError("this draft does not exist")
    if internal.is_internal_instrument(instrument_id):
        groups = _internal_groups(ctx, instrument_id, [row], "all")
        return {
            "d": groups[0]["drafts"][0],
            "instrument": instrument_id,
            "can_confirm": rbac.allowed(me.roles, "regkb.confirm"),
        }
    return {
        "d": _item(row, _articles(instrument_id)),
        "instrument": instrument_id,
        "can_confirm": rbac.allowed(me.roles, "regkb.confirm"),
    }
