"""WP18: every route is in the role matrix, is enforced, and every mutating action is audited."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import _IncludedRouter

from supervisor.adapters.auth.authz import RBAC_ATTR
from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.app import app
from supervisor.core import rbac
from supervisor.core.errors import AppendOnlyError

from .conftest import Console, add_gate_block

PARAMS = {
    "tab": "story",
    "fmt": "json",
    "agent_id": "payments",
    "agent": "payments",
    "name": "x.json",
    "notice_id": "N1",
    "risk_id": "RSK-X",  # WP29
    "control_id": "CTL-X",  # WP30
    "task_id": "tsk_x",  # WP30
}


def _walk(routes: Any) -> Iterator[Any]:
    for r in routes:
        if isinstance(r, _IncludedRouter):
            yield from _walk(r.effective_candidates())
        else:
            yield r


def app_routes() -> list[tuple[str, str, Any]]:
    out = []
    for r in _walk(app.router.routes):
        for method in sorted(getattr(r, "methods", None) or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            out.append((method, r.path, r))
    return out


def _deps(dependant: Any) -> Iterator[Any]:
    for d in getattr(dependant, "dependencies", ()):
        yield d
        yield from _deps(d)


def _needs_of(route: Any) -> list[str]:
    dependant = getattr(route, "dependant", None)
    return [
        getattr(d.call, RBAC_ATTR)
        for d in _deps(dependant)
        if d.call is not None and hasattr(d.call, RBAC_ATTR)
    ]


# ------------------------------------------------------------------ (a) coverage


def test_every_route_is_in_the_matrix() -> None:
    unmapped = [f"{m} {p}" for m, p, _ in app_routes() if rbac.route_entry(m, p) is None]
    assert not unmapped, f"routes missing from supervisor.core.rbac.ROUTES: {unmapped}"


def test_every_protected_route_has_the_needs_dependency() -> None:
    bad = []
    for m, p, r in app_routes():
        entry = rbac.route_entry(m, p)
        if entry in rbac.MARKERS:
            continue
        if _needs_of(r) != [entry]:
            bad.append(f"{m} {p}: matrix {entry!r}, route needs {_needs_of(r)}")
    assert not bad, bad


def test_matrix_has_no_stale_route() -> None:
    live = {(m, rbac.normalise_path(p)) for m, p, _ in app_routes()}
    stale = [k for k in rbac.ROUTES if k not in live]
    assert not stale, f"in ROUTES but not in the app: {stale}"


# ------------------------------------------------------------------ helpers


@pytest.fixture
def people(console: Console) -> dict[str, str]:
    """One user per role holding exactly that role."""
    out = {}
    for role in rbac.ROLES:
        uid = f"only.{role}"
        console.ctx.provider.users[uid] = AuthPrincipal(
            uid, "user", "dev_header", frozenset({role}), uid
        )
        out[role] = uid
    return out


def _case(console: Console) -> dict[str, Any]:
    console.get("/console/")  # intake
    return next(c for c in console.ctx.cases.list_cases() if "PAY-07" in c["summary"])


def _url(template: str, case_id: str, action: str = "pause") -> str:
    values = {**PARAMS, "case_id": case_id, "action": action}
    url = template
    for k, v in values.items():
        url = url.replace("{" + k + "}", v)
    return url


def _all_rows(console: Console) -> list[dict[str, Any]]:
    return console.ctx.tables.query("console_action", order_by=("ts",))


def _rows(console: Console) -> list[dict[str, Any]]:
    """The outcome rows (M4 also writes an ``attempted`` row before each side effect)."""
    return [r for r in _all_rows(console) if r["outcome"] != "attempted"]


def _call(console: Console, method: str, url: str, user: str) -> Any:
    if url.startswith(("/gate", "/v1/")):  # JSON APIs (WP26, WP27, WP29)
        body = {"agent_id": "payments", "reason": "t"}
        return console.client.request(
            method,
            url,
            json=body if method == "POST" else None,
            headers={"X-Dev-User": user},
        )
    if method == "GET":
        return console.get(url, user=user)
    return console.post(url, {"row_version": "1", "reason": "t"}, user=user)


def _human_cases() -> list[tuple[str, str, str, str]]:
    """(method, template, permission, action) for every route that needs a role."""
    out = []
    for (method, path), entry in rbac.ROUTES.items():
        if entry in rbac.MARKERS:
            continue
        if "{" in entry:
            for action in ("pause", "resume", "quarantine", "release"):
                out.append((method, path, f"agent.{action}", action))
        else:
            out.append((method, path, entry, "pause"))
    return sorted(out)


# ------------------------------------------------------------------ (b) route x role


@pytest.mark.parametrize(
    ("method", "template", "permission", "action"),
    _human_cases(),
    ids=lambda v: str(v),
)
def test_denied_roles_get_403_and_allowed_roles_do_not(
    console: Console,
    people: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    template: str,
    permission: str,
    action: str,
) -> None:
    monkeypatch.setattr(console.ctx.settings, "api_rbac_enabled", True)
    case = _case(console)
    url = _url(template, case["case_id"], action)
    is_gate = url.startswith(("/gate", "/v1/"))  # JSON answers (WP26, WP27, WP29)
    for role in rbac.ROLES:  # denied first: they change nothing
        if rbac.allowed([role], permission):
            continue
        r = _call(console, method, url, people[role])
        assert r.status_code == 403, (role, permission, r.status_code, r.text[:200])
        if is_gate:
            assert r.json()["error"]
        else:
            assert "msg-error" in r.text and "needs role" in r.text
    for role in rbac.ROLES:
        if not rbac.allowed([role], permission):
            continue
        r = _call(console, method, url, people[role])
        assert r.status_code != 403, (role, permission, r.text[:200])
        assert r.status_code < 500, (role, permission, r.status_code, r.text[:200])


# ------------------------------------------------------------------ (c) audit rows

POST_CASES: list[tuple[str, str, str, dict[str, str], str, str]] = [
    # (suffix, user, permission, form, outcome, target_kind)
    ("assign", "reviewer.an", "case.assign", {"assignee": "reviewer.an"}, "ok", "case"),
    ("comment", "reviewer.an", "case.comment", {"text": "note"}, "ok", "case"),
    ("itsm", "reviewer.an", "case.itsm", {"itsm_ref": "INC-1"}, "ok", "case"),
    (
        "transition",
        "reviewer.an",
        "case.transition",
        {"to": "triaged", "assignee": "reviewer.an", "note": "n"},
        "ok",
        "case",
    ),
    ("report-sent", "reviewer.an", "case.report_sent", {"kind": "preliminary"}, "ok", "case"),
    ("verify", "auditor.dung", "case.verify", {}, "ok", "case"),
    ("assign", "auditor.dung", "case.assign", {"assignee": "reviewer.an"}, "denied", "case"),
    ("signoff", "reviewer.an", "case.signoff", {"decision": "approve"}, "error", "case"),
]


@pytest.mark.parametrize(("suffix", "user", "permission", "form", "outcome", "kind"), POST_CASES)
def test_case_actions_write_exactly_one_row(
    console: Console,
    suffix: str,
    user: str,
    permission: str,
    form: dict[str, str],
    outcome: str,
    kind: str,
) -> None:
    c = _case(console)
    before = len(_rows(console))
    r = console.post(
        f"/console/cases/{c['case_id']}/{suffix}",
        {**form, "row_version": c["row_version"]},
        user=user,
    )
    assert r.status_code < 500, r.text
    rows = _rows(console)[before:]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["permission"] == permission
    assert row["outcome"] == outcome
    assert row["actor"] == user and row["actor_kind"] == "user"
    assert row["auth_method"] == "dev_header"
    assert row["method"] == "POST" and row["path"].endswith(f"/{suffix}")
    assert row["request_id"] and row["action_id"]
    assert row["target_kind"] == kind and row["target_id"] == c["case_id"]
    assert row["roles"] == sorted(console.ctx.provider.users[user].roles)
    assert row["before_hash"] and row["after_hash"]
    if outcome == "ok" and suffix in ("assign", "comment", "itsm", "transition", "report-sent"):
        assert row["before_hash"] != row["after_hash"], "the case row changed"
    else:
        assert row["before_hash"] == row["after_hash"]
    assert row["detail"] in (None, "permission_denied") or row["detail"].isidentifier()


def test_agent_action_hashes_change_with_the_agent_row(console: Console) -> None:
    r = console.post("/console/agents/payments/pause", {"reason": "t"})
    assert r.status_code == 200
    (row,) = _rows(console)
    assert (row["permission"], row["outcome"], row["target_kind"], row["target_id"]) == (
        "agent.pause",
        "ok",
        "agent",
        "payments",
    )
    assert row["before_hash"] != row["after_hash"]
    # a quarantine by a reviewer: denied by the matrix, row says so, agent row unchanged
    r = console.post("/console/agents/payments/quarantine", {"reason": "t"})
    assert r.status_code == 403
    denied = _rows(console)[-1]
    assert denied["outcome"] == "denied" and denied["permission"] == "agent.quarantine"
    assert denied["before_hash"] == denied["after_hash"] == row["after_hash"]


def test_other_mutating_routes_write_one_row_each(
    console: Console,
) -> None:
    add_gate_block(console.runtime.adapters)
    console.post("/console/intake/run")  # opens a case and a notice
    notice = console.ctx.inbox.list(status="unread")[0]
    calls = [
        ("/console/intake/run", {}, "reviewer.an", "intake.run", "ok", "reviewer.an"),
        ("/console/chain/verify", {}, "auditor.dung", "chain.verify", "ok", None),
        ("/console/chain/export", {}, "auditor.dung", "evidence.export", "ok", None),
        ("/console/export", {}, "auditor.dung", "evidence.export", "ok", None),
        ("/console/export", {}, "only.viewer", "evidence.export", "denied", None),
        ("/console/onboard/start", {"target": "x"}, "reviewer.an", "onboard.start", "error", None),
        (
            f"/console/inbox/{notice['notice_id']}/read",
            {"row_version": str(notice["row_version"])},
            "reviewer.an",
            "inbox.read",
            "ok",
            None,
        ),
        ("/console/dev/user", {"user": "admin.chi"}, "reviewer.an", "dev.user", "ok", None),
    ]
    console.ctx.provider.users["only.viewer"] = AuthPrincipal(
        "only.viewer", "user", "dev_header", frozenset({"viewer"})
    )
    for url, form, user, permission, outcome, _ in calls:
        before = len(_rows(console))
        r = console.post(url, form, user=user)
        assert r.status_code < 500, (url, r.text[:200])
        rows = _rows(console)[before:]
        assert len(rows) == 1, (url, rows)
        assert rows[0]["permission"] == permission, url
        assert rows[0]["outcome"] == outcome, (url, rows[0])
        assert rows[0]["request_id"]
    inbox_row = next(r for r in _rows(console) if r["permission"] == "inbox.read")
    assert inbox_row["target_kind"] == "notice"
    assert inbox_row["before_hash"] != inbox_row["after_hash"]


def test_every_post_route_is_covered_by_an_audit_test() -> None:
    covered = {
        "case.assign",
        "case.comment",
        "case.itsm",
        "case.transition",
        "case.report_sent",
        "case.verify",
        "case.signoff",
        "agent.pause",
        "intake.run",
        "chain.verify",
        "evidence.export",
        "onboard.start",
        "inbox.read",
        "alert.ack",
        "playground.run",  # WP-UX3: tests/console/test_ux3_playground.py
        "collectors.add",  # WP38: tests/console/test_collectors_page.py (two audit rows)
        "decisions.export",  # WP39: tests/console/test_wp39_decisions.py
        "dev.user",
        "transparency.generate",  # WP31: tests/console/test_transparency.py
    }
    posts = {
        rbac.resolve_permission(e, {"action": "pause"}) if e != rbac.DEV_ONLY else "dev.user"
        for (m, p), e in rbac.ROUTES.items()
        if m == "POST" and p.startswith("/console")
    }
    assert posts == covered


def test_audit_off_writes_nothing(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_audit_enabled", False)
    monkeypatch.setattr(console.ctx.settings, "supervisor_mode", "dev")  # M4: dev only
    c = _case(console)
    assert (
        console.post(
            f"/console/cases/{c['case_id']}/comment",
            {"text": "x", "row_version": c["row_version"]},
        ).status_code
        == 200
    )
    assert console.post("/console/agents/payments/quarantine", {"reason": "t"}).status_code == 403
    assert console.post("/console/agents/payments/pause", {"reason": "t"}).status_code == 200
    r = console.client.post(
        "/gate/pause",
        json={"agent_id": "payments", "reason": "t"},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert r.status_code == 200
    assert _rows(console) == []


def test_outcome_write_failure_is_a_warning_not_a_5xx(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: the ``attempted`` row is written; only the outcome row fails -> result + WARNING."""
    orig = console.ctx.tables.append

    def flaky(table: str, rows: Any, *a: Any, **k: Any) -> Any:
        if table == "console_action" and rows[0]["outcome"] != "attempted":
            raise RuntimeError("store down")
        return orig(table, rows, *a, **k)

    monkeypatch.setattr(console.ctx.tables, "append", flaky)
    r = console.post("/console/agents/payments/pause", {"reason": "t"})
    assert r.status_code == 200 and "WARNING: the console audit record failed" in r.text
    r = console.post("/console/agents/payments/quarantine", {"reason": "t"}, user="reviewer.an")
    assert r.status_code == 403  # denied before the wrapper: the dependency writes the row
    assert [x["outcome"] for x in _all_rows(console)] == ["attempted"]


def test_audit_detail_never_carries_typed_text(console: Console) -> None:
    c = _case(console)
    secret = "Nguyen Van A 0912345678"
    console.post(
        f"/console/cases/{c['case_id']}/comment",
        {"text": secret, "row_version": "999"},  # stale version: an error
    )
    rows = _rows(console)
    assert rows and rows[-1]["outcome"] == "error"
    assert secret not in json.dumps(rows, default=str)


def test_bad_action_name_is_a_400_and_audited_as_invalid(console: Console) -> None:
    r = console.post("/console/agents/payments/frobnicate", {"reason": "t"})
    assert r.status_code == 400
    (row,) = _rows(console)
    assert row["permission"] == "agent.invalid" and row["outcome"] == "error"


# ------------------------------------------------------------------ (d) append only


def test_console_action_is_append_only(console: Console) -> None:
    console.post("/console/agents/payments/pause", {"reason": "t"})
    x = console.runtime.adapters.executor
    with pytest.raises(AppendOnlyError):
        x.execute("UPDATE console_action SET actor = 'z'")
    with pytest.raises(AppendOnlyError):
        x.execute("DELETE FROM console_action")


# ------------------------------------------------------------------ (e) /gate


def test_gate_control_ignores_the_rbac_flag_and_the_agent_routes_keep_it(
    console: Console,
) -> None:
    assert console.ctx.settings.api_rbac_enabled is False
    # control routes always need a known identity (B1); a body principal is ignored
    r = console.client.post(
        "/gate/pause",
        json={"agent_id": "payments", "reason": "t", "principal": "someone"},
        headers={"X-Dev-User": "no-such-user"},
    )
    assert r.status_code == 403 and "error" in r.json()
    assert console.runtime.gateway.states.get_state("payments") != "PAUSED"
    # agent-facing read routes stay open while the flag is off
    assert console.client.get("/gate/metrics", headers={"X-Dev-User": "nobody"}).status_code == 200
    (row,) = _rows(console)
    assert row["permission"] == "agent.pause" and row["outcome"] == "denied"
    assert row["actor"] == "unverified:no-such-user" and row["actor_kind"] == "unverified"
    assert row["detail"] == "identity_unknown"
    r = console.client.post(
        "/gate/pause",
        json={"agent_id": "payments", "reason": "t"},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"
    row = _rows(console)[-1]
    assert row["outcome"] == "ok" and row["actor"] == "reviewer.an"
    assert row["actor_kind"] == "user" and row["auth_method"] == "dev_header"
    assert row["before_hash"] != row["after_hash"]


def test_gate_on_denies_a_viewer_and_allows_a_reviewer(
    console: Console, people: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "api_rbac_enabled", True)
    body = {"agent_id": "payments", "reason": "t"}
    r = console.client.post("/gate/pause", json=body, headers={"X-Dev-User": people["viewer"]})
    assert r.status_code == 403 and "error" in r.json()
    r = console.client.post("/v1/gate/pause", json=body, headers={"X-Dev-User": people["viewer"]})
    assert r.status_code in (403, 404)  # /v1/gate exists once W5 adds the aliases
    assert console.runtime.gateway.states.get_state("payments") != "PAUSED"
    r = console.client.post("/gate/pause", json=body, headers={"X-Dev-User": people["reviewer"]})
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"
    rows = _rows(console)
    assert rows[0]["outcome"] == "denied" and rows[0]["permission"] == "agent.pause"
    assert rows[-1]["outcome"] == "ok" and rows[-1]["actor"] == people["reviewer"]
    # reads: a viewer may read the gate, an unknown user gets a 400 (cannot be identified)
    ok = console.client.get("/gate/metrics", headers={"X-Dev-User": people["viewer"]})
    assert ok.status_code == 200


def test_gate_on_service_principal_cannot_control(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sp = AuthPrincipal("app-sp", "service_principal", "sp")
    monkeypatch.setattr(console.ctx.provider, "resolve", lambda h, c: (sp, None))
    r = console.client.post(
        "/gate/pause",
        json={"agent_id": "payments", "reason": "t"},
        headers={"X-Dev-User": "reviewer.an"},
    )
    assert r.status_code == 403 and "person" in r.json()["error"]
    assert console.client.get("/gate/metrics").status_code == 200


# ------------------------------------------------------------------ non-user principals


def test_service_principal_keeps_read_access_on_the_console(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sp = AuthPrincipal("app-sp", "service_principal", "sp")
    monkeypatch.setattr(console.ctx.provider, "resolve", lambda h, c: (sp, None))
    assert console.client.get("/console/").status_code == 200
    assert console.client.get("/console/agents").status_code == 200
    r = console.client.post(
        "/console/agents/payments/pause", data={}, headers={"HX-Request": "true"}
    )
    assert r.status_code == 403


# ------------------------------------------------------------------ audit pack


def test_audit_pack_carries_the_console_action_rows(console: Console, tmp_path: Any) -> None:
    import zipfile

    assert console.post("/console/agents/payments/pause", {"reason": "t"}).status_code == 200
    assert console.post("/console/agents/payments/quarantine", {"reason": "t"}).status_code == 403
    e = console.post("/console/export", {}, user="auditor.dung")
    assert e.status_code == 200, e.text
    zips = sorted(Path(console.ctx.settings.console_export_dir).glob("audit-pack-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        zf.extractall(tmp_path)
    root = tmp_path / zips[0].stem
    lines = (root / "console_action.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(x) for x in lines]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["console_actions"] == len(rows)
    rows = [r for r in rows if r["permission"].startswith("agent.")]  # + the export's own row
    assert "console_action.jsonl" in manifest["files_sha256"]
    assert [(r["permission"], r["outcome"]) for r in rows] == [
        ("agent.pause", "attempted"),
        ("agent.pause", "ok"),
        ("agent.quarantine", "denied"),
    ]
    assert rows[0]["request_id"] == rows[1]["request_id"]
    assert all(r["request_id"] and r["action_id"] for r in rows)
