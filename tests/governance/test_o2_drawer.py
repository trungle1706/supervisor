"""WP-O2: the Facts panel in the Candidates drawer, next to Source (CONSOLE_OVERVIEW_V4 +
ONBOARD_FACTS). Off path: the drawer has no Facts section."""

from __future__ import annotations

import io
import zipfile

import pytest

from supervisor.console import overview_v4

from .conftest import Console
from .test_n1_overview import fill, v4  # noqa: F401  (fixture)
from .test_n1_triage import golden_graph

HX = {"X-Dev-User": "reviewer.an", "HX-Request": "true"}


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "agent/app.py",
            'def get_fee(a):\n    return spark.sql("SELECT fee FROM main.synthetic.fees")\n',
        )
    return buf.getvalue()


def _node(c: Console) -> str:
    fill(c, golden_graph())
    return str(overview_v4.load_candidates(c.ctx)[0]["node_id"])  # type: ignore[index]


def test_drawer_off_has_no_facts_section(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(v4.ctx.settings, "onboard_intake", True)  # Source on, Facts off
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert "facts-slot" not in html and "intake-slot" in html
    assert v4.get(f"/console/facts/{nid}").status_code == 400


def test_drawer_on_loads_the_panel_next_to_source_and_reread_builds(
    v4: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v4.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(v4.ctx.settings, "onboard_facts", True)
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert f'hx-get="/console/facts/{nid}?lang=en"' in html and 'id="facts-slot"' in html
    assert html.index("intake-slot") < html.index("facts-slot")  # Facts comes after Source
    panel = v4.get(f"/console/facts/{nid}?lang=en", headers={"HX-Request": "true"})
    assert panel.status_code == 200 and 'data-empty="facts"' in panel.text
    up = v4.client.post(
        f"/console/intake/{nid}",
        files={"file": ("cand.zip", _zip(), "application/zip")},
        headers=HX,
    )
    assert up.status_code == 200
    r = v4.client.post(f"/console/facts/{nid}", headers=HX)
    assert r.status_code == 200, r.text
    assert "main.synthetic.fees" in r.text and "get_fee" in r.text
    assert "claims dropped (no evidence)" in r.text and 'data-action="reread"' in r.text
    page = v4.get(f"/console/facts/{nid}?lang=en")
    assert page.status_code == 200 and "<html" in page.text and "main.synthetic.fees" in page.text
