"""WP-L1: law agent drafts page. Off by default (HTTP 400), on: list with the quote marked,
Confirm and Drop (htmx), two audit rows per POST, the person recorded, permissions."""

from __future__ import annotations

import pytest

from supervisor.core import rbac
from supervisor.regkb.drafts import DraftStore
from supervisor.regkb.lawagent import BANNER, PROMPT_VERSION, split_articles
from supervisor.regkb.loader import _load_yaml
from tests.regkb.test_lawagent import INSTRUMENT, TEXT_PATH

from .conftest import Console
from .test_rbac_matrix import app_routes

URL = f"/console/regkb/{INSTRUMENT}/drafts"


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "lawagent_enabled", True)
    return console


def _seed(console: Console, n: int = 2) -> list[dict]:
    arts = {a.number: a for a in split_articles(TEXT_PATH.read_text("utf-8"))}
    store = DraftStore(console.ctx.state, console.ctx.clock)
    rows = []
    for number in (5, 6, 7)[:n]:
        art = arts[number]
        rows.append(
            {
                "instrument_id": INSTRUMENT,
                "article": f"Điều {number}",
                "duty_id": "risk_classification",
                "subject": "The deployer",
                "trigger": "Before use",
                "evidence_asked": "Classification record",
                "text_vi": art.body[:90].strip(),
                "summary_en": f"Summary {number}",
                "source": "model",
                "model_id": "fake-law-model-1",
                "prompt_version": PROMPT_VERSION,
                "run_id": "lr_test",
            }
        )
    return store.add(rows)


def test_off_by_default(console: Console) -> None:
    assert console.ctx.settings.lawagent_enabled is False
    _seed(console, 1)
    r = console.get(URL)
    assert r.status_code == 400 and "LAWAGENT_ENABLED=1" in r.text
    assert "Summary 5" not in r.text
    row = DraftStore(console.ctx.state, console.ctx.clock).list(INSTRUMENT)[0]
    p = console.post(
        f"{URL}/{row['draft_id']}/confirm", {"row_version": row["row_version"]}, user="admin.chi"
    )
    assert p.status_code == 400 and "LAWAGENT_ENABLED=1" in p.text
    assert (
        DraftStore(console.ctx.state, console.ctx.clock).get(row["draft_id"])["status"] == "draft"
    )


def test_on_lists_drafts_by_article_with_banner_and_marked_quote(on: Console) -> None:
    rows = _seed(on)
    r = on.get(URL)
    assert r.status_code == 200
    assert BANNER in r.text and 'data-regkb-banner="1"' in r.text
    assert 'data-article="5"' in r.text and 'data-article="6"' in r.text
    assert r.text.index('data-article="5"') < r.text.index('data-article="6"')
    for row in rows:
        assert f'data-draft="{row["draft_id"]}"' in r.text
        assert "<mark>" + row["text_vi"][:30] in r.text.replace("&#39;", "'")
    assert "risk_classification" in r.text and "fake-law-model-1" in r.text
    assert "MOCK MODEL" not in r.text
    assert "Run the agent" not in r.text and 'data-act="run"' not in r.text
    # the filters
    assert "Summary 5" not in on.get(URL + "?status=confirmed").text
    assert "Summary 5" in on.get(URL + "?status=all").text
    for bad in ("?status=bogus",):
        assert on.get(URL + bad).status_code == 400
    assert on.get("/console/regkb/VN-NOPE-1/drafts").status_code == 400
    assert on.get("/console/regkb/bad%20id/drafts").status_code == 400


def test_a_mock_row_is_labelled_on_screen(on: Console) -> None:
    store = DraftStore(on.ctx.state, on.ctx.clock)
    art = split_articles(TEXT_PATH.read_text("utf-8"))[4]
    store.add(
        [
            {
                "instrument_id": INSTRUMENT,
                "article": "Điều 5",
                "duty_id": "logging",
                "subject": "s",
                "trigger": "t",
                "evidence_asked": "e",
                "text_vi": art.body[:60],
                "summary_en": "m",
                "source": "model",
                "model_id": "mock-chat-v1",
                "run_id": "r",
            }
        ]  # fmt: skip
    )
    assert "MOCK MODEL" in on.get(URL).text


def test_confirm_records_the_person_and_writes_two_audit_rows(on: Console) -> None:
    row = _seed(on, 1)[0]
    r = on.post(
        f"{URL}/{row['draft_id']}/confirm", {"row_version": row["row_version"]}, user="approver.em"
    )
    assert r.status_code == 200
    assert 'data-status="confirmed"' in r.text and 'data-decided-by="1"' in r.text
    assert "approver.em" in r.text and 'data-act="confirm"' not in r.text  # buttons are gone
    saved = DraftStore(on.ctx.state, on.ctx.clock).get(row["draft_id"])
    assert saved["status"] == "confirmed" and saved["confirmed_by"] == "approver.em"
    assert saved["confirmed_at"] is not None
    audit = [
        x
        for x in on.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] == "regkb.confirm"
    ]
    assert [x["outcome"] for x in audit] == ["attempted", "ok"]
    assert audit[0]["request_id"] == audit[1]["request_id"]
    assert audit[0]["target_kind"] == "regkb_draft" and audit[0]["target_id"] == row["draft_id"]
    assert audit[0]["before_hash"] and audit[1]["after_hash"] != audit[1]["before_hash"]
    assert audit[1]["actor"] == "approver.em"


def test_drop_and_the_row_version_guard(on: Console) -> None:
    a, b = _seed(on)
    r = on.post(f"{URL}/{a['draft_id']}/drop", {"row_version": a["row_version"]}, user="admin.chi")
    assert r.status_code == 200 and 'data-status="dropped"' in r.text
    saved = DraftStore(on.ctx.state, on.ctx.clock).get(a["draft_id"])
    assert saved["status"] == "dropped" and saved["confirmed_by"] == "admin.chi"
    # a second decision on the same draft is a message, not a change
    again = on.post(
        f"{URL}/{a['draft_id']}/confirm", {"row_version": a["row_version"]}, user="admin.chi"
    )
    assert again.status_code == 400 and "already dropped" in again.text
    assert DraftStore(on.ctx.state, on.ctx.clock).get(a["draft_id"])["status"] == "dropped"
    # a stale row_version, a missing one, and a draft of another instrument are 400
    stale = on.post(f"{URL}/{b['draft_id']}/confirm", {"row_version": "99"}, user="admin.chi")
    assert stale.status_code == 400
    assert on.post(f"{URL}/{b['draft_id']}/confirm", {}, user="admin.chi").status_code == 400
    other = on.post(
        f"/console/regkb/VN-AI-2025/drafts/{b['draft_id']}/confirm",
        {"row_version": b["row_version"]},
        user="admin.chi",
    )
    assert other.status_code == 400
    assert (
        on.post(f"{URL}/rkd_nothere/confirm", {"row_version": "1"}, user="admin.chi").status_code
        == 400
    )
    assert DraftStore(on.ctx.state, on.ctx.clock).get(b["draft_id"])["status"] == "draft"


def test_post_needs_htmx_and_a_permitted_role(on: Console) -> None:
    row = _seed(on, 1)[0]
    form = {"row_version": row["row_version"]}
    assert (
        on.post(f"{URL}/{row['draft_id']}/confirm", form, user="admin.chi", htmx=False).status_code
        == 400
    )
    for user in ("reviewer.an", "viewer.hoa", "auditor.dung", "operator.khanh"):
        r = on.post(f"{URL}/{row['draft_id']}/confirm", form, user=user)
        assert r.status_code == 403, user
    assert DraftStore(on.ctx.state, on.ctx.clock).get(row["draft_id"])["status"] == "draft"
    denied = [
        x for x in on.ctx.tables.query("console_action") if x["permission"] == "regkb.confirm"
    ]
    assert {x["outcome"] for x in denied} >= {"denied"}


def test_every_role_can_view_but_only_compliance_roles_see_buttons(on: Console) -> None:
    _seed(on, 1)
    for user in ("viewer.hoa", "auditor.dung", "operator.khanh", "reviewer.an"):
        r = on.get(URL, user=user)
        assert r.status_code == 200, user
        assert 'data-act="confirm"' not in r.text, user
    for user in ("approver.em", "admin.chi"):
        r = on.get(URL, user=user)
        assert (
            r.status_code == 200 and 'data-act="confirm"' in r.text and 'data-act="drop"' in r.text
        )


def test_permissions_in_the_matrix() -> None:
    assert set(rbac.PERMISSIONS["regkb.view"][0]) == set(rbac.ROLES)
    assert set(rbac.PERMISSIONS["regkb.confirm"][0]) == {"approver", "admin"}
    found = {
        (m, p): rbac.route_entry(m, p)
        for m, p, _ in app_routes()
        if "/console/regkb" in p
        and "/internal" not in p
        and "/console/regkb/watch" not in p  # WP-W1
        and "/console/regkb/changes" not in p  # WP-W2
    }
    assert found == {
        ("GET", "/console/regkb/{instrument_id}/drafts"): "regkb.view",
        ("POST", "/console/regkb/{instrument_id}/drafts/{draft_id}/confirm"): "regkb.confirm",
        ("POST", "/console/regkb/{instrument_id}/drafts/{draft_id}/drop"): "regkb.confirm",
    }


def test_duty_vocabulary_has_the_duty_used_here() -> None:
    duties = _load_yaml(TEXT_PATH.parents[2] / "schema" / "duties.yaml")["duties"]
    assert "risk_classification" in duties and "logging" in duties
