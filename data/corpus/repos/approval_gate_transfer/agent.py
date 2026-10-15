"""Own agent loop: calls an OpenAI-compatible server inside the bank network."""

from __future__ import annotations

import json

import requests

from telemetry import setup_tracing
from tools import TOOL_SPECS, TOOLS

tracer = setup_tracing()

SYSTEM = (
    "You are a branch assistant. To use a tool reply with JSON "
    '{"tool": name, "args": {...}}. Otherwise reply in Vietnamese.\n'
    f"Tools: {json.dumps(TOOL_SPECS)}"
)


def ask_model(messages: list[dict]) -> str:
    with tracer.start_as_current_span("llm.call"):
        resp = requests.post(
            "https://llm.nganhang.internal/v1/chat/completions",
            json={"model": "qwen3-32b", "messages": messages, "temperature": 0},
            timeout=60,
        )
        return resp.json()["choices"][0]["message"]["content"]


def run(question: str, max_steps: int = 4) -> str:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for _ in range(max_steps):
        reply = ask_model(messages)
        try:
            call = json.loads(reply)
        except ValueError:
            return reply
        with tracer.start_as_current_span(f"tool.{call['tool']}"):
            result = TOOLS[call["tool"]](**call["args"])
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": json.dumps(result)})
    return "Stopped after too many steps."


if __name__ == "__main__":
    print(run("So du tai khoan 0123456789 la bao nhieu?"))
