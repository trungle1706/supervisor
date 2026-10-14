"""Keyed digest of tool arguments (``args_hash`` columns, ``args_hmac`` in chain payloads).

A plain SHA-256 of low-entropy arguments (an account id, an amount) can be brute-forced
from the chain. HMAC-SHA256 with a secret key (``ARGS_HASH_KEY``) cannot, yet the same
arguments still give the same digest inside one deployment (correlation works).

The default key is a fixed development key; every digest made with it carries the key
id ``dev`` so an auditor can see it. Production sets ``ARGS_HASH_KEY`` (key id = first
16 hex of SHA-256 of the key, so the key itself never appears).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

DEV_ARGS_HASH_KEY = "supervisor-dev-args-hash-key-NOT-FOR-PRODUCTION"
DEV_KEY_ID = "dev"


def as_key(key: str | bytes | None) -> bytes:
    if key is None or key == "":
        key = DEV_ARGS_HASH_KEY
    return key.encode("utf-8") if isinstance(key, str) else bytes(key)


def key_id(key: str | bytes | None) -> str:
    raw = as_key(key)
    if raw == DEV_ARGS_HASH_KEY.encode("utf-8"):
        return DEV_KEY_ID
    return hashlib.sha256(raw).hexdigest()[:16]


def args_text(args: Mapping[str, Any]) -> str:
    """Stable text of the arguments (sorted keys, compact, UTF-8)."""
    return json.dumps(
        dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def args_hmac(args: Mapping[str, Any], key: str | bytes | None) -> str:
    """HMAC-SHA256 (hex) of the arguments under ``key`` (None -> the dev key)."""
    return hmac.new(as_key(key), args_text(args).encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = ["DEV_ARGS_HASH_KEY", "DEV_KEY_ID", "args_hmac", "args_text", "as_key", "key_id"]
