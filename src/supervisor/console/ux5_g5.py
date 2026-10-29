"""UX5 helpers for group G5 (CONSOLE_UX5): dates, percentages and plain rule names.

Pure functions. Registered as Jinja filters in ``routes.py`` (``u5when``, ``u5pct``, ``u5rule``).
Used only by templates under ``ux5``."""

from __future__ import annotations

import datetime as dt
from typing import Any

ICT = dt.timezone(dt.timedelta(hours=7))


def _parse(value: Any) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    try:
        d = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def when(value: Any, short: bool = False) -> str:
    """``29 Oct 2026, 21:00`` (ICT); ``short`` drops the year. Unparseable text comes back as is."""
    d = _parse(value)
    if d is None:
        return "-" if value in (None, "") else str(value)
    return d.astimezone(ICT).strftime("%d %b %H:%M" if short else "%d %b %Y, %H:%M")


def pct(bp: Any, digits: int = 1) -> str:
    """Integer basis points (0..10000) as a percentage: ``316`` -> ``3.2%``."""
    try:
        v = int(bp) / 100
    except (TypeError, ValueError):
        return "-"
    text = f"{v:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text + "%"


def share(part: Any, whole: Any) -> str:
    """``part`` of ``whole`` as a percentage with one decimal (``-`` when whole is 0)."""
    try:
        p, w = int(part), int(whole)
    except (TypeError, ValueError):
        return "-"
    if w <= 0:
        return "-"
    return pct(p * 10000 // w)


_RULE_WORDS = {
    "dlp_vn": "Vietnamese personal data",
    "injection_regex": "Prompt injection patterns",
    "injection_classifier": "Indirect prompt injection",
    "document_intake": "Document and URL intake",
    "guard_model": "Guard model",
    "judge_advisory": "Judge advisory",
    "judge_moderation": "Judge moderation",
}


def rule(slug: Any) -> str:
    """A readable name for a detector slug or finding code.

    ``injection_regex`` -> ``Prompt injection patterns``; ``injection.instruction_override`` ->
    ``Injection: instruction override``; ``gf:vn-account-number-mask@1`` -> ``Vn account number
    mask`` (a custom guardian); anything else has its separators turned into spaces."""
    s = str(slug or "")
    if not s:
        return "-"
    if s in _RULE_WORDS:
        return _RULE_WORDS[s]
    if s.startswith("gf:"):
        s = s[3:].split("@", 1)[0]
        return s.replace("-", " ").replace("_", " ").capitalize()
    if s.startswith("guardian."):
        s = s[len("guardian.") :].split(".", 1)[0]
        return s.replace("-", " ").replace("_", " ").capitalize()
    if "." in s:
        head, _, tail = s.partition(".")
        return f"{head.replace('_', ' ').capitalize()}: {tail.replace('_', ' ').replace('.', ' - ')}"
    return s.replace("_", " ").replace("-", " ").capitalize()
