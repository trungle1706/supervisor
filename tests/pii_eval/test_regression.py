"""PII golden set (data/eval/pii_vn): shape, determinism, and the recall regression gate.

The gate fails on ANY per-entity drop below the committed baseline (``baseline_vn_regex-3.json``),
on any over-masked amount, and on a precision drop of more than 100 bp. To accept a new
baseline after a deliberate change: ``python -m supervisor.pii_eval --record`` and commit it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import pytest

from supervisor.adapters.masking import vn_text
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.data import wordlists as W
from supervisor.pii_eval import generate as G
from supervisor.pii_eval.harness import (
    DATA_DIR,
    evaluate,
    load_items,
    make_masker,
    run_all,
    wilson_bp,
)

BASELINE_V3 = DATA_DIR / "baseline_vn_regex-3.json"
BASELINE_V2 = DATA_DIR / "baseline_vn_regex-2.json"
PRECISION_SLACK_BP = 100


@lru_cache(maxsize=1)
def _report() -> dict[str, Any]:
    return run_all()


def test_golden_set_shape() -> None:
    dev, held = load_items("dev"), load_items("heldout")
    assert len(dev) + len(held) >= 400 and len(held) >= 100
    ids = [x["id"] for x in dev + held]
    assert len(ids) == len(set(ids))
    for it in dev + held:
        for k in ("id", "split", "source", "licence", "labeller", "text", "spans", "keep", "tags"):
            assert k in it
        assert it["labeller"] in ("synthetic", "expert rubric", "human")
        for sp in it["spans"]:
            assert it["text"][sp["start"] : sp["end"]] == sp["text"]
    types = {s["type"] for it in dev + held for s in it["spans"]}
    assert types == set(G.ENTITY_TYPES)
    for t in G.ENTITY_TYPES:  # at least 50 gold spans per entity over both splits
        n = sum(1 for it in dev + held for s in it["spans"] if s["type"] == t)
        assert n >= 50, (t, n)
    tags = {t for it in dev + held for t in it["tags"]}
    for want in ("uppercase", "no-diacritics", "telex", "address", "name-in-email", "cccd-phone",
                 "amount-next-to-account", "g7"):  # fmt: skip
        assert want in tags, want


def test_generator_is_deterministic_and_matches_committed_files() -> None:
    items = G.all_items()
    for split in ("dev", "heldout"):
        want = "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
            for r in items
            if r["split"] == split
        )
        assert (DATA_DIR / f"{split}.jsonl").read_text(encoding="utf-8") == want
    assert G.all_items() == items


def test_heldout_name_pools_stay_out_of_the_lexicon() -> None:
    base = {
        vn_text._k(w)
        for w in W.SURNAMES + W.MIDDLE_MALE + W.MIDDLE_FEMALE + W.GIVEN_MALE + W.GIVEN_FEMALE
    }
    held = {vn_text._k(w) for w in G.HELD_SURNAMES + G.HELD_MIDDLE + G.HELD_GIVEN} - base
    assert held, "held-out pools must add words the generator lists do not have"
    leaked = held & vn_text.NAME_LEXICON
    assert not leaked, f"never tune on the held-out split: {sorted(leaked)}"


def test_wilson_interval_known_values() -> None:
    assert wilson_bp(0, 0) is None
    lo, hi = wilson_bp(50, 50) or (0, 0)
    assert hi == 10000 and 9000 <= lo <= 9300  # 50/50 -> about [92.9%, 100%]
    lo, hi = wilson_bp(5, 10) or (0, 0)
    assert 2300 <= lo <= 2500 and 7500 <= hi <= 7700


def test_baselines_are_committed_and_v3_beats_v2() -> None:
    v2, v3 = json.loads(BASELINE_V2.read_text()), json.loads(BASELINE_V3.read_text())
    assert v2["masker"] == "vn_regex-2" and v3["masker"] == "vn_regex-3"
    for split in ("dev", "heldout"):
        for ent, b2 in v2["splits"][split]["entities"].items():
            b3 = v3["splits"][split]["entities"][ent]
            assert b3["leak_recall_bp"] >= b2["leak_recall_bp"], (split, ent)
        assert v2["splits"][split]["over_mask_amount_count"] > 0
        assert v3["splits"][split]["over_mask_amount_count"] == 0


@pytest.mark.parametrize("split", ["dev", "heldout"])
def test_no_recall_drop_per_entity(split: str) -> None:
    base = json.loads(BASELINE_V3.read_text())["splits"][split]
    now = _report()["splits"][split]
    for ent, b in base["entities"].items():
        cur = now["entities"][ent]
        assert cur["leak_recall_bp"] >= b["leak_recall_bp"], f"{split} {ent} leak recall dropped"
        assert cur["typed_recall_bp"] >= b["typed_recall_bp"], f"{split} {ent} typed recall dropped"
        assert cur["precision_bp"] + PRECISION_SLACK_BP >= b["precision_bp"], (
            f"{split} {ent} precision dropped"
        )


@pytest.mark.parametrize("split", ["dev", "heldout"])
def test_amounts_are_never_over_masked(split: str) -> None:
    now = _report()["splits"][split]
    assert now["over_mask_amount_count"] == 0  # hard fail: the rules need the amount
    assert all(v["touched"] == 0 for v in now["keep"].values())


def test_direct_identifier_floor_on_both_splits() -> None:
    """Structured identifiers are the primary metric: nothing leaks (ILLUSTRATIVE floor)."""
    for split, r in _report()["splits"].items():
        for ent in ("CCCD", "CMND", "PHONE", "EMAIL", "TAX_CODE", "BANK_ACCOUNT", "CARD_NUMBER"):
            assert r["entities"][ent]["leak_recall_bp"] == 10000, (split, ent)


def test_amount_entity_mode_when_the_capture_level_asks() -> None:
    items = load_items("dev")
    r = evaluate(make_masker(amounts=True), items, amounts_masked=True)
    assert r["entities"]["AMOUNT"]["leak_recall_bp"] == 10000
    assert r["entities"]["BANK_ACCOUNT"]["precision_bp"] == 10000


def test_masker_is_deterministic_on_the_golden_set() -> None:
    a, b = make_masker(), make_masker()
    assert isinstance(a, VnRegexMasker)
    for it in load_items("dev")[:60]:
        assert a.mask(it["text"]) == b.mask(it["text"])
