"""Objective catalogue: provenance, twins, descriptions, splits, limits in step with the policy."""

from __future__ import annotations

import re
from collections import Counter

import yaml

from supervisor.redteam.multiturn import __main__ as cli
from supervisor.redteam.multiturn.catalogue import (
    FAMILY_KINDS,
    build_objectives,
    dumps_objectives,
    load_objectives,
    validate_objectives,
)
from supervisor.redteam.multiturn.model import FAMILIES, Objective
from supervisor.redteam.multiturn.phrases import PH
from supervisor.redteam.multiturn.plans import (
    CRD_AMOUNT_LIMIT,
    DAY_S,
    KINDS,
    PAY_DAILY_LIMIT,
    PAY_SINGLE_LIMIT,
    SPLIT_WINDOW_S,
    SVC_WAIVER_LIMIT,
)
from tests.conftest import REPO_ROOT


def test_committed_data_files_are_current() -> None:
    assert cli.build_data(check=True) == 0


def test_catalogue_size_and_provenance(objectives: list[Objective]) -> None:
    assert validate_objectives(objectives) == []
    assert len(objectives) == 122
    per_family = Counter(o.family for o in objectives if o.lang == "vi")
    assert set(per_family) == set(FAMILIES)
    assert all(n >= 10 for n in per_family.values())
    for o in objectives:
        assert (o.source, o.licence, o.label, o.labeller) == (
            "own",
            "own",
            "attack",
            "expert rubric",
        )
        assert o.success_description.strip() and o.benign_description.strip()
        assert o.theme.get("purpose")


def test_twins_share_everything_but_language(objectives: list[Objective]) -> None:
    by_pair: dict[str, list[Objective]] = {}
    for o in objectives:
        by_pair.setdefault(o.pair_id, []).append(o)
    assert len(by_pair) == 61
    for pair in by_pair.values():
        vi, en = sorted(pair, key=lambda o: o.lang, reverse=True)
        assert (vi.lang, en.lang) == ("vi", "en")
        for f in ("family", "agent", "kind", "oracle", "expected_rules", "gap_class", "split"):
            assert getattr(vi, f) == getattr(en, f)
        assert vi.success_description != en.success_description
        assert re.search(r"[ăâđêôơư]", vi.success_description)  # real Vietnamese, with diacritics
        assert vi.theme["purpose"] != en.theme["purpose"]


def test_ids_are_unique_and_serialisation_is_stable(objectives: list[Objective]) -> None:
    assert len({o.id for o in objectives}) == len(objectives)
    assert dumps_objectives(build_objectives()) == dumps_objectives(load_objectives())


def test_split_is_30_percent_and_balanced(objectives: list[Objective]) -> None:
    held = [o for o in objectives if o.split == "heldout"]
    assert len(held) == 36  # 3 of 10 ordinals in each of 6 families, two languages
    assert Counter(o.family for o in held if o.lang == "vi") == dict.fromkeys(FAMILIES, 3)


def test_every_family_kind_exists_and_all_kinds_are_used() -> None:
    used = {k for kinds in FAMILY_KINDS.values() for k in kinds}
    assert used == set(KINDS)
    for fam, kinds in FAMILY_KINDS.items():
        assert len(kinds) == len(set(kinds)) == (11 if fam == "payload_split" else 10), fam


def test_limits_in_the_plans_match_the_baseline_policy() -> None:
    doc = yaml.safe_load((REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8"))
    rules = {r["id"]: r for r in doc["rules"]}

    def cond(rid: str) -> dict:
        return rules[rid]["when"]["all"][0]

    assert cond("PAY-02")["value"] == PAY_SINGLE_LIMIT
    assert rules["PAY-03"]["aggregate"]["limit"] == PAY_DAILY_LIMIT
    assert rules["PAY-03"]["aggregate"]["window_s"] == DAY_S
    assert rules["PAY-08"]["aggregate"]["limit"] == PAY_SINGLE_LIMIT
    assert rules["PAY-08"]["aggregate"]["window_s"] == SPLIT_WINDOW_S
    assert cond("SVC-01")["value"] == SVC_WAIVER_LIMIT
    assert cond("CRD-03")["value"] == CRD_AMOUNT_LIMIT
    assert rules["PAY-09"]["aggregate"]["limit"] == 3
    assert rules["SVC-02"]["aggregate"]["limit"] == 2
    assert rules["SVC-06"]["aggregate"]["limit"] == 2


def test_expected_rules_exist_in_the_policy_and_gaps_have_none(objectives: list[Objective]) -> None:
    doc = yaml.safe_load((REPO_ROOT / "policies" / "baseline.yaml").read_text(encoding="utf-8"))
    ids = {r["id"] for r in doc["rules"]}
    for o in objectives:
        assert set(o.expected_rules) <= ids
        if o.gap_class == "rule-missing":
            assert o.expected_rules == []


def test_phrase_pools_have_the_same_keys_in_both_languages() -> None:
    assert set(PH["vi"]) == set(PH["en"])
    for lang in PH:
        for key, variants in PH[lang].items():
            assert variants, key
            assert len(set(variants)) == len(variants), (lang, key)
