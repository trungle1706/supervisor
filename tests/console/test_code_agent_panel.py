"""Source analysis tab and panel (CODE_AGENT_ENABLED).

Off path first: no tab, every route answers 400 with the flag name, nothing is written. Then the
panel with no model (deterministic report, labelled), with a scripted model (agent findings,
disagreements, Use in assessment writing model rows that a facts re-read keeps), the file view and
its path check, and the audit rows. The model is a scripted stand-in (unit test only)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import Console
from .test_o2_facts import HX, actions, upload

NODE = "payments"


class Scripted:
    family, model_id, is_mock = "fake", "fake-gateway-v1", False

    def complete_json(self, messages: Any, schema: Any, timeout_s: float | None = None) -> dict:
        return {
            "findings": [
                {
                    "kind": "pii",
                    "name": "payee_id",
                    "file": "agent.py",
                    "line": 5,
                    "quote": "def refund_fee(account_id",
                    "attrs": {"tool": "refund_fee"},
                },
                {
                    "kind": "guardrail",
                    "name": "x",
                    "file": "agent.py",
                    "line": 7,
                    "quote": "not on that line at all",
                    "attrs": {"guard": "amount_limit"},
                },
            ],
            "next": {"tool": "finish"},
        }


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    monkeypatch.setattr(s, "onboard_intake", True)
    monkeypatch.setattr(s, "onboard_facts", True)
    monkeypatch.setattr(s, "code_agent_enabled", True)
    return console


def run(c: Console, user: str = "reviewer.an") -> Any:
    return c.client.post(f"/console/code-analysis/{NODE}/run", headers={"X-Dev-User": user, **HX})


def wait_done(c: Console) -> dict:
    for _ in range(100):
        st = c.client.get(
            f"/v1/code-analysis/{NODE}", headers={"X-Dev-User": "reviewer.an"}
        ).json()["status"]
        if st["state"] in ("done", "failed"):
            return st
        time.sleep(0.1)
    raise AssertionError("run did not finish")


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.code_agent_enabled is False


def test_off_no_tab_and_every_route_is_400_with_the_flag_name(console: Console) -> None:
    page = console.get(f"/console/agents/{NODE}")
    assert page.status_code == 200 and 'data-tab="analysis"' not in page.text
    for url in (f"/console/agents/{NODE}?tab=analysis", f"/console/code-analysis/{NODE}"):
        r = console.get(url)
        assert r.status_code == 400 and "CODE_AGENT_ENABLED=1" in r.text, url
    assert run(console).status_code == 400
    h = {"X-Dev-User": "reviewer.an"}
    for m, u in (
        ("get", f"/v1/code-analysis/{NODE}"),
        ("post", f"/v1/code-analysis/{NODE}/run"),
        ("post", f"/v1/code-analysis/{NODE}/apply"),
    ):
        r = getattr(console.client, m)(u, headers=h)
        assert r.status_code == 400 and "code_agent_off" in r.json()["error"], u


def test_off_facts_build_is_unchanged(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(console.ctx.settings, "onboard_facts", True)
    upload(console)
    r = console.client.post(f"/console/facts/{NODE}", headers={"X-Dev-User": "reviewer.an", **HX})
    assert r.status_code == 200 and "code agent" not in r.text


# ------------------------------------------------------------------------------ the panel


def test_tab_and_empty_panel(on: Console) -> None:
    page = on.get(f"/console/agents/{NODE}?tab=analysis")
    assert page.status_code == 200 and 'data-tab="analysis"' in page.text
    assert 'data-empty="code-agent"' in page.text and 'data-action="run"' in page.text


def test_run_without_a_source_is_400(on: Console) -> None:
    r = run(on)
    assert r.status_code == 400 and "no_attempt" in r.text


def test_no_model_gives_a_labelled_deterministic_report(on: Console) -> None:
    upload(on)
    assert run(on).status_code == 200
    assert wait_done(on)["state"] == "done"
    html = on.get(f"/console/code-analysis/{NODE}", headers={"HX-Request": "true"}).text
    assert 'data-det="1"' in html and 'data-ca="cards"' in html and "refund_fee" in html
    assert 'data-ca-state="done"' in html and "rules only" in html
    # Use in assessment needs agent findings
    r = on.client.post(f"/v1/code-analysis/{NODE}/apply", headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 400 and "no_agent_findings" in r.json()["error"]


def test_scripted_model_adds_findings_and_use_in_assessment_feeds_the_facts(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("supervisor.adapters.factory.make_chat_model", lambda settings: Scripted())
    upload(on)
    run(on)
    assert wait_done(on)["state"] == "done"
    html = on.get(f"/console/code-analysis/{NODE}", headers={"HX-Request": "true"}).text
    assert "model: fake-gateway-v1" in html and "refund_fee:payee_id" in html
    assert (
        'data-pointer="1"' in html
        and f"/console/code-analysis/{NODE}/file?n=1&amp;path=agent.py" in html
    )
    assert 'data-ca="use"' in html and 'data-action="apply"' in html and "claim" in html
    r = on.client.post(f"/v1/code-analysis/{NODE}/apply", headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 201, r.text
    rows = [
        x
        for x in on.ctx.state.query("onboard_facts", {"node_id": NODE})
        if (x["model_id"] or "").startswith("code-agent:")
    ]
    assert rows and all(x["source"] == "model" and x["file"] and x["line"] for x in rows)
    # a facts re-read keeps them while the analysis is applied
    on.client.post(f"/console/facts/{NODE}", headers={"X-Dev-User": "reviewer.an", **HX})
    kept = [
        x
        for x in on.ctx.state.query("onboard_facts", {"node_id": NODE})
        if (x["model_id"] or "").startswith("code-agent:")
        and str(x["active"]).lower() not in ("false", "0")
    ]
    assert len(kept) == len(rows)


def test_file_view_shows_the_scrubbed_line_and_refuses_other_paths(on: Console) -> None:
    upload(on)
    ok = on.get(f"/console/code-analysis/{NODE}/file?n=1&path=agent.py&line=3")
    assert (
        ok.status_code == 200
        and 'data-hit="1"' in ok.text
        and "[REDACTED:aws_access_key]" in ok.text
    )
    for bad in ("../../etc/passwd", "/etc/passwd", "nope.py"):
        r = on.get(f"/console/code-analysis/{NODE}/file?n=1&path={bad}&line=1")
        assert r.status_code == 400, bad


def test_two_audit_rows_per_post(on: Console) -> None:
    upload(on)
    run(on)
    wait_done(on)
    rows = actions(on, f"/console/code-analysis/{NODE}/run")
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["permission"] for r in rows} == {"systems.edit"}


def test_view_only_role_sees_the_report_but_not_the_buttons(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload(on)
    run(on)
    wait_done(on)
    page = on.get(f"/console/agents/{NODE}/tab/analysis", user="auditor.dung")
    assert page.status_code == 200 and 'data-ca="cards"' in page.text
    assert 'hx-post="/console/code-analysis/' not in page.text
    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    assert run(on, user="auditor.dung").status_code == 403
    api = on.client.post(f"/v1/code-analysis/{NODE}/run", headers={"X-Dev-User": "auditor.dung"})
    assert api.status_code == 403
