"""WP-UX2 review: i18n completeness of the WP-UX2 block and the drawer breakpoint."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from supervisor.console import i18n

from .conftest import Console

SRC = Path(i18n.__file__).read_text(encoding="utf-8")
CSS = (Path(i18n.__file__).parent / "static" / "console.css").read_text(encoding="utf-8")
# identical in both languages on purpose (ids, product words)
SAME_OK: set[str] = set()


def _ux2_keys() -> list[str]:
    block = SRC.split("# --- WP-UX2:", 1)[1].split("def translator", 1)[0]
    return re.findall(r'^\s+"([a-z0-9_]+)": \(', block, flags=re.M)


def test_ux2_block_is_complete_in_both_languages() -> None:
    keys = _ux2_keys()
    assert len(keys) >= 80, len(keys)
    table = i18n.table()
    missing = [k for k in keys if k not in table]
    assert not missing, missing
    same = [k for k in keys if table[k][0] == table[k][1] and k not in SAME_OK]
    assert not same, same  # every WP-UX2 label has a real Vietnamese text
    assert len(set(keys)) == len(keys), "a key is defined twice in the block"


def test_ux2_dynamic_keys_exist() -> None:
    from supervisor.console import agent_detail, alerts_list, analytics, inbox_list

    known = set(i18n.keys())
    dynamic = (
        [f"alerts_st_{s}" for s in alerts_list.STATUSES]
        + [f"inbox_st_{s}" for s in inbox_list.STATUSES]
        + [f"atab_{s}" for s in agent_detail.TABS]
        + [f"an_tab_{s}" for s in analytics.TABS]
    )
    assert not [k for k in dynamic if k not in known]


@pytest.mark.parametrize(
    "path",
    [
        "/console/alerts",
        "/console/signoff",
        "/console/analytics?tab=gate",
        "/console/analytics?tab=metrics",
        "/console/agents/payments",
        "/console/agents/payments?tab=policy",
        "/console/agents/payments?tab=traces",
    ],
)
def test_vietnamese_pages_hold_no_ux2_english_label(console: Console, path: str) -> None:
    sep = "&" if "?" in path else "?"
    html = console.get(f"{path}{sep}lang=vi").text
    en = {v[0] for k, v in i18n.table().items() if k in set(_ux2_keys()) and len(v[0]) > 12}
    leaked = sorted(s for s in en if f">{s}<" in html)
    assert not leaked, leaked


def test_drawer_sits_beside_the_list_only_from_1600_px() -> None:
    """Review fix: at 1360 px the list kept about 576 px next to the drawer. Side by side
    needs 248 + 56 + 760 + 480 = 1544 px; below 1600 px the drawer lies over the list."""
    m = re.search(
        r"@media \(min-width: (\d+)px\) \{ body:has\(#drawer:not\(\[hidden\]\)\) "
        r"\{ padding-right: 480px; \} \}",
        CSS,
    )
    assert m and int(m.group(1)) >= 1600


# databricks_app mode (SSO headers; the store adapter is covered by the fake-based tests)
from .test_databricks_mode import REVIEWER, TOKEN, dbx  # noqa: E402,F401


def test_ux2_pages_render_in_databricks_app_mode(dbx) -> None:  # noqa: F811
    client, ctx = dbx
    hx = {"HX-Request": "true", **REVIEWER}
    for url in (
        "/console/agents/credit_prequal",
        "/console/agents/credit_prequal/tab/policy",
        "/console/agents/credit_prequal/tab/traces",
        "/console/agents/credit_prequal/tab/cases",
        "/console/alerts",
        "/console/signoff",
        "/console/analytics?tab=gate",
        "/console/analytics?tab=metrics",
        "/console/analytics/tab/latency",
        "/console/cases",
        "/console/inbox",
    ):
        r = client.get(url, headers=hx if "/tab/" in url else REVIEWER)
        assert r.status_code == 200, (url, r.text[:300])
        assert TOKEN not in r.text
    # the service principal (no SSO header) reads but may not act
    r = client.post(
        "/console/agents/credit_prequal/pause", data={"reason": "x"}, headers={"HX-Request": "1"}
    )
    assert r.status_code == 403
    r = client.get("/console/metrics?lang=vi", headers=REVIEWER, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/console/analytics?")
