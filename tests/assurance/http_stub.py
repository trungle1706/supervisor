"""WP-O3b: a small FastAPI stub candidate and a TestClient-backed transport for the HTTP target.

The stub has the request and reply shape of the kb-chatbot of the testbed (``question`` and
``history`` in, ``answer``, ``sources`` and ``tool_calls`` out) and answers like a careful
assistant: it refuses attack-like requests, never repeats a value from the request and answers
other questions with a short, fixed policy sentence. No network is used: the transport calls the
ASGI app in process, so a test that also uses the ``no_network`` fixture proves it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

ATTACK = re.compile(
    r"(bỏ qua|ignore|system prompt|chỉ thị|hệ thống|chuyển|rút|xóa|vô hiệu|duyệt|miễn|"
    r"cccd|căn cước|số điện thoại|mật khẩu|nhắc lại|tài liệu đính kèm|tool|api)",
    re.IGNORECASE,
)
REFUSAL = "Tôi không thể thực hiện yêu cầu này. Tôi chỉ trả lời câu hỏi về chính sách nội bộ."
POLICY = "Theo chính sách nội bộ, vui lòng xem mục liên quan trong tài liệu chính sách."


class Turn(BaseModel):
    role: str
    text: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=6000)
    history: list[Turn] = Field(default_factory=list, max_length=12)


def make_app(
    seen: list[dict[str, Any]] | None = None,
    *,
    answer: Callable[[str, list[Turn]], str] | None = None,
) -> FastAPI:
    """The stub. ``seen`` collects ``{path, headers, body}`` of every request."""
    app = FastAPI(title="Stub KB chatbot (synthetic)")

    @app.post("/chat")
    async def chat(req: ChatRequest, request: Request) -> dict[str, Any]:
        if seen is not None:
            seen.append(
                {
                    "headers": dict(request.headers),
                    "question": req.question,
                    "n_hist": len(req.history),
                }
            )
        if answer is not None:
            text = answer(req.question, req.history)
        elif ATTACK.search(req.question):
            text = REFUSAL
        else:
            text = POLICY
        return {"answer": text, "sources": [], "tool_calls": []}

    return app


def asgi_transport(
    app: FastAPI,
    calls: list[dict[str, Any]] | None = None,
    *,
    fail_with: Exception | None = None,
    status: int | None = None,
    raw_json: Any = None,
) -> Callable[[str, dict[str, Any], float, Mapping[str, str]], tuple[int, Any]]:
    """A transport for ``HttpAgentTarget`` that calls ``app`` in process (no socket)."""
    client = TestClient(app)

    def transport(
        url: str, payload: dict[str, Any], timeout_s: float, headers: Mapping[str, str]
    ) -> tuple[int, Any]:
        if calls is not None:
            calls.append(
                {"url": url, "payload": payload, "timeout_s": timeout_s, "headers": dict(headers)}
            )
        if fail_with is not None:
            raise fail_with
        if status is not None:
            return status, raw_json
        path = urlsplit(url).path
        r = client.post(path, json=payload, headers=dict(headers))
        return r.status_code, (r.json() if r.content else None)

    return transport


def fake_auth() -> Mapping[str, str]:
    """A header like the SDK's ``authenticate()`` returns. The value is not a real token."""
    return {"Authorization": "Bearer FAKE-SP-TOKEN-0001"}
