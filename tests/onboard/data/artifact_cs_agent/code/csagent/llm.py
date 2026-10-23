"""Chat model factory.

LLM_TOOL_MODE=native  : ChatOpenAI with OpenAI tool calling (Databricks serving endpoints).
LLM_TOOL_MODE=text    : for an OpenAI-compatible server WITHOUT a tool-call parser (the local
                        vLLM here answers HTTP 400 "auto tool choice requires
                        --enable-auto-tool-choice"). Tools are rendered by the chat template with
                        tool_choice="none"; the Qwen XML `<tool_call>` text in the answer is
                        parsed into LangChain tool calls here. Thinking is switched off.
LLM_TOOL_MODE=auto (default): text when LLM_BASE_URL is a local address, else native.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

_THINK = re.compile(r"<think>.*?</think>", re.S)
_ORPHAN = re.compile(r"^.*?</think>", re.S)
_CALL = re.compile(r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.S)
_FUNC = re.compile(r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.S)
_PARAM = re.compile(
    r"<parameter=([^>\s]+)\s*>(.*?)(?:</parameter>|(?=<parameter=)|(?=</function>)|\Z)", re.S)


def strip_think(text: str) -> str:
    text = _THINK.sub("", text or "")
    if "</think>" in text:
        text = _ORPHAN.sub("", text, count=1)
    return text.strip()


def _convert(raw: str, schema: dict[str, Any]) -> Any:
    v = raw.strip("\r\n")
    types = set()
    t = schema.get("type")
    if isinstance(t, list):
        types.update(t)
    elif t:
        types.add(t)
    for alt in (schema.get("anyOf") or []):
        if isinstance(alt, dict) and alt.get("type"):
            types.add(alt["type"])
    types.discard("null")
    if "string" in types or not types:
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] == '"':
            try:
                return json.loads(s)
            except ValueError:
                return v
        return v
    try:
        return json.loads(v.strip())
    except ValueError:
        return v


def parse_tool_calls(text: str, tools: list[dict[str, Any]] | None) -> tuple[str, list[dict[str, Any]]]:
    """Return (text without tool calls, [{name, args, id, type}])."""
    props: dict[str, dict[str, Any]] = {}
    for t in tools or []:
        fn = t.get("function", {})
        props[fn.get("name", "")] = (fn.get("parameters") or {}).get("properties") or {}
    calls = []
    for m in _CALL.finditer(text or ""):
        body = m.group(1).strip()
        if body.startswith("{"):
            try:
                obj = json.loads(body)
                if obj.get("name"):
                    calls.append((obj["name"], obj.get("arguments") or obj.get("parameters") or {}))
                continue
            except ValueError:
                pass
        fm = _FUNC.search(body)
        if not fm:
            continue
        name = fm.group(1)
        args = {p.group(1): _convert(p.group(2), props.get(name, {}).get(p.group(1), {}))
                for p in _PARAM.finditer(fm.group(2))}
        calls.append((name, args))
    if not calls:
        return text, []
    rest = _CALL.sub("", text).strip()
    return rest, [{"name": n, "args": a if isinstance(a, dict) else {}, "id": "call_" + uuid.uuid4().hex[:20],
                   "type": "tool_call"} for n, a in calls]


def _render_calls(calls: list[dict[str, Any]]) -> str:
    out = []
    for c in calls:
        lines = ["<tool_call>", f"<function={c['name']}>"]
        for k, v in (c.get("args") or {}).items():
            lines += [f"<parameter={k}>", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False),
                      "</parameter>"]
        lines += ["</function>", "</tool_call>"]
        out.append("\n".join(lines))
    return "\n".join(out)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content or [])


def to_wire(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """LangChain messages to chat messages for a Qwen chat template (one leading system)."""
    system, rest = [], []
    for m in messages:
        kind = m.type
        if kind == "system":
            if rest:
                rest.append({"role": "user", "content": "[System note] " + _text(m.content)})
            else:
                system.append(_text(m.content))
        elif kind == "human":
            rest.append({"role": "user", "content": _text(m.content)})
        elif kind == "ai":
            body = _text(m.content)
            calls = getattr(m, "tool_calls", None) or []
            if calls:
                body = (body + "\n" if body else "") + _render_calls(calls)
            rest.append({"role": "assistant", "content": body})
        elif kind == "tool":
            rest.append({"role": "tool", "content": _text(m.content)})
    wire = rest
    if system:
        wire = [{"role": "system", "content": "\n\n".join(system)}] + wire
    return wire


class TextToolChat(BaseChatModel):
    base_url: str
    model: str
    api_key: str = "none"
    temperature: float = 0.1
    max_tokens: int = 700
    timeout: float = 120.0

    @property
    def _llm_type(self) -> str:
        return "text-tool-chat"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        from openai import OpenAI

        tools = kwargs.get("tools")
        body: dict[str, Any] = {
            "model": self.model, "messages": to_wire(messages), "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "none"
        if stop:
            body["stop"] = stop
        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout, max_retries=1)
        resp = client.chat.completions.create(**body)
        text = strip_think(resp.choices[0].message.content or "")
        text, calls = parse_tool_calls(text, tools) if tools else (text, [])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text, tool_calls=calls))])


def get_llm(settings: Any) -> Any:
    mode = settings.llm_tool_mode
    if mode == "auto":
        local = settings.llm_base_url.startswith(("http://127.", "http://localhost"))
        mode = "text" if local else "native"
    if mode == "text":
        return TextToolChat(base_url=settings.llm_base_url,
                            model=os.environ.get("LLM_MODEL", "qwen3.8-27b-int4"),
                            api_key=settings.llm_api_key or "none")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(base_url=settings.llm_base_url,
                      model=os.environ.get("LLM_MODEL", "qwen3.8-27b-int4"),
                      api_key=settings.llm_api_key or "none", temperature=0.1, max_tokens=700)
