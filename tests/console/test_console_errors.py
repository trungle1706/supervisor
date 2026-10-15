"""WP8: every user-facing failure answers HTTP 400 with a message partial htmx can show.

htmx drops 5xx responses (bank guide 0, rule 10), so none of these may be a 500.
"""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import Console


def _case(console: Console, rule: str = "PAY-07") -> dict[str, Any]:
    console.get("/console/")  # intake
    return next(c for c in console.ctx.cases.list_cases() if rule in c["summary"])


def _assert_400(r: Any, needle: str, status: int = 400) -> None:
    assert r.status_code == status, (r.status_code, r.text)
    assert "msg-error" in r.text and needle in r.text, r.text
    assert "<html" not in r.text  # a partial for #flash, not a page


def test_bad_transition(console: Console) -> None:
    c = _case(console)
    r = console.post(
        f"/console/cases/{c['case_id']}/transition",
        {"to": "contained", "note": "x", "row_version": c["row_version"]},
    )
    _assert_400(r, "cannot move to contained")
    r = console.post(f"/console/cases/{c['case_id']}/transition", {"to": "bogus", "row_version": 1})
    _assert_400(r, "unknown target state")


def test_missing_role(console: Console) -> None:
    c = _case(console)
    r = console.post(
        f"/console/cases/{c['case_id']}/assign",
        {"assignee": "reviewer.an", "row_version": c["row_version"]},
        user="auditor.dung",
    )
    _assert_400(r, "needs role", 403)  # WP18: a missing role is 403, not 400
    r = console.post("/console/agents/payments/quarantine", {"reason": "x"}, user="reviewer.an")
    _assert_400(r, "needs role admin", 403)


def test_second_approver_equals_first(console: Console) -> None:
    c = _case(console)
    svc, an = console.ctx.cases, console.ctx.provider.known_users()
    rev = next(u for u in an if u.user_id == "reviewer.an")
    c = svc.transition(c["case_id"], "triaged", rev, c["row_version"], assignee="reviewer.an")
    c = svc.transition(c["case_id"], "contained", rev, c["row_version"], note="paused")
    ok = console.post(
        f"/console/cases/{c['case_id']}/signoff",
        {
            "decision": "approve",
            "reason": "first",
            "affirm": "yes",
            "row_version": c["row_version"],
        },
    )
    assert ok.status_code == 200, ok.text
    c = svc.get(c["case_id"])
    r = console.post(
        f"/console/cases/{c['case_id']}/signoff",
        {
            "decision": "approve",
            "reason": "again",
            "affirm": "yes",
            "row_version": c["row_version"],
        },
    )
    _assert_400(r, "different person")
    r = console.post(
        f"/console/cases/{c['case_id']}/signoff",
        {"decision": "approve", "reason": "no box", "row_version": c["row_version"]},
        user="approver.em",
    )
    _assert_400(r, "tick the box")


def test_stale_row_version(console: Console) -> None:
    c = _case(console)
    url = f"/console/cases/{c['case_id']}/comment"
    assert console.post(url, {"text": "one", "row_version": c["row_version"]}).status_code == 200
    _assert_400(console.post(url, {"text": "two", "row_version": c["row_version"]}), "reload")
    _assert_400(console.post(url, {"text": "three"}), "row_version is missing")


def test_reviewer_cannot_resume_alone(console: Console) -> None:
    assert console.post("/console/agents/payments/pause", {"reason": "x"}).status_code == 200
    first = console.post("/console/agents/payments/resume", {"reason": "ok"})
    assert first.status_code == 200 and "needs the owner" in first.text
    _assert_400(
        console.post("/console/agents/payments/resume", {"reason": "ok"}), "already approved"
    )
    _assert_400(
        console.post("/console/agents/payments/resume", {"reason": "ok"}, user="auditor.dung"),
        "needs role",
        403,
    )


@pytest.mark.parametrize(
    ("method", "url", "kw", "needle"),
    [
        ("get", "/console/cases/CASE-NOPE", {}, "does not exist"),
        ("get", "/console/cases/bad%20id", {}, "invalid case id"),
        ("get", "/console/queue/rows?severity=extreme", {}, "unknown severity"),
        ("post", "/console/agents/payments/explode", {}, "unknown agent action"),
        ("post", "/console/agents/nobody/pause", {}, "unknown agent"),
        ("get", "/console/exports/../../etc.zip", {}, ""),
        ("get", "/console/exports/audit-pack-20990101T000000Z-abcdef.zip", {}, "does not exist"),
        ("post", "/console/dev/user", {"data": {"user": "mallory"}}, "unknown dev user"),
    ],
)
def test_other_user_errors_are_400(
    console: Console, method: str, url: str, kw: dict[str, Any], needle: str
) -> None:
    if method == "get":
        r = console.get(url, headers={"HX-Request": "true"})
    else:
        r = console.post(url, kw.get("data", {}))
    assert r.status_code in (400, 404), r.text
    if r.status_code == 400:
        assert "msg-error" in r.text and needle in r.text


def test_unknown_user_and_missing_htmx_header(console: Console) -> None:
    r = console.get("/console/", user="mallory")
    assert r.status_code == 400 and "unknown dev user" in r.text and "<html" in r.text
    c = _case(console)
    r = console.post(
        f"/console/cases/{c['case_id']}/comment",
        {"text": "csrf", "row_version": c["row_version"]},
        htmx=False,
    )
    assert r.status_code == 400 and "htmx" in r.text


def test_programmer_error_is_not_a_500(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(console.ctx.cases, "list_cases", boom)
    r = console.get("/console/queue/rows", headers={"HX-Request": "true"})
    assert r.status_code == 400 and "unexpected error: RuntimeError" in r.text


def test_case_file_error_is_404(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.evidence.casefile.builder import CaseFileError

    def missing(*_a: Any, **_k: Any) -> None:
        raise CaseFileError("case not found: C-404")

    monkeypatch.setattr(console.ctx.cases, "list_cases", missing)
    r = console.get("/console/queue/rows", headers={"HX-Request": "true"})
    assert r.status_code == 404 and "case not found: C-404" in r.text


def test_unexpected_error_logs_request_id_and_class(
    console: Console, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(console.ctx.cases, "list_cases", boom)
    with caplog.at_level("ERROR", logger="supervisor.app"):
        console.get("/console/queue/rows", headers={"HX-Request": "true"})
    recs = [r for r in caplog.records if r.name == "supervisor.app" and r.levelname == "ERROR"]
    assert recs and "RuntimeError" in recs[0].getMessage()
    assert "request_id=" in recs[0].getMessage() and "request_id=None" not in recs[0].getMessage()
    assert recs[0].exc_info is not None


@pytest.mark.parametrize(
    ("raw", "ok"), [("7", True), ("٣", False), ("1" * 12, False), ("1" * 11, True), ("", False)]
)
def test_version_helper(raw: str, ok: bool) -> None:
    from supervisor.console.routes import ConsoleInputError, _version

    if ok:
        assert _version({"row_version": raw}) == int(raw)
    else:
        with pytest.raises(ConsoleInputError):
            _version({"row_version": raw})
