"""WP-O1: the Source panel on the Candidates drawer (CONSOLE_OVERVIEW_V4 + ONBOARD_INTAKE), and the
full Source page of a candidate. Off path: the drawer has no Source section."""

from __future__ import annotations

import io
import zipfile

import pytest

from supervisor.console import overview_v4

from .conftest import Console
from .test_n1_overview import fill, v4  # noqa: F401  (fixture)
from .test_n1_triage import golden_graph


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("agent/app.py", "x = 1\n")
    return buf.getvalue()


def _node(c: Console) -> str:
    fill(c, golden_graph())
    return str(overview_v4.load_candidates(c.ctx)[0]["node_id"])  # type: ignore[index]


def test_drawer_off_has_no_source_section(v4: Console) -> None:  # noqa: F811
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert "intake-slot" not in html and "Source" not in html.split('class="drawer-body"', 1)[1]


def test_drawer_on_loads_the_panel_and_upload_works(
    v4: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v4.ctx.settings, "onboard_intake", True)
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert f'hx-get="/console/intake/{nid}?lang=en"' in html and 'hx-trigger="load"' in html
    panel = v4.get(f"/console/intake/{nid}?lang=en", headers={"HX-Request": "true"})
    assert panel.status_code == 200 and 'data-empty="intake"' in panel.text
    r = v4.client.post(
        f"/console/intake/{nid}",
        files={"file": ("cand.zip", _zip(), "application/zip")},
        headers={"X-Dev-User": "reviewer.an", "HX-Request": "true"},
    )
    assert r.status_code == 200 and 'data-attempt="1"' in r.text and "cand.zip" in r.text
    page = v4.get(f"/console/intake/{nid}?lang=en")
    assert page.status_code == 200 and "cand.zip" in page.text and "<html" in page.text
