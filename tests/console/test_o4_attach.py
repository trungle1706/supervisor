"""WP-O4 (phase 9): the Attach tab and panel (ONBOARD_ATTACH_VIEW) and Check now.

Off path first: no tab, every route answers 400 ``attach_off``. Then the model on synthetic rows
(plug point, floor, lit items by evidence age, counts, no floats), the page (tab, SVG with one
circle per item, list, How to attach without any secret), Check now (two audit rows, no call to the
candidate) and the roles."""

from __future__ import annotations

import datetime as dt
import html as html_lib
import math
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.console import attach_view
from supervisor.core.schema import load_model
from supervisor.governance import guardians as gd

from .conftest import Console

HX = {"HX-Request": "true"}
PLANTED = "tok-PLANTED-0123456789abcdef"  # a token that must never reach a page
MODEL = load_model()


# ------------------------------------------------------------------------------------ helpers


def row(table: str, **values: Any) -> dict[str, Any]:
    """A full row of ``table``: the given values, a typed default for every other column."""
    defaults: dict[str, Any] = {
        "string": "x",
        "text": "x",
        "int": 0,
        "bool": False,
        "json": "{}",
        "money": 0,
        "date": dt.date(2026, 10, 1),
        "timestamp": dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    }
    out: dict[str, Any] = {}
    for col in MODEL.table(table).columns:
        if col.name in values:
            out[col.name] = values[col.name]
        elif col.nullable:
            out[col.name] = None
        else:
            out[col.name] = defaults[col.type.rstrip("?")]
    return out


def uid(prefix: str, n: int) -> str:
    return f"{prefix}{n:06d}".ljust(32, "0")


class Rows:
    """Appends synthetic evidence rows to the console store, relative to the console clock."""

    def __init__(self, c: Console) -> None:
        self.c = c
        self.now = c.ctx.clock.now()
        self.n = 0

    def ago(self, days: int, hours: int = 0) -> dt.datetime:
        return self.now - dt.timedelta(days=days, hours=hours)

    def add(self, table: str, **values: Any) -> None:
        self.n += 1
        full = row(table, **values)
        if MODEL.table(table).kind == "state":
            self.c.ctx.state.insert(table, full)
        else:
            self.c.ctx.tables.append(table, [full])

    def finding(self, slug: str, ts: dt.datetime, agent: str = "payments") -> None:
        self.add(
            "finding",
            finding_id=uid("f", self.n + 1),
            ts=ts,
            agent_id=agent,
            detector_slug=slug,
            detector_id=f"{slug}@1",
        )

    def verdict(self, ts: dt.datetime, tier: int, role: str | None = None) -> None:
        self.add(
            "verdict",
            verdict_id=uid("v", self.n + 1),
            ts=ts,
            agent_id="payments",
            tier=tier,
            role=role,
            advisory=True,
            action="log",
            label="ok",
            checker_id=f"judge.t{tier}",
        )

    def event(self, ts: dt.datetime) -> None:
        self.add(
            "agent_event",
            event_id=uid("e", self.n + 1),
            ts=ts,
            agent_id="payments",
            event_type="gate_decision",
        )

    def pack(self, pack_id: str, ts: dt.datetime, status: str = "ok", mock: bool = False) -> None:
        self.add(
            "eval_result",
            run_id=uid("r", self.n + 1),
            ts=ts,
            pack_id=pack_id,
            target_kind="agent",
            target_id="payments",
            status=status,
            is_mock=mock,
        )


def items(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["slug"]: i for g in model["groups"] for i in g["items"]}


def walk(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in walk(v)]
    if isinstance(value, list | tuple):
        return [x for v in value for x in walk(v)]
    return [value]


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "onboard_attach_view", True)
    return console


def panel(c: Console, node: str = "payments", user: str = "reviewer.an") -> Any:
    return c.get(f"/console/attach/{node}", user=user, headers=HX)


def check(c: Console, node: str = "payments", user: str = "reviewer.an") -> Any:
    return c.client.post(f"/console/attach/{node}/check", headers={"X-Dev-User": user, **HX})


def actions(c: Console, path: str) -> list[dict]:
    return [r for r in c.ctx.tables.query("console_action", order_by=("ts",)) if r["path"] == path]


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.onboard_attach_view is False


def test_off_no_tab_and_every_route_is_400_attach_off(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-tab="attach"' not in page.text
    for url in ("/console/agents/payments?tab=attach", "/console/agents/payments/tab/attach"):
        r = console.get(url)
        assert r.status_code == 400 and "ONBOARD_ATTACH_VIEW=1" in r.text
    r = console.get("/console/attach/payments")
    assert r.status_code == 400 and "attach_off" in r.text
    r = check(console)
    assert r.status_code == 400 and "attach_off" in r.text


# --------------------------------------------------------------------- plug point detection


def fake_ctx(agent_row: dict | None, manifest: Any = None) -> Any:
    class State:
        def get(self, table: str, key: dict) -> dict | None:
            return agent_row

    agents = {"a1": manifest} if manifest is not None else {}
    policy = SimpleNamespace(current=lambda: SimpleNamespace(doc=SimpleNamespace(agents=agents)))
    return SimpleNamespace(
        state=State(), gateway=SimpleNamespace(states=SimpleNamespace(policy=policy))
    )


@pytest.mark.parametrize(
    ("plug", "host", "kind"),
    [
        ("gate_hook", "python_inprocess", "sdk"),
        ("sdk", "python", "sdk"),
        ("mcp_proxy", "python", "mcp_gateway"),
        ("proxy_log", "python", "http_proxy"),
        ("gate_hook", "databricks_app", "databricks_app"),
        ("sdk", "Databricks_Apps", "databricks_app"),
        ("otel", "python", "unknown"),
        ("", "", "unknown"),
    ],
)
def test_plug_point_from_the_agent_row(plug: str, host: str, kind: str) -> None:
    got = attach_view.plug_point(fake_ctx({"plug_point": plug, "host_type": host}), "a1")
    assert got["kind"] == kind
    assert got["decided_by"] == ("agent_row")


def test_plug_point_falls_back_to_the_policy_and_says_how() -> None:
    manifest = SimpleNamespace(plug_point="mcp_proxy", host_type="python")
    got = attach_view.plug_point(fake_ctx(None, manifest), "a1")
    assert got == {
        "kind": "mcp_gateway",
        "decided_by": "policy",
        "plug_point": "mcp_proxy",
        "host_type": "python",
    }
    # the row names something this view does not know: the policy decides
    got = attach_view.plug_point(fake_ctx({"plug_point": "otel", "host_type": "x"}, manifest), "a1")
    assert got["kind"] == "mcp_gateway" and got["decided_by"] == "policy"


def test_plug_point_unknown_when_nothing_names_one() -> None:
    got = attach_view.plug_point(fake_ctx(None), "a1")
    assert got["kind"] == "unknown" and got["decided_by"] == "none"


# ----------------------------------------------------------------------------------- floor


def test_floor_is_the_union_over_the_systems_plus_the_gate_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class State:
        def query(self, table: str, where: dict | None = None) -> list[dict]:
            if table == "ai_system":
                return [
                    {"system_id": "s1", "status": "active"},
                    {"system_id": "s2", "status": "archived"},
                    {"system_id": "s3", "status": "active"},
                ]
            return [
                {"system_id": "s1", "ref_id": "Payments", "active": True},
                {"system_id": "s2", "ref_id": "payments", "active": True},
                {"system_id": "s3", "ref_id": "other", "active": True},
            ]

    seen: list[str] = []

    def floor(settings: Any, state: Any, system_id: str) -> list[dict]:
        seen.append(system_id)
        return [{"slug": "dlp_vn"}]

    monkeypatch.setattr(gd, "_floor", floor)
    ctx = SimpleNamespace(state=State(), settings=SimpleNamespace())
    assert attach_view.agent_floor(ctx, "payments") == {"policy_rules", "dlp_vn"}
    assert seen == ["s1"]  # archived and other-agent systems do not count


def test_floor_items_are_marked_in_the_model(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attach_view, "agent_floor", lambda ctx, a: {"policy_rules", "dlp_vn"})
    m = attach_view.attach_model(on.ctx, "payments")
    it = items(m)
    assert it["policy_rules"]["floor"] and it["dlp_vn"]["floor"]
    assert not it["injection_regex"]["floor"]
    assert m["counts"]["floor"] == 2


def test_a_rules_file_that_cannot_be_read_gives_the_gate_rules_only(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any) -> list:
        raise OSError("no file")

    monkeypatch.setattr(gd, "_floor", boom)
    assert attach_view.agent_floor(on.ctx, "payments") <= {"policy_rules"}


# ------------------------------------------------------------------ evidence, lit, counts


def test_items_light_up_by_the_age_of_their_evidence(on: Console) -> None:
    r = Rows(on)
    base = items(attach_view.attach_model(on.ctx, "payments"))
    on.ctx.settings.detectors_enabled = True
    r.finding("dlp_vn", r.ago(1))
    r.finding("dlp_vn", r.ago(3))
    r.finding("dlp_vn", r.ago(20))
    r.finding("injection_regex", r.ago(10))  # older than 7 days: not lit
    r.event(r.ago(0, 2))
    r.event(r.ago(30))
    m = attach_view.attach_model(on.ctx, "payments")
    it = items(m)
    assert it["dlp_vn"]["count_7d"] == 2 and it["dlp_vn"]["lit"] is True
    assert it["dlp_vn"]["last_evidence_at"] == attach_view.format_ts(r.ago(1))
    assert it["injection_regex"]["count_7d"] == 0 and it["injection_regex"]["lit"] is False
    assert it["injection_regex"]["last_evidence_at"] == attach_view.format_ts(r.ago(10))
    assert it["policy_rules"]["count_7d"] == base["policy_rules"]["count_7d"] + 1
    assert it["policy_rules"]["lit"] is True
    assert m["counts"]["lit"] == sum(1 for i in it.values() if i["lit"])


def test_an_item_without_evidence_has_none_and_zero(on: Console) -> None:
    m = attach_view.attach_model(on.ctx, "payments")
    quiet = [i for i in items(m).values() if i["slug"] == "judge_challenger"]
    assert quiet[0]["last_evidence_at"] is None and quiet[0]["count_7d"] == 0
    assert quiet[0]["lit"] is False


def test_judges_packs_and_monitors_read_their_own_rows(on: Console) -> None:
    r = Rows(on)
    base = items(attach_view.attach_model(on.ctx, "payments"))
    r.verdict(r.ago(1), 1)
    r.verdict(r.ago(2), 2)
    r.verdict(r.ago(2, 1), 2)
    r.verdict(r.ago(1), 1, role="challenger")
    r.verdict(r.ago(1), 2, role="protocol")  # protocol rows are not judge evidence
    r.pack("pii_leak", r.ago(2), "ok")
    r.pack("pii_leak", r.ago(9), "fail")
    r.pack("jailbreak", r.ago(12), "ok", mock=True)
    r.add(
        "oversight_metric",
        metric_date=r.ago(3).date(),
        agent_id="payments",
        computed_at=r.ago(1),
        monitor_status='{"quality": {"status": "ok"}, "drift": {"status": "no_data"}}',
    )
    it = items(attach_view.attach_model(on.ctx, "payments"))
    assert it["judge_t1"]["count_7d"] == base["judge_t1"]["count_7d"] + 1
    assert it["judge_t2"]["count_7d"] == base["judge_t2"]["count_7d"] + 2
    assert it["judge_challenger"]["count_7d"] == base["judge_challenger"]["count_7d"] + 1
    assert it["pack:pii_leak"]["count_7d"] == 1 and it["pack:pii_leak"]["status"] == "ok"
    assert it["pack:jailbreak"]["lit"] is False and it["pack:jailbreak"]["mock"] is True
    assert it["monitor_quality"]["lit"] is True and it["monitor_quality"]["count_7d"] == 1
    assert it["monitor_drift"]["lit"] is False and it["monitor_drift"]["last_evidence_at"] is None
    assert it["monitor_drift"]["status"] == "no_data"


def test_judges_are_marked_mock_when_no_model_is_set(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "judge_enabled", True)
    monkeypatch.setattr(on.ctx.settings, "judge_t1_model", "")
    monkeypatch.setattr(on.ctx.settings, "judge_t2_model", "real-model")
    it = items(attach_view.attach_model(on.ctx, "payments"))
    assert it["judge_t1"]["mock"] is True and it["judge_t1"]["enabled"] is True
    assert it["judge_t2"]["mock"] is False


def test_enabled_follows_the_detector_master_flag(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "detectors_enabled", False)
    it = items(attach_view.attach_model(on.ctx, "payments"))
    assert it["dlp_vn"]["enabled"] is False
    assert it["policy_rules"]["enabled"] is True
    monkeypatch.setattr(on.ctx.settings, "detectors_enabled", True)
    assert items(attach_view.attach_model(on.ctx, "payments"))["dlp_vn"]["enabled"] is True


def test_model_shape_groups_and_no_floats(on: Console) -> None:
    r = Rows(on)
    r.finding("dlp_vn", r.ago(1))
    r.pack("pii_leak", r.ago(1))
    m = attach_view.attach_model(on.ctx, "payments")
    assert [g["key"] for g in m["groups"]] == ["gate", "detectors", "judges", "monitors"]
    assert m["plug"]["kind"] in attach_view.PLUG_KINDS
    for i in items(m).values():
        assert set(i) >= {"slug", "label", "floor", "enabled", "last_evidence_at", "count_7d"}
        assert isinstance(i["count_7d"], int) and not isinstance(i["count_7d"], bool)
        assert i["last_evidence_at"] is None or isinstance(i["last_evidence_at"], str)
    assert not [v for v in walk(m) if isinstance(v, float)]
    assert not [
        v for v in walk(attach_view.how_to_attach(on.ctx, "payments")) if isinstance(v, float)
    ]


def test_an_unknown_node_still_builds_a_model(on: Console) -> None:
    m = attach_view.attach_model(on.ctx, "no-such-candidate")
    assert m["plug"]["kind"] == "unknown" and m["gate"]["state"] is None
    assert m["counts"]["lit"] == 0


# --------------------------------------------------------------------------- the page


def test_tab_is_there_when_on(on: Console) -> None:
    page = on.get("/console/agents/payments?tab=attach")
    assert page.status_code == 200
    assert 'data-tab="attach"' in page.text and 'data-section="attach"' in page.text
    tabs = re.findall(r'data-tab="([a-z_]+)"', page.text)
    assert tabs[-1] == "attach" or tabs.index("attach") > tabs.index("overview")
    frag = on.get("/console/agents/payments/tab/attach")
    assert frag.status_code == 200 and "<html" not in frag.text
    assert 'id="attach-panel"' in frag.text


def test_attach_tab_comes_after_predeploy(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("onboard_intake", "onboard_facts", "onboard_predeploy"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    tabs = re.findall(r'data-tab="([a-z_]+)"', on.get("/console/agents/payments").text)
    assert tabs.index("predeploy") + 1 == tabs.index("attach")


def test_full_page_without_htmx_and_fragment_with(on: Console) -> None:
    full = on.get("/console/attach/payments")
    assert full.status_code == 200 and "<html" in full.text and 'id="attach-panel"' in full.text
    frag = panel(on)
    assert frag.status_code == 200 and "<html" not in frag.text


def test_bad_node_id_is_400(on: Console) -> None:
    r = on.get("/console/attach/bad%20id")
    assert r.status_code == 400 and "bad_node_id" in r.text


def svg_of(html: str) -> str:
    m = re.search(r"<svg.*?</svg>", html, re.S)
    assert m
    return m.group(0)


def test_svg_has_one_circle_per_item_and_lights_the_right_ones(on: Console) -> None:
    r = Rows(on)
    r.finding("dlp_vn", r.ago(1))
    r.pack("pii_leak", r.ago(1))
    html = panel(on).text
    svg = svg_of(html)
    m = attach_view.attach_model(on.ctx, "payments")
    it = items(m)
    assert svg.count("<circle") == len(it) == m["counts"]["total"]
    for slug, item in it.items():
        mm = re.search(rf'<circle[^>]*data-slug="{re.escape(slug)}"[^>]*>', svg)
        assert mm, slug
        assert f'data-lit="{1 if item["lit"] else 0}"' in mm.group(0)
        classes = re.search(r'class="([^"]*)"', mm.group(0)).group(1).split()  # type: ignore[union-attr]
        assert ("lit" in classes) == item["lit"] and ("off" in classes) == (not item["enabled"])
        assert (f'data-lock="{slug}"' in svg) == item["floor"]
    assert 'data-lit="1"' in svg
    assert svg.count("data-lock=") == m["counts"]["floor"]


def test_svg_rules_theme_variables_text_size_and_box_width(on: Console) -> None:
    svg = svg_of(panel(on).text)
    assert "viewBox=" in svg and "<title" in svg
    assert not re.search(r"(fill|stroke)=\"#", svg)  # no hard-coded colours in the markup
    for size in re.findall(r"font-size[:=]\s*\"?([0-9.]+)", svg):
        assert float(size) <= 12.5
    css = (Path(__file__).parents[2] / "src/supervisor/console/static/console.css").read_text(
        encoding="utf-8"
    )
    block = css[css.index("WP-O4 Attach panel") :]
    assert all(
        float(s) <= 12.5 for s in re.findall(r"\.at-svg text \{[^}]*font-size: ([0-9.]+)px", block)
    )
    assert "var(--surface)" in block and "var(--green)" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}", block.split(".at-env")[0])
    widths = [int(w) for w in re.findall(r'class="at-box[^"]*" [^>]*width="(\d+)"', svg)]
    assert len(widths) >= 7 and min(widths) >= 150  # agent, plug, gate and the four groups


def test_list_under_the_picture_has_every_item_with_time_and_count(on: Console) -> None:
    r = Rows(on)
    r.finding("dlp_vn", r.ago(2))
    r.finding("dlp_vn", r.ago(3))
    html = panel(on).text
    it = items(attach_view.attach_model(on.ctx, "payments"))
    for slug in it:
        assert f'data-item="{slug}"' in html
    mm = re.search(r'<tr class="row" data-item="dlp_vn".*?</tr>', html, re.S)
    assert mm and attach_view.format_ts(r.ago(2)) in mm.group(0)
    assert re.search(r'data-count="1">2<', mm.group(0))
    for group in ("gate", "detectors", "judges", "monitors"):
        assert f'data-table="attach-{group}"' in html


def test_plug_line_and_gate_state_are_shown(on: Console) -> None:
    html = panel(on).text
    m = attach_view.attach_model(on.ctx, "payments")
    assert f'data-plug="{m["plug"]["kind"]}"' in html
    assert "data-plug-line" in html and (m["gate"]["state"] or "state unknown") in html


# ----------------------------------------------------------------------- How to attach


def env_block(html: str) -> str:
    mm = re.search(r'<pre[^>]*id="attach-env"[^>]*>(.*?)</pre>', html, re.S)
    assert mm
    return html_lib.unescape(mm.group(1))


def set_plug(c: Console, plug: str, host: str = "python") -> None:
    key = {"agent_id": "payments"}
    cur = c.ctx.state.get("agent", key)
    c.ctx.state.update("agent", key, {"plug_point": plug, "host_type": host}, cur["row_version"])


def identities(tmp_path: Path, agent: str = "payments") -> Path:
    p = tmp_path / "ids.yaml"
    p.write_text(
        "principals:\n"
        "  - principal: sp-app-0001\n"
        f"    agents: [{agent}]\n"
        f"    token: {PLANTED}\n"
        f"    secret: {PLANTED}\n"
        "  - principal: FILL-ME-service-principal-application-id\n"
        "    agents: [FILL-ME-agent-id]\n"
        f"bearer: {PLANTED}\n",
        encoding="utf-8",
    )
    return p


def test_how_to_attach_sdk_lines_and_timeout(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "gate_decision_timeout_s", 20.0)
    set_plug(on, "gate_hook")
    html = panel(on).text
    block = env_block(html)
    assert "SUPERVISOR_GATE_URL=http://127.0.0.1:8000" in block
    assert "SUPERVISOR_AGENT_ID=payments" in block
    assert "SUPERVISOR_CREDENTIAL_KIND=hmac" in block
    assert "SUPERVISOR_TIMEOUT_S=25" in block
    assert 'data-variant="sdk"' in html and 'data-copy="#attach-env"' in html


@pytest.mark.parametrize(("raw", "want"), [(2.0, 7), (2.5, 8), (20.0, 25), (0.5, 6)])
def test_timeout_is_the_gate_budget_plus_five_as_an_integer(
    on: Console, monkeypatch: pytest.MonkeyPatch, raw: float, want: int
) -> None:
    monkeypatch.setattr(on.ctx.settings, "gate_decision_timeout_s", raw)
    assert attach_view.timeout_s(on.ctx.settings) == want == math.ceil(raw) + 5
    lines = attach_view.how_to_attach(on.ctx, "payments", "sdk")["lines"]
    assert f"set SUPERVISOR_TIMEOUT_S={want}" in lines


def test_how_to_attach_mcp_and_proxy_variants(on: Console) -> None:
    set_plug(on, "mcp_proxy")
    block = env_block(panel(on).text)
    assert "python -m supervisor.gateway.mcp_http" in block and "--agent payments" in block
    assert "set MCP_HTTP_ENABLED=1" in block and "SUPERVISOR_AGENT_ID=payments" in block
    set_plug(on, "proxy_log")
    block = env_block(panel(on).text)
    assert "SUPERVISOR_URL=http://127.0.0.1:8000" in block and "mcp_http" not in block


def test_how_to_attach_databricks_app_is_app_yaml(
    on: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(on.ctx.settings, "supervisor_mode", "databricks_app")
    monkeypatch.setattr(on.ctx.settings, "ingress_identities_file", identities(tmp_path))
    monkeypatch.setattr(on.ctx.settings, "gate_decision_timeout_s", 20.0)
    set_plug(on, "gate_hook", "databricks_app")
    html = panel(on).text
    block = env_block(html)
    assert block.startswith("env:")
    assert "- name: SUPERVISOR_GATE_URL" in block and "FILL-ME-supervisor-app-url" in block
    assert '- name: SUPERVISOR_CREDENTIAL_KIND\n    value: "databricks_oauth"' in block
    assert '- name: SUPERVISOR_TIMEOUT_S\n    value: "25"' in block
    assert 'data-principals="1"' in html and "sp-app-0001" in html
    assert "FILL-ME-service-principal" not in html.split("data-principals")[1].split("</p>")[0]


def test_how_to_attach_never_shows_a_secret_or_token(
    on: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(on.ctx.settings, "ingress_identities_file", identities(tmp_path))
    monkeypatch.setattr(on.ctx.settings, "ingress_credential_kind", "databricks_sp")
    monkeypatch.setenv("SUPERVISOR_CREDENTIAL", PLANTED)
    monkeypatch.setenv("DATABRICKS_TOKEN", PLANTED)
    for plug, host in (
        ("gate_hook", "python"),
        ("mcp_proxy", "python"),
        ("proxy_log", "python"),
        ("gate_hook", "databricks_app"),
        ("otel", "python"),
    ):
        set_plug(on, plug, host)
        page = panel(on).text
        assert PLANTED not in page and "tok-PLANTED" not in page
        assert "SUPERVISOR_CREDENTIAL=" not in env_block(page)
        how = attach_view.how_to_attach(on.ctx, "payments")
        assert PLANTED not in repr(how)
        assert not re.search(r"(?i)(token|secret|password|bearer)\s*[:=]\s*\S", how["text"])
    assert PLANTED not in on.get("/console/agents/payments?tab=attach").text


def test_no_principal_for_the_agent_is_said(
    on: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(on.ctx.settings, "ingress_identities_file", identities(tmp_path, "other"))
    monkeypatch.setattr(on.ctx.settings, "ingress_credential_kind", "databricks_sp")
    html = panel(on).text
    assert 'data-note="no_principal"' in html and "sp-app-0001" not in html


def test_hmac_names_no_principal_and_points_to_the_key_file(on: Console) -> None:
    how = attach_view.how_to_attach(on.ctx, "payments", "sdk")
    assert how["credential_kind"] == "hmac" and how["principals"] == []
    assert "secret_hmac" in how["notes"]


# ------------------------------------------------------------------------------ Check now


def test_check_now_writes_two_audit_rows_and_returns_the_panel(on: Console) -> None:
    before = len(actions(on, "/console/attach/payments/check"))
    r = check(on)
    assert r.status_code == 200, r.text
    assert 'id="attach-panel"' in r.text and "checked now" in r.text
    rows = actions(on, "/console/attach/payments/check")[before:]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert all(x["permission"] == "systems.edit" for x in rows)


def test_check_now_shows_evidence_that_arrived_since_the_last_read(on: Console) -> None:
    first = panel(on).text
    assert 'data-item="dlp_vn" data-lit="0"' in first
    r = Rows(on)
    r.finding("dlp_vn", r.ago(0, 1))
    r2 = check(on)
    assert 'data-item="dlp_vn" data-lit="1"' in r2.text


def test_check_now_rereads_the_gate_state_and_does_not_call_the_candidate(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    states = on.ctx.gateway.states
    real = states.invalidate
    monkeypatch.setattr(states, "invalidate", lambda a=None: (calls.append(str(a)), real(a))[1])
    import socket

    def no_network(*a: Any, **k: Any) -> Any:
        raise AssertionError("the Attach view must not call out")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    r = check(on)
    assert r.status_code == 200 and calls == ["payments"]


def test_read_time_shows_only_after_check_now(on: Console) -> None:
    assert "data-checked-at" not in panel(on).text
    assert "data-checked-at" in check(on).text


def test_check_now_is_htmx_only(on: Console) -> None:
    r = on.client.post("/console/attach/payments/check", headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 400


def test_get_is_read_only(on: Console) -> None:
    before = len(on.ctx.tables.query("console_action"))
    assert panel(on).status_code == 200
    assert len(on.ctx.tables.query("console_action")) == before


# -------------------------------------------------------------------------------- roles


def test_every_role_may_view_but_only_editors_may_check(on: Console) -> None:
    for user in ("viewer.hoa", "auditor.dung", "approver.em", "reviewer.an", "admin.chi"):
        assert panel(on, user=user).status_code == 200, user
    for user in ("viewer.hoa", "auditor.dung", "approver.em"):
        r = check(on, user=user)
        assert r.status_code == 403 and "needs role" in r.text, user
    assert check(on, user="reviewer.an").status_code == 200
    assert check(on, user="admin.chi").status_code == 200


def test_read_only_roles_see_no_button(on: Console) -> None:
    assert 'data-action="check-now"' not in panel(on, user="viewer.hoa").text
    assert 'data-action="check-now"' in panel(on, user="reviewer.an").text


def test_routes_are_in_the_permission_table() -> None:
    from supervisor.core import rbac

    assert rbac.ROUTES[("GET", "/console/attach/{node_id}")] == "systems.view"
    assert rbac.ROUTES[("POST", "/console/attach/{node_id}/check")] == "systems.edit"
