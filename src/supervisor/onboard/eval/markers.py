"""Marker strings shared by the eval and the analyser (untrusted text and prompt data blocks)."""

from __future__ import annotations

import re

UNTRUSTED_OPEN = "<untrusted>"
UNTRUSTED_CLOSE = "</untrusted>"

_UNTRUSTED_RE = re.compile(re.escape(UNTRUSTED_OPEN) + r".*?" + re.escape(UNTRUSTED_CLOSE), re.S)
_REPO_DATA_RE = re.compile(r"<<<REPO_DATA nonce=(\S+?)>>>.*?<<<END_REPO_DATA nonce=\1>>>", re.S)


def strip_untrusted(text: str) -> str:
    """Remove every ``<untrusted>...</untrusted>`` block."""
    return _UNTRUSTED_RE.sub("", text)


def strip_repo_data(text: str) -> str:
    """Remove every ``<<<REPO_DATA nonce=X>>> ... <<<END_REPO_DATA nonce=X>>>`` block."""
    return _REPO_DATA_RE.sub("", text)
