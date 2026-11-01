"""The console link check (UI audit batch 1) is ``tools/check_ui_links.py``. It must run in a
fresh process with the production flag set, so CI runs it as its own step (.github/workflows/
tests.yml); a pytest worker has already imported the app with other settings. These tests cover
the parts that do not need the app."""

from __future__ import annotations

from tools import check_ui_links as cl


def test_pattern_folds_ids_and_keeps_tab_drawer_filter() -> None:
    assert cl.pattern("/console/systems/shw_sys_0081?tab=duties&lang=en") == (
        "/console/systems/*?tab"
    )
    assert cl.pattern("/console/systems/shw_sys_0082?tab=duties") == cl.pattern(
        "/console/systems/shw_sys_0081?tab=duties"
    )


def test_the_link_pattern_reads_href_and_hx_get() -> None:
    page = '<a href="/console/cases?x=1">a</a><div hx-get="/console/inbox"></div><a href="#t">'
    assert [m.group(1) for m in cl.LINK.finditer(page)] == ["/console/cases?x=1", "/console/inbox"]


def test_the_flag_set_is_the_production_set_plus_the_new_flags() -> None:
    assert cl.PROD_FLAGS["CONSOLE_NAV_V3"] == "1" and cl.PROD_FLAGS["CONSOLE_UX5"] == "1"
    assert cl.PROD_FLAGS["SCHEDULER_ENABLED"] == "0"
    assert cl.PROD_FLAGS["STORE_READ_CACHE"] == "1" and cl.PROD_FLAGS["KBGRAPH_ENABLED"] == "1"


def test_a_too_small_crawl_fails() -> None:
    assert cl.MIN_PAGES >= 30 and cl.MIN_LINKS >= 150


def _good_facts() -> dict[str, object]:
    return {
        "risks_controls": [303, "/console/compliance?lang=en"],
        "guardians": [303, "/console/catalog?lang=en"],
        "detectors": [303, "/console/catalog?cat=detect&lang=en"],
        "judges": [303, "/console/catalog?cat=judge&lang=en"],
        "agents": [303, "/console/my/agents?scope=all&lang=en"],
        "agents_q": [303, "/console/my/agents?scope=all&q=abc&lang=en"],
        "side_hrefs": [
            "/console/compliance?lang=en",
            "/console/catalog?lang=en",
            "/console/catalogues?tab=models&lang=en",
        ],
        "cat_agents_tab": False,
        "cat_strip": ["models"],
        "catalog_tabs": False,
        "strip_onboard": False,
        "sys_tabs": ["overview"],
        "inventory_has_unmanaged_table": False,
        "inventory_candidates_link": True,
        "home_has_items_chip": False,
        "gov_flag_names": False,
        "systems_tiles_are_links": False,
        "catalog_off_hint_n": 1,
        "workflows_scheduler_table_rows": 0,
        "evidence_status": 200,
    }


def test_batch2_checks_pass_on_good_facts_and_name_each_failure() -> None:
    assert all(cl.batch2_checks(_good_facts()).values())
    bad = {**_good_facts(), "guardians": [200, ""], "gov_flag_names": True}
    failed = [k for k, ok in cl.batch2_checks(bad).items() if not ok]
    assert len(failed) == 2 and any("UI-310" in k for k in failed)
