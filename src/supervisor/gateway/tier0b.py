"""Tier 0b (ADR D02): asynchronous injection / PII pre-filter. Never blocks.

``Classifier`` is the port; ``RegexClassifier`` is the default. Findings become
``alert`` verdicts after the call; the gate decision is already made.
Findings carry only a kind and a count (no matched text: PII never enters the chain).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

MAX_SCAN_CHARS = 20_000


@dataclass(frozen=True)
class Finding:
    kind: str  # injection | pii_cccd | pii_phone | pii_email | pii_account
    count: int


class Classifier(Protocol):
    name: str

    def classify(self, tool_name: str, args: Mapping[str, Any]) -> list[Finding]: ...


_INJECTION = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (the |all )?(previous|prior|system) (instructions|prompt)",
    r"you are now (in )?(developer|admin|dan) mode",
    r"system prompt",
    r"override (the )?(policy|limit|rules)",
    r"b[oỏ] qua (t[aấ]t c[aả] )?(c[aá]c )?(h[uư][oớ]ng d[aẫ]n|quy t[aắ]c)",
    r"chuy[eể]n (ngay|g[aấ]p) .{0,40}(t[aà]i kho[aả]n|tk)",
    r"<\s*/?\s*(system|assistant)\s*>",
]
_PII = {
    "pii_cccd": r"(?<!\d)0\d{11}(?!\d)",
    "pii_phone": r"(?<!\d)(?:\+?84|0)(?:3|5|7|8|9)\d{8}(?!\d)",
    "pii_email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "pii_account": r"(?<!\d)\d{13,19}(?!\d)",
}


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if depth > 6:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v, depth + 1)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v, depth + 1)


class RegexClassifier:
    """Default Tier 0b classifier: Vietnamese + English injection phrases, VN PII shapes."""

    name = "regex_v1"

    def __init__(self) -> None:
        self._inj = [re.compile(p, re.IGNORECASE) for p in _INJECTION]
        self._pii = {k: re.compile(p) for k, p in _PII.items()}

    def classify(self, tool_name: str, args: Mapping[str, Any]) -> list[Finding]:
        text = "\n".join(_strings(args))[:MAX_SCAN_CHARS]
        out: list[Finding] = []
        inj = sum(len(p.findall(text)) for p in self._inj)
        if inj:
            out.append(Finding("injection", inj))
        for kind, pattern in self._pii.items():
            n = len(pattern.findall(text))
            if n:
                out.append(Finding(kind, n))
        return out
