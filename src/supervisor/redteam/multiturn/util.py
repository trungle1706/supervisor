"""Small deterministic helpers: seeded RNG, integer statistics, Wilson interval.

No ``random`` module: results must be identical on every platform and Python build, so the RNG
is a counter over SHA-256. All statistics are integers (basis points, counts).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


class DetRng:
    """Deterministic RNG from a string seed (SHA-256 in counter mode)."""

    def __init__(self, seed: str) -> None:
        self._label = seed
        self._seed = seed.encode("utf-8")
        self._n = 0

    def child(self, label: str) -> DetRng:
        return DetRng(f"{self._label}/{label}")

    def _next(self) -> int:
        digest = hashlib.sha256(self._seed + b":" + str(self._n).encode("ascii")).digest()
        self._n += 1
        return int.from_bytes(digest[:8], "big")

    def uniform_int(self, lo: int, hi: int) -> int:
        """Integer in ``lo..hi`` (both included)."""
        if hi < lo:
            raise ValueError("hi < lo")
        return lo + self._next() % (hi - lo + 1)

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("choice of an empty sequence")
        return items[self._next() % len(items)]

    def chance_bp(self, bp_value: int) -> bool:
        return self._next() % 10000 < bp_value

    def shuffled(self, items: Sequence[T]) -> list[T]:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self._next() % (i + 1)
            out[i], out[j] = out[j], out[i]
        return out


def stable_int(*parts: object) -> int:
    """A stable non-negative integer from the string forms of ``parts``."""
    text = "\x1f".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def bp(k: int, n: int) -> int | None:
    """k / n in integer basis points (floor); None when n is 0."""
    return None if n <= 0 else k * 10000 // n


def wilson_bp(k: int, n: int, z: float = 1.96) -> tuple[int, int] | None:
    """Wilson score interval for k of n, in basis points (low, high); None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0, math.floor((centre - half) * 10000)), min(
        10000, math.ceil((centre + half) * 10000)
    )


def median_int(values: Sequence[int]) -> int | None:
    """Nearest-rank median (always an observed value); None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[(len(ordered) + 1) // 2 - 1]


def cell(k: int, n: int) -> dict[str, int | None]:
    """{k, n, bp, lo, hi}: a count, its trials, the rate and the Wilson 95% interval in bp."""
    ci = wilson_bp(k, n)
    return {
        "k": k,
        "n": n,
        "bp": bp(k, n),
        "lo": ci[0] if ci else None,
        "hi": ci[1] if ci else None,
    }
