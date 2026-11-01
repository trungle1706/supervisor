"""Small statistics helpers for the evaluation harnesses (audit D10).

The results are integer basis points; the float maths stays inside the function.
"""

from __future__ import annotations

import math

# Two-sided 95 percent. The risk, controls, alerts and transparency harnesses use Z95; the
# detector, pii, redteam and collector harnesses use the rounded 1.96. Both stay (baselines).
Z95 = 1.959964
Z_196 = 1.96


def wilson_bp(k: int, n: int, z: float = Z_196) -> tuple[int, int] | None:
    """Wilson score interval of ``k`` successes in ``n`` trials as integer basis points
    ``(low, high)``; None when ``n`` is 0 or less."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0, math.floor((centre - half) * 10000)), min(
        10000, math.ceil((centre + half) * 10000)
    )


def wilson_bp_full(successes: int, n: int, z: float = Z95) -> tuple[int, int]:
    """Same interval with the 1.959964 default; ``(0, 10000)`` (no information) when ``n`` is 0."""
    return wilson_bp(successes, n, z) or (0, 10000)
