"""WP-O3b: ``HttpAgentTarget``: allow list, https only, auth header, timeout, turn cap and time
budget, masking of replies, and what is recorded on a pack result. No network: the transport
calls a FastAPI stub in process (tests/assurance/http_stub.py), and ``no_network`` fails the test
if a socket is opened."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.assurance.engine import execute
from supervisor.assurance.loader import load_packs
from supervisor.assurance.model import RunContext
from supervisor.assurance.targets import (
    HttpAgentTarget,
    HttpTargetConfig,
    TargetError,
    TurnLimitError,
    check_http_url,
    http_target_config,
)
from supervisor.config import REPO_ROOT, load_settings
from tests.assurance.http_stub import asgi_transport, fake_auth, make_app

pytestmark = pytest.mark.usefixtures("no_network")

HOST = "kb.example.invalid"
ALLOWED = [HOST]
TOKEN = "FAKE-SP-TOKEN-0001"
T0 = datetime(2026, 10, 28, tzinfo=UTC)


def cfg(**kw: Any) -> HttpTargetConfig:
    base: dict[str, Any] = {
        "url": f"https://{HOST}",
        "path": "/chat",
        "message_field": "question",
        "session_field": "",
        "history_field": "history",
        "answer_field": "answer",
    }
    base.update(kw)
    return HttpTargetConfig(**base)


def target(calls: list[dict[str, Any]] | None = None, **kw: Any) -> HttpAgentTarget:
    transport = kw.pop("transport", None) or asgi_transport(
        kw.pop("app", None) or make_app(), calls
    )
    return HttpAgentTarget(
        "kb_chatbot",
        kw.pop("cfg", None) or cfg(),
        allowed_hosts=kw.pop("allowed", ALLOWED),
        auth_headers=kw.pop("auth", fake_auth),
        transport=transport,
        **kw,
    )


# ------------------------------------------------------------------------------ allow list


@pytest.mark.parametrize(
    "url",
    [
        f"http://{HOST}",  # not https
        "https://other.example.invalid",  # not on the list
        f"https://user:pw@{HOST}",  # user info
        f"https://{HOST}/?a=1",  # query
        f"https://{HOST}/#x",  # fragment
        f"https://{HOST}:8443",  # port
        "https://",  # no host
        "ftp://kb.example.invalid",
        f"https://evil-{HOST}",  # suffix trick
        f"https://{HOST}.evil.invalid",  # prefix trick
    ],
)
def test_the_url_rules_refuse(url: str) -> None:
    with pytest.raises(TargetError, match="refused"):
        check_http_url(url, ALLOWED)


def test_an_empty_allow_list_allows_nothing_and_a_wildcard_matches_subdomains_only() -> None:
    with pytest.raises(TargetError, match="ALLOWED_HOSTS is empty"):
        check_http_url(f"https://{HOST}", [])
    assert check_http_url("https://a-1.aws.databricksapps.com", ["*.databricksapps.com"])
    assert check_http_url(f"https://{HOST}:443/prefix", ALLOWED) == HOST  # host only
    with pytest.raises(TargetError):
        check_http_url("https://databricksapps.com", ["*.databricksapps.com"])


def test_the_target_refuses_a_host_that_is_not_allowed_at_construction() -> None:
    with pytest.raises(TargetError, match="not in PREDEPLOY_HTTP_ALLOWED_HOSTS"):
        target(cfg=cfg(url="https://other.example.invalid"))


def test_the_block_is_validated_and_limits_can_only_be_lowered() -> None:
    ok = http_target_config(
        {"url": f"https://{HOST}", "timeout_s": 5, "max_turns": 9999, "budget_s": 60},
        allowed_hosts=ALLOWED,
        max_timeout_s=30,
        max_turns=50,
        max_budget_s=600,
    )
    assert (ok.timeout_s, ok.max_turns, ok.budget_s) == (5, 50, 60)
    assert ok.path == "/chat" and ok.message_field == "message" and ok.session_field == "session_id"
    for bad in (
        {"url": f"https://{HOST}", "path": "/../x"},
        {"url": f"https://{HOST}", "path": "chat"},
        {"url": f"https://{HOST}", "message_field": "a b"},
        {"url": f"https://{HOST}", "message_field": ""},
        {"url": f"https://{HOST}", "timeout_s": 0},
        {"url": f"https://{HOST}", "timeout_s": True},
        {"url": f"https://{HOST}", "token": "x"},  # a stored token is not a key at all
        {"url": ""},
    ):
        with pytest.raises(TargetError, match="refused"):
            http_target_config(bad, allowed_hosts=ALLOWED)


# ------------------------------------------------------------------------------ one turn


def test_a_turn_sends_the_configured_shape_and_the_service_principal_header() -> None:
    calls: list[dict[str, Any]] = []
    t = target(calls)
    reply = t.respond("Chính sách nghỉ phép năm là gì?")
    assert reply.text and reply.is_mock is False and reply.tool_calls == []
    c = calls[0]
    assert c["url"] == f"https://{HOST}/chat"
    assert c["payload"] == {"question": "Chính sách nghỉ phép năm là gì?"}  # no session, no history
    assert c["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert c["timeout_s"] == 30.0


def test_session_field_and_history_follow_the_config() -> None:
    calls: list[dict[str, Any]] = []
    t = target(calls, cfg=cfg(session_field="session_id"))
    sid = t.new_session()
    t.send(sid, "câu một")
    t.send(sid, "câu hai")
    first, second = calls[0]["payload"], calls[1]["payload"]
    assert first["session_id"] == second["session_id"] == sid and "history" not in first
    assert [h["role"] for h in second["history"]] == ["user", "assistant"]
    other = t.respond("câu ba")  # respond() is a fresh session each time
    assert calls[2]["payload"]["session_id"] != sid and "history" not in calls[2]["payload"]
    assert other.text


def test_the_auth_header_is_never_logged_stored_or_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    transport = asgi_transport(make_app(), fail_with=RuntimeError(f"boom Bearer {TOKEN}"))
    t = target(transport=transport)
    with pytest.raises(TargetError) as exc:
        t.respond("câu hỏi")
    assert TOKEN not in str(exc.value) and "RuntimeError" in str(exc.value)
    ok = target()
    reply = ok.respond("câu hỏi")
    assert TOKEN not in reply.text and TOKEN not in repr(ok.result_details())
    assert TOKEN not in caplog.text and TOKEN not in repr(vars(ok).get("cfg"))

    # a failing auth source gives its class name only
    def broken() -> dict[str, str]:
        raise OSError(f"cannot read {TOKEN}")

    with pytest.raises(TargetError) as exc2:
        target(auth=broken).respond("x")
    assert TOKEN not in str(exc2.value) and "OSError" in str(exc2.value)


def test_a_refused_identity_and_a_bad_status_and_a_bad_body_are_target_errors() -> None:
    for status, body, text in (
        (401, {"detail": "no"}, "refused our identity"),
        (403, {"detail": "no"}, "refused our identity"),
        (500, {"detail": "x"}, "HTTP 500"),
        (200, ["not", "an", "object"], "not a JSON object"),
        (200, {"unrelated": 1}, "no answer text"),
        (200, None, "not a JSON object"),
    ):
        t = target(transport=asgi_transport(make_app(), status=status, raw_json=body))
        with pytest.raises(TargetError, match=text):
            t.respond("hỏi")


def test_a_timeout_is_a_target_error_with_the_limit_in_the_text() -> None:
    calls: list[dict[str, Any]] = []
    transport = asgi_transport(make_app(), calls, fail_with=TimeoutError("slow"))
    t = target(cfg=cfg(timeout_s=7), transport=transport)
    with pytest.raises(TargetError, match="more than 7 s"):
        t.respond("hỏi")
    assert calls[0]["timeout_s"] == 7.0


def test_the_default_transport_maps_httpx_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from supervisor.adapters import http_json

    def slow(*a: Any, **k: Any) -> Any:
        raise httpx.ReadTimeout("t", request=httpx.Request("POST", "https://x.invalid/chat"))

    monkeypatch.setattr(httpx, "post", slow)
    with pytest.raises(TimeoutError):
        http_json.post_json_status("https://x.invalid/chat", {}, 1.0, headers={})

    def dead(*a: Any, **k: Any) -> Any:
        raise httpx.ConnectError("secret-url-part", request=httpx.Request("POST", "https://x"))

    monkeypatch.setattr(httpx, "post", dead)
    with pytest.raises(ConnectionError) as exc:
        http_json.post_json_status("https://x.invalid/chat", {}, 1.0, headers={})
    assert "secret-url-part" not in str(exc.value)

    seen: dict[str, Any] = {}

    def fine(url: str, **k: Any) -> Any:
        seen.update(k)
        return httpx.Response(302, headers={"location": "https://other.invalid"})

    monkeypatch.setattr(httpx, "post", fine)
    status, data = http_json.post_json_status("https://x.invalid/chat", {}, 1.0, headers={})
    assert status == 302 and data is None and seen["follow_redirects"] is False


# ------------------------------------------------------------------------------ limits


def test_the_turn_cap_is_per_pack_and_a_new_pack_starts_a_new_count() -> None:
    t = target(cfg=cfg(max_turns=3))
    t.begin_pack("a")
    for i in range(3):
        t.respond(f"hỏi {i}")
    assert t.turns == 3 and t.turns_left() == 0
    with pytest.raises(TurnLimitError, match="turn cap 3 reached"):
        t.respond("hỏi 4")
    assert t.turns == 3  # the refused turn was not sent
    t.begin_pack("b")
    t.respond("hỏi 5")
    assert t.turns == 1 and t.total_turns == 4


def test_the_total_time_budget_stops_the_target() -> None:
    now = {"t": 0.0}
    t = target(cfg=cfg(budget_s=10), monotonic=lambda: now["t"])
    t.respond("một")
    now["t"] = 11.0
    with pytest.raises(TurnLimitError, match="time budget 10 s"):
        t.respond("hai")


# ------------------------------------------------------------------------------ masking


def test_replies_are_masked_but_a_value_the_pack_sent_is_kept() -> None:
    canary = "079201001234"  # a synthetic CCCD, planted by the pack
    other = "079201009999"  # a value the candidate made up or fetched
    masker = VnRegexMasker(b"test-key", "test")

    def talk(question: str, history: Any) -> str:
        return f"Số CCCD {canary} và {other}. Liên hệ 0912345678."

    t = target(app=make_app(answer=talk), masker=masker)
    reply = t.respond(f"Khách có CCCD {canary}, hãy nhắc lại.")
    assert canary in reply.text  # the pack reads its own canary back
    assert other not in reply.text and "0912345678" not in reply.text
    assert "<CCCD:" in reply.text or "<CMND:" in reply.text or "<PHONE:" in reply.text
    # without the pack sending it, even the same value is masked
    again = t.respond("Hãy nhắc lại số căn cước.")
    assert canary not in again.text


def test_secrets_in_a_reply_are_scrubbed_too() -> None:
    key = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at run time: the repo secret scan stays quiet
    t = target(app=make_app(answer=lambda q, h: f"khóa {key}"), masker=VnRegexMasker(b"k", "t"))
    assert key not in t.respond("hỏi").text


# ------------------------------------------------------------------------------ results


def test_a_pack_result_records_target_kind_host_and_turn_count() -> None:
    packs = {p.id: p for p in load_packs()}
    assert target(cfg=cfg(url=f"https://{HOST}/some/prefix")).host == HOST  # host only
    t = target(cfg=cfg(max_turns=100))
    ctx = RunContext(target=t, repo_root=REPO_ROOT, data_root=None, max_items=60)
    t.begin_pack("finance_harm_refusal")
    results = execute([packs["finance_harm_refusal"]], t, ctx, "run-test", FixedClock(T0))
    assert len(results) == 1
    r = results[0]
    assert r.target_kind == "agent"  # the pack kind; the transport is in details
    assert r.details["target_kind"] == "http" and r.details["target_host"] == HOST
    assert r.details["turns"] == t.turns and t.turns > 0
    assert r.is_mock is False
    assert "/" not in r.details["target_host"] and "?" not in str(r.details)


def test_the_multiturn_pack_runs_in_text_mode_and_keeps_no_reply_text(tmp_path: Path) -> None:
    packs = {p.id: p for p in load_packs()}
    pack = packs["multiturn_redteam_vi"]
    t = target(cfg=cfg(max_turns=200, session_field="session_id"))
    ctx = RunContext(
        target=t, repo_root=REPO_ROOT, data_root=None, extras={"out_dir": str(tmp_path)}
    )
    t.begin_pack(pack.id)
    (r,) = execute([pack], t, ctx, "run-test", FixedClock(T0))
    assert r.status in ("ok", "warn", "fail"), r.reasons
    assert r.is_mock is False and r.details["mode"] == "text_only_http"
    assert r.details["target_kind"] == "http" and r.details["turns"] > 0
    assert r.metrics["text_leak_count"] == 0 and r.metrics["unexpected_escape_count"] == 0
    assert r.metrics["text_attack_success_bp"] == 0  # the stub refuses attack-like turns
    assert r.metrics["gate_catch_bp"] is None  # the sandbox oracle did not run
    assert "Tôi không thể" not in str(r.details)  # no reply text in the details


# ------------------------------------------------------------------------------ settings


def test_settings_default_off_and_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings(sql_backend="sqlite")
    assert s.predeploy_http_target is False and s.predeploy_http_allowed_hosts == ""
    assert (s.predeploy_http_timeout_s, s.predeploy_http_max_turns, s.predeploy_http_budget_s) == (
        30,
        300,
        600,
    )
    monkeypatch.setenv("PREDEPLOY_HTTP_TARGET", "1")
    monkeypatch.setenv("PREDEPLOY_HTTP_ALLOWED_HOSTS", "a.example.invalid, *.b.example.invalid")
    s2 = load_settings(sql_backend="sqlite")
    assert s2.predeploy_http_target is True
    assert "a.example.invalid" in s2.predeploy_http_allowed_hosts


def test_app_yaml_has_the_commented_lines_and_no_active_one() -> None:
    text = (REPO_ROOT / "app.yaml").read_text(encoding="utf-8")
    for name in ("PREDEPLOY_HTTP_TARGET", "PREDEPLOY_HTTP_ALLOWED_HOSTS"):
        assert f"# - name: {name}" in text
        assert f"\n  - name: {name}" not in text
