"""WP-G3: shadow start, review, allow-lists, two-person approval, go-live, rollback, retire, the
daily job, and the chain records (integers only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.guardian_factory import attach, caps
from supervisor.guardian_factory.bench_service import BenchService
from supervisor.guardian_factory.definition import GuardianFactoryError
from supervisor.guardian_factory.promotion import Promotion
from supervisor.guardian_factory.shadow import ShadowRunner
from supervisor.guardian_factory.store import GuardianDefStore, check_transition

from .conftest import ListSink, person, regex_def

DEF = "account-numbers"
AN = person("reviewer.an", "reviewer")  # author, model_risk by role mapping
OTHER = person("reviewer.binh", "reviewer", "approver")
LEAD = AuthPrincipal(
    "lead.model", "user", "t", frozenset({"approver"}), "x", frozenset({"model_risk"})
)
SEC = AuthPrincipal(
    "second.line", "user", "t", frozenset({"approver"}), "x", frozenset({"platform"})
)
ADMIN = person("admin.chi", "admin", "reviewer")
VIEWER = person("viewer.hoa", "viewer")
CALL = {
    "args": {"note": "so tai khoan 0123456789012"},
    "meta": {"agent_id": "payments", "tool_name": "x"},
}


class Clk:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.t

    def advance(self, days: int) -> None:
        self.t += timedelta(days=days)


@pytest.fixture
def clk() -> Clk:
    return Clk()


@pytest.fixture
def gstore(gadapters: Any, sink: ListSink, clk: Clk) -> GuardianDefStore:
    return GuardianDefStore(
        gadapters.state, gadapters.tables, clk, gadapters.settings, evidence=sink
    )


@pytest.fixture
def promo(gstore: GuardianDefStore) -> Promotion:
    return Promotion(gstore)


def benchmarked(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, def_id: str = DEF, **over: Any
) -> None:
    base = {"owner_group": "model_risk", "benchmark_pack": "starter", "id": def_id}
    gstore.create(regex_def(**{**base, **over}), AN)
    svc = BenchService(gstore, data_dir=gadapters.settings.data_dir, evidence=sink)
    svc.generate(def_id, "starter", AN)
    svc.start_run(def_id, AN, background=False)
    assert gstore.mark_benchmarked(def_id, AN)["state"] == "benchmarked"


def runner(gadapters: Any, clk: Clk, **kw: Any) -> ShadowRunner:
    return ShadowRunner(gadapters.state, gadapters.settings, now=clk.now, ttl_s=0, **kw)


def one_finding(gadapters: Any, clk: Clk, n: int = 1) -> list[str]:
    r = runner(gadapters, clk)
    for i in range(n):
        r.observe(CALL, "input", f"corr-{i}")
    r.flush()
    return [f["finding_id"] for f in gadapters.state.query("guardian_shadow_finding", {})]


def to_shadow(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, **over: Any
) -> None:
    benchmarked(gstore, gadapters, sink, **over)
    assert promo.start_shadow(DEF, AN)["state"] == "shadow"


# ============================================================ transitions


def test_transition_table_g3_moves_open() -> None:
    for a, b in [
        ("benchmarked", "shadow"),
        ("shadow", "approved"),
        ("approved", "live"),
        ("live", "retired"),
        ("retired", "live"),
        ("shadow", "draft"),
    ]:
        check_transition(a, b)
    for a, b in [
        ("draft", "live"),
        ("draft", "shadow"),
        ("benchmarked", "live"),
        ("live", "draft"),
    ]:
        with pytest.raises(GuardianFactoryError) as e:
            check_transition(a, b)
        assert e.value.code == "bad_transition", (a, b)
    assert caps.ALLOWED_NOW <= {(a, b) for a, ts in caps.TRANSITIONS.items() for b in ts}


def test_start_shadow_conditions(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion
) -> None:
    gstore.create(regex_def(owner_group="model_risk"), AN)
    with pytest.raises(GuardianFactoryError) as e:  # a draft
        promo.start_shadow(DEF, AN)
    assert e.value.code == "bad_transition"
    svc = BenchService(gstore, data_dir=gadapters.settings.data_dir, evidence=sink)
    gstore.save(DEF, regex_def(owner_group="model_risk", benchmark_pack="starter"), AN)
    svc.generate(DEF, "starter", AN)
    svc.start_run(DEF, AN, background=False)
    gstore.mark_benchmarked(DEF, AN)
    from supervisor.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        promo.start_shadow("nope", AN)
    with pytest.raises(Exception) as pe:  # a viewer may not edit
        promo.start_shadow(DEF, VIEWER)
    assert "guardians.edit" in str(pe.value)
    out = promo.start_shadow(DEF, AN)
    assert out["state"] == "shadow"
    assert out["definition"]["lifecycle"]["shadow_days"] == caps.SHADOW_DAYS_DEFAULT
    with pytest.raises(GuardianFactoryError) as e:  # twice
        promo.start_shadow(DEF, AN)
    assert e.value.code == "bad_transition"
    actions = [r["action"] for r in gadapters.tables.query("guardian_def_event", {"def_id": DEF})]
    assert "shadow_started" in actions


def test_shadow_days_from_definition_and_cap(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion
) -> None:
    benchmarked(gstore, gadapters, sink, lifecycle={"shadow_days": 3})
    out = promo.start_shadow(DEF, AN)
    assert out["definition"]["lifecycle"]["shadow_days"] == 3
    assert promo.status(promo._version(DEF, None))["days_total"] == 3  # noqa: SLF001
    assert Promotion.days_of({"lifecycle": {"shadow_days": 0}}) == 7
    assert Promotion.days_of({"lifecycle": {"shadow_days": 90}}) == 90


# ============================================================ review and allow-lists


def test_review_marks_and_counts(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    ids = one_finding(gadapters, clk, 3)
    assert len(ids) == 3
    assert promo.review(DEF, ids[0], "correct", AN)["reviewed"] == "correct"
    assert promo.review(DEF, ids[1], "false", AN)["reviewed"] == "false"
    with pytest.raises(GuardianFactoryError) as e:
        promo.review(DEF, ids[2], "maybe", AN)
    assert e.value.code == "bad_mark"
    st = promo.status(promo._version(DEF, None))  # noqa: SLF001
    assert (st["reviewed_correct"], st["reviewed_false"], st["pending_n"]) == (1, 1, 1)
    assert st["false_rate_pct"] == 50 and st["calls_seen"] == 3 and st["would_act"] == 3
    rows = promo.findings(DEF)
    assert len(rows) == 3 and {r["reviewed"] for r in rows} == {"correct", "false", None}
    assert len(promo.findings(DEF, pending_only=True)) == 1
    blob = json.dumps(rows)
    assert "0123456789012" not in blob  # hashes and counts only


def test_false_mark_with_allow_entry_and_expiry_rules(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    fid = one_finding(gadapters, clk)[0]
    exp = (clk.now() + timedelta(days=30)).date().isoformat()
    out = promo.review(
        DEF, fid, "false", AN, {"reason": "the batch job sends account numbers", "expires": exp}
    )
    assert out["allow"]["agent_id"] == "payments" and out["allow"]["expires"] == exp
    with pytest.raises(GuardianFactoryError) as e:  # an allow entry goes with a false mark
        promo.review(DEF, fid, "correct", AN, {"reason": "x", "expires": exp})
    assert e.value.code == "bad_mark"
    far = (clk.now() + timedelta(days=91)).date().isoformat()
    past = (clk.now() - timedelta(days=1)).date().isoformat()
    for bad in (far, past, "2026-13-40", "tomorrow", None):
        with pytest.raises(GuardianFactoryError) as e:
            promo.add_allow(DEF, None, "other-agent", "a reason", bad, AN)
        assert e.value.code == "bad_expiry", bad
    with pytest.raises(GuardianFactoryError) as e:
        promo.add_allow(DEF, None, "other-agent", "  ", exp, AN)
    assert e.value.code == "bad_allow"
    with pytest.raises(GuardianFactoryError) as e:
        promo.add_allow(DEF, None, "payments", "again", exp, AN)
    assert e.value.code == "allow_exists"
    last_day = (clk.now() + timedelta(days=90)).date().isoformat()
    assert promo.add_allow(DEF, None, "a2", "ninety days", last_day, AN)["expires"] == last_day
    # the shadow detector now skips the allow-listed agent: no new finding
    before = len(gadapters.state.query("guardian_shadow_finding", {}))
    one_finding(gadapters, clk)
    assert len(gadapters.state.query("guardian_shadow_finding", {})) == before


def test_allow_entry_expires_ignored_flagged_and_removed_by_the_job(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    exp = (clk.now() + timedelta(days=2)).date().isoformat()
    promo.add_allow(DEF, None, "payments", "short", exp, AN)
    row = promo._version(DEF, None)  # noqa: SLF001
    assert promo.allow_view(row)[0]["expired"] is False
    clk.advance(3)
    assert promo.allow_view(row)[0]["expired"] is True  # flagged on the panel
    assert promo.summary(DEF)["allow_list"][0]["expired"] is True
    # an expired entry is ignored: the shadow detector fires for the agent again
    assert len(one_finding(gadapters, clk)) == 1
    assert promo.expire_allow_entries() == 1
    assert promo.allow_view(promo._version(DEF, None)) == []  # noqa: SLF001
    ev = [
        r
        for r in gadapters.tables.query("guardian_def_event", {"def_id": DEF})
        if r["action"] == "allow_expired"
    ]
    assert len(ev) == 1
    assert promo.expire_allow_entries() == 0
    assert [r for _, _, r in sink.records if r.get("action") == "allow_expired"]


# ============================================================ approval, live, rollback


def finish_shadow(promo: Promotion, gadapters: Any, clk: Clk, reviews: str = "correct") -> None:
    for fid in one_finding(gadapters, clk, 2):
        promo.review(DEF, fid, reviews, AN)
    clk.advance(8)


def test_approve_refusals_and_two_person_flow(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    ids = one_finding(gadapters, clk, 2)
    # period not complete: 400 shadow_not_passed with the numbers
    with pytest.raises(GuardianFactoryError) as e:
        promo.approve(DEF, LEAD)
    assert e.value.code == "shadow_not_passed"
    assert "day 0 of 7" in str(e.value) and "calls seen 2" in str(e.value)
    clk.advance(8)
    with pytest.raises(GuardianFactoryError) as e:  # complete, nothing reviewed
        promo.approve(DEF, LEAD)
    assert e.value.code == "shadow_not_passed" and "no finding is reviewed" in str(e.value)
    promo.review(DEF, ids[0], "false", AN)
    promo.review(DEF, ids[1], "correct", AN)
    with pytest.raises(GuardianFactoryError) as e:  # 50 percent false, limit 5
        promo.approve(DEF, LEAD)
    assert e.value.code == "shadow_not_passed" and "50 percent" in str(e.value)
    assert e.value.problems[0]["false_rate_pct"] == 50
    promo.review(DEF, ids[0], "correct", AN)
    # who may not approve
    with pytest.raises(GuardianFactoryError) as e:
        promo.approve(DEF, AN)  # the author, and a reviewer
    assert e.value.code in ("not_eligible", "author_cannot_approve")
    with pytest.raises(GuardianFactoryError) as e:
        promo.approve(DEF, VIEWER)
    assert e.value.code == "not_eligible"
    with pytest.raises(GuardianFactoryError) as e:
        promo.approve(DEF, LEAD, "boss")
    assert e.value.code == "bad_kind"
    first = promo.approve(DEF, LEAD)
    assert first["approved"] is False and first["approval"]["kind"] == "owner_lead"
    assert first["state"] == "shadow"
    with pytest.raises(GuardianFactoryError) as e:  # the same kind again
        promo.approve(DEF, LEAD, "owner_lead")
    assert e.value.code == "same_person"
    with pytest.raises(GuardianFactoryError) as e:  # go-live too early
        promo.go_live(DEF, LEAD)
    assert e.value.code == "bad_transition"
    second = promo.approve(DEF, SEC)
    assert second["approved"] is True and second["state"] == "approved"
    assert {a["kind"] for a in second["definition"]["lifecycle"]["approvals"]} == set(
        caps.APPROVAL_KINDS
    )


def test_same_person_and_author_rules(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    finish_shadow(promo, gadapters, clk)
    promo.approve(DEF, ADMIN, "owner_lead")
    with pytest.raises(GuardianFactoryError) as e:  # an admin is both kinds, but one person
        promo.approve(DEF, ADMIN, "platform_security")
    assert e.value.code == "same_person"
    with pytest.raises(GuardianFactoryError) as e:  # case does not matter
        promo.approve(DEF, person("ADMIN.CHI", "admin"), "platform_security")
    assert e.value.code == "same_person"
    # the author, even as an admin, never approves
    row = promo._version(DEF, None)  # noqa: SLF001
    assert "reviewer.an" in promo.authors_of(row)
    author_admin = person("reviewer.an", "admin", "reviewer")
    with pytest.raises(GuardianFactoryError) as e:
        promo.approve(DEF, author_admin, "platform_security")
    assert e.value.code == "author_cannot_approve"
    assert promo.approve(DEF, SEC)["state"] == "approved"


def test_go_live_attaches_replaces_and_rolls_back(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    finish_shadow(promo, gadapters, clk)
    promo.approve(DEF, LEAD)
    promo.approve(DEF, SEC)
    with pytest.raises(GuardianFactoryError) as e:  # a reviewer is not an owner lead
        promo.go_live(DEF, AN)
    assert e.value.code == "not_eligible"
    live = promo.go_live(DEF, LEAD)
    assert live["state"] == "live" and live["binding"] == {
        "slug": "gf:account-numbers@1",
        "agents": "*",
    }
    assert attach.live_slugs(gadapters.state) == ["gf:account-numbers@1"]
    # immutable: no save in place
    with pytest.raises(GuardianFactoryError) as e:
        gstore.save(DEF, regex_def(owner_group="model_risk"), AN)
    assert e.value.code == "not_draft"
    # version 2: new version, bench, shadow, approve, live; version 1 becomes retired
    gstore.new_version(DEF, AN)
    svc = BenchService(gstore, data_dir=gadapters.settings.data_dir, evidence=sink)
    svc.start_run(DEF, AN, background=False)
    gstore.mark_benchmarked(DEF, AN)
    promo.start_shadow(DEF, AN)
    clk.advance(8)
    promo.approve(DEF, LEAD)
    promo.approve(DEF, SEC)
    promo.go_live(DEF, LEAD)
    states = {
        r["version"]: r["state"] for r in gadapters.state.query("guardian_def", {"def_id": DEF})
    }
    assert states == {1: "retired", 2: "live"}
    assert attach.live_slugs(gadapters.state) == ["gf:account-numbers@2"]
    assert gstore.get(DEF, 1)["state"] == "retired"  # stays readable
    # rollback: admin only, with a reason
    for who, code in ((LEAD, "not_admin"), (AN, "not_admin")):
        with pytest.raises(GuardianFactoryError) as e:
            promo.rollback(DEF, who, "a long enough reason for the rollback")
        assert e.value.code == code
    with pytest.raises(GuardianFactoryError) as e:
        promo.rollback(DEF, ADMIN, "short")
    assert e.value.code == "reason_needed"
    back = promo.rollback(DEF, ADMIN, "version 2 blocks a nightly batch")
    assert back["version"] == 1 and back["state"] == "live"
    states = {
        r["version"]: r["state"] for r in gadapters.state.query("guardian_def", {"def_id": DEF})
    }
    assert states == {1: "live", 2: "retired"}
    with pytest.raises(GuardianFactoryError) as e:  # nothing older than version 1
        promo.rollback(DEF, ADMIN, "version 1 blocks a nightly batch")
    assert e.value.code == "no_previous_version"


def test_retire_on_request_and_stop_shadow(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    assert promo.stop_shadow(DEF, AN)["state"] == "draft"
    benchmarked_again = gstore.mark_benchmarked(DEF, AN)
    assert benchmarked_again["state"] == "benchmarked"
    promo.start_shadow(DEF, AN)
    assert promo.retire_version(DEF, None, AN)["state"] == "retired"
    with pytest.raises(GuardianFactoryError) as e:
        promo.stop_shadow(DEF, AN)
    assert e.value.code == "bad_transition"


def test_events_and_chain_records_hold_integers_and_ids_only(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    finish_shadow(promo, gadapters, clk)
    promo.approve(DEF, LEAD)
    promo.approve(DEF, SEC)
    promo.go_live(DEF, LEAD)
    actions = [r["action"] for r in gadapters.tables.query("guardian_def_event", {"def_id": DEF})]
    for a in ("shadow_started", "approval", "approved", "live"):
        assert a in actions, a
    recs = sink.of("guardian_promotion")
    assert [r["action"] for r in recs if r["action"] in ("shadow_started", "approved", "live")] == [
        "shadow_started",
        "approved",
        "live",
    ]
    for r in recs:
        assert set(r) >= {
            "def_id",
            "version",
            "action",
            "from",
            "to",
            "def_sha256",
            "actor_ref",
            "ts",
        }
        assert r["actor_ref"].startswith(("p-", "a-", "u-")) or len(r["actor_ref"]) >= 8
        assert not any(isinstance(v, float) for v in r.values())
        assert "reviewer.an" not in json.dumps(r) and "lead.model" not in json.dumps(r)
    approved = next(r for r in recs if r["action"] == "approved")
    assert (
        approved["approvals_n"] == 2
        and approved["from"] == "shadow"
        and approved["to"] == "approved"
    )


def test_daily_job_closes_days_with_counts_only(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    fids = one_finding(gadapters, clk, 2)
    promo.review(DEF, fids[0], "false", AN)
    assert promo.close_days() == 0  # today is not closed
    clk.advance(1)
    assert promo.close_days() == 1
    assert promo.close_days() == 0  # once
    rec = sink.of("guardian_shadow_day")
    assert len(rec) == 1
    r = rec[0]
    assert (r["calls_seen"], r["would_act"], r["findings_n"]) == (2, 2, 2)
    assert (r["reviewed_false_n"], r["reviewed_correct_n"]) == (1, 0)
    assert all(isinstance(v, (int, str)) for v in r.values())
    assert "0123456789012" not in json.dumps(r)


def test_job_module_runs(gadapters: Any, gstore: GuardianDefStore, sink: ListSink) -> None:
    from supervisor.jobs import guardian_shadow
    from supervisor.monitors.common import MonitorContext

    assert guardian_shadow.enabled(gadapters.settings)
    ctx = MonitorContext.from_adapters(gadapters, sink)
    out = guardian_shadow.run(ctx, gadapters.settings)
    assert out == {"allow_expired": 0, "days_closed": 0}


def _short_trial(
    gadapters: Any, monkeypatch: pytest.MonkeyPatch, hours: int, showcase: bool
) -> None:
    monkeypatch.setattr(gadapters.settings, "guardian_shadow_min_hours", hours)
    monkeypatch.setattr(gadapters.settings, "showcase_enabled", showcase)


def test_shadow_min_default_is_unchanged(
    gstore: GuardianDefStore, gadapters: Any, sink: ListSink, promo: Promotion, clk: Clk
) -> None:
    to_shadow(gstore, gadapters, sink, promo)
    clk.t += timedelta(hours=2)
    st = promo.status(promo._version(DEF, None))
    assert not st["complete"] and st["demo_min_hours"] is None
    assert "day 0 of 7" in "; ".join(st["problems"])


def test_shadow_min_short_value_honoured_with_showcase(
    gstore: GuardianDefStore,
    gadapters: Any,
    sink: ListSink,
    promo: Promotion,
    clk: Clk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _short_trial(gadapters, monkeypatch, 1, True)
    to_shadow(gstore, gadapters, sink, promo)
    row = promo._version(DEF, None)
    assert not promo.status(row)["complete"]
    clk.t += timedelta(minutes=61)
    st = promo.status(row)
    assert st["complete"] and st["demo_min_hours"] == 1


def test_shadow_min_short_value_ignored_without_showcase(
    gstore: GuardianDefStore,
    gadapters: Any,
    sink: ListSink,
    promo: Promotion,
    clk: Clk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _short_trial(gadapters, monkeypatch, 1, False)
    to_shadow(gstore, gadapters, sink, promo)
    clk.t += timedelta(hours=3)
    st = promo.status(promo._version(DEF, None))
    assert not st["complete"] and st["demo_min_hours"] is None
