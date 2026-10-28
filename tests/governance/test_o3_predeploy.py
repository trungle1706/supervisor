"""WP-O3: the Pre-deploy panel in the Candidates drawer (next to Facts) and the link in register
workflow v2 step 3 (readiness). With the flag off, or with no report yet, both are as before."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

from supervisor.console import overview_v4
from supervisor.onboard import predeploy
from supervisor.onboard.intake import IntakeService

from .conftest import Console
from .test_n1_overview import fill, v4  # noqa: F401  (fixture)
from .test_n1_triage import golden_graph
from .test_n3_register import ME, new, reg, seed_node  # noqa: F401  (fixture)

HX = {"X-Dev-User": "reviewer.an", "HX-Request": "true"}


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "agent/app.py",
            'def get_fee(a):\n    return spark.sql("SELECT fee FROM main.synthetic.fees")\n',
        )
    return buf.getvalue()


class _Target:
    kind = "agent"
    is_mock = False

    def close(self) -> None:
        return None


def _executor(packs: Any, *a: Any, **k: Any) -> list[Any]:
    from tests.onboard.test_predeploy import result

    return [result(p.id, "ok") for p in packs]


def _report(c: Console, node: str) -> dict[str, Any]:
    s = c.ctx.settings
    n = IntakeService(s, c.ctx.state, c.ctx.clock).submit_zip(node, _zip(), "s.zip", ME)["n"]
    svc = predeploy.PredeployService(
        s, c.ctx.state, c.ctx.clock, executor=_executor, target_factory=lambda *a, **k: _Target()
    )
    return svc.start(node, n, ME, background=False)


@pytest.fixture(autouse=True)
def _clean_runs() -> Any:
    predeploy._RUNNING.clear()
    yield
    predeploy._RUNNING.clear()


# ------------------------------------------------------------------------------ the drawer


def _node(c: Console) -> str:
    fill(c, golden_graph())
    return str(overview_v4.load_candidates(c.ctx)[0]["node_id"])  # type: ignore[index]


def test_drawer_off_has_no_predeploy_section(v4: Console, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(v4.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(v4.ctx.settings, "onboard_facts", True)
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert "predeploy-slot" not in html and "facts-slot" in html
    assert v4.get(f"/console/predeploy/{nid}").status_code == 400


def test_drawer_on_loads_the_panel_after_facts(
    v4: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for flag in ("onboard_intake", "onboard_facts", "onboard_predeploy"):
        monkeypatch.setattr(v4.ctx.settings, flag, True)
    nid = _node(v4)
    html = v4.get(f"/console/candidates/{nid}/drawer?lang=en").text
    assert f'hx-get="/console/predeploy/{nid}?lang=en"' in html and 'id="predeploy-slot"' in html
    assert html.index("facts-slot") < html.index("predeploy-slot")  # next to Facts, after it
    panel = v4.get(f"/console/predeploy/{nid}?lang=en", headers={"HX-Request": "true"})
    assert panel.status_code == 200 and 'data-empty="predeploy"' in panel.text
    page = v4.get(f"/console/predeploy/{nid}?lang=en")
    assert page.status_code == 200 and "<html" in page.text


# ------------------------------------------------------------------------------ register step 3


def test_step3_off_or_without_a_report_keeps_the_folder_scan(
    reg: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nid = seed_node(reg)
    did = new(reg, f"?from={nid}")
    html = reg.get(f"/console/register/{did}/step/3?lang=en").text
    assert 'data-register="step3"' in html and 'data-register="predeploy"' not in html
    assert 'name="repo_path"' in html or "ux4b_f_repo" in html or "Readiness advisor" in html
    monkeypatch.setattr(reg.ctx.settings, "onboard_predeploy", True)  # on, but no report yet
    html = reg.get(f"/console/register/{did}/step/3?lang=en").text
    assert 'data-register="predeploy"' not in html and "Readiness advisor" in html


def test_step3_shows_the_verdict_and_links_to_the_panel_instead_of_the_scan(
    reg: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for flag in ("onboard_intake", "onboard_facts", "onboard_predeploy"):
        monkeypatch.setattr(reg.ctx.settings, flag, True)
    nid = seed_node(reg)
    rep = _report(reg, nid)
    did = new(reg, f"?from={nid}")
    html = reg.get(f"/console/register/{did}/step/3?lang=en").text
    assert 'data-register="predeploy"' in html
    assert f'data-verdict="{rep["verdict"]}"' in html
    assert f'href="/console/predeploy/{nid}?lang=en"' in html or (
        f"/console/predeploy/{nid.replace(':', '%3A')}?lang=en" in html
    )
    assert 'name="repo_path"' not in html  # the folder scan is gone
    assert 'data-gap="rg2_chk_readiness"' not in html
    assert 'data-gap="rg2_chk_policy"' in html or 'data-table="gaps"' in html
    # flag off again: the folder scan is back and no verdict shows
    monkeypatch.setattr(reg.ctx.settings, "onboard_predeploy", False)
    html = reg.get(f"/console/register/{did}/step/3?lang=en").text
    assert 'data-register="predeploy"' not in html
