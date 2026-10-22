"""WP-D3: the Catalog card of the guard model (English and Vietnamese, advises, off by default)."""

from __future__ import annotations

from types import SimpleNamespace

from supervisor.console import catalog_view, i18n


def entry() -> catalog_view.Entry:
    return next(e for e in catalog_view.ENTRIES if e.key == "guard_model")


def test_the_card_advises_and_names_its_switch_and_doc() -> None:
    e = entry()
    assert e.cat == "detect" and e.kind == "advises"
    assert "guard_model.enabled" in e.env and e.doc == "docs/guard-model-decision.md"
    assert catalog_view.KINDS[e.kind][1] == "catk_advises"


def test_the_card_is_on_only_with_the_flag_and_the_enabled_entry() -> None:
    e = entry()
    assert e.on is not None
    s_on, s_off = SimpleNamespace(detectors_enabled=True), SimpleNamespace(detectors_enabled=False)
    assert e.on(s_on, {"guard_model": True}) is True
    assert e.on(s_on, {"guard_model": False}) is False
    assert e.on(s_on, {}) is False
    assert e.on(s_off, {"guard_model": True}) is False


def test_the_texts_exist_in_english_and_vietnamese() -> None:
    t_en, t_vi = i18n.translator("en"), i18n.translator("vi")
    for key in ("cat_guard_model", "cat_guard_model_d"):
        en, vi = t_en(key), t_vi(key)
        assert en != key and vi != key and en != vi
    assert "approver" in t_en("cat_guard_model_d") and "phê duyệt" in t_vi("cat_guard_model_d")
