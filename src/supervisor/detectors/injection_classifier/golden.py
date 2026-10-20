"""Loader for the injection classifier golden set (WP25). Files: ``data/eval/injection_vi_en/``.

Splits: ``train`` (fitting only), ``dev`` (thresholds), ``heldout`` (reported), ``evasion``
(heldout positives and benign twins re-written with one evasion), ``adversarial`` (62 hand-written
probes). Provenance of every item: ``id, source, licence ("synthetic, this repo"), label,
labeller``. Regenerate with ``uv run python data/eval/injection_vi_en/generate.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from supervisor.config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data" / "eval" / "injection_vi_en"
SPLITS = ("train", "train_b", "dev", "heldout", "evasion", "adversarial")


def load(split: str) -> list[dict[str, Any]]:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    path = DATA_DIR / f"{split}.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def manifest() -> dict[str, Any]:
    return json.loads((DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def verify_files() -> list[str]:
    """Names of golden files whose SHA-256 differs from MANIFEST.json (empty = intact)."""
    bad = []
    for name, info in manifest()["files"].items():
        data = (DATA_DIR / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            bad.append(name)
    return bad
