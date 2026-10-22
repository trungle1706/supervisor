"""WP-D1: the collectors pass file attachments as context.documents, only when the flag is on."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from supervisor.gateway.adapters import attachments
from supervisor.gateway.adapters.common import GateClient
from supervisor.gateway.adapters.fastapi_mw import SupervisorASGIMiddleware
from supervisor.gateway.sdk import supervised_tool
from tests.collectors.fakes import ALLOW, FakeGate
from tests.collectors.test_fastapi_mw import App, call
from tests.collectors.test_langgraph import Tool, mw, req


@pytest.fixture(autouse=True)
def reset_flag() -> Iterator[None]:
    attachments.set_document_intake(None)
    yield
    attachments.set_document_intake(None)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@dataclass
class Human:
    content: Any
    type: str = "human"


def with_state(messages: list[Any]) -> Any:
    r = req()
    r.state = {"messages": messages}
    return r


FILE_BLOCK = {
    "type": "file",
    "base64": b64(b"%PDF-1.4 x"),
    "mime_type": "application/pdf",
    "filename": "hd.pdf",
}
MESSAGES = [Human([{"type": "text", "text": "Doc giup toi"}, FILE_BLOCK])]


# ---------------------------------------------------------------------------- the switch


def test_the_switch_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCUMENT_INTAKE_ENABLED", raising=False)
    assert attachments.intake_on() is False
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("DOCUMENT_INTAKE_ENABLED", value)
        assert attachments.intake_on() is True
    monkeypatch.setenv("DOCUMENT_INTAKE_ENABLED", "0")
    assert attachments.intake_on() is False
    attachments.set_document_intake(True)
    assert attachments.intake_on() is True


def test_to_documents_forms_and_limits(tmp_path: Path) -> None:
    f = tmp_path / "hd.txt"
    f.write_text("xin chao", encoding="utf-8")
    docs = attachments.to_documents(
        [
            {"name": "a", "text": "t"},
            b"raw",
            ("b.pdf", b"%PDF"),
            f,
            {"text": "t", "url": "https://x.example/"},  # two sources: skipped
            42,
        ]
    )
    assert [sorted(d) for d in docs] == [
        ["name", "text"],
        ["bytes_b64"],
        ["bytes_b64", "media_type", "name"],
        ["bytes_b64", "media_type", "name"],
    ]
    assert docs[2]["media_type"] == "application/pdf" and docs[3]["media_type"] == "text/plain"
    assert base64.b64decode(docs[3]["bytes_b64"]) == b"xin chao"
    many = attachments.to_documents([b"x"] * 30)
    assert len(many) == 11  # one over the limit, so the gate can say so
    big = attachments.to_documents([b"a" * (3 * 1024 * 1024)])
    assert len(base64.b64decode(big[0]["bytes_b64"])) == 2 * 1024 * 1024 + 1
    assert attachments.to_documents(None) == [] and attachments.to_documents("x") == []


# ---------------------------------------------------------------------------- GateClient


def test_the_client_sends_documents_only_with_the_switch_on() -> None:
    gate = FakeGate(ALLOW)
    client = GateClient(gate, "a", "1")
    client.check("t", {}, documents=[{"text": "hi"}])
    assert "documents" not in gate.calls[0]["context"]
    attachments.set_document_intake(True)
    client.check("t", {}, documents=[{"text": "hi"}])
    assert gate.calls[1]["context"]["documents"] == [{"text": "hi"}]
    client.check("t", {}, direction="output", context={"output": "x"}, documents=[{"text": "hi"}])
    assert "documents" not in gate.calls[2]["context"]  # an output check carries no document
    client.check("t", {})
    assert "documents" not in gate.calls[3]["context"]


# ---------------------------------------------------------------------------- SDK


def test_sdk_decorator_sends_the_attachment_argument_as_documents() -> None:
    gate = FakeGate(ALLOW)

    @supervised_tool("a", "1", "summarise", "read_only", gate=gate, documents_arg="files")
    def summarise(question: str, files: list[Any] | None = None) -> str:
        return question

    assert summarise("q", files=[b"%PDF-1.4"]) == "q"
    off = gate.calls[0]
    assert off["args"] == {"question": "q", "files": [b"%PDF-1.4"]}  # the flag off: as before
    assert "documents" not in off["context"]
    attachments.set_document_intake(True)
    summarise("q", files=[("hd.pdf", b"%PDF-1.4")])
    on = gate.calls[1]
    assert on["args"] == {"question": "q"}  # the bytes are not in args
    assert on["context"]["documents"][0]["name"] == "hd.pdf"
    assert on["context"]["declared_risk_class"] == "read_only"


def test_sdk_decorator_without_documents_arg_is_unchanged() -> None:
    gate = FakeGate(ALLOW)
    attachments.set_document_intake(True)

    @supervised_tool("a", "1", "t", "read_only", gate=gate)
    def t(x: int) -> int:
        return x

    t(1)
    assert gate.calls[0]["context"] == {"declared_risk_class": "read_only"}


# ---------------------------------------------------------------------------- LangGraph


def test_langgraph_sends_the_newest_human_attachments() -> None:
    gate = FakeGate(ALLOW)
    attachments.set_document_intake(True)
    mw(gate).wrap_tool_call(with_state(MESSAGES), Tool())
    docs = gate.calls[0]["context"]["documents"]
    assert docs == [
        {"name": "hd.pdf", "media_type": "application/pdf", "bytes_b64": FILE_BLOCK["base64"]}
    ]
    assert "documents" not in gate.calls[1]["context"]  # the output check


def test_langgraph_sends_nothing_with_the_switch_off_or_the_option_off() -> None:
    gate = FakeGate(ALLOW)
    mw(gate).wrap_tool_call(with_state(MESSAGES), Tool())
    assert "documents" not in gate.calls[0]["context"]
    attachments.set_document_intake(True)
    gate2 = FakeGate(ALLOW)
    mw(gate2, send_documents=False).wrap_tool_call(with_state(MESSAGES), Tool())
    assert "documents" not in gate2.calls[0]["context"]


def test_langgraph_block_shapes_and_a_getter() -> None:
    attachments.set_document_intake(True)
    anthropic = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": b64(b"%PDF")},
    }
    data_url = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + b64(b"\x89PNG")},
    }
    remote = {"type": "image_url", "image_url": {"url": "https://img.example.com/a.png"}}
    docs = attachments.documents_from_message(
        Human([anthropic, data_url, remote, {"type": "text", "text": "x"}])
    )
    assert [sorted(d) for d in docs] == [
        ["bytes_b64", "media_type"],
        ["bytes_b64", "media_type"],
        ["url"],
    ]
    gate = FakeGate(ALLOW)
    mw(gate, documents_getter=lambda request: [b"abc"]).wrap_tool_call(req(), Tool())
    assert gate.calls[0]["context"]["documents"] == [{"bytes_b64": b64(b"abc")}]

    def broken(request: Any) -> Any:
        raise RuntimeError("boom")

    gate = FakeGate(ALLOW)
    mw(gate, documents_getter=broken).wrap_tool_call(req(), Tool())
    assert "documents" not in gate.calls[0]["context"]  # a failing getter means no documents


# ---------------------------------------------------------------------------- FastAPI middleware

BOUNDARY = "XBOUNDARY"
MULTIPART = (
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="question"\r\n\r\n'
    "Tom tat ho so\r\n"
    f"--{BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="file"; filename="cv.txt"\r\n'
    "Content-Type: text/plain\r\n\r\n"
    "Nguyen Van An 001203004567\r\n"
    f"--{BOUNDARY}--\r\n"
).encode()
HEADERS = [(b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode())]


def test_asgi_multipart_files_become_documents_with_the_switch_on() -> None:
    gate = FakeGate(ALLOW)
    app = App()
    attachments.set_document_intake(True)
    mw_ = SupervisorASGIMiddleware(
        app, gate=gate, agent_id="a", agent_version="1", check_output=False
    )
    status, _, _ = call(mw_, MULTIPART, HEADERS)
    assert status == 200
    c = gate.calls[0]
    assert c["args"]["form"] == {"question": "Tom tat ho so"}
    assert "body" not in c["args"] and "text" not in c["args"]
    (doc,) = c["context"]["documents"]
    assert doc["name"] == "cv.txt" and doc["media_type"] == "text/plain"
    assert base64.b64decode(doc["bytes_b64"]) == b"Nguyen Van An 001203004567"
    assert app.bodies == [MULTIPART]  # the app still gets the original upload


def test_asgi_multipart_is_as_before_with_the_switch_off() -> None:
    gate = FakeGate(ALLOW)
    mw_ = SupervisorASGIMiddleware(
        App(), gate=gate, agent_id="a", agent_version="1", check_output=False
    )
    call(mw_, MULTIPART, HEADERS)
    c = gate.calls[0]
    assert "documents" not in c["context"] and "text" in c["args"] and "form" not in c["args"]


def test_asgi_json_request_is_unchanged_with_the_switch_on() -> None:
    gate = FakeGate(ALLOW)
    attachments.set_document_intake(True)
    mw_ = SupervisorASGIMiddleware(
        App(), gate=gate, agent_id="a", agent_version="1", check_output=False
    )
    call(mw_, b'{"q": "hi"}')
    assert gate.calls[0]["args"]["body"] == {"q": "hi"}
    assert "documents" not in gate.calls[0]["context"]
