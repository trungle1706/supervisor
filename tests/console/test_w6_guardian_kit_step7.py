# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""W6 (GUARDIAN_KIT): the block on step 7 (Guardians) of the nine-step register workflow.

Off: the page is as before, with no block. On: the block loads by htmx with the system id and the
source key of the draft, no form is nested in the step form, and Back, Save and Continue still
submit the step form."""

from __future__ import annotations

import re

import pytest

from tests.governance.conftest import Console, mounted, on  # noqa: F401  (fixtures)
from tests.governance.test_c3_register_v3 import (
    draft_of,
    to_step3,
    v3,  # noqa: F401  (fixture)
)
from tests.governance.test_n3_register import ME

HX = {"HX-Request": "true"}


def step7(c: Console, did: str, lang: str = "en") -> str:
    r = c.get(f"/console/register/{did}/step/7?lang={lang}", user=ME)
    assert r.status_code == 200, r.text[:400]
    return str(r.text)


def test_off_the_step_has_no_block(v3: Console) -> None:
    assert v3.ctx.settings.guardian_kit is False
    html = step7(v3, to_step3(v3))
    assert 'data-register="step5"' in html
    assert "guardian-kit" not in html and "gkit" not in html


def test_on_the_block_is_loaded_with_the_system_and_the_source_key(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "guardian_kit", True)
    did = to_step3(v3)
    d = draft_of(v3, did)
    sid = d["data"]["sys"]
    html = step7(v3, did)
    m = re.search(r'<section id="gkit"[^>]*hx-get="([^"]+)"', html)
    assert m, "the block shell is on the page"
    assert m.group(1).startswith(f"/console/guardian-kit/{sid}?src={did}")
    assert 'hx-trigger="load"' in html
    # the step form holds the guardian table and nothing with a form of its own
    form = re.search(r'<form id="rg-guardians-form".*?</form>', html, re.S)
    assert form and "<form" not in form.group(0)[5:] and "guardian-kit" not in form.group(0)
    # Back / Save / Continue sit after the block and submit the step form
    tail = html.split('id="gkit"', 1)[1]
    assert tail.count('form="rg-guardians-form"') == 2
    assert re.search(r'<button class="[^"]*" type="submit" form="rg-guardians-form"', tail)
    # the slot of the red-team panel comes after the kit and before the buttons (or is absent)
    assert html.index('id="gkit"') < html.index('form="rg-guardians-form"')


def test_the_block_loads_for_the_draft_system_and_a_viewer_gets_it_read_only(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "guardian_kit", True)
    did = to_step3(v3)
    monkeypatch.setattr(v3.ctx.settings, "onboard_intake", True)
    sid = draft_of(v3, did)["data"]["sys"]
    r = v3.get(f"/console/guardian-kit/{sid}?src={did}&lang=en", user=ME, headers=HX)
    assert r.status_code == 200 and 'data-gk-pill="not_checked"' in r.text
    assert 'data-gk="no-source"' in r.text  # no source stored yet: no check button
    # a source key that is not the draft of this system is refused, and nothing is stored
    other = v3.get(f"/console/guardian-kit/{sid}?src=inv_other&lang=en", user=ME, headers=HX)
    assert other.status_code == 400 and "does not belong" in other.text
    bad = v3.post(f"/console/guardian-kit/{sid}/check", {"src": "inv_other"}, user=ME)
    assert bad.status_code == 400 and v3.ctx.state.query("guardian_ready_check") == []
    v = v3.get(f"/console/guardian-kit/{sid}?src={did}", user="viewer.hoa", headers=HX)
    assert v.status_code == 200 and 'data-action="check"' not in v.text


def test_the_step_still_saves_with_the_block_on(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v3.ctx.settings, "guardian_kit", True)
    did = to_step3(v3)
    r = v3.post(f"/console/register/{did}/step/7", {"bind_form": "1"}, user=ME)
    assert r.status_code == 200 and "/step/8" in r.headers["hx-redirect"]
