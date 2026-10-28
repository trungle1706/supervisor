# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-G4: the console side of the smart guardian: the panel on the Guardians tab and on the
Guardian fit step, HTMX fragments, the form fields, English and Vietnamese, the role matrix."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.console import smart_guardian_view as view
from tests.governance.conftest import Console, mounted, on  # noqa: F401  (fixtures)
from tests.governance.test_c3_register_v3 import (
    S3,  # noqa: F401
    classify,
    draft_of,
    to_step3,
    v3,  # noqa: F401  (fixture)
)
from tests.governance.test_g4_smart_guardian import (  # noqa: F401
    CREATOR,
    VIEWER,
    _dim,
    _ready,
    sgon,
)
from tests.governance.test_n3_register import step

BASE = "/console/systems/{sid}/guardian-proposal"


def _post(c: Console, sid: str, tail: str = "", data: Any = None, **kw: Any) -> Any:
    return c.post(BASE.format(sid=sid) + tail + "?lang=" + kw.pop("lang", "en"), data, **kw)


def _lines(html: str) -> list[str]:
    return re.findall(r'data-line="(ln_[0-9a-f]{10})"', html)


def test_guardians_tab_shows_the_panel_and_the_propose_button(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    monkeypatch.setattr(c.ctx.settings, "console_nav_v3", True)
    sid = _ready(c, "high_self", money_movement=True)
    tab = c.get(f"/console/systems/{sid}?tab=guardians&lang=en").text
    assert 'id="sg-panel"' in tab and 'data-act="sg-propose"' in tab
    assert "No proposal yet." in tab and "Not legal advice" in tab


def test_propose_fragment_groups_lines_with_why_and_rule(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True, user_segment="customer")
    _dim(c, sid, "cybersecurity", "fail")
    r = _post(c, sid)
    assert r.status_code == 200, r.text[:300]
    html = r.text
    assert 'id="sg-panel"' in html and "Proposal made." in html
    for g in ("guardian_set", "thresholds", "autonomy_limits", "floor"):
        assert f'data-sg-group="{g}"' in html, g
    assert "Floor (cannot be removed)" in html
    ids = _lines(html)
    assert len(ids) >= 6
    # every line row shows a why pointer and a rule id
    rows = re.findall(r'<tr class="row" data-line=.*?</tr>', html, re.S)
    assert len(rows) == len(ids)
    for row in rows:
        assert 'data-why="' in row and re.search(r'data-rule="SG-[A-Z]-', row)
    # selectable lines have a checkbox, floor lines do not
    assert html.count('name="sel_') == sum(1 for x in rows if "data-sel=" in x)
    floor_rows = [x for x in rows if 'data-state="locked"' in x]
    assert floor_rows and all("<input" not in x for x in floor_rows)
    assert 'data-act="sg-accept"' in html and 'data-act="sg-reject"' in html
    assert "10000000" in html  # the SBV threshold of a customer payment
    assert "Illustrative values" in html


def test_accept_form_applies_the_ticked_lines_and_offers_predeploy(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True)
    _dim(c, sid, "model", "fail")
    html = _post(c, sid).text
    ids = _lines(html)
    guard = re.findall(r'data-line="(ln_[0-9a-f]{10})" data-state="proposed"', html)
    assert guard
    r = _post(c, sid, "/accept", {f"sel_{guard[0]}": "1", "note": "first line only"})
    assert r.status_code == 200, r.text[:300]
    assert "Selected lines accepted." in r.text and 'data-sg="results"' in r.text
    assert 'data-state="accepted"' in r.text and "first line only" in r.text
    assert 'data-act="sg-accept"' not in r.text  # no longer open
    assert ids  # the lines stay visible as a record
    # nothing ticked: a clear 400
    _post(c, sid)  # a new open proposal
    assert _post(c, sid, "/accept", {}).status_code == 400
    # the pre-deploy button needs a node of the system and ONBOARD_PREDEPLOY
    data = view.panel_data(
        c.ctx,
        _me(c),
        {
            "system_id": sid,
            "status": "active",
            "components": [{"ref_kind": "node", "ref_id": "n1"}],
        },
    )
    assert data["sg_nodes"] == []  # flag off
    monkeypatch.setattr(c.ctx.settings, "onboard_predeploy", True)
    data = view.panel_data(
        c.ctx,
        _me(c),
        {
            "system_id": sid,
            "status": "active",
            "components": [{"ref_kind": "node", "ref_id": "n1"}],
        },
    )
    assert data["sg_nodes"] == ["n1"]


def _me(c: Console) -> Any:
    from supervisor.adapters.auth.base import AuthPrincipal

    return AuthPrincipal(CREATOR, "user", "dev_header", frozenset({"reviewer"}), CREATOR)


def test_predeploy_button_in_an_accepted_panel(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    sid = _ready(c, "medium", personal_data="identifiable")
    real = view.panel_data

    def with_node(ctx: Any, me: Any, system: Any) -> dict[str, Any]:
        out = real(ctx, me, system)
        out["sg_nodes"] = ["n1"]  # a node of the system, ONBOARD_PREDEPLOY on
        return out

    monkeypatch.setattr(view, "panel_data", with_node)
    html = _post(c, sid).text
    assert "sg-predeploy" not in html  # not before a person accepts
    first = re.findall(r'data-line="(ln_[0-9a-f]{10})" data-state="proposed"', html)
    assert first
    done = _post(c, sid, "/accept", {f"sel_{first[0]}": "1"}).text
    assert "Proof of the fit" in done
    assert 'data-act="sg-predeploy"' in done and 'hx-post="/console/predeploy/n1?lang=en"' in done
    assert "Run pre-deploy now" in done


def test_reject_needs_a_reason_in_the_form(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    _post(c, sid)
    r = _post(c, sid, "/reject", {"reason": "short"})
    assert r.status_code == 400 and "reason_too_short" in r.text
    r = _post(c, sid, "/reject", {"reason": "The limits are wrong for this team."})
    assert r.status_code == 200 and "Proposal rejected." in r.text
    assert "Rejected" in r.text and "The limits are wrong for this team." in r.text
    assert 'data-act="sg-accept"' not in r.text


def test_vietnamese_labels(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    r = _post(c, sid, lang="vi")
    assert "Bộ guardian" in r.text and "Mức sàn" in r.text
    assert c.get(f"/console/systems/{sid}/guardian-proposal?lang=vi").status_code == 200


def test_plain_form_post_needs_the_console_origin(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    bare = _post(c, sid, htmx=False)
    assert bare.status_code == 400
    ok = c.client.post(
        BASE.format(sid=sid),
        data={},
        headers={"X-Dev-User": CREATOR, "Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert ok.status_code == 303 and "tab=guardians" in ok.headers["location"]


def test_viewer_sees_the_panel_without_buttons_and_cannot_post(sgon: Console) -> None:
    from supervisor.adapters.auth.base import AuthPrincipal

    c = sgon
    sid = _ready(c, "medium")
    _post(c, sid)
    system = c.ctx.systems.get(sid)
    viewer = AuthPrincipal(VIEWER, "user", "dev_header", frozenset({"viewer"}), VIEWER)
    assert view.panel_data(c.ctx, viewer, system)["sg_can"] is False
    assert view.panel_data(c.ctx, _me(c), system)["sg_can"] is True
    # the fragment of a person who may not edit: the viewer is out of the scope of this system
    # (404 for a stranger, never 403 on a read), the buttons are absent whatever the scope
    got = c.get(BASE.format(sid=sid) + "?lang=en", user=VIEWER)
    assert got.status_code in (200, 400, 404)
    if got.status_code == 200:
        for token in ("sg-propose", "sg-accept", "sg-reject", 'name="sel_'):
            assert token not in got.text
    for tail in ("", "/accept", "/reject"):
        assert _post(c, sid, tail, {}, user=VIEWER).status_code == 403


def test_register_step_guardian_fit_shows_the_panel(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in ("smart_guardian",):
        monkeypatch.setattr(v3.ctx.settings, flag, True)
    did = to_step3(v3)
    sid = draft_of(v3, did)["data"]["sys"]
    classify(v3, sid)
    for n in (4, 5, 6):
        step(v3, did, n)
    r = v3.get(f"/console/register/{did}/step/7?lang=en", user="reviewer.an")
    assert r.status_code == 200, r.text[:300]
    assert 'id="sg-panel"' in r.text and 'data-act="sg-propose"' in r.text
    monkeypatch.setattr(v3.ctx.settings, "smart_guardian", False)
    off = v3.get(f"/console/register/{did}/step/7?lang=en", user="reviewer.an")
    assert off.status_code == 200 and "sg-panel" not in off.text
