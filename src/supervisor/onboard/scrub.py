"""Regex secret scrubber: runs on every repo or workspace text before an LLM sees it.

ADR D12: the goal is gitleaks; plan v2 uses this in-process scrubber (lower recall).
Each match is replaced with ``[REDACTED:<kind>]`` (plus the same number of line breaks,
so file:line evidence stays valid). Only counts are logged and recorded,
never the matched text. The scrubber is idempotent (a redaction marker never matches).

    s = Scrubber()
    clean = s.scrub(text, source="agent.py")
    s.totals          # {"aws_access_key": 1, ...}
    s.files           # {"agent.py": 1}
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from supervisor.core.secret_patterns import redact

log = logging.getLogger("supervisor.onboard.scrub")


def _marker(kind: str) -> str:
    return f"[REDACTED:{kind}]"


@dataclass
class ScrubResult:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def scrub_text(text: str) -> ScrubResult:
    """Replace every secret-looking span. Returns the clean text and counts per kind."""
    counts: Counter[str] = Counter()

    def marker(kind: str, value: str) -> str:
        # Keep the line count so file:line evidence stays correct after scrubbing.
        return _marker(kind) + "\n" * value.count("\n")

    def hit(kind: str, _value: str) -> None:
        counts[kind] += 1

    out = redact(text, marker, hit)
    return ScrubResult(out, dict(counts))


@dataclass
class Scrubber:
    """Stateful wrapper: keeps totals per kind and per source (counts only)."""

    totals: Counter[str] = field(default_factory=Counter)
    files: Counter[str] = field(default_factory=Counter)
    texts_scrubbed: int = 0

    def scrub(self, text: str, source: str = "<text>") -> str:
        res = scrub_text(text)
        self.texts_scrubbed += 1
        if res.counts:
            self.totals.update(res.counts)
            self.files[source] += res.total
            log.warning(
                "secret scrubber redacted %d span(s) in one input (%s)",
                res.total,
                ", ".join(f"{k}={v}" for k, v in sorted(res.counts.items())),
            )
        return res.text

    @property
    def total(self) -> int:
        return sum(self.totals.values())

    def summary(self) -> dict[str, object]:
        """Counts only: safe for the profile, the report and the evidence chain."""
        return {
            "texts_scrubbed": self.texts_scrubbed,
            "secrets_redacted": self.total,
            "by_kind": dict(sorted(self.totals.items())),
            "files_with_secrets": len(self.files),
        }
