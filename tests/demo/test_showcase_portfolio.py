"""WP-D1: the showcase portfolio seeder (`python -m supervisor.demo.showcase portfolio`).

Runs on SQLite (the Delta path writes literal batch INSERTs through the same executor and is
covered by the literal builder test). One module-scoped store holds the 300-system portfolio; the
remove and idempotent tests use small stores of their own.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.adapters.factory import Adapters, build_adapters, make_masker
from supervisor.config import Settings
from supervisor.console import overview_v4, portfolio
from supervisor.demo import showcase
from supervisor.demo import showcase_portfolio as sp
from supervisor.demo.session import build_session, demo_settings
from supervisor.governance import risk_dimensions as rd
from supervisor.jobs import bootstrap_schema

ENV = {"SHOWCASE_ENABLED": "1"}
FLAGS: dict[str, Any] = {
    "governance_enabled": True,
    "classification_v2": True,
    "risk_dimensions": True,
    "overview_portfolio": True,
    "console_overview_v4": True,
    "console_nav_v3": True,
    "inventory_enabled": True,
}
NOW = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.UTC)
ADMIN = AuthPrincipal(
    user_id="admin.chi",
    kind="user",
    auth_method="dev_header",
    roles=frozenset({"admin", "reviewer"}),
)


def _settings(path: Path, **extra: Any) -> Settings:
    s = demo_settings(path, **FLAGS, **extra)
    a = build_adapters(s)
    try:
        bootstrap_schema.run(s, a)
    finally:
        a.close()
    return s


def _rows(s: Settings, table: str) -> list[dict[str, Any]]:
    a = build_adapters(s)
    try:
        return list(a.state.query(table))
    finally:
        a.close()


@pytest.fixture(scope="module")
def big(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, sp.Report]:
    s = _settings(tmp_path_factory.mktemp("showcase300"))
    rep = sp.run(s, systems=300, seed=1, env=ENV, now=NOW, echo=lambda _l: None)
    assert rep.ok, "\n".join(rep.lines)
    return s, rep


@pytest.fixture(scope="module")
def systems(big: tuple[Settings, sp.Report]) -> list[dict[str, Any]]:
    return _rows(big[0], "ai_system")


def _tags(row: dict[str, Any]) -> dict[str, str]:
    import json

    raw = row["tags"]
    return raw if isinstance(raw, dict) else json.loads(raw)


# ----------------------------------------------------------------------------- distribution


def test_counts_per_class_and_stage_match_the_plan(
    big: tuple[Settings, sp.Report], systems: list[dict[str, Any]]
) -> None:
    assert len(systems) == 300
    assert Counter(_tags(r)["class"] for r in systems) == Counter(sp.CLASS_COUNTS)
    assert Counter(r["lifecycle_stage"] for r in systems) == Counter(sp.STAGE_COUNTS)
    # the classification records say the same as the tags
    cls = _rows(big[0], "classification_v2")
    approved = {r["system_id"]: r["outcome"] for r in cls if r["approved_by"]}
    assert Counter(approved.values()) == Counter(
        {k: v for k, v in sp.CLASS_COUNTS.items() if k != "none"}
    )
    assert 300 - len(approved) == 28  # not classified yet
    assert all(r["tags"] and sp.TAG in _tags(r) for r in systems)


def test_counts_scale_and_sum(tmp_path: Path) -> None:
    pf = sp.build_portfolio(40, 3, now=NOW)
    assert len(pf.rows["ai_system"]) == 40
    assert sum(sp.apportion(40, sp.CLASS_COUNTS).values()) == 40
    assert sum(sp.apportion(7, sp.STAGE_COUNTS).values()) == 7


# ----------------------------------------------------------------------------- consistency


def test_cross_field_rules(big: tuple[Settings, sp.Report], systems: list[dict[str, Any]]) -> None:
    s = big[0]
    by_id = {r["system_id"]: r for r in systems}
    cls = {sid: _tags(r)["class"] for sid, r in by_id.items()}
    # high risk: money or credit, no pre-approval
    high = [sid for sid, c in cls.items() if c in ("high_certify", "high_self")]
    assert len(high) == 44
    for sid in high:
        r = by_id[sid]
        assert r["money_movement"] or r["credit_decision"], r["name"]
        assert r["human_control"] != "pre_approval", r["name"]
        assert r["decision33_class"] == "high_risk"
        assert r["risk_level"] == "high"
    # medium systems mostly face customers or partners; low systems are internal assistance
    medium = [by_id[sid] for sid, c in cls.items() if c == "medium"]
    facing = [r for r in medium if r["user_segment"] in ("customer", "partner")]
    assert len(facing) / len(medium) >= 0.6
    for sid, c in cls.items():
        r = by_id[sid]
        if c == "low":
            assert r["user_segment"] == "internal" and not r["money_movement"]
            assert not r["credit_decision"]
        if c in ("medium", "low"):
            assert r["risk_level"] == c
        if c == "none":
            assert r["decision33_class"] == "unclassified" and r["risk_level"] == "unspecified"
    # operation: agent + guardian bindings + 30 days of rollups; design: risk types not started
    agents = {r["agent_id"] for r in _rows(s, "agent")}
    comps = _rows(s, "system_component")
    agent_of = {c["system_id"]: c["ref_id"] for c in comps if c["ref_kind"] == "agent"}
    bound = {r["system_id"] for r in _rows(s, "guardian_binding")}
    days: Counter[str] = Counter(
        r["dim_key"] for r in _rows(s, "decision_daily") if r["dimension"] == "agent"
    )
    dims = _rows(s, "risk_dimension_status")
    status_of: dict[str, set[str]] = {}
    for d in dims:
        status_of.setdefault(d["system_id"], set()).add(d["status"])
    for sid, r in by_id.items():
        stage = r["lifecycle_stage"]
        if stage in ("operation", "re_evaluation"):
            assert agent_of[sid] in agents
            assert sid in bound
            assert days[agent_of[sid]] == sp.DAYS
        else:
            assert sid not in agent_of
            assert days.get(sid) is None
        if stage == "initiation":
            assert status_of[sid] == {"not_started"}
        if stage == "design":
            assert status_of[sid] <= {"not_started", "in_progress"}
    # eight risk types per system, a pass has evidence
    assert len(dims) == 300 * 8
    assert all(d["evidence_json"] for d in dims if d["status"] == "pass")
    ops = [
        d
        for sid, r in by_id.items()
        if r["lifecycle_stage"] == "operation"
        for d in dims
        if d["system_id"] == sid
    ]
    share = Counter(d["status"] for d in ops)
    assert share["pass"] > 0.6 * len(ops) and 0 < share["fail"] < 0.1 * len(ops)
    # classification approved by a second person; some past the yearly review
    c2 = _rows(s, "classification_v2")
    assert all(r["approved_by"] != r["decided_by"] for r in c2 if r["approved_by"])
    assert sum(1 for r in c2 if r["approved_by"] and r["valid_until"] < NOW) >= 5
    # stage approvals have two different people
    for a in _rows(s, "stage_approval"):
        assert a["requested_by"] != a["decided_by"]
    # duties, gap tasks, incidents, cases, inventory
    ob = _rows(s, "obligation_status")
    assert len(ob) > 2000 and {r["coverage"] for r in ob} >= {"partial", "none"}
    tasks = _rows(s, "task")
    assert any(t["template_id"].startswith("DUTY-") and t["status"] == "open" for t in tasks)
    assert len(_rows(s, "incident")) == 14 and len(_rows(s, "cases")) == 10
    nodes = _rows(s, "inventory_node")
    assert sum(1 for n in nodes if n["status"] == "unmanaged") == 40


def test_gate_rollup_totals_add_up(big: tuple[Settings, sp.Report]) -> None:
    for r in _rows(big[0], "decision_daily"):
        parts = r["allows"] + r["reports"] + r["transforms"] + r["pauses"] + r["blocks"]
        assert parts + r["skips"] == r["requests"]
        assert r["dimension"] == "agent" and r["dim_key"].startswith(sp.PREFIX)


# ----------------------------------------------------------------------------- dashboard


def test_portfolio_blocks_and_summary_apis_show_the_seeded_numbers(
    big: tuple[Settings, sp.Report],
) -> None:
    session = build_session(big[0])
    try:
        ctx = session.console
        rows = ctx.systems.list_systems(ctx.systems.scope_for(ADMIN), {})
        shw = [r for r in rows if r["system_id"].startswith(sp.PREFIX)]
        assert len(shw) == 300
        block = portfolio.block_data(ctx, shw)
        bars = {b["outcome"]: b["count"] for b in block["classification"]["bars"]}
        assert bars == {
            "prohibited": 2,
            "high_certify": 6,
            "high_self": 38,
            "medium": 96,
            "low": 118,
            "not_system": 12,
            "none": 28,
        }
        c = block["classification"]
        assert c["systems_n"] == 300 and c["approved_n"] == 272
        assert c["not_classified_n"] == 28 and c["review_due_n"] >= 5
        assert c["waiting_for_approval_n"] >= 1
        assert sum(b["pct"] for b in c["bars"]) == 100
        # the service behind the summary API says the same
        summary = ctx.classification_v2.summary([r["system_id"] for r in shw])
        assert summary["counts"]["high_self"] == 38 and summary["review_due_n"] == c["review_due_n"]
        risk = block["risk"]
        assert risk["systems_n"] == 300 and len(risk["dimension_ids"]) == 8
        assert risk["rows_total"] == 300 and len(risk["rows"]) == portfolio.GRID_ROWS
        assert risk["past_valid_until_n"] >= 5
        env = rd.Env.from_console(ctx)
        total = rd.summary(env, [r["system_id"] for r in shw])
        assert total["systems"] == 300
        for d in risk["dimensions"]:
            assert d["pass"] + d["open"] + d["fail"] + d["waived"] + d["not_applicable"] == 300
        assert sum(d["fail"] for d in risk["dimensions"]) > 0
        # the effective risk equals the class (tool classes agree with the class)
        eff = Counter(r["effective_risk_level"] for r in shw)
        assert eff["prohibited"] == 2 and eff["high"] == 44 and eff["medium"] == 96
        assert sum(eff.values()) == 300
    finally:
        session.close()


def test_my_overview_renders_the_portfolio(big: tuple[Settings, sp.Report]) -> None:
    session = build_session(big[0])
    try:
        ctx = session.console
        data = overview_v4.my_overview(ctx, ADMIN, "all", NOW, {})
        assert data["totals"]["systems"] == 300
        assert data["totals"]["agents"] == 152
        assert data["totals"]["cases"] == 10
        assert dict(data["totals"]["tiers"]) == {
            "sy_risk_prohibited": 2,
            "sy_risk_high": 44,
            "sy_risk_medium": 96,
            "sy_risk_low": 158,
        }
        assert data["cand"] is not None and data["cand"]["cand_total"] == 40
        scores = [r["score"] for r in data["cand"]["cand_page"].items]
        assert scores and scores == sorted(scores, reverse=True) and scores[0] > scores[-1]
        assert data["portfolio"] is not None
        stages = dict(data["pipeline"])
        assert stages["candidates"] == 40 and stages["production"] == 140
        assert stages["classified"] == 272
        assert any(c["name"] and c["risk"] for c in data["cards"])
    finally:
        session.close()


# ----------------------------------------------------------------------------- safety


def test_idempotent_same_seed_same_ids(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    first = sp.run(s, systems=40, seed=7, env=ENV, now=NOW, echo=lambda _l: None)
    assert first.ok and sum(first.written.values()) > 500
    before = {t: len(_rows(s, t)) for t in sp.TABLE_ORDER}
    again = sp.run(s, systems=40, seed=7, env=ENV, now=NOW, echo=lambda _l: None)
    assert again.ok and sum(again.written.values()) == 0
    assert {t: len(_rows(s, t)) for t in sp.TABLE_ORDER} == before
    a = sp.build_portfolio(40, 7, now=NOW)
    b = sp.build_portfolio(40, 7, now=NOW)
    assert [r["system_id"] for r in a.rows["ai_system"]] == [
        r["system_id"] for r in b.rows["ai_system"]
    ]
    assert a.rows["ai_system"] == b.rows["ai_system"] and a.rows["task"] == b.rows["task"]
    other = sp.build_portfolio(40, 8, now=NOW)
    assert [r["name"] for r in other.rows["ai_system"]] != [r["name"] for r in a.rows["ai_system"]]


def test_remove_deletes_exactly_the_showcase_rows(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    a = build_adapters(s)
    try:
        # a real-looking system and agent that the seeder must not touch
        a.state.insert(
            "agent",
            {
                "agent_id": "payments-prod",
                "name": "Payments",
                "owner_team": "x",
                "owner_user": "u",
                "risk_tier": "high",
                "host_type": "app",
                "plug_point": "sdk",
                "model_family": "qwen",
                "status": "enforced",
                "gate_state": "RUNNING",
                "created_at": NOW,
            },
        )
    finally:
        a.close()
    rep = sp.run(s, systems=40, seed=2, env=ENV, now=NOW, echo=lambda _l: None)
    assert rep.ok
    gone = sp.run(s, remove=True, env=ENV, now=NOW, echo=lambda _l: None)
    assert gone.ok and sum(gone.removed.values()) == sum(rep.written.values())
    for table, (col, prefix) in sp.SCOPE.items():
        left = [r for r in _rows(s, table) if str(r[col]).startswith(prefix)]
        assert left == [], table
    assert [r for r in _rows(s, "ai_system") if sp.TAG in str(r["tags"])] == []
    assert [r["agent_id"] for r in _rows(s, "agent")] == ["payments-prod"]
    # a second remove is a no-op and the store can be seeded again
    assert sum(sp.run(s, remove=True, env=ENV, echo=lambda _l: None).removed.values()) == 0
    assert sp.run(s, systems=40, seed=2, env=ENV, now=NOW, echo=lambda _l: None).ok


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    rep = sp.run(s, systems=30, dry_run=True, env=ENV, echo=lambda _l: None)
    assert rep.ok and rep.portfolio is not None and not rep.written
    assert _rows(s, "ai_system") == []


def test_flag_off_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(tmp_path)
    lines: list[str] = []
    rep = sp.run(s, systems=20, env={}, echo=lines.append)
    assert not rep.ok and "SHOWCASE_ENABLED=1" in rep.lines[0]
    assert _rows(s, "ai_system") == []
    rep2 = sp.run(s, systems=20, env={"SHOWCASE_ENABLED": "0"}, echo=lambda _l: None)
    assert not rep2.ok
    app = sp.check_enabled({"SUPERVISOR_MODE": "databricks_app"})
    assert app is not None and "Databricks App" in app
    assert sp.check_enabled({"SUPERVISOR_MODE": "databricks_app", "SHOWCASE_ENABLED": "1"}) is None
    # the CLI exits 1 with the message
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    assert showcase.main(["portfolio", "--systems", "5", "--dry-run"]) == 1
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")
    assert showcase.main(["portfolio", "--systems", "5", "--dry-run"]) == 0
    assert showcase.main(["nonsense"]) == 2


def test_only_state_tables_are_written() -> None:
    from supervisor.core.schema import load_model

    model = load_model()
    for table in sp.SCOPE:
        assert not model.table(table).append_only, table  # nothing append-only, no chain record


def test_literal_builder_for_delta() -> None:
    assert sp._lit(None, "string") == "NULL"
    assert sp._lit("it's", "text") == "'it''s'"
    assert sp._lit(True, "bool") == "true" and sp._lit(5, "int") == "5"
    assert sp._lit(dt.date(2026, 1, 2), "date") == "DATE'2026-01-02'"
    assert sp._lit(NOW, "timestamp").startswith("TIMESTAMP'2026-10-29 09:00:00.000000")
    assert sp._lit({"b": 1, "a": [1]}, "json") == '\'{"a":[1],"b":1}\''
    with pytest.raises(sp.ShowcaseError):
        sp._lit("a\\b", "text")


# ----------------------------------------------------------------------------- no personal data


_ID_LIKE = ("_id", "_sha256", "_hash", "id", "_by", "owner_user", "assignee", "dim_key", "dim_key2")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            s
            for k, v in value.items()
            if "sha256" not in k and "hash" not in k
            for s in _strings(v)
        ]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_no_personal_data_looking_value(big: tuple[Settings, sp.Report]) -> None:
    masker = make_masker(big[0])
    assert masker is not None
    adapters: Adapters = build_adapters(big[0])
    bad: list[str] = []
    try:
        pf = big[1].portfolio
        assert pf is not None
        for table, rows in pf.rows.items():
            t = adapters.model.table(table)
            for row in rows:
                for c in t.columns:
                    if c.type not in ("string", "text", "json") or c.name.endswith(_ID_LIKE):
                        continue
                    for text in _strings(row.get(c.name)):
                        if masker.mask(text) != text:
                            bad.append(f"{table}.{c.name}: {text[:60]}")
    finally:
        adapters.close()
    assert not bad[:5], bad[:5]


def test_no_person_names_in_teams_and_users() -> None:
    pf = sp.build_portfolio(60, 5, now=NOW)
    for r in pf.rows["ai_system"]:
        for f in ("owner_user", "business_owner"):
            assert "." in r[f] and r[f].split(".")[0] in ("owner", "bizowner")
        assert r["owner_team"].endswith("team")
