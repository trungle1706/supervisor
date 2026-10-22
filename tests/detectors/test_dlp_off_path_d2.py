"""WP-D2 golden: with ``secrets`` absent and ``custom_rules`` empty, ``dlp_vn`` output is byte for
byte what it was before WP-D2. ``EXPECTED`` was computed on the commit before WP-D2."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.detectors.dlp_vn import DlpVnDetector

PAYLOADS: list[tuple[dict[str, Any], str]] = [
    ({"args": {"note": "Chuyen 1.500.000.000 VND, so dien thoai 0912345678"}}, "input"),
    ({"args": {"cccd": "001203004567", "payee_name": "NGUYEN VAN THU"}}, "input"),
    ({"args": {"mst": "0312345678", "stk": "190123456789"}}, "input"),
    ({"args": {"c": {"notes": ["ok", "lien he a.nguyen@example.com"]}}}, "input"),
    ({"output": "So the 4111 1111 1111 1111 cua khach, email khach@example.com"}, "output"),
    ({"args": {"id": "C-1"}, "tool_results": [{"body": "SDT 0987654321"}]}, "input"),
    ({"args": {"note": "khong co gi ca"}}, "input"),
    ({"args": {"k": "password = 'S3cr3t-Value!' va token abcdefghijklmnop"}}, "input"),
]
SETTINGS: list[dict[str, Any]] = [
    {"preset": "balanced"},
    {"preset": "strict", "mode": "transform", "transform_risk_classes": ["pii_export"]},
    {"preset": "balanced", "mode": "report"},
    {"preset": "balanced", "pseudonym_mode": "typed", "transform_tools": ["add_payee"]},
]
EXPECTED = "c048410d6d6411430066065b787c9c0fdf5f4b44332d9b7d707a1bf8e1fd7a0b"


def _digest(extra: dict[str, Any] | None = None) -> str:
    det = DlpVnDetector(VnRegexMasker(b"golden-d2-key", "g"))
    rows = []
    for settings in SETTINGS:
        for payload, direction in PAYLOADS:
            p = dict(payload)
            p["meta"] = {"tool_name": "add_payee", "risk_class": "pii_export"}
            found = det.evaluate(p, {**settings, **(extra or {})}, direction)
            rows.append(
                [{"f": f.to_dict(), "t": f.transformed_payload, "d": f.digest()} for f in found]
            )
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_dlp_vn_off_path_is_byte_identical() -> None:
    if EXPECTED == "PLACEHOLDER":
        pytest.fail(_digest())
    assert _digest() == EXPECTED


def test_explicit_off_values_are_byte_identical() -> None:
    """``secrets`` present but disabled, empty rules and empty mask tokens: same bytes."""
    off = {
        "secrets": {"enabled": False, "action": "report"},
        "custom_rules": [],
        "mask_tokens": {},
    }
    assert _digest(off) == EXPECTED
