"""The one source of secret patterns (WP-D2).

Two callers use it: the onboarding scrubber (``supervisor.onboard.scrub``: repo text before an
LLM sees it) and the ``dlp_vn`` detector (``secrets`` group: tool arguments, results and output).
A pattern added here protects both.

``PATTERNS`` is ``(kind, regex, group)``: ``group`` is the part of the match that is the secret
(0 = the whole match). Order matters: specific first. ``redact`` replaces every secret span with
a marker built by the caller and calls ``on_hit(kind, value)`` once per replaced span, so the
caller can count or hash it. The text of a secret never leaves this module except through that
callback.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# (kind, pattern, group to redact: 0 = whole match). Order matters: specific first.
PATTERNS: tuple[tuple[str, str, int], ...] = (
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
        r"(?i)aws_?secret_?access_?key\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])",
        1,
    ),
    ("azure_storage_key", r"(?i)AccountKey=([A-Za-z0-9+/]{40,}={0,2})", 1),
    ("azure_sas_signature", r"(?i)[?&]sig=([A-Za-z0-9%+/=]{30,})", 1),
    ("azure_client_secret", r"\b[A-Za-z0-9_~.-]{3}8Q~[A-Za-z0-9_~.-]{31,34}\b", 0),
    ("gcp_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b", 0),
    ("gcp_private_key_id", r"\"private_key_id\"\s*:\s*\"([0-9a-f]{40})\"", 1),
    ("github_token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})\b", 0),
    # WP-D2: kinds the scrubber did not have. Prefixes are distinct from every pattern below.
    ("gitlab_token", r"\bglpat-[A-Za-z0-9_-]{20,}", 0),
    ("huggingface_token", r"\bhf_[A-Za-z0-9]{30,}\b", 0),
    ("stripe_key", r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b", 0),
    ("sendgrid_key", r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b", 0),
    ("npm_token", r"\bnpm_[A-Za-z0-9]{36}\b", 0),
    ("vault_token", r"\bhv[sbr]\.[A-Za-z0-9_-]{24,}", 0),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", 0),
    ("llm_api_key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b", 0),
    (
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        0,
    ),
    ("gcp_oauth_token", r"\bya29\.[0-9A-Za-z_-]{20,}", 0),
    ("bearer_token", r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)", 1),
    ("basic_auth", r"(?i)\bbasic\s+([A-Za-z0-9+/]{12,}={0,2})(?![A-Za-z0-9+/=])", 1),
    ("url_password", r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@\"']*:([^\s@/\"']+)@", 1),
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
    (
        # Unquoted YAML / INI / .env values: `api_key: abc123def`, `password = hunter22`.
        # The value must hold a digit and end the line, so code such as
        # `api_key = settings.llm_api_key` or `token: str` is left alone.
        "assigned_secret_unquoted",
        r"(?im)^[ \t-]*[\w.-]*(?:password|passwd|pwd|secret|api_?key|apikey|token|"
        r"client_?secret|private_?key)[\w.-]*[ \t]*[:=][ \t]*"
        r"(?![\"'$<{]|os\.|FILL-ME|\[REDACTED|<SECRET)(?=[^\s\"'#,;]*\d)([^\s\"'#,;]{6,})[ \t]*$",
        1,
    ),
)

COMPILED = tuple((kind, re.compile(p), g) for kind, p, g in PATTERNS)
KINDS: tuple[str, ...] = tuple(dict.fromkeys(kind for kind, _, _ in PATTERNS))
_MARKERS = re.compile(r"\[REDACTED:[a-z_]+\]|<SECRET:[a-z_]+(?::[0-9a-f]+)?>")
_PLACEHOLDER_CHARS = {"*", "x", "X", "."}


def refine_kind(kind: str, value: str) -> str:
    """The reporting kind of a hit: the LLM key pattern covers two vendors; report them apart."""
    if kind == "llm_api_key":
        return "anthropic_api_key" if value.startswith("sk-ant-") else "openai_api_key"
    return kind


def is_placeholder(value: str | None) -> bool:
    """A redaction marker, a documented placeholder or a mask: not a secret."""
    if value is None or _MARKERS.fullmatch(value):
        return True
    if value.startswith(("[REDACTED:", "<SECRET:")) or value.startswith("FILL-ME"):
        return True
    return set(value) <= _PLACEHOLDER_CHARS


def redact(
    text: str,
    marker: Callable[[str, str], str],
    on_hit: Callable[[str, str], None] | None = None,
) -> str:
    """Replace every secret span of ``text`` with ``marker(kind, value)``.

    ``on_hit(kind, value)`` is called for each replaced span (the raw kind of the pattern).
    Idempotent: a marker, a placeholder and a mask never match. For a pattern with a group, only
    the group is replaced and the rest of the match stays."""
    out = text
    for kind, pat, group in COMPILED:

        def repl(m: re.Match[str], kind: str = kind, group: int = group) -> str:
            value = m.group(group)
            if value is None or is_placeholder(value):
                return m.group(0)
            if on_hit is not None:
                on_hit(kind, value)
            mark = marker(kind, value)
            if group == 0:
                return mark
            start, end = m.span(group)
            base = m.start(0)
            whole = m.group(0)
            return whole[: start - base] + mark + whole[end - base :]

        out = pat.sub(repl, out)
    return out
