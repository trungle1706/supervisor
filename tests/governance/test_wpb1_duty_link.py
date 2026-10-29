# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-B1 item 3: the Law changes tab under Risks & controls, and the link from the system Duties
tab to the law change that re-opened a row (the note carries the package sha, first 8 characters).
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import re

import pytest

from supervisor.governance.register_v2 import duties as dut
from tests.console.test_nav_v3 import v3, v3all  # noqa: F401
from tests.governance.conftest import Console, mounted, on  # noqa: F401
from tests.governance.test_l3_duties import _seed, _system, _tab, dty  # noqa: F401

IID = "VN-DEC142-2026"
SHA = "ab12cd34" + "0" * 56
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)


def _insert_change(c: Console, affected: list[str], status: str = "applied") -> None:
    c.ctx.state.insert(
        "regkb_change",
        {
            "change_id": "rc_" + "1" * 20,
            "package_sha": SHA,
            "instrument_id": IID,
            "status": status,
            "old_sha": "1" * 64,
            "new_sha": "2" * 64,
            "incoming_name": f"{IID}/2026-10-21/x.txt",
            "articles_changed": 1,
            "articles_added": 0,
            "articles_removed": 0,
            "changed_chars": 12,
            "articles": [5],
            "obligations_affected": affected,
            "classification_hit": False,
            "drafts_n": 0,
            "model_id": None,
            "obligations_added": 0,
            "obligations_updated": 0,
            "obligations_removed": 0,
            "created_at": NOW,
            "created_by": "approver.em",
            "applied_at": NOW if status == "applied" else None,
            "applied_by": "approver.em" if status == "applied" else None,
        },
    )


def _note(c: Console, sid: str, oid: str, note: str) -> None:
    key = {"status_id": dut.status_id(sid, oid)}
    row = c.ctx.state.get("obligation_status", key)
    c.ctx.state.update("obligation_status", key, {"note": note}, row["row_version"])


def _strip(html: str) -> str:
    return htmllib.unescape(html.split('<nav class="subtabs sec-tabs"', 1)[1].split("</nav>", 1)[0])


def test_tab_is_absent_while_the_flag_is_off(v3all: Console) -> None:
    strip = _strip(v3all.get("/console/risks?lang=en").text)
    assert "Law changes" not in strip


@pytest.mark.parametrize("missing", ["regkb_change_loop", "lawagent_enabled", "governance_enabled"])
def test_tab_needs_the_flag_and_what_it_needs(
    v3all: Console, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for flag in ("regkb_change_loop", "lawagent_enabled", "governance_enabled"):
        monkeypatch.setattr(v3all.ctx.settings, flag, flag != missing)
    assert "Law changes" not in _strip(v3all.get("/console/risks?lang=en").text)


def test_tab_shows_with_the_flag_and_marks_the_changes_page(
    v3all: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in ("regkb_change_loop", "lawagent_enabled", "governance_enabled"):
        monkeypatch.setattr(v3all.ctx.settings, flag, True)
    strip = _strip(v3all.get("/console/risks?lang=en").text)
    assert "Law changes" in strip and 'href="/console/regkb/changes?lang=en"' in strip
    page = _strip(v3all.get("/console/regkb/changes?lang=en", user="reviewer.an").text)
    assert re.findall(r'class="on" aria-current="page">([^<]+)<', page) == ["Law changes"]
    vi = _strip(v3all.get("/console/risks?lang=vi").text)
    assert "Thay đổi quy định" in vi


def test_duties_tab_links_to_the_change(dty: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dty.ctx.settings, "regkb_change_loop", True)
    monkeypatch.setattr(dty.ctx.settings, "lawagent_enabled", True)
    sid = _system(dty)
    a, b = _seed(dty, sid, IID, 2)
    _note(dty, sid, a, "article changed on 2026-10-22 (package ab12cd34) | earlier")
    _note(dty, sid, b, "article changed on 2026-10-22 (package ffffffff)")  # no such package
    _insert_change(dty, [a])
    html = _tab(dty, sid).text
    link = f'href="/console/regkb/changes/{SHA}/{IID}"'
    assert link in html and html.count('data-du="change-link"') == 1
    # a change that is only diffed is not a link target; flag off: no link at all
    dty.ctx.state.update(
        "regkb_change",
        {"change_id": "rc_" + "1" * 20},
        {"status": "diffed"},
        dty.ctx.state.get("regkb_change", {"change_id": "rc_" + "1" * 20})["row_version"],
    )
    assert 'data-du="change-link"' not in _tab(dty, sid).text
    monkeypatch.setattr(dty.ctx.settings, "regkb_change_loop", False)
    assert 'data-du="change-link"' not in _tab(dty, sid).text
