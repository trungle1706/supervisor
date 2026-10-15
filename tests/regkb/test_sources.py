"""Every stored primary text under regulations/sources/ has a sidecar with url, fetched_at and the
sha256 of the stored bytes; every instrument that claims primary_text_fetched has a stored file."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from supervisor.regkb import load_kb

SOURCES = Path(__file__).resolve().parents[2] / "regulations" / "sources"
FILES = sorted(p for p in SOURCES.glob("*/*") if p.is_file() and not p.name.endswith(".meta.json"))


@pytest.mark.parametrize("path", FILES, ids=[f"{p.parent.name}/{p.name}" for p in FILES])
def test_stored_file_has_matching_sidecar(path: Path) -> None:
    sidecar = path.with_name(path.stem + ".meta.json")
    assert sidecar.is_file(), f"no sidecar for {path.name}"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["url"].startswith("http")
    assert meta["fetched_at"].endswith("Z")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]


def test_primary_text_flag_matches_disk() -> None:
    kb = load_kb()
    for ins in kb.instruments:
        if ins.primary_text_fetched:
            folder = SOURCES / ins.id
            assert folder.is_dir() and any(folder.iterdir()), f"{ins.id}: no stored text"
