"""DETECTORS_ENABLED off: the gate behaves exactly as in v0.3.0 (WP37, ADR D23).

``EXPECTED`` was computed on v0.3.0 with this same sequence, before any WP37 code existed. A
change to an answer, a row or a chain payload (one new key is enough) changes the hash.
"""

from __future__ import annotations

from typing import Any

from supervisor.gateway.engine import Gateway
from tests.detectors.fingerprint import fingerprint, run_sequence

EXPECTED = "6522e57b4792ffda4e924b82a610cafdfcd393992c41ebea3edfa9e78be0c4df"


def test_flag_off_fingerprint_is_the_v030_value(gateway: Gateway, evidence: Any) -> None:
    answers = run_sequence(gateway)
    assert fingerprint(gateway, answers, evidence) == EXPECTED
