"""Link check of the console (UI audit batch 1: UI-001, UI-091, UI-092, UI-190).

With the production flag set (the 0/1 values of the bank App ``app.yaml``, v0.11.0, with the
scheduler off and the read cache and the regulation graph on) on a fresh seeded SQLite store,
every link on the console pages must answer below 400 for an administrator.

Everything runs in this one process (no subprocess): the flags are set in the environment
before ``supervisor`` is imported, because the app mounts routers and reads page flags once at
import. That is also why this is a tool and not a pytest test: a pytest worker has already
imported the app with other settings. CI runs it as its own step.

    python -m tools.check_ui_links [--systems 12] [--max-pages 120]

Read only on the console: it follows ``href`` and ``hx-get`` links with GET, as admin, and never
submits a form. Exit 0 when no link is 400 or above and the crawl is not empty, else 1."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

PROD_FLAGS: dict[str, str] = {
    "AGENTS_API_ENABLED": "1",
    "SSL_OS_TRUSTSTORE": "0",
    "SCHEDULER_ENABLED": "0",
    "GATE_RECORD_ASYNC": "1",
    "JUDGE_ENABLED": "1",
    "JUDGE_FAMILY_CONFLICT_ALLOW": "1",
    "SCHEMA_SELFCHECK": "1",
    "CLASSIFIER_AI_PREFILL": "1",
    "ONBOARD_ADVISOR_ENABLED": "1",
    "ONBOARD_COMPLIANCE_ENABLED": "1",
    "CONSOLE_INTEGRATION_ENABLED": "1",
    "CONSOLE_COMPLIANCE_ENABLED": "1",
    "GOVERNANCE_ENABLED": "1",
    "CONSOLE_SYSTEMS_ENABLED": "1",
    "CONSOLE_NAV_SECTIONS": "1",
    "CONSOLE_NAV_V3": "1",
    "CONSOLE_CATALOG_ENABLED": "1",
    "INVENTORY_ENABLED": "1",
    "GOVERNANCE_ACTIONS_ENABLED": "1",
    "GUARDIAN_BINDINGS_ENABLED": "1",
    "MCP_SERVER_ENABLED": "1",
    "CONSOLE_WORKFLOW_ACTIONS": "1",
    "WEBHOOKS_ENABLED": "0",
    "TRANSPARENCY_ENABLED": "1",
    "INVENTORY_SCAN_V2": "0",
    "INVENTORY_AUTOREGISTER": "0",
    "CONSOLE_OVERVIEW_V4": "1",
    "CONSOLE_MY_AGENTS": "1",
    "CONSOLE_REGISTER_V2": "1",
    "CONSOLE_REGISTER_DUTIES": "1",
    "RISK_DUTIES": "1",
    "RISK_DIMENSIONS": "1",
    "ONBOARD_ORCHESTRATOR": "1",
    "SMART_GUARDIAN": "1",
    "AGENT_FACTORY": "1",
    "GUARDIAN_FACTORY": "1",
    "GUARDIAN_SHADOW": "1",
    "OVERVIEW_PORTFOLIO": "1",
    "AGENT_FACTORY_GATE": "1",
    "FACTORY_SEED_STARTERS": "1",
    "REGULATOR_PACK": "1",
    "CONSOLE_STATE_ACTIONS": "1",
    "ONBOARD_INTAKE": "1",
    "ONBOARD_FACTS": "1",
    "CLASSIFICATION_V2": "1",
    "REGISTER_V3": "1",
    "ONBOARD_PREDEPLOY": "1",
    "ONBOARD_ATTACH_VIEW": "1",
    "PREDEPLOY_HTTP_TARGET": "1",
    "ONBOARD_POSTDEPLOY": "1",
    "DETECTORS_ENABLED": "1",
    "DOCUMENT_INTAKE_ENABLED": "1",
    "URL_FETCH_ENABLED": "0",
    "GUARD_MODEL_FAIL_CLOSED_APPROVED": "0",
    "LAWAGENT_ENABLED": "1",
    "REGKB_INTERNAL": "1",
    "REGWATCH_ENABLED": "1",
    "REGKB_CHANGE_LOOP": "1",
    "SHOWCASE_ENABLED": "1",
    "INLINE_REDACTION_ENABLED": "1",
    "CONSOLE_UX5": "1",
    "STORE_READ_CACHE": "1",
    "KBGRAPH_ENABLED": "1",
    "CODE_AGENT_ENABLED": "1",
}

ADMIN = {"X-Dev-User": "admin.chi"}
LINK = re.compile(r"""(?:href|hx-get)="(/[^"#]*)\"""")
SKIP = ("/console/static", "/static", "/docs", "/openapi", "/redoc")
PER_PATTERN = 2  # pages fetched per URL pattern (the first two examples)
MIN_PAGES, MIN_LINKS = 30, 150  # an empty crawl must fail, not pass


def setup_env(data: Path) -> None:
    for k in [k for k in os.environ if k.startswith("SUPERVISOR_")]:
        del os.environ[k]
    os.environ.pop("DATABRICKS_TOKEN", None)
    os.environ.update(PROD_FLAGS)
    os.environ.update(
        {
            "SCHEDULER_ENABLED": "0",
            "SUPERVISOR_ENV_FILE": os.devnull,
            "DATA_DIR": str(data),
            "SQL_BACKEND": "sqlite",
            "SUPERVISOR_MODE": "laptop",
        }
    )


def seed(systems: int) -> None:
    from supervisor.demo import showcase
    from supervisor.jobs import bootstrap_schema

    assert bootstrap_schema.main([]) == 0, "bootstrap_schema failed"
    assert showcase.main(["portfolio", "--systems", str(systems), "--seed", "1"]) == 0
    assert showcase.main(["journeys", "--step", "1"]) == 0


def pattern(url: str) -> str:
    path, _, query = url.partition("?")
    path = re.sub(r"/[^/]*\d[^/]*", "/*", path)
    keep = sorted(
        k for k in (p.split("=")[0] for p in query.split("&") if p) if k in ("tab", "drawer", "f")
    )
    return path + "?" + ",".join(keep)


def run(max_pages: int) -> dict[str, object]:
    from fastapi.testclient import TestClient

    from supervisor.app import app

    with TestClient(app, raise_server_exceptions=False) as client:
        status: dict[str, int] = {}
        found_on: dict[str, set[str]] = defaultdict(set)
        per: dict[str, int] = defaultdict(int)
        queue = ["/console/"]
        seen_pages: set[str] = set()
        n_pages = 0
        while queue and n_pages < max_pages:
            url = queue.pop(0)
            if url in seen_pages:
                continue
            seen_pages.add(url)
            sep = "&" if "?" in url else "?"
            r = client.get(f"{url}{sep}lang=en", headers=ADMIN)
            status[url] = r.status_code
            if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                continue
            n_pages += 1
            for m in LINK.finditer(r.text):
                u = html.unescape(m.group(1))
                if u.startswith(SKIP) or "/export" in u or "download" in u:
                    continue
                if u.startswith("//") or "lang=" in u and u.startswith("?"):
                    continue
                u = re.sub(r"([?&])lang=\w+", r"\1", u).rstrip("?&").replace("?&", "?")
                found_on[u].add(url)
                if u.startswith("/console") and u not in seen_pages:
                    key = pattern(u)
                    if per[key] < PER_PATTERN and u not in queue:
                        per[key] += 1
                        queue.append(u)
        bad = []
        for u in sorted(found_on):
            if u not in status:
                sep = "&" if "?" in u else "?"
                status[u] = client.get(f"{u}{sep}lang=en", headers=ADMIN).status_code
            if status[u] >= 400:
                bad.append({"url": u, "status": status[u], "on": sorted(found_on[u])[:3]})
        return {"pages": n_pages, "links": len(found_on), "bad": bad}


def page_facts() -> dict[str, object]:
    """UI audit batch 2 facts: redirects (not followed), the sidebar hrefs and page facts."""
    from fastapi.testclient import TestClient

    from supervisor.app import app

    out: dict[str, object] = {}
    with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as c:

        def get(url: str):  # noqa: ANN202
            sep = "&" if "?" in url else "?"
            return c.get(f"{url}{sep}lang=en", headers=ADMIN)

        for key, url in {
            "risks_controls": "/console/risks-controls",
            "guardians": "/console/guardians",
            "detectors": "/console/guardians?tab=detectors",
            "judges": "/console/guardians?tab=judges",
            "agents": "/console/agents",
            "agents_q": "/console/agents?q=abc",
        }.items():
            r = get(url)
            out[key] = [r.status_code, r.headers.get("location", "")]
        home = get("/console/")
        found = re.findall(r'<a href="(/console[^"]*)" class="', home.text)
        out["side_hrefs"] = sorted({html.unescape(h) for h in found})
        out["home_has_items_chip"] = "items wait for you" in home.text
        out["home_has_open_cases_chip"] = "g1-facts" in home.text and "open cases</a>" in home.text
        sysd = get("/console/systems/shw_sys_0001?tab=overview")
        out["sys_tabs"] = sorted(set(re.findall(r'data-tab="(\w+)"', sysd.text)))
        out["systems_tiles_are_links"] = 'class="tile ' in get("/console/systems").text
        out["strip_onboard"] = "/console/onboard" in get("/console/systems").text
        out["cat_strip"] = sorted(
            set(
                re.findall(
                    r"/console/catalogues\?tab=(\w+)", get("/console/catalogues?tab=models").text
                )
            )
        )
        out["cat_agents_tab"] = "/console/agents" in get("/console/catalogues?tab=models").text
        cat = get("/console/catalog")
        out["catalog_tabs"] = "tab=detectors" in cat.text or "tab=judges" in cat.text
        out["catalog_off_hint_n"] = cat.text.count("Ask the platform team")
        gov = get("/console/governance")
        out["gov_flag_names"] = bool(re.search(r"[A-Z]+_ENABLED", gov.text))
        inv = get("/console/inventory")
        out["inventory_has_unmanaged_table"] = 'id="inv-unmanaged"' in inv.text
        out["inventory_candidates_link"] = "/console/candidates" in inv.text
        ev = get("/console/evidence")
        out["evidence_status"] = ev.status_code
        out["evidence_quiet"] = "chain is empty" not in ev.text.lower() or "Lanes" not in ev.text
        wf = get("/console/workflows")
        out["workflows_scheduler_table_rows"] = wf.text.count("not running in this process")
    return out


def batch2_checks(f: dict[str, object]) -> dict[str, bool]:
    """UI audit batch 2: one canonical page per concept, duplicates redirect (303) and leave the
    nav, dead or repeated blocks are gone. Old flag paths stay in the code (owner decision)."""
    hrefs = set(f["side_hrefs"])  # type: ignore[call-overload]
    agents, agents_q = f["agents"], f["agents_q"]
    return {
        "risks-controls redirects to Compliance (UI-310)": f["risks_controls"]
        == [303, "/console/compliance?lang=en"],
        "guardians redirects to Library (UI-310)": f["guardians"]
        == [303, "/console/catalog?lang=en"],
        "agents redirects to My agents, keeps q (UI-011)": agents[0] == 303  # type: ignore[index]
        and str(agents[1]).startswith("/console/my/agents?scope=all")  # type: ignore[index]
        and "q=abc" in str(agents_q[1]),  # type: ignore[index]
        "detectors tab redirects to a Library chip (UI-160)": f["detectors"]
        == [303, "/console/catalog?cat=detect&lang=en"],
        "judges tab redirects to a Library chip (UI-160)": str(f["judges"][1]).startswith(  # type: ignore[index]
            "/console/catalog?cat=judge"
        ),
        "sidebar opens canonical URLs": {
            "/console/compliance?lang=en",
            "/console/catalog?lang=en",
            "/console/catalogues?tab=models&lang=en",
        }
        <= hrefs
        and not hrefs
        & {
            "/console/risks-controls?lang=en",
            "/console/guardians?lang=en",
            "/console/catalogues?lang=en",
        },
        "no Agents tab under Catalogues (UI-011)": f["cat_agents_tab"] is False,
        "Inventory not a Catalogues tab": "unmanaged" not in f["cat_strip"],  # type: ignore[operator]
        "no detector/judge tabs on Library (UI-160)": f["catalog_tabs"] is False,
        "no Onboard tab while it is off (UI-080)": f["strip_onboard"] is False,
        "no Reviews tab before a review (UI-069)": "reviews" not in f["sys_tabs"],  # type: ignore[operator]
        "Inventory hands unmanaged items to Candidates (UI-022)": f["inventory_has_unmanaged_table"]
        is False
        and f["inventory_candidates_link"] is True,
        "no 'items wait' chip repeat on Home (UI-003)": f["home_has_items_chip"] is False,
        "no flag names on Governance (UI-043)": f["gov_flag_names"] is False,
        "Systems tiles are figures, not filters (UI-050)": f["systems_tiles_are_links"] is False,
        "Library off hint once (UI-161)": f["catalog_off_hint_n"] == 1,
        "Workflows scheduler line once (UI-140)": int(f["workflows_scheduler_table_rows"]) <= 1,  # type: ignore[call-overload]
        "Evidence page opens": f["evidence_status"] == 200,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tools.check_ui_links", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--systems", type=int, default=12)
    ap.add_argument("--max-pages", type=int, default=120)
    ap.add_argument("--data-dir", default=None, help="default: a new temporary folder")
    a = ap.parse_args(argv)
    data = Path(a.data_dir or tempfile.mkdtemp(prefix="linkcheck-"))
    setup_env(data)
    seed(a.systems)
    out = run(a.max_pages)
    print("LINKCRAWL " + json.dumps(out))  # noqa: T201 - CLI output
    failed = [name for name, ok in batch2_checks(page_facts()).items() if not ok]
    for name in failed:
        print(f"[FAIL] {name}")  # noqa: T201
    for b in out["bad"]:  # type: ignore[union-attr]
        print(f"[FAIL] {b['status']} {b['url']} (on {', '.join(b['on'])})")  # noqa: T201
    if out["pages"] < MIN_PAGES or out["links"] < MIN_LINKS:  # type: ignore[operator]
        print(f"[FAIL] crawl too small: {out['pages']} pages, {out['links']} links")  # noqa: T201
        return 1
    return 1 if out["bad"] or failed else 0


if __name__ == "__main__":
    sys.exit(main())
