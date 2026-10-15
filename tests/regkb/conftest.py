"""Small fixture knowledge bases written to tmp_path (independent of the research data)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

SRC = {
    "url": "https://example.invalid/doc",
    "title": "Doc",
    "fetched_at": "2026-10-15",
    "kind": "primary",
}


def instrument(iid: str = "VN-TEST-2026", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": iid,
        "jurisdiction": "VN",
        "kind": "law",
        "issuer": "Test Issuer",
        "number": "1/2026/QH15",
        "title_vi": "Luat thu nghiem",
        "title_en": "Test law",
        "status": "in_force",
        "binding": True,
        "dates": {
            "issued": {
                "date": "2026-01-01",
                "source": "https://example.invalid/d",
                "verification": "VERIFIED_PRIMARY",
            }
        },
        "sources": [dict(SRC)],
        "verification": "VERIFIED_PRIMARY",
        "primary_text_fetched": False,
        "last_checked": "2026-10-15",
    }
    data.update(over)
    return data


def obligation(oid: str = "VN-TEST-2026-A1-01", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": oid,
        "article_ref": "Art. 1",
        "text_vi": "Dieu 1",
        "summary_en": "Test duty.",
        "duties": ["human_oversight"],
        "applies_to": {"agent_class": ["any"]},
        "control_mapping": [{"kind": "catalogue", "id": "pii_masking", "coverage": "partial"}],
        "evidence_needed": ["a record"],
        "verification": "VERIFIED_PRIMARY",
        "sources": [dict(SRC)],
        "confidence": "high",
    }
    data.update(over)
    return data


def kb_file(inst: dict[str, Any] | None = None, obs: list[dict[str, Any]] | None = None):
    return {
        "schema_version": 1,
        "instrument": inst or instrument(),
        "obligations": obs if obs is not None else [obligation()],
    }


def write_file(directory: Path, name: str, data: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(yaml.safe_dump(copy.deepcopy(data), allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """tmp_path/regulations with one valid VN file."""
    reg = tmp_path / "regulations"
    write_file(reg / "vn", "test.yaml", kb_file())
    (reg / "intl").mkdir()
    return reg
