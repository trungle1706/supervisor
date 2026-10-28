# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-C3: the console side of the nine-step register workflow: the audit rows of its writes, the
role matrix of its routes and panels, HTMX fragments, the flag-off answers."""

from __future__ import annotations

from typing import Any

import pytest

from tests.governance.conftest import Console, mounted, on  # noqa: F401  (fixtures)
from tests.governance.test_c3_register_v3 import (
    S3,
    classify,
    draft_of,
    to_step3,
    v3,  # noqa: F401  (fixture)
)
from tests.governance.test_n3_register import ME, new, step, submit

VIEWER = "viewer.hoa"
HX = {"HX-Request": "true"}


def audit(c: Console) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.tables.query("console_action", order_by=("ts",))]


def test_off_routes_answer_400_and_write_nothing(on: Console) -> None:
    assert on.ctx.settings.register_v3 is False
    for url in ("/console/register", "/console/register/rd_x/step/9"):
        assert on.get(url).status_code == 400, url
    assert on.ctx.state.query("registration_draft") == []


def test_submit_and_abandon_write_audit_rows(v3: Console) -> None:
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    for n in (4, 5, 6):
        step(v3, did, n)
    step(v3, did, 7, {"bind_form": "1"})
    before = len(audit(v3))
    assert submit(v3, did).status_code == 200
    got = audit(v3)[before:]
    assert got, "the submit writes console_action rows"
    assert all(r["permission"] == "systems.edit" for r in got)
    assert any("register submit" in str(r.get("detail", "")) for r in got)
    other = new(v3)
    n0 = len(audit(v3))
    assert v3.post(f"/console/register/{other}/abandon", {}, user=ME).status_code == 200
    assert len(audit(v3)) > n0


def test_viewer_is_denied_every_write_and_the_panels_are_read_only(v3: Console) -> None:
    did = to_step3(v3)
    assert v3.post(f"/console/register/{did}/step/3", dict(S3), user=VIEWER).status_code == 403
    assert v3.post(f"/console/register/{did}/abandon", {}, user=VIEWER).status_code == 403
    assert v3.get("/console/register/new", user=VIEWER).status_code == 403
    # the panels the steps embed answer a viewer as view-only fragments
    for url in (f"/console/intake/{did}", f"/console/facts/{did}", f"/console/predeploy/{did}"):
        r = v3.get(url, user=VIEWER, headers=HX)
        assert r.status_code in (200, 400), url  # 400 while the flag of that panel is off
    # but a viewer cannot press their buttons
    for url in (f"/console/intake/{did}", f"/console/facts/{did}", f"/console/predeploy/{did}"):
        assert v3.post(url, {}, user=VIEWER).status_code == 403, url


@pytest.mark.parametrize("user,code", [(ME, 200), ("reviewer.binh", 200), (VIEWER, 403)])
def test_step_page_role_matrix(v3: Console, user: str, code: int) -> None:
    did = new(v3)
    r = v3.get(f"/console/register/{did}/step/1", user=user)
    if user == ME:
        assert r.status_code == code
    elif user == VIEWER:
        assert r.status_code == code
    else:  # another person with the edit permission does not see my draft
        assert r.status_code == 400


def test_a_panel_without_its_flag_is_400_with_the_flag_name(v3: Console) -> None:
    did = new(v3)
    r = v3.get(f"/console/intake/{did}", user=ME, headers=HX)
    assert r.status_code == 400 and "ONBOARD_INTAKE" in r.text.upper()
    r = v3.post(f"/console/facts/{did}", {}, user=ME)
    assert r.status_code == 400 and "ONBOARD_FACTS" in r.text.upper()
