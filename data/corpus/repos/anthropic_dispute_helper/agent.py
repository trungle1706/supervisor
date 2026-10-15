"""Tool-use loop for the dispute helper."""
import json
import os
import sys

import anthropic

from actions import doc_giao_dich, hoan_phi, mo_khieu_nai

client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "doc_giao_dich",
        "description": "Read a card transaction by id.",
        "input_schema": {
            "type": "object",
            "properties": {"transaction_id": {"type": "string"}},
            "required": ["transaction_id"],
        },
    },
    {
        "name": "mo_khieu_nai",
        "description": "Open a dispute case for a transaction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "transaction_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "transaction_id", "reason"],
        },
    },
    {
        "name": "hoan_phi",
        "description": "Refund a fee to the customer's own account.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}, "fee_id": {"type": "string"}},
            "required": ["customer_id", "fee_id"],
        },
    },
]

HANDLERS = {"doc_giao_dich": doc_giao_dich, "mo_khieu_nai": mo_khieu_nai, "hoan_phi": hoan_phi}


def run(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                out = HANDLERS[block.name](**block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)}
                )
        messages.append({"role": "user", "content": results})
    return summarise(messages)


def summarise(messages: list) -> str:
    summary = client.messages.create(
        model=os.environ["SUMMARY_MODEL"],
        max_tokens=300,
        messages=[
            {"role": "user", "content": "Summarise this case in 3 lines: " + json.dumps(messages, default=str)}
        ],
    )
    return summary.content[0].text


if __name__ == "__main__":
    print(run(sys.argv[1]))
