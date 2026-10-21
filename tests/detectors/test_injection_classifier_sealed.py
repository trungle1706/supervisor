"""WP25b protocol: the held-out, evasion and adversarial sets are sealed."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from supervisor.config import REPO_ROOT

DATA = REPO_ROOT / "data" / "eval" / "injection_vi_en"
SEALED = ("heldout.jsonl", "evasion.jsonl", "adversarial.jsonl")


def _sha(name: str) -> str:
    return hashlib.sha256((DATA / name).read_bytes()).hexdigest()


def test_sealed_files_have_not_changed() -> None:
    sealed = json.loads((DATA / "SEALED.json").read_text(encoding="utf-8"))["sha256"]
    assert set(sealed) == set(SEALED)
    for name in SEALED:
        assert _sha(name) == sealed[name], f"{name} is sealed (WP25b); do not change it"


def test_manifest_and_every_model_card_carry_the_sealed_hashes() -> None:
    sealed = json.loads((DATA / "SEALED.json").read_text(encoding="utf-8"))["sha256"]
    files = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
    for name in SEALED:
        assert files[name]["sha256"] == sealed[name]
    for card in (REPO_ROOT / "data" / "models" / "injection_vi_en").glob("*/model_card.json"):
        assert json.loads(card.read_text(encoding="utf-8"))["sealed_sets"] == sealed


def test_training_and_tuning_code_never_open_a_sealed_file() -> None:
    for rel in ("tools/train_classifier.py", "tools/cross_validate.py"):
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for name in SEALED:
            assert not re.search(rf"[\"']{name.split('.')[0]}[\"']", text), (rel, name)
    assert isinstance(Path(__file__), Path)


def test_the_loader_refuses_a_sealed_name_at_run_time() -> None:
    """WP25b review: the name check above is static; the loader must also refuse at run time."""
    from tools import train_classifier as TC

    for name in SEALED:
        with pytest.raises(ValueError):
            TC.load_items(name.split(".")[0])
    assert TC.main(["--pools", "heldout", "--no-card", "--out", "/nonexistent"]) == 2
