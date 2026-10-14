"""Regex secret scrubber: runs on every repo or workspace text before an LLM sees it.

ADR D12: the goal is gitleaks; plan v2 uses this in-process scrubber (lower recall).
Each match is replaced with ``[REDACTED:<kind>]``. Only counts are logged and recorded,
never the matched text. The scrubber is idempotent (a redaction marker never matches).

    s = Scrubber()
    clean = s.scrub(text, source="agent.py")
    s.totals          # {"aws_access_key": 1, ...}
    s.files           # {"agent.py": 1}
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

log = logging.getLogger("supervisor.onboard.scrub")

# (kind, pattern, group to redact: 0 = whole match). Order matters: specific first.
_PATTERNS: tuple[tuple[str, str, int], ...] = (
    (
        "pem_private_key",
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        0,
    ),
    ("databricks_token", r"\bdapi[0-9a-f]{32}(?:-\d+)?\b", 0),
    ("databricks_oauth_secret", r"\bdose[0-9a-f]{32}\b", 0),
    ("aws_access_key", r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b", 0),
    (
        "aws_secret_key",
        r"(?i)aws_?secret_?access_?key\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b",
        1,
    ),
    ("azure_storage_key", r"(?i)AccountKey=([A-Za-z0-9+/]{40,}={0,2})", 1),
    ("azure_sas_signature", r"(?i)[?&]sig=([A-Za-z0-9%+/=]{30,})", 1),
    ("azure_client_secret", r"\b[A-Za-z0-9_~.-]{3}8Q~[A-Za-z0-9_~.-]{31,34}\b", 0),
    ("gcp_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b", 0),
    ("gcp_private_key_id", r"\"private_key_id\"\s*:\s*\"([0-9a-f]{40})\"", 1),
    ("github_token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})\b", 0),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", 0),
    ("llm_api_key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b", 0),
    (
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        0,
    ),
    ("bearer_token", r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)", 1),
    ("url_password", r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@\"']+:([^\s@/\"']+)@", 1),
    (
        "assigned_secret",
        r"(?i)\b[\w.-]*(?:password|passwd|pwd|secret|api_?key|access_?token|auth_?token|"
        r"client_?secret|private_?key)[\w.-]*\s*[\"']?\s*[:=]\s*[\"']([^\"'\s]{6,})[\"']",
        1,
    ),
    (
        "assigned_secret_env",
        r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY|APIKEY)[A-Z0-9_]*"
        r"\s*=\s*([^\s\"'#]{8,})",
        1,
    ),
)

_COMPILED = tuple((kind, re.compile(p), g) for kind, p, g in _PATTERNS)
_MARKER = re.compile(r"\[REDACTED:[a-z_]+\]")


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
    out = text
    for kind, pat, group in _COMPILED:

        def repl(m: re.Match[str], kind: str = kind, group: int = group) -> str:
            value = m.group(group)
            if value is None or _MARKER.fullmatch(value) or value.startswith("[REDACTED:"):
                return m.group(0)
            if value.startswith("FILL-ME") or set(value) <= {"*", "x", "X", "."}:
                return m.group(0)  # documented placeholders are not secrets
            counts[kind] += 1
            if group == 0:
                return _marker(kind)
            start, end = m.span(group)
            base = m.start(0)
            whole = m.group(0)
            return whole[: start - base] + _marker(kind) + whole[end - base :]

        out = pat.sub(repl, out)
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
