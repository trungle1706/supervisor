"""WP29 follow-ups after review: evidence sources in the starters, no raw actor id on the chain,
a bounded latest-evidence read, the CLI --by rule, judge-scored packs as references."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.core.schema import load_model
from supervisor.risk import __main__ as cli
from supervisor.risk import evidence as ev
from supervisor.risk import harness as H
from supervisor.risk.harness import _Env
from supervisor.risk.service import RiskService

from .conftest import STARTERS, ListSink, risk_data


def _file(tmp_path: Path, links: str) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    (d / "x.yaml").write_text(
        "version: 1\nrisks:\n  - {id: X-1, agent: payments, title: t, category: pii,\n"
        "     treatment: mitigate, owner: o, inherent: {likelihood: 2, impact: 2},\n"
        f"     links: {links}}}\n",
        encoding="utf-8",
    )
    return d


# ---- 1. starters need a real evidence source ------------------------------------------------


def test_every_starter_has_an_evidence_source_and_none_uses_statusless_monitors() -> None:
    assert H.check_starters()["problems"] == []
    for f in STARTERS.glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "monitor: [oversight]" not in text and "monitor: [sweeps]" not in text


@pytest.mark.parametrize(
    "links",
    [
        "{matrix: [VN-TT50-2024-A10.1-01]}",
        "{matrix: [VN-TT50-2024-A10.1-01], monitor: [oversight], pack: [halueval_vi]}",
        "{monitor: [quality]}",
    ],
)
def test_a_risk_with_only_reference_links_fails_the_starter_check(
    tmp_path: Path, links: str
) -> None:
    out = H.check_starters(_file(tmp_path, links))
    assert any("only reference links" in p for p in out["problems"]), out


def test_a_rule_link_is_an_evidence_source(tmp_path: Path) -> None:
    assert H.check_starters(_file(tmp_path, "{rule: [PAY-02]}"))["problems"] == []


# ---- 2. no raw actor id on the chain --------------------------------------------------------


def test_chain_payloads_carry_a_keyed_hash_not_the_actor(svc: RiskService, sink: ListSink) -> None:
    who = "ops.lead@bank.example"
    svc.create(risk_data(), who, risk_id="R-1", links=[("rule", "PAY-02")])
    svc.update("R-1", {"owner": "x"}, who)
    svc.add_link("R-1", "monitor", "drift", who)
    svc.run_evidence()
    assert sink.records
    for _, _, payload in sink.records:
        assert "@" not in json.dumps(payload) and "actor" not in payload
    refs = {p["actor_ref"] for p in sink.of("risk_change")}
    assert refs == {svc.actor_ref(who)} and svc.actor_ref(who).startswith("act_")
    assert svc.actor_ref("someone.else") != svc.actor_ref(who)


# ---- 3. bounded latest-evidence read ---------------------------------------------------------


def test_latest_evidence_is_found_beyond_the_old_20000_row_cap(svc: RiskService) -> None:
    svc.create(risk_data(), "t", risk_id="R-OLD")
    svc.create(risk_data(title="other"), "t", risk_id="R-NEW")
    cols = load_model().table("risk_evidence").column_names
    base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def row(i: int, rid: str, ts: dt.datetime) -> dict[str, Any]:
        r: dict[str, Any] = {c: 0 for c in cols}
        r |= {
            "evidence_id": f"e{i}", "risk_id": rid, "ts": ts, "window_start": ts, "window_end": ts,
            "state": "working", "reason": "controls_working", "digest": "0" * 64,
            "chain_hash": None,
        }  # fmt: skip
        return r

    rows = [row(0, "R-OLD", base)]
    rows += [row(i, "R-NEW", base + dt.timedelta(minutes=i)) for i in range(1, 20_200)]
    svc.tables.append("risk_evidence", rows)
    assert len(svc.tables.query("risk_evidence", limit=30_000)) == 20_200
    latest = svc._latest_evidence()  # noqa: SLF001
    assert latest["R-OLD"]["evidence_id"] == "e0"
    assert latest["R-NEW"]["evidence_id"] == "e20199"


# ---- 4. CLI import needs --by ----------------------------------------------------------------


def test_import_without_by_is_refused(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setenv("RISK_REGISTER_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    with pytest.raises(SystemExit) as stop:
        cli.main(["import", str(STARTERS)])
    assert stop.value.code == 2
    assert "--by" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["import", str(STARTERS), "--by", "bad id"])
    assert "--by" in cli.__doc__ and "own" in cli.__doc__


def test_import_by_is_audited_and_chained_as_a_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    monkeypatch.setenv("RISK_REGISTER_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    assert cli.main(["import", str(STARTERS), "--by", "ops.lead@bank.example"]) == 0
    a = build_adapters(load_settings())
    try:
        (row,) = [
            r
            for r in a.tables.query("console_action")
            if r["permission"] == "risks.edit" and r["method"] == "CLI"
        ]
        assert row["actor"] == "ops.lead@bank.example" and row["outcome"] == "ok"
        payloads = [
            json.loads(
                a.tables.query("chain_payload", {"lane": e["lane"], "seq": e["seq"]})[0]["payload"]
            )
            for e in a.tables.query("chain_entry", {"record_type": "risk_change"})
        ]
        assert payloads and all("@" not in json.dumps(p) for p in payloads)
    finally:
        a.close()


# ---- 5. judge-scored packs are references by default -----------------------------------------


def test_judge_scored_pack_is_idle_unless_the_owner_allows_it(env: _Env) -> None:
    env.svc.catalogue._src["pack"] = lambda: ["groundedness_monitor", "pack_a"]  # noqa: SLF001
    env.agent("pay")
    rid = env.risk("judged", "pay", [("pack", "groundedness_monitor")])
    env.pack("pay", "groundedness_monitor", "ok", env.window_time())
    env.svc.run_evidence()
    r = env.svc.get(rid)
    assert r["evidence_state"] == "no_evidence" and r["residual_score"] == 20
    assert env.settings.risk_evidence_judged_packs is False

    env.settings.risk_evidence_judged_packs = True
    other = env.risk("judged on", "pay", [("pack", "groundedness_monitor")])
    env.svc.run_evidence()
    assert env.svc.get(other)["evidence_state"] == "working"


def test_judged_pack_list_matches_the_packs_that_exist() -> None:
    from supervisor.assurance.loader import load_packs

    assert set(ev.JUDGED_PACKS) <= {p.id for p in load_packs()}
