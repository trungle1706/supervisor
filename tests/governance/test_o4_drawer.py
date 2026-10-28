"""WP-O4: the Attach panel in the Candidates drawer (CONSOLE_OVERVIEW_V4 + ONBOARD_ATTACH_VIEW).
Off path: the drawer has no Attach section and the route answers 400 ``attach_off``."""

from __future__ import annotations

import pytest

from supervisor.console import overview_v4

from .conftest import Console
from .test_n1_overview import fill, v4  # noqa: F401  (fixture)
from .test_n1_triage import golden_graph

HX = {"HX-Request": "true"}


def _node(c: Console) -> str:
    fill(c, golden_graph())
    return str(overview_v4.load_candidates(c.ctx)[0]["node_id"])  # type: ignore[index]


def test_drawer_off_has_no_attach_section(v4: Console) -> None:  # noqa: F811
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert "attach-slot" not in html
    r = v4.get(f"/console/attach/{nid}")
    assert r.status_code == 400 and "attach_off" in r.text


def test_drawer_on_loads_the_panel_for_the_candidate(
    v4: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v4.ctx.settings, "onboard_attach_view", True)
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert f'hx-get="/console/attach/{nid}?lang=en"' in html and 'id="attach-slot"' in html
    panel = v4.get(f"/console/attach/{nid}?lang=en", headers=HX)
    assert panel.status_code == 200 and 'id="attach-panel"' in panel.text
    assert f'data-node="{nid}"' in panel.text and "<circle" in panel.text
    # a candidate that is not a registered agent: plug point unknown, nothing lit, no error
    assert 'data-plug="unknown"' in panel.text or 'data-plug="sdk"' in panel.text
