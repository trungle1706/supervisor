# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""Code clean-up batch B (audit D4, owner decision 2026-10-31): the owner test and the
"another person" test compare user ids without letter case in every governance path, the
classification paths included. Owner ``TrungLQ2@bank.vn`` and actor ``trunglq2@bank.vn`` are one
person."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.core.people import is_system_owner, same_person
from supervisor.governance.classification import OwnerCannotApply
from supervisor.governance.classification_v2 import V2Error
from supervisor.governance.model import SegregationOfDuties, SystemsError
from supervisor.mcp_server.apps import McpAppError

from .conftest import Console, draft, mounted, on  # noqa: F401  (fixtures)
from .test_c1_classification import APPROVER, DECIDER, decide, medium_body, req
from .test_p2_separation import _drafted, gon, pon  # noqa: F401

OWNER = "TrungLQ2@bank.vn"
ACTOR = "trunglq2@bank.vn"
_N = [0]


def _person(user_id: str, perm: str) -> Any:
    return SimpleNamespace(user_id=user_id, roles=tuple(rbac.roles_for(perm)), kind="user")


def _system(c: Console, owner: str = OWNER) -> str:
    _N[0] += 1
    row = c.ctx.systems.register(draft(name=f"Case test system {_N[0]}", owner_user=owner), owner)
    return str(row["system_id"])


def test_helper_is_case_insensitive_for_both_callers() -> None:
    assert same_person(OWNER, ACTOR) and same_person(ACTOR, OWNER)
    assert is_system_owner({"owner_user": OWNER}, [], ACTOR)
    team = [{"user_id": OWNER, "team_role": "system_owner", "active": True}]
    assert is_system_owner({"owner_user": "x"}, team, ACTOR)
    assert not is_system_owner({"owner_user": "x"}, team, "someone.else")


def test_v2_owner_cannot_approve_when_only_the_letter_case_differs(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "classification_v2", True)
    sid = _system(on)
    assert decide(on, sid, medium_body(), APPROVER).status_code in (200, 201)
    svc = on.ctx.classification_v2
    assert svc._is_owner(sid, ACTOR) and svc._is_owner(sid, OWNER.upper())
    with pytest.raises(V2Error) as exc:
        svc.approve(sid, _person(ACTOR, "systems.approve"))
    assert exc.value.code == "owner_cannot_approve"
    # a team owner is found in any letter case too
    sid2 = _system(on, owner="someone.else")
    on.ctx.systems.add_member(sid2, OWNER, "system_owner", "someone.else")
    assert on.ctx.classification_v2._is_owner(sid2, ACTOR)


def test_v2_decider_cannot_approve_in_another_letter_case(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "classification_v2", True)
    sid = _system(on, owner="someone.else")
    on.ctx.systems.add_member(sid, "someone.else", "system_owner", "someone.else")
    assert decide(on, sid, medium_body(), DECIDER).status_code in (200, 201)
    with pytest.raises(V2Error) as exc:
        on.ctx.classification_v2.approve(sid, _person(DECIDER.upper(), "systems.approve"))
    assert exc.value.code == "same_person"


def test_v1_apply_owner_and_team_roles_in_another_letter_case(pon: Console) -> None:
    sid = _drafted(pon, owner=DECIDER)
    svc = pon.ctx.classification
    assert svc._is_owner(sid, DECIDER.upper())
    # the owner in another letter case cannot apply
    with pytest.raises(OwnerCannotApply):
        svc.apply(sid, _person(DECIDER.upper(), "systems.edit"))
    # a reviewer of the system in another letter case hits segregation of duties
    pon.ctx.systems.add_member(sid, "Reviewer.Binh", "reviewer", DECIDER)
    with pytest.raises(SegregationOfDuties):
        svc.apply(sid, _person("REVIEWER.BINH", "systems.edit"))


def test_systems_owner_checks_ignore_letter_case(on: Console) -> None:
    systems = on.ctx.systems
    sid = _system(on)
    row = on.ctx.state.get("ai_system", {"system_id": sid})
    on.ctx.state.update("ai_system", {"system_id": sid}, {"risk_level": "high"}, row["row_version"])
    # lowering the risk level: the owner (another letter case) is refused
    with pytest.raises(SegregationOfDuties):
        systems.lower_risk_level(sid, "low", "owner tries to lower the level", ACTOR)
    # the owner cannot also be the reviewer of the own system
    with pytest.raises(SegregationOfDuties):
        systems.add_member(sid, ACTOR, "reviewer", OWNER)
    # a reviewer cannot become the owner in another letter case
    sid2 = _system(on, owner="some.owner")
    systems.add_member(sid2, "Reviewer.Binh", "reviewer", "some.owner")
    with pytest.raises(SegregationOfDuties):
        systems.add_member(sid2, "REVIEWER.BINH", "system_owner", "some.owner")
    # the owner is not removable and keeps the role in any letter case
    with pytest.raises(SystemsError):
        systems.remove_member(sid, ACTOR, OWNER)


def test_register_in_scope_compares_the_owner_without_case() -> None:
    from supervisor.core.people import same_person as sp

    assert sp(OWNER, ACTOR)


def test_connected_app_cannot_be_approved_by_its_issuer_in_another_letter_case() -> None:
    from supervisor.mcp_server.apps import McpAppService

    row = {"created_by": OWNER, "status": "pending", "app_id": "app1"}
    svc = McpAppService.__new__(McpAppService)
    svc.get_row = lambda app_id: row  # type: ignore[method-assign]
    with pytest.raises(McpAppError):
        svc.approve("app1", ACTOR)


_ = (mounted, req)
