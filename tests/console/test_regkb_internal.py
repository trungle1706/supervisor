"""WP-W3: internal documents through the console and the JSON API. Off by default (HTTP 400
regkb_internal_off), upload, the reader API, the Draft duties button, accept on the drafts page,
audit rows, permissions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.regkb import internal as it
from supervisor.regkb.drafts import DraftStore
from supervisor.regkb.loader import load_kb
from tests.regkb.test_regkb_internal_docs import CCCD, PHONE, FakeChat, fixture_text

from .conftest import Console
from .test_rbac_matrix import app_routes

API = "/v1/regkb/internal"
PAGE = "/console/regkb/internal"


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    monkeypatch.setattr(console.ctx.settings, "lawagent_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "regkb_internal", True)
    monkeypatch.setattr(console.ctx.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(it, "make_chat", lambda settings: FakeChat())
    return console


def upload(c: Console, name: str = "legal", user: str = "reviewer.an", **fields: str) -> Any:
    data = {"title": "Chinh sach mau", "owner_group": "Model Risk", "version_label": "v2", **fields}
    return c.client.post(
        API,
        data=data,
        files={"file": (f"{name}.txt", fixture_text(name).encode("utf-8"), "text/plain")},
        headers={"X-Dev-User": user},
    )


def test_off_by_default_every_route_answers_400_with_the_code(console: Console) -> None:
    s = console.ctx.settings
    assert s.regkb_internal is False and s.lawagent_enabled is False
    r = upload(console)
    assert r.status_code == 400 and "regkb_internal_off" in r.text
    for url in (API, f"{API}/AAAAAAAAAAAA", f"{API}/AAAAAAAAAAAA/sections/1", PAGE):
        got = console.get(url)
        assert got.status_code == 400 and "regkb_internal_off" in got.text, url
    assert (
        console.client.post(
            f"{API}/AAAAAAAAAAAA/draft", headers={"X-Dev-User": "reviewer.an"}
        ).status_code
        == 400
    )
    assert console.post(PAGE, {}).status_code == 400
    assert console.post(f"{PAGE}/AAAAAAAAAAAA/draft", {}).status_code == 400
    assert not (Path(s.data_dir) / "regkb").exists()


def test_flag_alone_is_not_enough(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "regkb_internal", True)
    r = console.get(API)
    assert r.status_code == 400 and "regkb_internal_off" in r.text


def test_upload_reader_api_and_masking(on: Console) -> None:
    r = upload(on, "numbered")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "uploaded" and doc["owner_group"] == "Model Risk"
    assert doc["instrument_id"] == f"VN-INT-{doc['doc_id']}" and doc["section_count"] == 5
    listed = on.get(API).json()["documents"]
    assert [d["doc_id"] for d in listed] == [doc["doc_id"]]
    one = on.get(f"{API}/{doc['doc_id']}").json()
    assert [s["label"] for s in one["sections"]] == ["1", "2", "2.1", "2.2", "3"]
    assert one["sha256"] == doc["sha256"]
    sec = on.get(f"{API}/{doc['doc_id']}/sections/1").json()
    assert sec["masked"] is True and PHONE not in sec["text"] and CCCD not in sec["text"]
    assert "Mục đích" in sec["text"]
    # nothing in any reader answer carries the personal data
    for body in (on.get(API).text, on.get(f"{API}/{doc['doc_id']}").text):
        assert PHONE not in body and CCCD not in body
    # 400, never 500
    for url in (
        f"{API}/AAAAAAAAAAAA",
        f"{API}/bad-id",
        f"{API}/{doc['doc_id']}/sections/0",
        f"{API}/{doc['doc_id']}/sections/99",
        f"{API}/{doc['doc_id']}/sections/x",
    ):
        assert on.get(url).status_code == 400, url


def test_upload_refusals_are_400_with_a_code(on: Console) -> None:
    bad = on.client.post(
        API,
        data={"owner_group": "g"},
        files={"file": ("x.docx", b"x" * 100, "application/octet-stream")},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert bad.status_code == 400 and "bad_type" in bad.text
    assert "owner_group_required" in upload(on, owner_group="").text
    none = on.client.post(API, data={"owner_group": "g"}, headers={"X-Dev-User": "reviewer.an"})
    assert none.status_code == 400
    assert on.get(API).json()["documents"] == []


def test_draft_button_accept_on_the_drafts_page_and_the_instrument(on: Console) -> None:
    doc = upload(on).json()
    iid = doc["instrument_id"]
    r = on.post(f"{PAGE}/{doc['doc_id']}/draft", {}, user="reviewer.an")
    assert r.status_code == 200, r.text
    assert "3 draft(s) written" in r.text and f"/console/regkb/{iid}/drafts" in r.text
    page = on.get(f"{PAGE}?lang=en")
    assert page.status_code == 200
    assert 'data-regkb-banner="1"' in page.text and f'data-doc="{doc["doc_id"]}"' in page.text
    assert 'data-act="draft"' in page.text and 'data-act="open-drafts"' in page.text
    # the existing drafts page shows internal instruments, grouped by section
    url = f"/console/regkb/{iid}/drafts"
    d = on.get(url, user="approver.em")
    assert d.status_code == 200 and "Điều 2" in d.text and 'data-section-ref="S2"' in d.text
    assert 'data-dimension="model"' in d.text and "<mark>" in d.text
    assert 'data-act="confirm"' in d.text
    rows = DraftStore(on.ctx.state, on.ctx.clock).list(iid)
    assert len(rows) == 3
    # a person with regkb.confirm accepts a row: the instrument file appears
    first = rows[0]
    c = on.post(
        f"{url}/{first['draft_id']}/confirm", {"row_version": first["row_version"]},
        user="approver.em",
    )  # fmt: skip
    assert c.status_code == 200 and 'data-status="confirmed"' in c.text
    assert (Path(on.ctx.settings.data_dir) / "regkb" / "internal" / doc["doc_id"]
            / "instrument.yaml").is_file()  # fmt: skip
    kb = load_kb(docs_dir=Path(on.ctx.settings.data_dir) / "regkb" / "internal")
    assert len(kb.obligations_of(iid)) == 1
    status = on.get(f"{API}/{doc['doc_id']}").json()
    assert status["status"] == "confirmed" and status["has_instrument"] is True
    assert status["drafts"] == {"draft": 2, "confirmed": 1, "dropped": 0}
    # a drop does not change the instrument
    second = rows[1]
    dr = on.post(
        f"{url}/{second['draft_id']}/drop", {"row_version": second["row_version"]},
        user="approver.em",
    )  # fmt: skip
    assert dr.status_code == 200
    assert len(load_kb(docs_dir=Path(on.ctx.settings.data_dir) / "regkb" / "internal")
               .obligations_of(iid)) == 1  # fmt: skip
    # audit rows: two per POST, with the person
    audit = [
        x for x in on.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] in ("regkb.upload", "regkb.confirm")
    ]  # fmt: skip
    assert [x["outcome"] for x in audit] == ["attempted", "ok"] * 4  # upload, draft, confirm, drop
    assert {x["actor"] for x in audit} == {"reviewer.an", "approver.em"}


def test_unknown_internal_instrument_page_is_400(on: Console) -> None:
    assert on.get("/console/regkb/VN-INT-AAAAAAAAAAAA/drafts").status_code == 400
    assert on.get("/console/regkb/VN-INT-nothex/drafts").status_code == 400


def test_draft_with_a_mock_model_is_refused(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # back to the real make_chat; the settings of the test have no gateway
    monkeypatch.setattr(on.ctx.settings, "lawagent_enabled", True)
    monkeypatch.setattr(on.ctx.settings, "regkb_internal", True)
    monkeypatch.setattr(on.ctx.settings, "llm_base_url", "")
    doc = on.client.get(API, headers={"X-Dev-User": "reviewer.an"})
    assert doc.status_code == 200
    created = upload(on)
    assert created.status_code == 201
    r = on.client.post(
        f"{API}/{created.json()['doc_id']}/draft", headers={"X-Dev-User": "reviewer.an"}
    )
    assert r.status_code == 400 and "model_is_mock" in r.text


def test_permissions(on: Console) -> None:
    for user in ("viewer.hoa", "auditor.dung", "operator.khanh"):
        assert upload(on, user=user).status_code == 403, user
        assert on.get(API, user=user).status_code == 200, user
        assert on.get(PAGE, user=user).status_code == 200, user
    doc = upload(on).json()
    assert on.post(f"{PAGE}/{doc['doc_id']}/draft", {}, user="auditor.dung").status_code == 403
    assert (
        on.post(f"{PAGE}/{doc['doc_id']}/draft", {}, user="reviewer.an", htmx=False).status_code
        == 400
    )
    page = on.get(PAGE, user="auditor.dung").text
    assert 'data-act="draft"' not in page and 'name="file"' not in page
    # the confirm routes are unchanged: a reviewer cannot accept
    assert on.post(f"/console/regkb/{doc['instrument_id']}/drafts/rkd_{'0' * 20}/confirm", {},
                   user="reviewer.an").status_code == 403  # fmt: skip


def test_permissions_in_the_matrix() -> None:
    assert set(rbac.PERMISSIONS["regkb.upload"][0]) == {"reviewer", "owner", "approver", "admin"}
    found = {(m, p): rbac.route_entry(m, p) for m, p, _ in app_routes() if "/regkb/internal" in p}
    assert found == {
        ("GET", "/v1/regkb/internal"): "regkb.view",
        ("POST", "/v1/regkb/internal"): "regkb.upload",
        ("GET", "/v1/regkb/internal/{doc_id}"): "regkb.view",
        ("GET", "/v1/regkb/internal/{doc_id}/sections/{n}"): "regkb.view",
        ("POST", "/v1/regkb/internal/{doc_id}/draft"): "regkb.upload",
        ("GET", "/console/regkb/internal"): "regkb.view",
        ("POST", "/console/regkb/internal"): "regkb.upload",
        ("POST", "/console/regkb/internal/{doc_id}/draft"): "regkb.upload",
    }
