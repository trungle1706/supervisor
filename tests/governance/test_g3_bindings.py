"""WP-G3: a live guardian of the guardian factory is bindable by id and version (slug
gf:<id>@<version>) through the existing guardian bindings; the floor and the off path hold."""

# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
from __future__ import annotations

import json

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core.detectors import DetectorRegistry
from supervisor.detectors.config import ResolvedDetectors, parse_config
from supervisor.gateway.detector_gate import DetectorGate
from supervisor.governance.guardians import GuardianNarrower, GuardianService, instance_on
from supervisor.governance.model import SystemsError
from supervisor.governance.systems import SystemService
from supervisor.guardian_factory import attach
from supervisor.guardian_factory.definition import validate_definition

from .s1_support import OWNER, guard, make_system, narrow, sadapters, ssvc  # noqa: F401  (fixtures)

SLUG = "gf:account-numbers@1"


def put_def(a: Adapters, state: str = "live", version: int = 1) -> None:
    d = validate_definition(
        {
            "id": "account-numbers",
            "name": "Account numbers",
            "owner_group": "model_risk",
            "type": "regex",
            "stage": "input",
            "action_on_fail": "block",
            "sensitivity": 2,
            "config": {"pattern": r"\d{9,14}"},
            "created_by": "reviewer.an",
            "lifecycle": {"state": state, "version": version},
        }
    )
    a.state.insert(
        "guardian_def",
        {
            "def_id": d.id,
            "version": version,
            "owner_group": d.owner_group,
            "type": d.type,
            "stage": d.stage,
            "definition_json": json.dumps(d.model_dump(mode="json")),
            "state": state,
            "created_by": "reviewer.an",
        },
    )


def test_flag_off_a_gf_slug_is_unknown(
    sadapters: Adapters, guard: GuardianService, ssvc: SystemService
) -> None:
    put_def(sadapters)
    sid = make_system(ssvc)
    with pytest.raises(SystemsError, match="unknown feature slug"):
        guard.set(sid, SLUG, "off", OWNER, "no")
    assert SLUG not in [g["slug"] for g in guard.get(sid)["guardians"]]


def test_live_guardian_is_listed_and_switched_off_by_binding(
    sadapters: Adapters,
    guard: GuardianService,
    ssvc: SystemService,
    narrow: GuardianNarrower,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sadapters.settings, "guardian_factory", True)
    put_def(sadapters)
    sid = make_system(ssvc, ("payments",))
    row = next(g for g in guard.get(sid)["guardians"] if g["slug"] == SLUG)
    assert row["instance_on"] is True and row["effective"] is True and row["group"] == "detect"
    out = guard.set(sid, SLUG, "off", OWNER, "the batch job sends account numbers")
    assert out["state"] == "off" and out["effective"] is False
    assert SLUG in narrow.off("payments")
    # the gate adds it to the disable list of the agent
    reg = DetectorRegistry()
    live = attach.LiveGuardians(sadapters.state, sadapters.settings, reg, ttl_s=0)
    assert live.slugs_for("payments") == [SLUG]
    gate = DetectorGate(reg, ResolvedDetectors(parse_config("version: 1\n", "t"), reg))
    gate.narrow = narrow
    assert gate._narrowed(None, "payments").disable == [SLUG]  # noqa: SLF001
    # back on
    guard.set(sid, SLUG, "on", OWNER)
    assert SLUG not in narrow.off("payments")


def test_only_a_live_version_is_bindable(
    sadapters: Adapters,
    guard: GuardianService,
    ssvc: SystemService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sadapters.settings, "guardian_factory", True)
    put_def(sadapters, "shadow")
    sid = make_system(ssvc)
    with pytest.raises(SystemsError, match="unknown feature slug"):
        guard.set(sid, SLUG, "off", OWNER, "no")
    with pytest.raises(SystemsError, match="unknown feature slug"):
        guard.set(sid, "gf:account-numbers@2", "off", OWNER, "no")
    assert instance_on(sadapters.settings, SLUG) is True
