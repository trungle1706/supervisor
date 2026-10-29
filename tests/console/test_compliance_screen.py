"""WP14: Compliance tab - off by default, read-only, advisory only."""

from __future__ import annotations

import pytest

from supervisor.advisory.compliance import demo_product
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.advisory.compliance.render import to_json
from supervisor.console import readmodels
from supervisor.regkb import load_kb

from .conftest import Console
from .test_rbac_matrix import app_routes

GAP_ID = "VN-TT53-2026-A5.01G2-01"


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "console_compliance_enabled", True)
    return console


def test_off_by_default_no_nav_link(console: Console) -> None:
    assert console.ctx.settings.console_compliance_enabled is False
    home = console.get("/console/")
    assert "/console/compliance" not in home.text
    for url in (
        "/console/compliance",
        "/console/compliance/payments",
        f"/console/compliance/payments/obligation/{GAP_ID}",
    ):
        r = console.get(url)
        assert r.status_code == 400, url  # Onboard Start / Integration pattern
        assert "CONSOLE_COMPLIANCE_ENABLED=1" in r.text
        assert GAP_ID not in r.text


def test_on_list_page_and_nav(on: Console) -> None:
    assert 'href="/console/compliance?lang=en"' in on.get("/console/").text
    r = on.get("/console/compliance")
    assert r.status_code == 200
    for agent in ("payments", "credit_prequal", "customer_service"):
        assert f'data-agent="{agent}"' in r.text
    assert "Advisory only" in r.text and "Not legal advice" in r.text
    assert "High risk" in r.text and "Gap" in r.text


def test_matrix_page_and_filters(on: Console) -> None:
    r = on.get("/console/compliance/payments")
    assert r.status_code == 200
    assert "Advisory only" in r.text and "PAY-03" in r.text and "Decision 33" in r.text
    gap = on.get("/console/compliance/payments?status=gap")
    assert gap.status_code == 200
    assert f'data-obligation="{GAP_ID}"' in gap.text
    assert 'data-status="partial"' not in gap.text
    met = on.get("/console/compliance/payments?status=met")
    assert f'data-obligation="{GAP_ID}"' not in met.text
    inst = on.get("/console/compliance/payments?instrument=VN-TT53-2026&status=gap")
    assert f'data-obligation="{GAP_ID}"' in inst.text
    assert 'data-obligation="VN-QD33-' not in inst.text
    vi = on.get("/console/compliance/payments?lang=vi")
    assert "Cố vấn tuân thủ" in vi.text and "Thiếu" in vi.text


def test_obligation_page_shows_vietnamese_text(on: Console) -> None:
    r = on.get(f"/console/compliance/payments/obligation/{GAP_ID}")
    assert r.status_code == 200
    kb = load_kb()
    text_vi = kb.obligations[GAP_ID].text_vi
    assert text_vi
    assert 'data-text-vi="1"' in r.text
    # Jinja escapes quotes; compare on a safe prefix
    assert text_vi[:30].replace("&", "&amp;") in r.text or "Gap" in r.text
    assert "Advisory only" in r.text


def test_bad_input_is_400(on: Console) -> None:
    for url in (
        "/console/compliance/nosuchagent",
        "/console/compliance/payments/obligation/NOPE-1",
        "/console/compliance/payments/obligation/bad%20id",
        "/console/compliance/payments?status=bogus",
        "/console/compliance/payments?instrument=a%20b",
        "/console/compliance/payments?applies=maybe",
    ):
        r = on.get(url)
        assert r.status_code == 400, (url, r.status_code)


def test_onboarded_json_backed_view(on: Console) -> None:
    m = build_matrix(load_kb(), demo_product("customer_service"), chat=None)
    d = readmodels.onboard_dir(on.ctx.settings, "my_agent")
    d.mkdir(parents=True)
    (d / "compliance_matrix.json").write_text(to_json(m), encoding="utf-8")
    page = on.get("/console/compliance")
    assert 'data-agent="my_agent"' in page.text
    r = on.get("/console/compliance/my_agent?status=gap")
    assert r.status_code == 200 and "data-obligation=" in r.text


def test_every_compliance_route_is_get_only_and_in_rbac() -> None:
    from supervisor.core import rbac

    found = [(m, p) for m, p, _ in app_routes() if p.startswith("/console/compliance")]
    assert len(found) == 3
    for method, path in found:
        assert method == "GET", path
        assert rbac.route_entry(method, path) == "compliance.view", path


def test_all_roles_can_view(on: Console) -> None:
    for user in ("auditor.dung", "reviewer.an"):
        assert on.get("/console/compliance", user=user).status_code == 200


def test_counts_card_says_what_it_counts_and_adds_up_to_the_table(on: Console) -> None:
    """UX5-BUG: the status card counts rows that apply; the table also holds the rows that wait
    for an answer. The card states both and the table total."""
    import re

    from supervisor.console import compliance_view

    m = compliance_view.matrix_for(on.ctx.settings, "payments")
    yes = m["summary"]["by_applies"].get("yes", 0)
    na = m["summary"]["needs_answer"]
    total = len(m["rows"])
    html = on.get("/console/compliance/payments?lang=en").text
    assert f"Rows that apply ({yes}), by status" in html
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert f"{yes} apply + {na} need an answer = {total} rows in the table below" in flat
    assert f"Showing {total} of {total} rows" in flat
