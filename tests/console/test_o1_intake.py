"""WP-O1 (phase 9): the Source panel and the intake API (ONBOARD_INTAKE).

Off path first: no tab, every route answers 400 with the flag name and nothing is written. Then the
agent tab, the upload through the console form and the JSON API, the two audit rows per POST,
the roles (systems.edit to add, systems.view to look) and the planted secret."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from .conftest import Console

HX = {"HX-Request": "true"}
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(console.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(console.ctx.settings, "onboard_git_hosts", "git.example.invalid")
    return console


def upload(
    c: Console, node: str, entries: dict[str, str], user: str = "reviewer.an", name: str = "s.zip"
):
    return c.client.post(
        f"/console/intake/{node}",
        files={"file": (name, zip_bytes(entries), "application/zip")},
        headers={"X-Dev-User": user, **HX},
    )


def intake_dir(c: Console) -> Path:
    return Path(c.ctx.settings.data_dir) / "intake"


def actions(c: Console, path: str) -> list[dict]:
    return [r for r in c.ctx.tables.query("console_action", order_by=("ts",)) if r["path"] == path]


# ------------------------------------------------------------------------------ off path


def test_flags_default_off(console: Console) -> None:
    s = console.ctx.settings
    assert (s.onboard_intake, s.onboard_intake_max_mb, s.onboard_git_hosts) == (False, 20, "")


def test_off_no_tab_and_every_route_is_400_with_the_flag_name(console: Console) -> None:
    page = console.get("/console/agents/payments")
    assert page.status_code == 200 and 'data-tab="source"' not in page.text
    r = console.get("/console/agents/payments?tab=source")
    assert r.status_code == 400 and "ONBOARD_INTAKE=1" in r.text
    r = console.get("/console/agents/payments/tab/source")
    assert r.status_code == 400 and "ONBOARD_INTAKE=1" in r.text
    assert console.get("/console/intake/payments").status_code == 400
    r = upload(console, "payments", {"a.py": "x = 1\n"})
    assert r.status_code == 400 and "ONBOARD_INTAKE=1" in r.text
    api = console.client.get("/v1/intake/payments", headers={"X-Dev-User": "reviewer.an"})
    assert api.status_code == 400 and "intake_off" in api.json()["error"]
    api = console.client.post(
        "/v1/intake/payments",
        files={"file": ("s.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert api.status_code == 400 and "intake_off" in api.json()["error"]
    assert not intake_dir(console).exists()
    assert console.ctx.state.query("intake_attempt") == []


# ------------------------------------------------------------------------------ the panel


def test_agent_tab_and_panel_empty_state(on: Console) -> None:
    page = on.get("/console/agents/payments?tab=source")
    assert page.status_code == 200
    assert 'data-tab="source"' in page.text and 'data-section="intake"' in page.text
    assert 'data-empty="intake"' in page.text and 'hx-post="/console/intake/payments"' in page.text
    assert 'name="git_url"' in page.text and "git.example.invalid" in page.text
    frag = on.get("/console/agents/payments/tab/source")
    assert frag.status_code == 200 and "<html" not in frag.text and 'id="intake-panel"' in frag.text


def test_git_field_hidden_when_no_host_is_configured(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "onboard_git_hosts", "")
    assert 'name="git_url"' not in on.get("/console/agents/payments/tab/source").text


def test_upload_then_reupload_makes_attempt_two_and_shows_the_button(on: Console) -> None:
    r = upload(on, "payments", {"main.py": "x = 1\n", "cfg.yaml": "a: 1\n"}, name="first.zip")
    assert r.status_code == 200, r.text
    assert 'data-attempt="1"' in r.text and "first.zip" in r.text and "scrubbed" in r.text
    assert 'data-action="reupload"' in r.text and "Re-upload" in r.text
    assert "attempt 1 stored" in r.text
    r = upload(on, "payments", {"main.py": "x = 2\n"}, name="second.zip")
    assert 'data-attempt="2"' in r.text and 'data-attempt="1"' in r.text
    assert r.text.index('data-attempt="2"') < r.text.index('data-attempt="1"')  # newest first
    assert (intake_dir(on) / "payments" / "1" / "main.py").read_text() == "x = 1\n"
    assert (intake_dir(on) / "payments" / "2" / "main.py").read_text() == "x = 2\n"
    page = on.get("/console/agents/payments?tab=source")
    assert "second.zip" in page.text and "first.zip" in page.text
    full = on.get("/console/intake/payments")
    assert full.status_code == 200 and "<html" in full.text and "second.zip" in full.text


def test_two_audit_rows_per_post(on: Console) -> None:
    upload(on, "payments", {"main.py": "x = 1\n"})
    rows = actions(on, "/console/intake/payments")
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["permission"] for r in rows} == {"systems.edit"} and rows[0]["request_id"] == rows[1][
        "request_id"
    ]
    assert rows[1]["target_kind"] == "node" and rows[1]["target_id"] == "payments"
    assert rows[0]["after_hash"] is None and rows[1]["after_hash"] != rows[1]["before_hash"]
    assert rows[1]["detail"] == "upload n=1"
    api = on.client.post(
        "/v1/intake/payments",
        files={"file": ("a.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert api.status_code == 201
    assert [r["outcome"] for r in actions(on, "/v1/intake/payments")] == ["attempted", "ok"]


def test_refusal_is_400_with_a_code_and_two_rows(on: Console) -> None:
    r = upload(on, "payments", {"../evil.py": "x = 1\n"})
    assert r.status_code == 400 and "bad_path" in r.text
    r = upload(on, "payments", {"a.bin": "x"})
    assert r.status_code == 400 and "file_type_not_allowed" in r.text
    assert [x["outcome"] for x in actions(on, "/console/intake/payments")] == [
        "attempted",
        "error",
        "attempted",
        "error",
    ]
    page = on.get("/console/agents/payments/tab/source").text
    assert page.count("failed") >= 2  # both refusals are listed as failed attempts


def test_nothing_sent_is_400(on: Console) -> None:
    r = on.client.post(
        "/console/intake/payments",
        files={"git_url": (None, "")},
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r.status_code == 400 and "nothing_to_take_in" in r.text


def test_console_post_without_htmx_is_refused(on: Console) -> None:
    r = on.client.post(
        "/console/intake/payments",
        files={"file": ("s.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert r.status_code == 400 and on.ctx.state.query("intake_attempt") == []


def test_git_url_through_the_form_and_api_hosts(on: Console) -> None:
    r = on.client.post(
        "/console/intake/payments",
        files={"git_url": (None, "https://evil.example.invalid/org/repo")},
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r.status_code == 400 and "git_host_not_allowed" in r.text
    api = on.client.post(
        "/v1/intake/payments",
        json={"git_url": "https://evil.example.invalid/org/repo"},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert api.status_code == 400 and "git_host_not_allowed" in api.json()["error"]
    ws = on.client.post(
        "/v1/intake/payments",
        json={"workspace": "/Workspace/Users/x/agent"},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert (
        ws.status_code == 400
        and "not_built" in ws.json()["error"]
        and "WP-O1c" in ws.json()["error"]
    )


def test_api_list_and_post_shapes(on: Console) -> None:
    h = {"X-Dev-User": "reviewer.an"}
    post = on.client.post(
        "/v1/intake/payments",
        files={"file": ("a.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers=h,
    )
    body = post.json()
    assert post.status_code == 201 and body["n"] == 1 and body["status"] == "scrubbed"
    assert set(body) == {
        "attempt_id",
        "node_id",
        "n",
        "source_kind",
        "source_ref",
        "sha256",
        "size_bytes",
        "file_count",
        "created_by",
        "created_at",
        "status",
        "detail",
    }  # no server path
    listing = on.client.get("/v1/intake/payments", headers=h).json()
    assert listing["node_id"] == "payments" and [a["n"] for a in listing["attempts"]] == [1]
    bad = on.client.post(
        "/v1/intake/payments", content=b"x", headers={**h, "content-type": "text/plain"}
    )
    assert bad.status_code == 400 and "bad_body" in bad.json()["error"]
    cross = on.client.post(
        "/v1/intake/payments",
        files={"file": ("a.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers={**h, "Origin": "https://evil.example.invalid"},
    )
    assert cross.status_code == 400 and "cross_site" in cross.json()["error"]
    assert on.client.get("/v1/intake/bad id", headers=h).status_code in (400, 404)


# ------------------------------------------------------------------------------ roles


def test_view_only_role_sees_the_attempts_but_not_the_form(on: Console) -> None:
    upload(on, "payments", {"main.py": "x = 1\n"})
    page = on.get("/console/agents/payments/tab/source", user="auditor.dung")
    assert page.status_code == 200 and 'data-attempt="1"' in page.text
    assert 'hx-post="/console/intake/payments"' not in page.text
    assert (
        on.client.get("/v1/intake/payments", headers={"X-Dev-User": "auditor.dung"}).status_code
        == 200
    )


def test_post_needs_systems_edit(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    r = upload(on, "payments", {"main.py": "x = 1\n"}, user="auditor.dung")
    assert r.status_code == 403 and "needs role" in r.text
    api = on.client.post(
        "/v1/intake/payments",
        files={"file": ("a.zip", zip_bytes({"a.py": "x=1\n"}), "application/zip")},
        headers={"X-Dev-User": "auditor.dung"},
    )
    assert api.status_code == 403
    assert on.ctx.state.query("intake_attempt") == []


# ------------------------------------------------------------------------------ secrets


def test_planted_secret_never_lands_in_the_tree_the_page_or_the_audit_rows(on: Console) -> None:
    r = upload(
        on,
        "payments",
        {"app.py": f"KEY = '{AWS_KEY}'\npassword = 'S3cr3t-Value!'\n"},
        name=f"{AWS_KEY}.zip",
    )
    assert r.status_code == 200
    assert AWS_KEY not in r.text and "S3cr3t-Value!" not in r.text
    tree = (intake_dir(on) / "payments" / "1" / "app.py").read_text()
    assert "[REDACTED:" in tree and AWS_KEY not in tree and "S3cr3t-Value!" not in tree
    dump = json.dumps(
        [dict(x) for x in on.ctx.tables.query("console_action")], default=str
    ) + json.dumps([dict(x) for x in on.ctx.state.query("intake_attempt")], default=str)
    assert AWS_KEY not in dump and "S3cr3t-Value!" not in dump


def test_vi_labels_exist(on: Console) -> None:
    html = on.get("/console/agents/payments/tab/source?lang=vi").text
    assert "Mã nguồn" in html and "Tải mã nguồn lên" in html
