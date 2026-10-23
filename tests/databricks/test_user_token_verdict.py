"""WP-P4: verdict label and gate independence for the forwarded-token judge path."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from supervisor.adapters.auth.base import UserToken
from supervisor.adapters.auth.user_token import forwarded_token
from supervisor.adapters.clock import FixedClock
from supervisor.config import load_settings
from supervisor.judge.router import JudgeRouter
from supervisor.judge.service import JudgeService
from tests.databricks.test_user_token_forward import USER_TOKEN, _judge_chat
from tests.judge.conftest import T0, MemoryEvidence, make_events
from tests.judge.test_service import chat as mock_chat


def test_judge_403_is_unavailable_advisory_and_labelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 on the judge path gives a judge_unavailable verdict labelled user_forwarded;
    the verdict stays advisory and nothing in the call path can touch the gate."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    real = _judge_chat(monkeypatch, handler)
    s = load_settings(judge_t2_sample_bp=0)
    router = JudgeRouter.from_settings(s, chats={"t1": real, "t2": mock_chat(2, "t2")})
    ev = MemoryEvidence()
    svc = JudgeService(router, FixedClock(T0), evidence=ev, max_retries=0)
    with forwarded_token(UserToken(USER_TOKEN)):
        out = svc.evaluate_trace(make_events(["Xem so du"]))
    assert out.t1.label == "judge_unavailable" and out.t1.status == "unavailable"
    assert out.t1.auth == "user_forwarded"
    first = ev.of_type("judge_verdict")[0]
    assert first["auth"] == "user_forwarded" and first["advisory"] is True
    assert USER_TOKEN not in repr(ev.entries)
    assert first["action"] not in ("block", "pause")


def test_verdict_has_no_auth_field_without_forwarding() -> None:
    router = JudgeRouter.from_settings(
        load_settings(judge_t2_sample_bp=0),
        chats={"t1": mock_chat(1, "t1"), "t2": mock_chat(2, "t2")},
    )
    ev = MemoryEvidence()
    JudgeService(router, FixedClock(T0), evidence=ev).evaluate_trace(make_events(["Xem"]))
    assert "auth" not in ev.of_type("judge_verdict")[0]


def test_gate_does_not_depend_on_judge_or_user_token() -> None:
    """The gate decision path never imports the judge, the serving client or the carrier,
    so a judge 403 cannot change a gate decision."""
    banned = ("supervisor.judge", "supervisor.databricks.serving", "user_token")
    root = Path(__file__).resolve().parents[2] / "src" / "supervisor" / "gateway"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert not any(b in n for b in banned), f"{path.name} imports {n}"
