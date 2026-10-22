"""WP-G1 services: stage approvals and the lifecycle move, reviews, outbound events, chain."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core.errors import NotFoundError
from supervisor.governance import events
from supervisor.governance.lifecycle import LifecycleService
from supervisor.governance.model import SegregationOfDuties, SystemsError
from supervisor.governance.reviews import ReviewService
from supervisor.governance.systems import SystemService

from .conftest import ListSink, draft, person

OWNER = "owner.lan"
REV = person("rev.an", "reviewer")
APPROVER = person("approver.em", "approver")


@pytest.fixture
def life(svc: SystemService) -> LifecycleService:
    return LifecycleService(svc)


@pytest.fixture
def revs(svc: SystemService) -> ReviewService:
    return ReviewService(svc)


def _system(svc: SystemService, **over: Any) -> str:
    return str(svc.register(draft(**over), OWNER)["system_id"])


def _sink_payloads(sink: ListSink, kind: str) -> list[dict[str, Any]]:
    return sink.of(kind)


# ------------------------------------------------------------------ stage approval


def test_default_policy_marks_deployment_and_operation(life: LifecycleService) -> None:
    assert [
        s for s in ("design", "deployment", "operation", "retirement") if life.needs_approval(s)
    ] == [
        "deployment",
        "operation",
    ]


def test_a_stage_without_approval_moves_directly(
    svc: SystemService, life: LifecycleService, sink: ListSink
) -> None:
    sid = _system(svc)
    out = life.move(sid, "design", OWNER)
    assert out["lifecycle_stage"] == "design"
    (rec,) = sink.of("stage_change")
    assert (
        rec["action"] == "move"
        and rec["from_stage"] == "initiation"
        and rec["to_stage"] == "design"
    )
    with pytest.raises(SystemsError, match="already in the design"):
        life.move(sid, "design", OWNER)
    with pytest.raises(SystemsError, match="to_stage"):
        life.move(sid, "launch", OWNER)


def test_a_stage_with_approval_needs_an_approved_row(
    svc: SystemService, life: LifecycleService
) -> None:
    sid = _system(svc)
    with pytest.raises(SystemsError, match="needs an approved stage approval"):
        life.move(sid, "deployment", OWNER)
    ap = life.request(sid, "deployment", OWNER)
    assert ap["status"] == "pending" and ap["from_stage"] == "initiation"
    with pytest.raises(SystemsError, match="needs an approved"):
        life.move(sid, "deployment", OWNER)  # pending is not enough
    life.decide(sid, ap["approval_id"], "approve", APPROVER)
    assert life.move(sid, "deployment", OWNER)["lifecycle_stage"] == "deployment"
    row = svc.state.get("stage_approval", {"approval_id": ap["approval_id"]})
    assert row["applied_at"] is not None
    # the approval is used up: going back and again needs a new one
    life.move(sid, "design", OWNER)
    with pytest.raises(SystemsError, match="needs an approved"):
        life.move(sid, "deployment", OWNER)


def test_request_rules(svc: SystemService, life: LifecycleService) -> None:
    sid = _system(svc)
    with pytest.raises(SystemsError, match="needs no approval"):
        life.request(sid, "design", OWNER)
    with pytest.raises(SystemsError, match="already in the initiation"):
        life.request(sid, "initiation", OWNER)
    life.request(sid, "deployment", OWNER)
    with pytest.raises(SystemsError, match="already waiting"):
        life.request(sid, "deployment", OWNER)
    life.request(sid, "operation", OWNER)  # another target is fine
    with pytest.raises(NotFoundError):
        life.request("sys_nope", "deployment", OWNER)


def test_approver_rules_and_segregation_of_duties(
    svc: SystemService, life: LifecycleService
) -> None:
    sid = _system(svc)
    ap = life.request(sid, "deployment", "tech.minh")
    aid = ap["approval_id"]
    # a person with no standing
    with pytest.raises(SystemsError, match="only a reviewer or oversight manager"):
        life.decide(sid, aid, "approve", person("someone", "owner"))
    # a team reviewer may answer; an oversight manager too
    svc.add_member(sid, "rev.an", "reviewer", OWNER)
    svc.add_member(sid, "over.sight", "oversight_manager", OWNER)
    # the requester cannot answer, even as team reviewer
    svc.add_member(sid, "tech.minh", "reviewer", OWNER)
    with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
        life.decide(sid, aid, "approve", person("tech.minh", "reviewer"))
    # the owner cannot answer, even with the approver role (any case)
    with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
        life.decide(sid, aid, "approve", person("Owner.Lan", "approver"))
    # the system_owner team role counts as owner too
    svc.add_member(sid, "co.owner", "system_owner", OWNER)
    with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
        life.decide(sid, aid, "approve", person("co.owner", "approver"))
    out = life.decide(sid, aid, "approve", person("over.sight", "viewer"), "Looks right")
    assert out["status"] == "approved" and out["decided_by"] == "over.sight"
    assert out["reason"] == "Looks right" and out["decided_at"].endswith("Z")
    with pytest.raises(SystemsError, match="already answered"):
        life.decide(sid, aid, "reject", APPROVER, "late")


def test_reject_needs_a_reason_and_blocks_the_move(
    svc: SystemService, life: LifecycleService
) -> None:
    sid = _system(svc)
    aid = life.request(sid, "operation", OWNER)["approval_id"]
    with pytest.raises(SystemsError, match="reason is required"):
        life.decide(sid, aid, "reject", APPROVER)
    with pytest.raises(SystemsError, match="decision"):
        life.decide(sid, aid, "maybe", APPROVER)
    out = life.decide(sid, aid, "reject", APPROVER, "Evidence missing")
    assert out["status"] == "rejected"
    with pytest.raises(SystemsError, match="needs an approved"):
        life.move(sid, "operation", OWNER)
    with pytest.raises(NotFoundError):
        life.decide(sid, "ap_nope", "approve", APPROVER)
    other = _system(svc, name="Other system")
    with pytest.raises(NotFoundError):  # an approval of another system
        life.decide(other, aid, "approve", APPROVER)


def test_a_stale_approval_is_refused(svc: SystemService, life: LifecycleService) -> None:
    sid = _system(svc)
    aid = life.request(sid, "deployment", OWNER)["approval_id"]
    life.move(sid, "design", OWNER)
    with pytest.raises(SystemsError, match="ask again"):
        life.decide(sid, aid, "approve", APPROVER)
    # an approval granted before the system moved cannot be used from another stage
    sid2 = _system(svc, name="Second")
    a2 = life.request(sid2, "deployment", OWNER)["approval_id"]
    life.decide(sid2, a2, "approve", APPROVER)
    life.move(sid2, "design", OWNER)
    with pytest.raises(SystemsError, match="needs an approved"):
        life.move(sid2, "deployment", OWNER)


def test_retired_and_archived_systems_do_not_move(
    svc: SystemService, life: LifecycleService
) -> None:
    sid = _system(svc)
    life.move(sid, "retirement", OWNER)
    with pytest.raises(SystemsError, match="retired"):
        life.move(sid, "design", OWNER)
    other = _system(svc, name="Other")
    svc.archive(other, OWNER)
    with pytest.raises(SystemsError, match="archived"):
        life.move(other, "design", OWNER)
    with pytest.raises(SystemsError, match="archived"):
        life.request(other, "deployment", OWNER)


def test_patch_cannot_change_the_stage(svc: SystemService) -> None:
    sid = _system(svc)
    with pytest.raises(SystemsError, match="/stage"):
        svc.update_fields(sid, {"lifecycle_stage": "deployment"}, OWNER)
    # the same value is a no-op next to another field
    out = svc.update_fields(sid, {"lifecycle_stage": "initiation", "purpose": "New"}, OWNER)
    assert out["purpose"] == "New" and out["lifecycle_stage"] == "initiation"


def test_stage_policy_can_come_from_the_file(svc: SystemService) -> None:
    life = LifecycleService(svc, policy={"design": True})
    sid = _system(svc)
    with pytest.raises(SystemsError, match="needs an approved"):
        life.move(sid, "design", OWNER)
    assert life.move(sid, "deployment", OWNER)["lifecycle_stage"] == "deployment"


def test_stage_change_chain_records_hold_ids_and_enums_only(
    svc: SystemService, life: LifecycleService, sink: ListSink
) -> None:
    sid = _system(svc, owner_user="owner.lan")
    aid = life.request(sid, "deployment", "tech.minh@bank.example")["approval_id"]
    life.decide(sid, aid, "approve", person("approver.em@bank.example", "approver"), "Because X")
    life.move(sid, "deployment", "owner.lan")
    recs = _sink_payloads(sink, "stage_change")
    assert [r["action"] for r in recs] == ["request", "approve", "move"]
    text = json.dumps(recs, sort_keys=True)
    for secret in ("tech.minh", "bank.example", "Because X", "owner.lan"):
        assert secret not in text
    assert "." not in "".join(str(v) for r in recs for v in r.values() if isinstance(v, int))
    assert not [v for r in recs for v in r.values() if isinstance(v, float)]
    assert all(r["ts"].endswith("Z") for r in recs)
    assert recs[1]["reason_hash"] and recs[2]["approval_id"] == aid
    assert recs[1]["actor_ref"].startswith("act_") and recs[1]["actor_ref"] != recs[0]["actor_ref"]


# ------------------------------------------------------------------ reviews


def _review(revs: ReviewService, sid: str, **over: Any) -> dict[str, Any]:
    data = {
        "kind": "internal",
        "title": "Annual review",
        "reviewer_user": "rev.an",
        "scope": [{"kind": "agent", "id": "payments"}, {"kind": "system", "id": sid}],
        "window_start": "2026-01-01T00:00:00Z",
        "window_end": "2026-03-31T00:00:00Z",
        **over,
    }
    return revs.create(sid, data, "plan.er")


def test_review_lifecycle_lock_and_reopen(
    svc: SystemService, revs: ReviewService, sink: ListSink
) -> None:
    sid = _system(svc)
    r = _review(revs, sid)
    rid = r["review_id"]
    assert r["status"] == "planned" and r["locked"] is False and r["reports"] == []
    assert r["window_start"].endswith("Z") and r["scope"][0]["kind"] == "agent"
    out = revs.update(
        sid,
        rid,
        {
            "status": "in_progress",
            "reports": [
                {"kind": "file", "ref": "reports/q1.pdf", "sha256": "A" * 64},
                {"kind": "link", "ref": "https://intranet.example/review/1"},
                {"kind": "note", "ref": "Checked the logs."},
            ],
        },
        "plan.er",
    )
    assert out["status"] == "in_progress" and len(out["reports"]) == 3
    assert out["reports"][0]["sha256"] == "a" * 64
    assert out["reports"][2]["sha256"] and out["reports"][1]["sha256"] == ""
    with pytest.raises(SystemsError, match="only the reviewer"):
        revs.complete(sid, rid, person("someone.else", "reviewer"))
    done = revs.complete(sid, rid, person("rev.an", "reviewer"))
    assert done["status"] == "completed" and done["locked"] is True
    assert done["completed_at"].endswith("Z") and done["completed_by"] == "rev.an"
    with pytest.raises(SystemsError, match="locked"):
        revs.update(sid, rid, {"title": "New"}, "plan.er")
    with pytest.raises(SystemsError, match="already completed"):
        revs.complete(sid, rid, person("rev.an", "reviewer"))
    with pytest.raises(SystemsError, match="reason is required"):
        revs.reopen(sid, rid, person("rev.an", "reviewer"), "")
    with pytest.raises(SystemsError, match="only the reviewer"):
        revs.reopen(sid, rid, person("someone.else", "reviewer"), "Need more")
    back = revs.reopen(sid, rid, person("approver.em", "approver"), "New evidence arrived")
    assert back["status"] == "reopened" and back["locked"] is False
    assert back["reopen_count"] == 1 and back["reopen_reason"] == "New evidence arrived"
    assert (
        revs.update(sid, rid, {"title": "Annual review 2"}, "plan.er")["title"] == "Annual review 2"
    )
    again = revs.complete(sid, rid, person("admin.chi", "admin"))
    assert again["status"] == "completed" and again["locked"] is True
    with pytest.raises(SystemsError, match="only a completed"):
        revs.reopen(sid, _review(revs, sid, title="Second")["review_id"], APPROVER, "why")
    actions = [(p["action"], p["locked"]) for p in sink.of("review_change")]
    assert actions == [
        ("create", 0),
        ("update", 0),
        ("complete", 1),
        ("reopen", 0),
        ("update", 0),
        ("complete", 1),
        ("create", 0),
    ]


def test_review_validation(svc: SystemService, revs: ReviewService) -> None:
    sid = _system(svc)
    base = {"kind": "internal", "title": "T", "reviewer_user": "rev.an"}
    bad: list[tuple[dict[str, Any], str]] = [
        ({**base, "kind": "audit"}, "kind"),
        ({**base, "title": ""}, "required"),
        ({**base, "reviewer_user": "bad user"}, "reviewer_user"),
        ({**base, "scope": [{"kind": "model", "id": "x"}]}, "scope kind"),
        ({**base, "scope": [{"kind": "agent"}]}, "ref_id"),
        ({**base, "scope": "all"}, "list"),
        ({**base, "reports": [{"kind": "file", "ref": "a"}]}, "sha256"),
        ({**base, "reports": [{"kind": "file", "ref": "a", "sha256": "xyz"}]}, "64"),
        ({**base, "reports": [{"kind": "link", "ref": "javascript:alert(1)"}]}, "https"),
        ({**base, "reports": [{"kind": "blob", "ref": "a"}]}, "report kind"),
        ({**base, "window_start": "yesterday"}, "RFC 3339"),
        (
            {**base, "window_start": "2026-05-01T00:00:00Z", "window_end": "2026-01-01T00:00:00Z"},
            "later",
        ),
        ({**base, "status": "completed"}, "planned"),
        ({**base, "colour": "red"}, "unknown field"),
        ({"kind": "internal"}, "required"),
    ]
    for data, text in bad:
        with pytest.raises(SystemsError, match=text):
            revs.create(sid, data, "plan.er")
    with pytest.raises(NotFoundError):
        revs.get(sid, "rv_nope")
    with pytest.raises(NotFoundError):
        revs.list_reviews("sys_nope")
    r = revs.create(sid, base, "plan.er")
    with pytest.raises(SystemsError, match="cannot change"):
        revs.update(sid, r["review_id"], {"locked": False}, "plan.er")
    with pytest.raises(SystemsError, match="status"):
        revs.update(sid, r["review_id"], {"status": "completed"}, "plan.er")
    with pytest.raises(SystemsError, match="nothing to change"):
        revs.update(sid, r["review_id"], {}, "plan.er")
    other = _system(svc, name="Other")
    with pytest.raises(NotFoundError):
        revs.get(other, r["review_id"])


def test_the_owner_cannot_review_their_own_system(svc: SystemService, revs: ReviewService) -> None:
    sid = _system(svc)
    with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
        revs.create(sid, {"kind": "internal", "title": "T", "reviewer_user": "OWNER.lan"}, "x")
    ok = revs.create(sid, {"kind": "internal", "title": "T", "reviewer_user": "rev.an"}, "x")
    with pytest.raises(SegregationOfDuties):
        revs.update(sid, ok["review_id"], {"reviewer_user": OWNER}, "x")
    svc.add_member(sid, "co.owner", "system_owner", OWNER)
    with pytest.raises(SegregationOfDuties):
        revs.update(sid, ok["review_id"], {"reviewer_user": "co.owner"}, "x")


def test_review_chain_record_holds_ids_enums_and_hashes_only(
    svc: SystemService, revs: ReviewService, sink: ListSink
) -> None:
    sid = _system(svc)
    r = _review(revs, sid, title="Secret title", reviewer_user="rev.an@bank.example")
    revs.update(sid, r["review_id"], {"reports": [{"kind": "note", "ref": "Private note"}]}, "x")
    revs.complete(sid, r["review_id"], person("rev.an@bank.example", "reviewer"))
    revs.reopen(sid, r["review_id"], APPROVER, "Private reason")
    recs = sink.of("review_change")
    text = json.dumps(recs, sort_keys=True)
    for secret in ("Secret title", "Private note", "Private reason", "bank.example", "payments"):
        assert secret not in text
    assert not [v for p in recs for v in p.values() if isinstance(v, float)]
    last = recs[-1]
    assert last["action"] == "reopen" and last["reason_hash"] and last["reopen_count"] == 1
    assert last["scope_n"] == 2 and last["reports_n"] == 1 and len(last["reports_hash"]) == 64


# ------------------------------------------------------------------ outbound events


def test_events_are_written_on_the_four_occasions(
    adapters: Adapters, svc: SystemService, life: LifecycleService, revs: ReviewService
) -> None:
    sid = _system(svc)
    aid = life.request(sid, "deployment", OWNER)["approval_id"]
    life.decide(sid, aid, "approve", APPROVER)
    r = _review(revs, sid)
    revs.complete(sid, r["review_id"], person("rev.an", "reviewer"))
    svc.archive(sid, OWNER)
    rows = events.list_events(adapters.state, sid)
    assert sorted(e["kind"] for e in rows) == [
        "review_completed",
        "stage_approved",
        "system_archived",
        "system_registered",
    ]
    for e in rows:
        assert e["delivered"] in (False, 0) and e["delivered_at"] is None
        payload = e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"])
        assert payload["system_id"] == sid
        assert all(isinstance(v, (str, int)) for v in payload.values())
        assert "owner" not in json.dumps(payload) and "Payments" not in json.dumps(payload)
    by = {e["kind"]: e for e in rows}
    ap = by["stage_approved"]["payload"]
    ap = ap if isinstance(ap, dict) else json.loads(ap)
    assert ap == {
        "approval_id": aid,
        "from_stage": "initiation",
        "system_id": sid,
        "to_stage": "deployment",
    }
    assert events.deliver_pending(adapters.state, adapters.clock, adapters.settings) == 0


def test_a_rejection_makes_no_stage_approved_event(
    adapters: Adapters, svc: SystemService, life: LifecycleService
) -> None:
    sid = _system(svc)
    aid = life.request(sid, "deployment", OWNER)["approval_id"]
    life.decide(sid, aid, "reject", APPROVER, "No")
    assert "stage_approved" not in [e["kind"] for e in events.list_events(adapters.state, sid)]


def test_webhook_stub_marks_delivered_and_logs(
    adapters: Adapters,
    svc: SystemService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapters.settings.webhooks_enabled = True
    caplog.set_level("INFO", logger="supervisor.notify.outbound")
    sid = _system(svc)
    (e,) = events.list_events(adapters.state, sid)
    assert e["kind"] == "system_registered" and e["delivered"] in (True, 1)
    assert e["delivered_at"] is not None
    assert any("not sent" in rec.message and e["event_id"] in rec.message for rec in caplog.records)


def test_deliver_pending_sends_the_backlog_when_turned_on(
    adapters: Adapters, svc: SystemService
) -> None:
    _system(svc, name="A")
    _system(svc, name="B")
    assert events.deliver_pending(adapters.state, adapters.clock, adapters.settings) == 0
    adapters.settings.webhooks_enabled = True
    assert events.deliver_pending(adapters.state, adapters.clock, adapters.settings) == 2
    assert events.deliver_pending(adapters.state, adapters.clock, adapters.settings) == 0


def test_event_payload_must_be_ids_and_enums(adapters: Adapters) -> None:
    for bad in ({"name": "has space"}, {"x": 1.5}, {"x": True}, {"x": ["a"]}, {"bad key": "a"}):
        with pytest.raises(SystemsError):
            events.check_payload(bad)
    # a write that fails is logged and dropped, never raised
    assert (
        events.emit(adapters.state, adapters.clock, adapters.settings, "nope", "sys_x", {}) is None
    )
    assert (
        events.emit(
            adapters.state,
            adapters.clock,
            adapters.settings,
            "system_archived",
            "sys_x",
            {"n": "a b"},
        )
        is None
    )
