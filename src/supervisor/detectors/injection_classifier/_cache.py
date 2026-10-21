"""A small bounded cache keyed by a hash of the text, not by the text (WP25c, review G5).

The feature and typo caches used the raw window or token as the key, so text of a call (account
digits, names) stayed in process memory after the call. Here the key is a 16-byte BLAKE2b digest of
the text (plus the other arguments); the values are feature ids, which carry no text. Deterministic:
a hit and a miss give the same value. Thread safe enough for the gate (a lost race only recomputes).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


def text_key(text: str, *extra: str) -> bytes:
    h = hashlib.blake2b(digest_size=16)
    h.update(text.encode("utf-8", "surrogatepass"))
    for e in extra:
        h.update(b"\x1f" + e.encode("utf-8"))
    return h.digest()


class HashedLRU:
    """``cached(text, *extra)``: ``fn(text, *extra)`` memoised under ``text_key``."""

    def __init__(self, fn: Callable[..., Any], maxsize: int) -> None:
        self._fn = fn
        self._max = maxsize
        self._data: OrderedDict[bytes, Any] = OrderedDict()

    def __call__(self, text: str, *extra: str) -> Any:
        key = text_key(text, *extra)
        hit = self._data.get(key)
        if hit is not None:
            self._data.move_to_end(key)
            return hit
        value = self._fn(text, *extra)
        self._data[key] = value
        if len(self._data) > self._max:
            self._data.popitem(last=False)
        return value

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> list[bytes]:
        return list(self._data)
