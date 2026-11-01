"""W4: every label of the inventory run pages exists in English and Vietnamese with the same
placeholders, and the labels carry no setting name or API path."""

from __future__ import annotations

import re
from pathlib import Path

from supervisor.console import factory_inventory_view as fiv
from supervisor.console.i18n_finv import FINV

TEMPLATES = Path(__file__).parents[2] / "src" / "supervisor" / "console" / "templates"
FILES = (
    "factory_inventory_list.html",
    "factory_inventory_run.html",
    "factory_inventory_system.html",
    "_factory_inventory_progress.html",
    "_factory_inventory_dashboard.html",
)
HOLES = re.compile(r"\{(\w+)\}")
DYNAMIC = {
    "finv_b_": ("needs_action", "open", "clear", "errors"),
    "finv_c_": ("team", "level"),
    "finv_es_": ("fail", "open", "pass"),
    "finv_key_": fiv.KEY_LABELS,
    "finv_keyname_": fiv.KEY_LABELS,
    "finv_level_": ("high", "medium", "low", "prohibited", "unspecified"),
    "finv_outcome_": ("classification", "derived"),
    "finv_role_": (
        "system_owner",
        "risk_team",
        "security",
        "data_owner",
        "legal",
        "model_validation",
    ),
    "finv_sev_": ("high", "medium", "low"),
    "finv_state_": ("draft", "tested", "approved", "live", "retired"),
    "finv_status_": ("queued", "running", "done", "cancelled", "failed"),
    "finv_v_": ("fail", "question", "pass", "not_applicable", "none", "error"),
}


def used_keys() -> set[str]:
    keys: set[str] = set()
    for name in (*FILES, "factory_editor.html"):
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for k in re.findall(r"['\"](finv_[a-z0-9_]+)['\"]", text):
            if k in DYNAMIC:
                keys |= {k + v for v in DYNAMIC[k]}
            else:
                keys.add(k)
    return keys


def test_every_used_key_exists_in_both_languages() -> None:
    missing = sorted(k for k in used_keys() if k not in FINV)
    assert not missing, missing
    for k, (en, vi) in FINV.items():
        assert en and vi, k
        assert set(HOLES.findall(en)) == set(HOLES.findall(vi)), k


def test_no_setting_name_or_path_in_a_label() -> None:
    for k, (en, vi) in FINV.items():
        for text in (en, vi):
            assert not re.search(r"[A-Z]{4,}_[A-Z_]+|/console/|/v1/|\bflag\b|\bpayload\b", text), k


def test_the_key_sentences_have_a_count_and_a_single_form() -> None:
    for k in fiv.KEY_LABELS:
        assert "{n}" in FINV[f"finv_key_{k}"][0] and "{n}" in FINV[f"finv_key_{k}"][1]
        assert "{n}" not in FINV[f"finv_key_{k}_one"][0]
