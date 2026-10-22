"""WP-S1 service: bindings, the floor, the chain record, and what the narrower resolves."""

# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
from __future__ import annotations

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core.errors import NotFoundError
from supervisor.governance.guardians import (
    GuardianNarrower,
    GuardianService,
    bindable_slugs,
    make_narrower,
)
from supervisor.governance.model import SystemsError
from supervisor.governance.systems import SystemService

from .conftest import ListSink
from .s1_support import CUSTOMER, MONEY, OWNER, guard, make_system, narrow, sadapters, ssvc  # noqa: F401  (fixtures)


def test_the_catalogue_of_slugs(sadapters: Adapters) -> None:
    slugs = bindable_slugs(sadapters.settings)
    assert {"dlp_vn", "injection_regex", "session_monitor", "judge_t2_sample"} <= set(slugs)
    assert "policy_rules" not in slugs and len(slugs) == len(set(slugs))


def test_no_binding_means_everything_is_on(guard: GuardianService, ssvc: SystemService) -> None:
    sid = make_system(ssvc)
    out = guard.get(sid)
    assert out["count"] == len(out["guardians"]) and out["never_bindable"] == ["policy_rules"]
    assert {g["state"] for g in out["guardians"]} == {"on"}
    assert all(g["default"] and not g["locked"] for g in out["guardians"])
    dlp = next(g for g in out["guardians"] if g["slug"] == "dlp_vn")
    assert dlp["instance_on"] is True and dlp["effective"] is True


def test_switch_off_and_on_writes_one_chain_record_each(
    guard: GuardianService,
    ssvc: SystemService,
    sink: ListSink,
) -> None:
    sid = make_system(ssvc)
    r = guard.set(sid, "injection_regex", "off", OWNER, "too noisy for this assistant")
    assert r["state"] == "off" and r["effective"] is False and r["set_by"] == OWNER
    assert r["reason"] == "too noisy for this assistant"
    again = guard.set(sid, "injection_regex", "off", OWNER)  # a repeat changes nothing
    assert again["state"] == "off" and len(sink.of("binding_change")) == 1
    guard.set(sid, "injection_regex", "on", OWNER)
    first, second = sink.of("binding_change")
    assert (first["from_state"], first["to_state"]) == ("default", "off")
    assert (second["from_state"], second["to_state"]) == ("off", "on")
    assert first["system_id"] == sid and first["feature_slug"] == "injection_regex"
    # ids, enums and hashes only: the reason text is not in the record
    assert "too noisy" not in repr(first) and len(first["reason_sha256"]) == 64
    assert OWNER not in repr(first) and "reason" not in first
    assert [ref for t, ref, _ in sink.records if t == "binding_change"] == [f"system:{sid}"] * 2


def test_a_floor_slug_cannot_be_switched_off(
    guard: GuardianService,
    ssvc: SystemService,
    sink: ListSink,
) -> None:
    sid = make_system(ssvc, **MONEY)
    out = guard.get(sid)
    locked = {g["slug"] for g in out["guardians"] if g["locked"]}
    assert locked == {"dlp_vn", "injection_regex"}
    with pytest.raises(SystemsError, match="guardian floor.*AR-PDPL-CUSTOMER.*cannot be switched"):
        guard.set(sid, "dlp_vn", "off", OWNER)
    assert sink.of("binding_change") == []
    ok = guard.set(sid, "dlp_vn", "on", OWNER)  # on is allowed; mandatory is recorded
    assert ok["locked"] and ok["effective"] and sink.of("binding_change")[0]["mandatory"] is True
    guard.set(sid, "session_monitor", "off", OWNER)  # a non-floor slug of the same system


def test_gate_rules_unknown_slugs_and_bad_input_are_400s(
    guard: GuardianService,
    ssvc: SystemService,
) -> None:
    sid = make_system(ssvc)
    with pytest.raises(SystemsError, match="never bindable"):
        guard.set(sid, "policy_rules", "off", OWNER)
    with pytest.raises(SystemsError, match="never bindable"):
        guard.set(sid, "policy_rules", "on", OWNER)
    with pytest.raises(SystemsError, match="unknown feature slug"):
        guard.set(sid, "not_a_guardian", "off", OWNER)
    with pytest.raises(SystemsError, match="state must be one of on, off"):
        guard.set(sid, "dlp_vn", "maybe", OWNER)
    with pytest.raises(SystemsError, match="reason"):
        guard.set(sid, "dlp_vn", "off", OWNER, "x" * 501)
    with pytest.raises(SystemsError, match="actor"):
        guard.set(sid, "dlp_vn", "off", "bad actor!")
    with pytest.raises(NotFoundError):
        guard.set("sys_nope", "dlp_vn", "off", OWNER)
    ssvc.archive(sid, OWNER)
    with pytest.raises(SystemsError, match="archived"):
        guard.set(sid, "dlp_vn", "off", OWNER)


def test_the_service_refuses_with_either_flag_off(sadapters: Adapters, ssvc: SystemService) -> None:
    sid = make_system(ssvc)
    svc = GuardianService.from_adapters(sadapters)
    sadapters.settings.guardian_bindings_enabled = False
    with pytest.raises(SystemsError, match="GUARDIAN_BINDINGS_ENABLED"):
        svc.get(sid)
    sadapters.settings.guardian_bindings_enabled = True
    sadapters.settings.governance_enabled = False
    with pytest.raises(SystemsError, match="GOVERNANCE_ENABLED"):
        svc.set(sid, "dlp_vn", "off", OWNER)


# ---------------------------------------------------------------------------- the narrower
def test_the_narrower_returns_what_the_systems_switched_off(
    guard: GuardianService,
    ssvc: SystemService,
    narrow: GuardianNarrower,
) -> None:
    sid = make_system(ssvc, ("pay-agent",))
    make_system(ssvc, ("other-agent",), name="Other")
    assert narrow.off("pay-agent") == frozenset()
    guard.set(sid, "injection_regex", "off", OWNER)
    guard.set(sid, "monitor_drift", "off", OWNER)
    assert narrow.off("pay-agent") == {"injection_regex", "monitor_drift"}
    assert narrow.off("PAY-AGENT") == {"injection_regex", "monitor_drift"}  # ids compare folded
    assert narrow.off("pay-agent/consumer-7") == narrow.off("pay-agent")  # a consumer: its agent
    assert narrow.off("other-agent") == frozenset() and narrow.off("unlinked") == frozenset()
    assert narrow.is_off("pay-agent", "monitor_drift")
    guard.set(sid, "injection_regex", "on", OWNER)
    assert narrow.off("pay-agent") == {"monitor_drift"}


def test_a_floor_added_later_wins_over_an_old_off_row(
    guard: GuardianService,
    ssvc: SystemService,
    narrow: GuardianNarrower,
) -> None:
    sid = make_system(ssvc, ("pay-agent",))
    guard.set(sid, "dlp_vn", "off", OWNER)
    assert narrow.off("pay-agent") == {"dlp_vn"}
    ssvc.update_fields(sid, dict(CUSTOMER), OWNER)  # the rules now put dlp_vn in the floor
    row = next(g for g in guard.get(sid)["guardians"] if g["slug"] == "dlp_vn")
    assert row["state"] == "off" and row["locked"] and row["effective"] is True
    assert narrow.off("pay-agent") == frozenset()  # the floor is read at resolution time


def test_an_agent_on_two_systems_loses_a_feature_only_when_both_agree(
    guard: GuardianService,
    ssvc: SystemService,
    narrow: GuardianNarrower,
) -> None:
    a = make_system(ssvc, ("shared",))
    b = make_system(ssvc, ("shared",), name="Second")
    guard.set(a, "injection_regex", "off", OWNER)
    assert narrow.off("shared") == frozenset()
    guard.set(b, "injection_regex", "off", OWNER)
    guard.set(b, "session_monitor", "off", OWNER)
    assert narrow.off("shared") == {"injection_regex"}


def test_an_archived_system_binds_nothing(
    guard: GuardianService,
    ssvc: SystemService,
    narrow: GuardianNarrower,
) -> None:
    sid = make_system(ssvc, ("pay-agent",))
    guard.set(sid, "injection_regex", "off", OWNER)
    ssvc.archive(sid, OWNER)
    assert narrow.off("pay-agent") == frozenset()


def test_a_lookup_that_fails_leaves_every_feature_on(sadapters: Adapters) -> None:
    class Broken:
        def query(self, *a: object, **k: object) -> list[object]:
            raise RuntimeError("store down")

    n = GuardianNarrower(Broken(), sadapters.settings, ttl_s=0)
    assert n.off("pay-agent") == frozenset()


def test_the_cache_follows_a_write_in_the_same_process(
    sadapters: Adapters,
    guard: GuardianService,
    ssvc: SystemService,
) -> None:
    sid = make_system(ssvc, ("pay-agent",))
    cached = GuardianNarrower(sadapters.state, sadapters.settings, ttl_s=3600)
    assert cached.off("pay-agent") == frozenset()
    guard.set(sid, "injection_regex", "off", OWNER)
    assert cached.off("pay-agent") == {"injection_regex"}


def test_make_narrower_needs_both_flags(sadapters: Adapters) -> None:
    s = sadapters.settings
    assert make_narrower(s, sadapters.state) is not None
    assert make_narrower(s, None) is None
    s.guardian_bindings_enabled = False
    assert make_narrower(s, sadapters.state) is None
    s.guardian_bindings_enabled, s.governance_enabled = True, False
    assert make_narrower(s, sadapters.state) is None
