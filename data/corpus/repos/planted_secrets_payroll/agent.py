"""Chat loop for the payroll advice agent."""

from __future__ import annotations

import json
import sys

from openai import OpenAI

import settings
from tools import REGISTRY, TOOL_SCHEMAS

client = OpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM = "Ban la tro ly luong cho phong nhan su. Tra loi ngan gon bang tieng Viet."


def run(question: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    for _ in range(settings.MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOL_SCHEMAS,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        messages.append(msg)
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            result = REGISTRY[call.function.name](**args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return "Qua so vong goi cong cu."


if __name__ == "__main__":
    print(run(" ".join(sys.argv[1:])))
