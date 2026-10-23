"""WP-P4: the Playground dry run carries the forwarded user token; the gate check pool does not."""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

import httpx
import pytest

from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.user_token import current_forwarded_token, forwarded_token
from supervisor.gateway.engine import Gateway
from tests.databricks.test_user_token_forward import (
    MSGS,
    SCHEMA,
    SP_TOKEN,
    USER_TOKEN,
    _judge_chat,
)


def _bare_gateway(judge: Any) -> Gateway:
    gw = Gateway.__new__(Gateway)
    gw.timeout_s = 5.0
    gw._dry_pool = cf.ThreadPoolExecutor(max_workers=1)
    gw._pool = cf.ThreadPoolExecutor(max_workers=1)
    gw._req = lambda *a, **k: None  # type: ignore[method-assign]
    gw._dry = lambda *a: {"dry_run": True, "out": judge()}  # type: ignore[method-assign]
    return gw


def test_dry_run_judge_uses_forwarded_token_and_check_pool_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["authorization"])
        return httpx.Response(200, json={"output_text": '{"a": 1}'})

    chat = _judge_chat(monkeypatch, handler)
    gw = _bare_gateway(lambda: chat.complete_json(MSGS, SCHEMA))

    with forwarded_token(UserToken(USER_TOKEN)):
        out = gw.evaluate_only("a", "1", "t", {})
        assert out["out"] == {"a": 1}
        # the gate check path (_pool) does not copy the context: service principal
        gw._pool.submit(lambda: chat.complete_json(MSGS, SCHEMA)).result()
        assert gw._pool.submit(current_forwarded_token).result() is None
    assert seen == [f"Bearer {USER_TOKEN}", f"Bearer {SP_TOKEN}"]
