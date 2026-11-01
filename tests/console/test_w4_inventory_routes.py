"""W4: the inventory run pages (flag FACTORY_INVENTORY_RUN): off path, start, progress, dashboard,
filters, system page, CSV, RBAC. A fake ChatModel and a five-system synthetic inventory."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest

from supervisor.console import factory_inventory_view as fiv
from supervisor.factory import inventory_run as inv
from tests.factory.test_w4_inventory_run import Chat, StubExec, mk_system

from .conftest import Console

AGENT = "mr-agent"
BASE = f"/console/factory/{AGENT}/inventory"
RUN0 = "inv_" + "0" * 20


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in ("governance_enabled", "agent_factory", "factory_inventory_run"):
        monkeypatch.setattr(s, flag, True)
    console.ctx.gate_chat = Chat(fail_for=("sys-a",))  # type: ignore[attr-defined]
    monkeypatch.setattr(inv, "_executive", lambda: StubExec())
    ctx = console.ctx
    mk_system(ctx, "sys-a", "Tro ly tin dung", level="high", d33="high_risk", team="Nhom Tin dung")
    mk_system(ctx, "sys-b", "Chatbot khach hang", level="low", segment="customer")
    mk_system(ctx, "sys-c", "He thong cu", status="archived")
    mk_system(ctx, "sys-d", "He thong nghi huu", stage="retirement")
    mk_system(ctx, "sys-e", "He thong bi cam", level="prohibited")
    r = console.post("/console/factory/new", {"dimension_id": "model", "id": AGENT, "name": "Mine"})
    assert r.status_code == 200, r.text
    return console


def run_it(c: Console, user: str = "reviewer.an") -> str:
    r = c.post(f"{BASE}/run", {"version": "0.1"}, user)
    assert r.status_code == 200, r.text
    inv.join(AGENT)
    m = re.search(r"(inv_[0-9a-f]{20})", r.headers["HX-Redirect"])
    assert m
    return m.group(1)


HX = {"HX-Request": "true"}

# ------------------------------------------------------------------------------ off path


def test_setting_defaults_off(console: Console) -> None:
    assert console.ctx.settings.factory_inventory_run is False
    assert console.ctx.settings.factory_inventory_parallel == 4
    assert console.ctx.settings.factory_inventory_max == 0


GETS = (
    BASE,
    f"{BASE}/{RUN0}",
    f"{BASE}/{RUN0}/progress",
    f"{BASE}/{RUN0}/system/sys-a",
    f"{BASE}/{RUN0}/export.csv",
)


def test_off_every_route_is_400_and_nothing_is_read(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = console.ctx.state.query
    monkeypatch.setattr(
        console.ctx.state, "query", lambda t, *a, **k: (seen.append(t), real(t, *a, **k))[1]
    )
    for flags in ({}, {"agent_factory": True, "governance_enabled": True}):
        for k, v in flags.items():
            monkeypatch.setattr(console.ctx.settings, k, v)
        for url in GETS:
            r = console.get(url, "admin.chi")
            assert r.status_code == 400 and "factory_inventory_off" in r.text, url
        for url in (f"{BASE}/run", f"{BASE}/{RUN0}/cancel"):
            r = console.post(url, {}, "admin.chi")
            assert r.status_code == 400 and "factory_inventory_off" in r.text, url
    assert "ai_system" not in seen


def test_off_the_editor_has_no_button(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("governance_enabled", "agent_factory"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    console.post("/console/factory/new", {"dimension_id": "model", "id": AGENT, "name": "Mine"})
    assert 'data-act="inventory-run"' not in console.get(f"/console/factory/{AGENT}").text
    monkeypatch.setattr(console.ctx.settings, "factory_inventory_run", True)
    assert 'data-act="inventory-run"' in console.get(f"/console/factory/{AGENT}").text


# ------------------------------------------------------------------------------ list and start


def test_list_page_has_the_banner_and_the_form(on: Console) -> None:
    page = on.get(BASE).text
    assert (
        'data-banner="1"' in page
        and "Simulation on the inventory. It does not change any assessment." in page
    )
    assert 'data-act="run-inventory"' in page and 'name="version"' in page
    assert "No run yet." in page
    vi = on.get(BASE + "?lang=vi").text
    assert "Mô phỏng trên danh mục" in vi


def test_a_viewer_sees_the_list_without_the_button(on: Console) -> None:
    page = on.get(BASE, "viewer.hoa").text
    assert 'data-act="run-inventory"' not in page and 'data-readonly="1"' in page
    r = on.post(f"{BASE}/run", {"version": "0.1"}, "viewer.hoa")
    assert r.status_code == 403


def test_start_redirects_to_the_run_and_the_run_finishes(on: Console) -> None:
    run_id = run_it(on)
    run = inv.read_run(Path(on.ctx.settings.data_dir), AGENT, run_id)
    assert run["status"] == "done" and run["done"] == 2
    audit = [r for r in on.ctx.tables.query("console_action") if r["path"] == f"{BASE}/run"]
    assert audit


def test_start_errors_are_400(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    assert on.post(f"{BASE}/run", {"version": "9.9"}).status_code == 400
    assert (
        on.post("/console/factory/not-an-agent/inventory/run", {"version": ""}).status_code == 400
    )
    assert on.post("/console/factory/BAD..ID/inventory/run", {}).status_code == 400
    on.ctx.gate_chat = None  # type: ignore[attr-defined]
    monkeypatch.setattr(on.ctx.settings, "llm_base_url", "")
    r = on.post(f"{BASE}/run", {"version": "0.1"})
    assert r.status_code == 400 and "model_not_configured" in r.text


# ------------------------------------------------------------------------------ the dashboard


def test_dashboard_shows_tiles_risks_mix_breakdowns_and_heat_table(on: Console) -> None:
    run_id = run_it(on)
    page = on.get(f"{BASE}/{run_id}").text
    assert 'data-page="finv-run"' in page and 'data-status="done"' in page
    assert 'data-draft="1"' in page and "Draft agent, not tested" in page
    assert "Simulation on the inventory. It does not change any assessment." in page
    tile = lambda k: re.search(rf'data-tile="{k}"[^>]*><b>(\d+)</b>', page).group(1)  # noqa: E731
    assert (tile("scope"), tile("assessed"), tile("needs_action")) == ("2", "2", "1")
    assert "fake-gateway-1" in page and "Model calls" in page
    assert "built-in method" not in page
    assert 'data-section="gaps"' in page and 'data-section="risks"' in page
    assert 'data-risk="money_tool_no_gate"' in page
    assert "1 system can send payments with no approval step" in page
    assert 'class="finv-mixrow"' in page and 'data-verdict="question"' in page
    assert 'data-table="by-team"' in page and 'data-table="by-level"' in page
    assert 'data-system="sys-a"' in page and 'data-system="sys-b"' in page
    assert 'data-system="sys-c"' not in page
    # fails sort first
    assert page.index('data-system="sys-a"') < page.index('data-system="sys-b"')
    assert 'class="finv-scroll"' in page  # the heat table scrolls inside its own container
    assert 'data-act="export-csv"' in page
    vi = on.get(f"{BASE}/{run_id}?lang=vi").text
    assert "1 hệ thống có thể chuyển tiền" in vi


def test_filters(on: Console) -> None:
    run_id = run_it(on)
    u = f"{BASE}/{run_id}"
    sys_ids = lambda html: set(re.findall(r'<tr data-system="([^"]+)"', html))  # noqa: E731
    assert sys_ids(on.get(u + "?team=Nhom+Tin+dung").text) == {"sys-a"}
    assert sys_ids(on.get(u + "?customer=yes").text) == {"sys-b"}
    assert sys_ids(on.get(u + "?customer=no").text) == {"sys-a"}
    assert sys_ids(on.get(u + "?level=low").text) == {"sys-b"}
    assert sys_ids(on.get(u + "?q=chatbot").text) == {"sys-b"}
    assert sys_ids(on.get(u + "?key=money_tool_no_gate").text) == {"sys-a"}
    assert sys_ids(on.get(u + "?bucket=needs_action").text) == {"sys-a"}
    assert 'data-empty="1"' in on.get(u + "?q=zzzz").text
    assert sys_ids(on.get(u + "?page=9").text) == {"sys-a", "sys-b"}  # past the end: last page


def test_bad_filters_are_400_never_500(on: Console) -> None:
    run_id = run_it(on)
    u = f"{BASE}/{run_id}"
    for q in (
        "?level=extreme",
        "?customer=maybe",
        "?bucket=x",
        "?page=abc",
        "?page=-1",
        "?page=" + "9" * 9,
    ):
        assert on.get(u + q).status_code == 400, q
    for bad in ("inv_zz", "inv_" + "g" * 20, "..%2Fx"):
        assert on.get(f"{BASE}/{bad}").status_code in (400, 404), bad
        assert on.get(f"{BASE}/{bad}/progress").status_code in (400, 404), bad
    assert on.get(f"{BASE}/{RUN0}").status_code == 400  # a well-formed id that does not exist
    assert on.get(f"/console/factory/no-such-agent/inventory/{run_id}").status_code == 400


def test_system_page_shows_executive_and_masked_findings(on: Console) -> None:
    run_id = run_it(on)
    page = on.get(f"{BASE}/{run_id}/system/sys-a").text
    assert 'data-page="finv-system"' in page and 'data-key="money_tool_no_gate"' in page
    assert "Sends money with no approval" in page and 'data-finding="' in page
    assert 'data-verdict="fail"' in page
    assert on.get(f"{BASE}/{run_id}/system/sys-zzz").status_code == 400
    assert on.get(f"{BASE}/{run_id}/system/..%2F..").status_code in (400, 404)
    assert on.get(f"{BASE}/{run_id}/system/{'a' * 70}").status_code == 400


def test_csv_download(on: Console) -> None:
    run_id = run_it(on)
    r = on.get(f"{BASE}/{run_id}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [x["system_id"] for x in rows] == ["sys-a", "sys-b"]
    assert rows[0]["result"] == "needs_action" and rows[0]["risk_level"] == "high"
    first = inv.read_run(Path(on.ctx.settings.data_dir), AGENT, run_id)["checklist"][0]["id"]
    assert first in rows[0] and rows[0]["customer_facing"] == "no"


# ------------------------------------------------------------------------------ progress, cancel


def test_progress_panel_while_running_and_redirect_after(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    chat = on.ctx.gate_chat  # type: ignore[attr-defined]
    chat.gate = threading.Event()
    monkeypatch.setattr(on.ctx.settings, "factory_inventory_parallel", 1)
    r = on.post(f"{BASE}/run", {"version": "0.1"})
    run_id = re.search(r"(inv_[0-9a-f]{20})", r.headers["HX-Redirect"]).group(1)  # type: ignore[union-attr]
    page = on.get(f"{BASE}/{run_id}").text
    assert 'id="finv-progress"' in page and 'hx-trigger="every 2s"' in page
    assert 'role="progressbar"' in page and 'data-act="cancel-inventory"' in page
    assert "data-tiles" not in page  # no dashboard yet
    frag = on.get(f"{BASE}/{run_id}/progress", headers=HX)
    assert frag.status_code == 200 and "finv-progress" in frag.text
    # the list disables the start button while a run goes
    assert 'data-running="1"' in on.get(BASE).text
    again = on.post(f"{BASE}/run", {"version": "0.1"})
    assert again.status_code == 400 and "run_in_progress" in again.text
    # cancel
    c = on.post(f"{BASE}/{run_id}/cancel", {})
    assert c.status_code == 200 and 'data-cancelling="1"' in c.text
    assert on.post(f"{BASE}/{run_id}/cancel", {}, "viewer.hoa").status_code == 403
    chat.gate.set()
    inv.join(AGENT)
    done = on.get(f"{BASE}/{run_id}/progress", headers=HX)
    assert done.status_code == 200 and done.headers["HX-Redirect"].endswith(run_id)
    assert inv.read_run(Path(on.ctx.settings.data_dir), AGENT, run_id)["status"] == "cancelled"
    final = on.get(f"{BASE}/{run_id}").text
    assert 'data-run-cancelled="1"' in final
    assert on.post(f"{BASE}/{run_id}/cancel", {}).status_code == 400  # already ended


# ------------------------------------------------------------------------------ RBAC and misc


def test_rbac_matrix_of_the_new_routes() -> None:
    from supervisor.core import rbac

    want = {
        ("GET", f"{BASE.replace(AGENT, '{agent_id}')}"): "systems.view",
        ("POST", "/console/factory/{agent_id}/inventory/run"): "factory.edit",
        ("POST", "/console/factory/{agent_id}/inventory/{run_id}/cancel"): "factory.edit",
        ("GET", "/console/factory/{agent_id}/inventory/{run_id}/export.csv"): "systems.view",
        (
            "GET",
            "/console/factory/{agent_id}/inventory/{run_id}/system/{system_id}",
        ): "systems.view",
    }
    for key, perm in want.items():
        assert rbac.ROUTES[key] == perm, key


def test_no_inline_handlers_and_no_floats_in_the_run_files(on: Console) -> None:
    run_id = run_it(on)
    for url in (BASE, f"{BASE}/{run_id}", f"{BASE}/{run_id}/system/sys-a"):
        html = on.get(url).text
        assert not re.search(r"\son(click|change|submit|load)=", html), url
    d = inv.run_dir(Path(on.ctx.settings.data_dir), AGENT, run_id)
    assert json.loads((d / "run.json").read_text())["format"] == inv.FORMAT


def test_risks_found_never_lists_gaps_and_the_page_is_paged(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = run_it(on)
    page = on.get(f"{BASE}/{run_id}").text
    risks = page.split('data-list="risks"')[1].split("</ol>")[0]
    assert "need an answer" not in risks and "pack" not in risks.lower()
    gaps = page.split('data-list="gaps"')[1].split("</ul>")[0]
    assert gaps.count("<li") <= 5
    assert on.get(f"{BASE}/{run_id}?kstatus=maybe").status_code == 400
    assert on.get(f"{BASE}/{run_id}?key=money_tool_no_gate&kstatus=fail").status_code == 200
    # 25 rows a page, the rest behind a link; the team table shows 10 and a disclosure
    monkeypatch.setattr(fiv, "PAGE_SIZE", 1)
    one = on.get(f"{BASE}/{run_id}").text
    assert one.count("<tr data-system=") == 1 and "page=2" in one
    assert fiv.PAGE_SIZE == 1 and fiv.TOP_TEAMS == 10
