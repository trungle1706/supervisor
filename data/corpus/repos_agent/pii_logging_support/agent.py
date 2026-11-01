"""Tool-use loop on the Anthropic Messages API."""
import json

import anthropic

from tools import HANDLERS

client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "tra_cuu_khach_hang",
        "description": "Find a customer by phone number.",
        "input_schema": {
            "type": "object",
            "properties": {"so_dien_thoai": {"type": "string"}},
            "required": ["so_dien_thoai"],
        },
    },
    {
        "name": "cap_nhat_dia_chi",
        "description": "Update the address of a customer.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}, "dia_chi": {"type": "string"}},
            "required": ["customer_id", "dia_chi"],
        },
    },
    {
        "name": "gui_otp",
        "description": "Send a one-time code by SMS.",
        "input_schema": {
            "type": "object",
            "properties": {"so_dien_thoai": {"type": "string"}},
            "required": ["so_dien_thoai"],
        },
    },
]


def run(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    for _ in range(5):
        rep = client.messages.create(
            model="claude-3-5-haiku-20241022", max_tokens=800, tools=TOOLS, messages=messages
        )
        messages.append({"role": "assistant", "content": rep.content})
        if rep.stop_reason != "tool_use":
            return "".join(b.text for b in rep.content if b.type == "text")
        results = []
        for block in rep.content:
            if block.type == "tool_use":
                out = HANDLERS[block.name](**block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)}
                )
        messages.append({"role": "user", "content": results})
    return ""


if __name__ == "__main__":
    print(run("Khach 0900000001 doi dia chi sang 12 Nguyen Hue, Quan 1"))
