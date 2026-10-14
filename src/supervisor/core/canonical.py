"""Canonical JSON and SHA-256 for the evidence chain.

Spec (version 1). Any verifier in any language must reproduce these bytes.

* Objects: keys are strings, sorted by Python ``str`` order (code point order).
  This equals RFC 8785 order for keys in the Basic Multilingual Plane.
* Separators ``,`` and ``:``; no whitespace; UTF-8; non-ASCII is written raw
  (no ``\\u`` escapes). Strings are not Unicode-normalised: hash what you store.
* Timestamps: timezone-aware ``datetime`` only, converted to UTC and written as
  RFC 3339 ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (always 6 fraction digits).
  Naive datetimes are rejected. ``date`` is ``YYYY-MM-DD``.
* Integers: must fit in signed 64 bits (BIGINT). ``bool`` is ``true``/``false``.
* Money: any key ending in ``_minor`` must hold an ``int`` (integer minor units)
  or ``null``. Floats, Decimals and strings are rejected there.
* Floats: allowed only outside money keys, must be finite, written with Python's
  shortest round-trip ``repr``. ``Decimal`` and ``bytes`` are rejected.
* Enums are written as their ``value``; pydantic models as ``model_dump()``;
  tuples as arrays; ``uuid.UUID`` as its string.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

CANONICAL_VERSION = 1
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MONEY_SUFFIX = "_minor"


class CanonicalError(TypeError):
    """The value cannot be encoded canonically."""


def format_ts(value: datetime) -> str:
    """RFC 3339 UTC with 6 fraction digits and a Z suffix."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalError(f"naive datetime is not allowed: {value!r}")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(text: str) -> datetime:
    """Parse an RFC 3339 / ISO 8601 timestamp into an aware UTC datetime."""
    value = datetime.fromisoformat(text.strip().replace(" ", "T"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)  # Databricks TIMESTAMP strings are UTC
    return value.astimezone(UTC)


def _normalise(value: Any, key: str | None, path: str) -> Any:
    is_money = key is not None and key.endswith(MONEY_SUFFIX)
    if is_money and value is not None and (type(value) is not int):
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
        if not math.isfinite(value):
            raise CanonicalError(f"{path}: non-finite float")
        return value
    if isinstance(value, datetime):
        return format_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump(mode="python"), key, path)
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalError(f"{path}: object keys must be strings, got {k!r}")
            out[k] = _normalise(v, k, f"{path}.{k}")
        return out
    if isinstance(value, list | tuple):
        return [_normalise(v, key, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, Decimal | bytes | bytearray):
        raise CanonicalError(f"{path}: {type(value).__name__} is not allowed")
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
    """SHA-256 hex digest of the canonical bytes of ``value``."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
