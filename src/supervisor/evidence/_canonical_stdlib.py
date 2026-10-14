"""Stdlib-only canonical JSON + SHA-256 for the offline verifier.

Byte-identical to ``supervisor.core.canonical`` (spec version 1) for every value the
evidence chain allows: ``None``, ``bool``, ``str``, ``int`` (signed 64 bits), lists and
tuples, string-keyed mappings, timezone-aware ``datetime``, ``date``, ``uuid.UUID`` and
``enum.Enum``. Money keys (suffix ``_minor``) must hold an ``int`` or ``null``.

Unlike the writer-side module this one REJECTS floats: chain payloads never hold them.
It imports nothing outside the standard library, so the verifier runs on an auditor
laptop that has no pydantic. Tests compare both implementations byte for byte.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MONEY_SUFFIX = "_minor"


class CanonicalError(TypeError):
    """The value cannot be encoded canonically."""


def format_ts(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalError(f"naive datetime is not allowed: {value!r}")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalise(value: Any, key: str | None, path: str) -> Any:
    if key is not None and key.endswith(MONEY_SUFFIX) and value is not None:
        if type(value) is not int:
            raise CanonicalError(
                f"{path}: money must be an int of minor units, got {type(value).__name__}"
            )
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, enum.Enum):
        return _normalise(value.value, key, path)
    if isinstance(value, int):
        if not INT64_MIN <= value <= INT64_MAX:
            raise CanonicalError(f"{path}: integer outside signed 64-bit range")
        return value
    if isinstance(value, float):
        raise CanonicalError(f"{path}: floats are not allowed in chain data")
    if isinstance(value, datetime):
        return format_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalError(f"{path}: object keys must be strings, got {k!r}")
            out[k] = _normalise(v, k, f"{path}.{k}")
        return out
    if isinstance(value, list | tuple):
        return [_normalise(v, key, f"{path}[{i}]") for i, v in enumerate(value)]
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalise(value, None, "$"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
