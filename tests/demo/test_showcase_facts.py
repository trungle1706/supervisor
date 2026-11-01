"""Synthetic code-scan facts for the showcase portfolio (python -m supervisor.demo.showcase_facts).

One module-scoped store holds the 300-system portfolio and the facts. The idempotency, reset and
protection tests use small stores of their own. No subprocess, no network.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.factory import build_adapters
from supervisor.config import Settings
from supervisor.demo import showcase_facts as sf
from supervisor.demo import showcase_portfolio as sp
from supervisor.demo.session import demo_settings
from supervisor.factory.schemas.facts_v1 import export_card
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import orchestrator as orch
from supervisor.onboard.facts import FactsService
from supervisor.onboard.scrub import scrub_text

ENV = {"SHOWCASE_ENABLED": "1"}
NOW = dt.datetime(2026, 10, 29, 9, 0, tzinfo=dt.UTC)
PROTECTED = "inv_0d33cdf0bc7aeebb"
FIELD_VOCAB = {*sf.ID_FIELDS, *sf.PSEUDO_FIELDS, *sf.SPECIAL_FIELDS}


def _settings(path: Path, **extra: Any) -> Settings:
    s = demo_settings(path, onboard_facts=True, **extra)
    a = build_adapters(s)
    try:
        bootstrap_schema.run(s, a)
    finally:
        a.close()
    return s


def _seed_portfolio(s: Settings, n: int) -> None:
    rep = sp.run(s, systems=n, seed=1, env=ENV, now=NOW, echo=lambda _l: None)
    assert rep.ok, "\n".join(rep.lines)


def _run(s: Settings, **kw: Any) -> sf.Report:
    rep = sf.run(s, env=ENV, now=NOW, echo=lambda _l: None, **kw)
    assert rep.ok, "\n".join(rep.lines)
    return rep


def _all(s: Settings, table: str) -> list[dict[str, Any]]:
    a = build_adapters(s)
    try:
        return [dict(r) for r in a.state.query(table)]
    finally:
        a.close()


def _ctx(s: Settings) -> Any:
    a = build_adapters(s)
    return SimpleNamespace(settings=s, state=a.state, clock=a.clock, tables=a.tables, _a=a)


@pytest.fixture(scope="module")
def big(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, sf.Generated]:
    s = _settings(tmp_path_factory.mktemp("facts300"))
    _seed_portfolio(s, 300)
    _run(s)
    a = build_adapters(s)
    try:
        gen = sf.generate(sf.load_systems(a), sf.DEFAULT_SEED, NOW)
    finally:
        a.close()
    return s, gen


# ----------------------------------------------------------------------------- determinism


def test_generator_is_deterministic(big: tuple[Settings, sf.Generated]) -> None:
    s, gen = big
    a = build_adapters(s)
    try:
        systems = sf.load_systems(a)
    finally:
        a.close()
    again = sf.generate(systems, sf.DEFAULT_SEED, NOW)
    assert again.facts == gen.facts
    assert again.intake == gen.intake
    later = sf.generate(systems, sf.DEFAULT_SEED, NOW + dt.timedelta(days=3))
    strip = lambda g: {  # noqa: E731
        n: [{k: v for k, v in r.items() if k != "created_at"} for r in rows]
        for n, rows in g.facts.items()
    }
    assert strip(later) == strip(gen)
    other = sf.generate(systems, sf.DEFAULT_SEED + 1, NOW)
    assert strip(other) != strip(gen)


def test_stored_rows_equal_generated_rows(big: tuple[Settings, sf.Generated]) -> None:
    s, gen = big
    stored = {r["fact_id"] for r in _all(s, "onboard_facts") if r["model_id"] == sf.SYN}
    wanted = {r["fact_id"] for rows in gen.facts.values() for r in rows}
    assert stored == wanted


# ----------------------------------------------------------------------------- rates


def test_every_agent_node_has_facts(big: tuple[Settings, sf.Generated]) -> None:
    s, gen = big
    comps = _all(s, "system_component")
    agents = {c["ref_id"] for c in comps if c["ref_kind"] == "agent"}
    assert len(agents) == 152
    assert agents <= set(gen.facts)
    assert len(gen.facts) == 230  # plus validation and deployment systems on their application node


def test_planted_rates_are_exact_or_in_tolerance(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    n = len(gen.systems)
    c = gen.key_counts()

    def near(key: str, rate: float, tol: int = 2) -> None:
        assert abs(c[key] - round(rate * n)) <= tol, (key, c[key], round(rate * n))

    near("no_tracing", sf.RATES["no_tracing"])
    near("hardcoded_secret", sf.RATES["hardcoded_secret"])
    near("model_unknown", sf.RATES["model_unknown"])
    near("risk_level_mismatch", sf.RATES["risk_level_mismatch"])
    near("personal_data_mismatch", sf.RATES["personal_data_mismatch"])
    near("external_endpoint", sf.RATES["external_endpoint"], 3)
    near("pii_export_tool", sf.RATES["pii_export_tool"], 3)
    assert 0.07 * n <= c["money_tool_no_gate"] <= 0.14 * n
    assert 0.04 * n <= c["declared_control_mismatch"] <= 0.12 * n
    assert c["personal_data_fields"] > 0.4 * n


def test_summary_table_lists_every_key(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    text = "\n".join(sf.summary_table(gen))
    for k in sf.KEYS:
        assert k in text


def test_clean_records_mostly_look_clean(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    serious = {
        "money_tool_no_gate",
        "declared_control_mismatch",
        "personal_data_mismatch",
        "risk_level_mismatch",
        "hardcoded_secret",
    }
    clean = [
        s
        for s in gen.systems
        if s.rec["risk_level"] in ("low", "medium") and s.rec["human_control"] == "post_review"
    ]
    assert len(clean) > 80
    hit = sum(1 for s in clean if gen.keys[s.sid] & serious)
    assert hit / len(clean) < 0.2
    # a system without a planted pattern never fires a record-versus-code key
    for s in gen.systems:
        planted = gen.specs[s.sid].plants
        if not planted & {"risk_level_mismatch", "personal_data_mismatch"}:
            assert not gen.keys[s.sid] & {"risk_level_mismatch", "personal_data_mismatch"}


def test_mismatch_keys_follow_the_record(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    for s in gen.systems:
        keys = gen.keys[s.sid]
        if "personal_data_mismatch" in keys:
            assert s.rec["personal_data"] == "none"
        if "risk_level_mismatch" in keys:
            assert s.rec["risk_level"] in ("low", "medium", "unspecified")
        if "declared_control_mismatch" in keys:
            assert s.rec["human_control"] in ("pre_approval", "post_review")


# ----------------------------------------------------------------------------- shape and marker


def test_export_validates_and_is_marked_synthetic(big: tuple[Settings, sf.Generated]) -> None:
    s, gen = big
    ctx = _ctx(s)
    try:
        svc = FactsService(s, ctx.state, ctx.clock)
        for node in sorted(gen.facts)[:60]:
            doc = export_card(svc.card(node))
            assert doc["facts"], node
            assert doc["attempt_n"] == 1 and doc["latest_attempt"] == 1
            assert doc["newer_attempt"] is False
            assert doc["summary"]["detail"].startswith(sf.BANNER)
            assert doc["summary"]["model_id"] == sf.SYN
            assert {f["model_id"] for f in doc["facts"]} == {sf.SYN}
            assert {f["source"] for f in doc["facts"]} == {"rule"}
    finally:
        ctx._a.close()


def test_every_fact_has_a_pointer_and_known_kind(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    for rows in gen.facts.values():
        for r in rows:
            if r["kind"] == "summary":
                continue
            assert r["file"] and r["line"] >= 1 and r["quote"], r
            assert r["file"].startswith(("code/", "app.yaml", "supervisor.manifest.yaml"))
            assert len(r["quote"]) <= 200 and len(r["detail"]) <= 500


def test_no_personal_data_values_and_no_secret_values(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    digits = re.compile(r"\d{9,}")
    email = re.compile(r"[\w.]+@[\w.]+\.\w+")
    seen_fields: set[str] = set()
    for rows in gen.facts.values():
        for r in rows:
            blob = " ".join(str(r.get(k) or "") for k in ("name", "detail", "quote"))
            assert not digits.search(blob) and not email.search(blob), blob
            q = r.get("quote") or ""
            clean = scrub_text(q).text
            assert clean == q, q  # the scrubber finds nothing more to hide
            if r["name"].startswith("Handles personal data field"):
                field = re.search(r"'([a-z_]+)'", r["name"]).group(1)  # type: ignore[union-attr]
                assert field in FIELD_VOCAB
                assert q.strip() == f"{field}: str"
                seen_fields.add(field)
            if r["kind"] == "secret_use":
                assert "[REDACTED:" in q
    assert {"cccd", "so_tai_khoan", "ho_ten", "so_dien_thoai", "dia_chi"} <= seen_fields


def test_vocabulary_of_the_scanner(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    tool_classes: set[str] = set()
    families: set[str] = set()
    autonomy: set[str] = set()
    for rows in gen.facts.values():
        for r in rows:
            if r["kind"] == "tool":
                tool_classes.add(re.search(r"risk_class=(\w+)", r["detail"]).group(1))  # type: ignore[union-attr]
            if r["kind"] in ("model", "endpoint"):
                families.add(re.search(r"family=(\w+)", r["detail"]).group(1))  # type: ignore[union-attr]
            if r["kind"] == "autonomy":
                autonomy.add(r["name"])
    assert tool_classes == {"read_only", "money", "credit", "pii_export"}
    assert {"glm", "qwen", "openai", "anthropic", "unknown"} <= families
    assert autonomy <= {"L0", "L1", "L2", "L3"} and {"L1", "L2", "L3"} <= autonomy


def test_external_addresses_are_synthetic_hosts(big: tuple[Settings, sf.Generated]) -> None:
    _, gen = big
    for rows in gen.facts.values():
        for r in rows:
            if r["kind"] != "external_url":
                continue
            n = r["name"]
            assert n.startswith("http://127.0.0.1") or ".example/" in n or "FILL-ME" in n, n


# ----------------------------------------------------------------------------- facts_for


def test_facts_for_round_trip(big: tuple[Settings, sf.Generated]) -> None:
    s, gen = big
    ctx = _ctx(s)
    try:
        systems = {r["system_id"]: r for r in ctx.state.query("ai_system")}
        with_agent = [x for x in gen.systems if x.on_agent][:12]
        for x in with_agent:
            doc = orch.facts_for(ctx, x.sid)
            assert doc is not None and doc["version"] == 1
            assert x.node_id in doc["nodes"]
            assert len(doc["facts"]) == len(gen.facts[x.node_id]) - 1  # all but the summary
        prelive = [
            sid
            for sid, r in systems.items()
            if r["created_by"] == sp.CREATED_BY and r["lifecycle_stage"] in ("design", "initiation")
        ]
        assert prelive
        assert orch.facts_for(ctx, prelive[0]) is None  # no code yet: honest "not known"
        flag_off = SimpleNamespace(
            **{**ctx.__dict__, "settings": s.model_copy(update={"onboard_facts": False})}
        )
        assert orch.facts_for(flag_off, with_agent[0].sid) is None  # off path
    finally:
        ctx._a.close()


def test_the_demo_use_case_node_is_never_a_target() -> None:
    bad = sf.SysIn(sid="shw_sys_9999", node_id=PROTECTED, on_agent=False, rec={})
    with pytest.raises(sp.ShowcaseError):
        sf.generate([bad], 1, NOW)


# ----------------------------------------------------------------------------- idempotency, reset


def _foreign_rows(s: Settings) -> None:
    """A real-looking fact on the protected node and an intake by a person, to prove isolation."""
    a = build_adapters(s)
    try:
        a.state.insert(
            "onboard_facts",
            {
                "fact_id": "fct_realrealrealreal0001",
                "node_id": PROTECTED,
                "attempt_n": 1,
                "kind": "tool",
                "name": "transfer",
                "detail": "risk_class=money; approved=yes",
                "file": "code/payops/tools.py",
                "line": 49,
                "quote": "def transfer(",
                "source": "rule",
                "model_id": None,
                "dropped_claims": None,
                "active": True,
                "created_at": NOW,
            },
        )
        a.state.insert(
            "intake_attempt",
            {
                "attempt_id": "ita_realrealrealrealreal01",
                "node_id": PROTECTED,
                "n": 1,
                "source_kind": "upload",
                "source_ref": "payment-ops-copilot.zip",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "file_count": 1,
                "created_by": "reviewer.an",
                "created_at": NOW,
                "status": "scrubbed",
                "detail": "files=1 redacted=0",
            },
        )
    finally:
        a.close()


def test_idempotent_and_reset_touches_only_its_own_rows(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _seed_portfolio(s, 60)
    _foreign_rows(s)
    first = _run(s)
    n_facts, n_intake = first.written["onboard_facts"], first.written["intake_attempt"]
    assert n_facts > 100 and n_intake > 20
    again = _run(s)
    assert again.written == {"intake_attempt": 0, "onboard_facts": 0}
    assert again.skipped == {"intake_attempt": n_intake, "onboard_facts": n_facts}
    assert len(_all(s, "onboard_facts")) == n_facts + 1
    assert len(_all(s, "intake_attempt")) == n_intake + 1
    # a dry run and a reset dry run write and remove nothing
    _run(s, dry_run=True)
    _run(s, reset=True, dry_run=True)
    assert len(_all(s, "onboard_facts")) == n_facts + 1
    # reset removes exactly what this module wrote
    rep = _run(s, reset=True)
    assert rep.removed == {"onboard_facts": n_facts, "intake_attempt": n_intake}
    facts = _all(s, "onboard_facts")
    assert [r["fact_id"] for r in facts] == ["fct_realrealrealreal0001"]
    assert [r["created_by"] for r in _all(s, "intake_attempt")] == ["reviewer.an"]
    assert {r["system_id"] for r in _all(s, "ai_system")}  # the portfolio itself stays
    # and it can be written again
    assert _run(s).written["onboard_facts"] == n_facts


def test_another_seed_does_not_duplicate_a_node(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _seed_portfolio(s, 40)
    _run(s, seed=1)
    before = len(_all(s, "onboard_facts"))
    rep = _run(s, seed=2)
    assert len(_all(s, "onboard_facts")) == before
    assert rep.nodes_kept  # left alone, said so


def test_agents_only_skips_application_nodes(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _seed_portfolio(s, 60)
    rep = _run(s, agents_only=True)
    comps = _all(s, "system_component")
    agents = {c["ref_id"] for c in comps if c["ref_kind"] == "agent"}
    nodes = {r["node_id"] for r in _all(s, "onboard_facts")}
    assert nodes == agents
    assert rep.written["intake_attempt"] == len(agents)


# ----------------------------------------------------------------------------- switches


def test_refused_without_the_flag(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    rep = sf.run(s, env={}, echo=lambda _l: None)
    assert not rep.ok and "SHOWCASE_ENABLED" in rep.lines[-1]
    assert _all(s, "onboard_facts") == []


def test_fails_cleanly_when_there_is_no_portfolio(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    rep = sf.run(s, env=ENV, echo=lambda _l: None)
    assert not rep.ok and "showcase portfolio" in rep.lines[-1]


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        sf.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--reset" in out and "SYNTHETIC" in out
