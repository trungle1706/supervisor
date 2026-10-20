"""WP21: the webhook notifier really sends (flag + URL), with retry, idempotency and a dead-letter
file; pager and ITSM stay stubs behind the same Notifier interface."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.integrations import IntegrationError
from supervisor.adapters.integrations.deadletter import DeadLetter
from supervisor.adapters.notify import (
    FanoutNotifier,
    InboxNotifier,
    StubNotifier,
    WebhookNotifier,
    WebhookNotifierStub,
    build_notifier,
    webhook_dead_letter_path,
)
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


class Hook:
    def __init__(self, fail: int = 0) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls.append(payload)
        if self.fail:
            self.fail -= 1
            raise ConnectionError("down")
        return {}


def test_off_by_default_and_url_required() -> None:
    s = load_settings()
    assert s.notify_webhook_enabled is False
    inbox = None
    with pytest.raises(IntegrationError, match="FILL-ME"):
        WebhookNotifier(inbox, "FILL-ME-url")  # type: ignore[arg-type]
    with pytest.raises(IntegrationError):
        WebhookNotifier(inbox, "  ")  # type: ignore[arg-type]


def test_flag_and_url_build_the_real_notifier_flag_alone_builds_the_stub(
    adapters: Adapters,
) -> None:
    def mk(**kw):
        return build_notifier(
            adapters.settings.model_copy(update={"notify_webhook_enabled": True, **kw}),
            adapters.state,
            adapters.clock,
        )[0].targets

    assert any(isinstance(t, WebhookNotifier) for t in mk(notify_webhook_url="https://h.invalid/x"))
    assert any(isinstance(t, WebhookNotifierStub) for t in mk(notify_webhook_url=""))
    off = build_notifier(adapters.settings, adapters.state, adapters.clock)[0].targets
    assert not any(isinstance(t, (WebhookNotifier, WebhookNotifierStub)) for t in off)
    assert webhook_dead_letter_path(adapters.settings) == (
        adapters.settings.data_dir / "notify" / "webhook.dead.jsonl"
    )


def test_notice_is_sent_with_idempotency_key_and_status(adapters: Adapters) -> None:
    inbox = InboxNotifier(adapters.state, adapters.clock)
    hook = Hook()
    n = WebhookNotifier(inbox, "https://h.invalid/x", transport=hook, sleep=lambda _s: None)
    n.notify("reviewers", "New case", "case C1 opened")
    assert hook.calls == []  # notify only queues: no network on a request path
    assert inbox.list(channel="webhook:reviewers")[0]["status"] == "queued"
    assert n.drain() == {"sent": 1, "dead_letter": 0}
    assert n.drain() == {"sent": 0, "dead_letter": 0}  # nothing is sent twice
    assert len(hook.calls) == 1
    body = hook.calls[0]
    assert body["kind"] == "notice" and body["channel"] == "reviewers"
    assert body["subject"] == "New case" and body["body"] == "case C1 opened"
    row = inbox.list(channel="webhook:reviewers")[0]
    assert body["idempotency_key"] == body["notice_id"] == row["notice_id"]
    assert row["status"] == "sent" and n.sent == 1


def test_retry_with_backoff_then_dead_letter_and_replay(adapters: Adapters, tmp_path: Path) -> None:
    inbox = InboxNotifier(adapters.state, adapters.clock)
    slept: list[float] = []
    dl = DeadLetter(tmp_path / "dead.jsonl")
    hook = Hook(fail=3)  # all three attempts fail
    n = WebhookNotifier(
        inbox, "https://h.invalid/x", transport=hook, dead_letter=dl, sleep=slept.append
    )
    n.notify("reviewers", "s", "b")  # must not raise
    assert hook.calls == []
    assert n.drain() == {"sent": 0, "dead_letter": 1}  # must not raise
    assert len(hook.calls) == 3 and slept == [1.0, 2.0] and n.dead_lettered == 1
    assert inbox.list(channel="webhook:reviewers")[0]["status"] == "dead_letter"
    [entry] = dl.entries()
    assert entry["kind"] == "webhook" and entry["attempts"] == 3
    key = entry["key"]
    assert entry["payload"]["idempotency_key"] == key
    # later the receiver is back: replay sends the same key and empties the file
    assert n.replay_dead_letter() == (1, 0)
    assert hook.calls[-1]["idempotency_key"] == key and dl.count() == 0


def test_succeeds_on_the_second_try_without_a_dead_letter(
    adapters: Adapters, tmp_path: Path
) -> None:
    inbox = InboxNotifier(adapters.state, adapters.clock)
    dl = DeadLetter(tmp_path / "dead.jsonl")
    hook = Hook(fail=1)
    n = WebhookNotifier(
        inbox, "https://h.invalid/x", transport=hook, dead_letter=dl, sleep=lambda _s: None
    )
    n.notify("c", "s", "b")
    n.drain()
    assert len(hook.calls) == 2 and dl.count() == 0
    assert inbox.list(channel="webhook:c")[0]["status"] == "sent"


def test_a_dead_webhook_never_breaks_the_fanout(adapters: Adapters) -> None:
    inbox = InboxNotifier(adapters.state, adapters.clock)
    n = WebhookNotifier(
        inbox, "https://h.invalid/x", transport=Hook(fail=99), sleep=lambda _s: None
    )
    fan = FanoutNotifier([inbox, n])
    fan.notify("reviewers", "s", "b")
    assert [x["channel"] for x in inbox.list()] == ["webhook:reviewers", "reviewers"] or {
        x["channel"] for x in inbox.list()
    } == {"reviewers", "webhook:reviewers"}


def test_text_is_masked_like_the_inbox(adapters: Adapters) -> None:
    from supervisor.adapters.factory import make_masker

    inbox = InboxNotifier(adapters.state, adapters.clock, make_masker(adapters.settings))
    hook = Hook()
    n = WebhookNotifier(inbox, "https://h.invalid/x", transport=hook, sleep=lambda _s: None)
    n.notify("c", "s", "khach hang so dien thoai 0912345678")
    n.drain()
    assert "0912345678" not in hook.calls[0]["body"]


def test_pager_and_itsm_stubs_share_the_interface_and_never_send(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "create_connection", refuse)
    inbox = InboxNotifier(adapters.state, adapters.clock)
    for kind in ("pager", "itsm"):
        stub = StubNotifier(kind, inbox)
        assert callable(stub.notify) and stub.kind == kind
        stub.notify("alert", f"{kind} subject", "body")
    assert sorted(n["channel"] for n in inbox.list(status="queued")) == [
        "itsm:alert",
        "pager:alert",
    ]
    with pytest.raises(ValueError):
        StubNotifier("sms", inbox)


def test_token_comes_from_settings_and_stays_secret(adapters: Adapters) -> None:
    on = adapters.settings.model_copy(
        update={
            "notify_webhook_enabled": True,
            "notify_webhook_url": "https://h.invalid/x",
            "notify_webhook_token": SecretStr("tok-123"),
        }
    )
    targets = build_notifier(on, adapters.state, adapters.clock)[0].targets
    hook = next(t for t in targets if isinstance(t, WebhookNotifier))
    assert "tok-123" not in repr(hook.transport) and "tok-123" not in repr(on)
    assert hook.transport._token == "tok-123"  # noqa: SLF001


def test_a_dead_hook_costs_a_request_nothing(adapters: Adapters) -> None:
    """F9: the request path only queues. A hook that hangs 5 s per call is not touched."""
    import time

    inbox = InboxNotifier(adapters.state, adapters.clock)

    def hangs(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        time.sleep(5)
        raise ConnectionError("down")

    n = WebhookNotifier(inbox, "https://h.invalid/x", transport=hangs)
    fan = FanoutNotifier([inbox, n])
    t0 = time.perf_counter()
    for i in range(5):
        fan.notify("reviewers", f"s{i}", "b")
    assert time.perf_counter() - t0 < 1.0
    assert len(inbox.list(status="queued")) == 5
