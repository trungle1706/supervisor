from __future__ import annotations

import json
from pathlib import Path

from supervisor.config import load_settings
from supervisor.judge.mrm import card as card_mod
from supervisor.judge.mrm._common import identity_for, router_factory
from supervisor.judge.mrm.card import build_card, render_card_md

NOW = "2026-10-15T00:00:00+00:00"


def _now():
    return card_mod.parse_now(NOW)


def test_card_builds_with_identity_and_roles(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path)
    card = build_card(s, now=_now())
    ident = identity_for(s, router_factory(s, "settings")())
    assert card["identity"]["prompt_hash"] == ident.prompt_hash
    assert card["identity"]["is_mock"] is True
    assert card["identity"]["tiers"]["t1"]["kind"] == "mock"
    assert all("FILL-ME" in v for v in card["roles"].values())
    assert set(card["roles"]) == {"owner", "developer", "validator", "approver"}
    assert card["metrics"]["status"] == "ok"
    assert card["metrics"]["split"] == "heldout"
    assert card["data"]["golden_set_hash"] == ident.golden_set_hash


def test_card_missing_eval_report(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path)
    card = build_card(s, eval_report_path=tmp_path / "none.json", now=_now())
    assert card["metrics"] == {"status": "no_eval_report"}
    assert "no eval report" in render_card_md(card)


def test_md_and_json_deterministic(tmp_path: Path) -> None:
    s = load_settings(data_dir=tmp_path)
    a = build_card(s, now=_now())
    b = build_card(s, now=_now())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    md = render_card_md(a)
    assert "## Identity" in md and "FILL-ME" in md and md.isascii()


def test_cli_writes_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert card_mod.main(["--out", str(out), "--now", NOW]) == 0
    assert (out / "judge_model_card.json").is_file()
    assert (out / "judge_model_card.md").is_file()
    first = (out / "judge_model_card.json").read_bytes()
    assert card_mod.main(["--out", str(out), "--now", NOW]) == 0
    assert (out / "judge_model_card.json").read_bytes() == first
