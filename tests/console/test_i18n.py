"""WP12: every console label exists in English and Vietnamese; templates use known keys."""

from __future__ import annotations

import re
from pathlib import Path

from supervisor.cases.service import SEVERITIES
from supervisor.console import i18n, readmodels
from supervisor.console.routes import CASE_TABS, SOURCE_KINDS

TEMPLATES = Path(i18n.__file__).parent / "templates"


def test_both_dictionaries_have_the_same_keys() -> None:
    table = i18n.table()
    en = {k: v[0] for k, v in table.items()}
    vi = {k: v[1] for k, v in table.items()}
    assert set(en) == set(vi)
    assert all(isinstance(v, tuple) and len(v) == 2 for v in table.values())
    empty = [k for k in table if not en[k].strip() or not vi[k].strip()]
    assert not empty, empty


def test_placeholders_match_between_languages() -> None:
    for key, (en, vi) in i18n.table().items():
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", vi)), key


def test_every_literal_key_in_templates_exists() -> None:
    known = set(i18n.keys())
    used: set[str] = set()
    for path in TEMPLATES.glob("*.html"):
        used |= set(re.findall(r"\bt\('([a-z0-9_]+)'\s*[,)]", path.read_text(encoding="utf-8")))
    missing = sorted(used - known)
    assert not missing, missing


def test_dynamic_keys_exist() -> None:
    known = set(i18n.keys())
    dynamic = (
        [
            f"role_{r}"
            for r in ("admin", "approver", "reviewer", "owner", "auditor", "service", "viewer")
        ]
        + [f"stage_{s}" for s in readmodels.STAGES]
        + [f"ws_{s}" for s in readmodels.STAGES]
        + [f"src_{s}" for s in SOURCE_KINDS]
        + [f"opened_by_{s}" for s in SOURCE_KINDS]
        + [f"tab_{s}" for s in CASE_TABS]
        + [f"flow_{s}" for s in readmodels.CASE_FLOW]
        + [f"next_{s}" for s in ("triaged", "contained", "closed")]
        + [f"outcome_{s}" for s in ("blocked", "paused", "allowed")]
        + [f"fail_{s}" for s in ("closed", "open", "mixed", "-")]
        + [f"kind_{s}" for s in ("audit", "chain")]
        + [f"key_{s}" for s in ("dev", "managed")]
        + [f"anchor_target_{s}" for s in ("worm", "uc")]
        + list(readmodels.RISK_WORD.values())
        + list(readmodels.WHAT_BY_CLASS.values())
        + ["what_call", "hl_pause", "hl_block", "ev_close", "ev_other", "st_signoff"]
        + ["case_line_pause", "case_line_block", "contain_btn", "contain_btn_running"]
        + list(readmodels.EVENT_KEYS.values())
        + [
            "st_planned",
            "st_read",
            "st_called",
            "st_rule_pause",
            "st_rule_block",
            "st_t0b",
            "st_judge",
        ]
        + ["greet_morning", "greet_afternoon", "greet_evening"]
        + ["cov_src_capabilities", "cov_src_metric", "cov_src_events", "cov_src_none"]
        + ["stage_note_shadow", "stage_note_enforced"]
        + list(SEVERITIES)
        + ["open", "triaged", "contained", "closed", "confirmed", "false_alarm"]
        + [
            f"h_{s}"
            for s in ("mode", "identity", "judge", "key", "anchor", "databricks", "onboard")
        ]
    )
    missing = sorted(set(dynamic) - known)
    assert not missing, missing


def test_translator_formats_and_falls_back() -> None:
    t_en, t_vi = i18n.translator("en"), i18n.translator("vi")
    assert t_en("greet_evening", name="An") == "Good evening, An"
    assert t_vi("greet_evening", name="An") == "Chào buổi tối, An"
    assert t_en("no_such_key") == "no_such_key"
    assert t_en("greet_evening") == "Good evening, {name}"  # no kwargs: raw text


def test_no_key_is_defined_twice() -> None:
    """A key in the ``_T`` literal and again in a ``_T.update({...})`` block (or twice in one
    literal) silently overrides the first text. Found at the wave-1 merge of WP-UX2 and WP-UX3."""
    import ast
    from collections import Counter

    tree = ast.parse(Path(i18n.__file__).read_text(encoding="utf-8"))
    keys = Counter(
        k.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    )
    assert [k for k, n in keys.items() if n > 1] == []
