"""WP-G1: the store, the transition table, the group check, the chain record."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.cases.service import PermissionDenied
from supervisor.config import load_settings
from supervisor.core.errors import NotFoundError
from supervisor.guardian_factory import caps
from supervisor.guardian_factory.definition import GuardianFactoryError
from supervisor.guardian_factory.store import GuardianDefStore, check_transition

from .conftest import ListSink, person, regex_def

AN = person("reviewer.an", "reviewer")
ADMIN = person("admin.chi", "admin", "reviewer")
VIEWER = person("viewer.hoa", "viewer")
APPROVER = person("approver.em", "approver")  # in legal and model_risk, not in data


def test_create_get_list(store: GuardianDefStore) -> None:
    out = store.create(regex_def(), AN)
    assert out["state"] == "draft" and out["version"] == 1 and out["created_by"] == "reviewer.an"
    got = store.get("account-numbers")
    assert got["definition"]["config"]["mask_token"] == "<ACCOUNT>"
    assert got["versions"] == [1]
    rows = store.list_defs(
        {"state": "draft", "owner_group": "data", "stage": "input", "type": "regex"}
    )
    assert [r["id"] for r in rows] == ["account-numbers"] and "definition" not in rows[0]
    assert store.list_defs({"state": "live"}) == []
    assert store.counts()["draft"] == 1
    with pytest.raises(GuardianFactoryError):
        store.list_defs({"colour": "red"})


def test_caller_cannot_set_state_version_or_approvals(store: GuardianDefStore) -> None:
    data = regex_def(
        lifecycle={
            "state": "live",
            "version": 7,
            "approvals": [{"by": "x", "group": "data", "at": "2026-10-28T09:00:00Z"}],
        }
    )
    out = store.create(data, AN)
    d = out["definition"]["lifecycle"]
    assert (out["state"], out["version"], d["state"], d["version"], d["approvals"]) == (
        "draft",
        1,
        "draft",
        1,
        [],
    )


def test_duplicate_and_not_found(store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    with pytest.raises(GuardianFactoryError) as e:
        store.create(regex_def(), AN)
    assert e.value.code == "duplicate_id"
    with pytest.raises(NotFoundError):
        store.get("missing")


def test_save_validates_and_replaces_the_draft(store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    out = store.save("account-numbers", regex_def(name="Renamed", sensitivity=3), AN)
    assert out["name"] == "Renamed" and out["definition"]["sensitivity"] == 3
    assert out["row_version"] >= 2
    with pytest.raises(GuardianFactoryError) as e:
        store.save("account-numbers", regex_def(config={"pattern": "(a+)+b"}), AN)
    assert e.value.problems[0]["field"] == "config.pattern"
    assert store.get("account-numbers")["name"] == "Renamed"  # the bad save changed nothing
    with pytest.raises(GuardianFactoryError):
        store.save("account-numbers", regex_def(id="other"), AN)


def test_transition_table_only_the_g1_and_g2_moves_are_open() -> None:
    check_transition("draft", "retired")
    check_transition("retired", "draft")
    check_transition("draft", "benchmarked")  # WP-G2
    check_transition("benchmarked", "draft")  # WP-G2
    for a, b in [
        ("benchmarked", "shadow"),
        ("shadow", "approved"),
        ("approved", "live"),
        ("live", "retired"),
    ]:
        with pytest.raises(GuardianFactoryError) as e:
            check_transition(a, b)
        assert e.value.code == "transition_not_yet_allowed", (a, b)
    with pytest.raises(GuardianFactoryError) as e:
        check_transition("draft", "live")
    assert e.value.code == "bad_transition"
    # the table is complete: every state has an entry and every target is a state
    assert set(caps.TRANSITIONS) == set(caps.STATES)
    assert all(t in caps.STATES for ts in caps.TRANSITIONS.values() for t in ts)
    assert caps.ALLOWED_NOW <= {(a, b) for a, ts in caps.TRANSITIONS.items() for b in ts}


def test_retire_reopen_new_version(store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    out = store.retire("account-numbers", AN)
    assert out["state"] == "retired"
    with pytest.raises(GuardianFactoryError) as e:  # a retired version is not edited in place
        store.save("account-numbers", regex_def(), AN)
    assert e.value.code == "not_draft"
    with pytest.raises(GuardianFactoryError) as e:
        store.retire("account-numbers", AN)
    assert e.value.code == "bad_transition"
    v2 = store.new_version("account-numbers", AN)
    assert (v2["version"], v2["state"]) == (2, "draft")
    assert store.get("account-numbers")["versions"] == [1, 2]
    assert store.get("account-numbers", 1)["state"] == "retired"
    with pytest.raises(GuardianFactoryError) as e:
        store.new_version("account-numbers", AN)
    assert e.value.code == "draft_exists"
    assert [r["id"] for r in store.list_defs()] == ["account-numbers"]  # one row, newest version
    assert store.list_defs()[0]["version"] == 2


def test_reopen_a_retired_guardian(store: GuardianDefStore) -> None:
    store.create(regex_def(), AN)
    store.retire("account-numbers", AN)
    assert store.reopen("account-numbers", AN)["state"] == "draft"


def test_events_and_chain_hold_hashes_and_ids_only(
    store: GuardianDefStore, sink: ListSink, gadapters: Any
) -> None:
    store.create(regex_def(), AN)
    store.save("account-numbers", regex_def(name="Renamed"), AN)
    store.retire("account-numbers", AN)
    actions = [r["action"] for r in gadapters.tables.query("guardian_def_event", {})]
    assert sorted(actions) == ["created", "retired", "saved"]
    recs = sink.of("guardian_def")
    assert [r["action"] for r in recs] == ["created", "saved", "retired"]
    blob = json.dumps(recs)
    assert "ACCOUNT" not in blob and "\\\\d" not in blob and "Renamed" not in blob
    assert all(len(r["def_sha256"]) == 64 for r in recs)
    assert all(not isinstance(v, float) for r in recs for v in r.values())
    assert "reviewer.an" not in blob  # the actor is a keyed reference, not the id
    assert recs[2]["from_state"] == "draft" and recs[2]["to_state"] == "retired"


def test_rbac_group_and_roles(store: GuardianDefStore) -> None:
    with pytest.raises(PermissionDenied):
        store.create(regex_def(), VIEWER)
    with pytest.raises(PermissionDenied):  # the approver is not in the data group
        store.create(regex_def(), APPROVER)
    store.create(regex_def(), AN)
    with pytest.raises(PermissionDenied):
        store.save("account-numbers", regex_def(), APPROVER)
    with pytest.raises(PermissionDenied):
        store.retire("account-numbers", APPROVER)
    store.create(regex_def(id="legal-one", owner_group="legal"), APPROVER)  # own group
    assert store.save("account-numbers", regex_def(name="By admin"), ADMIN)["name"] == "By admin"
    with pytest.raises(PermissionDenied):  # cannot move a guardian into a group you are not in
        store.save("legal-one", regex_def(id="legal-one", owner_group="data"), APPROVER)


def test_service_principal_is_refused(store: GuardianDefStore) -> None:
    from supervisor.adapters.auth.base import AuthPrincipal

    sp = AuthPrincipal("svc", "service_principal", "x", frozenset({"admin"}), "svc")
    with pytest.raises(GuardianFactoryError) as e:
        store.create(regex_def(), sp)
    assert e.value.code == "person_required"


def test_off_path_reads_no_table(
    gadapters: Any, sink: ListSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    for kw in (
        {"guardian_factory": False, "detectors_enabled": True},
        {"guardian_factory": True, "detectors_enabled": False},
    ):
        s = load_settings(
            sql_backend="sqlite", data_dir=gadapters.settings.data_dir, llm_base_url="", **kw
        )
        st = GuardianDefStore(gadapters.state, gadapters.tables, gadapters.clock, s, evidence=sink)

        def boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("a table was read")

        monkeypatch.setattr(gadapters.state, "query", boom)
        monkeypatch.setattr(gadapters.state, "get", boom)
        for call in (
            lambda st=st: st.list_defs(),
            lambda st=st: st.get("x"),
            lambda st=st: st.create(regex_def(), AN),
            lambda st=st: st.save("x", {}, AN),
            lambda st=st: st.retire("x", AN),
        ):
            with pytest.raises(GuardianFactoryError) as e:
                call()
            assert e.value.code == "guardian_factory_off"
        monkeypatch.undo()
    assert sink.records == []
