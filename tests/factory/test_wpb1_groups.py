"""WP-B1 item 5: every synthetic user of config/users.yaml has an explicit ``groups:`` list; the
role mapping stays the fallback for a user without one."""

from __future__ import annotations

import pytest
import yaml

from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
from supervisor.factory import registry
from supervisor.factory.store import permits
from tests.conftest import REPO_ROOT

USERS = yaml.safe_load((REPO_ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))["users"]
GROUPS = registry.load_groups()
GROUP_IDS = {g.group_id for g in GROUPS.groups}


def test_every_user_has_an_explicit_groups_list_of_known_groups() -> None:
    for uid, spec in USERS.items():
        assert isinstance(spec.get("groups"), list), f"{uid} has no groups: list"
        assert set(spec["groups"]) <= GROUP_IDS, uid


@pytest.mark.parametrize("uid", sorted(USERS))
def test_explicit_groups_give_the_reach_the_role_mapping_gave(uid: str) -> None:
    spec = USERS[uid]
    for gid in sorted(GROUP_IDS):
        via_groups = permits(spec["roles"], gid, GROUPS, spec["groups"])
        via_roles = permits(spec["roles"], gid, GROUPS, None)
        if uid.startswith(("lead.", "second.")):
            assert via_groups == (gid in spec["groups"])  # a lead owns one group only
        else:
            assert via_groups == via_roles, (uid, gid)


def test_a_user_without_groups_falls_back_to_the_role_mapping() -> None:
    assert permits(["reviewer"], "cyber", GROUPS, None) is True
    assert permits(["reviewer"], "cyber", GROUPS, []) is True
    assert permits(["viewer"], "cyber", GROUPS, None) is False
    assert permits(["reviewer"], "cyber", GROUPS, ["legal"]) is False  # explicit list is exact


def test_the_loader_reads_the_groups() -> None:
    users = DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users
    assert users["reviewer.an"].groups == frozenset(USERS["reviewer.an"]["groups"])
    assert users["viewer.hoa"].groups == frozenset()
