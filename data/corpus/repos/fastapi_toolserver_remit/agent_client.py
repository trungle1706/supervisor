"""Agent client: lets a local model call the remittance tool server."""
import json
import os

import httpx
from openai import OpenAI

TOOL_SERVER = "http://toolserver.example.vn"
MODEL = "qwen2.5-14b-instruct"

client = OpenAI(
    base_url="http://llm.nganhang.internal:8000/v1",
    api_key=os.environ["LLM_API_KEY"],
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "quote_fee",
            "description": "Quote the fee of a remittance",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "integer"}, "currency": {"type": "string"}},
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_watchlist",
            "description": "Check a beneficiary name against the watch list",
            "parameters": {
                "type": "object",
                "properties": {"full_name": {"type": "string"}},
                "required": ["full_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_remittance",
            "description": "Send a remittance abroad",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "payee_name": {"type": "string"},
                    "beneficiary_account": {"type": "string"},
                    "amount": {"type": "integer"},
                },
                "required": ["customer_id", "beneficiary_account", "amount"],
            },
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    if name == "quote_fee":
        return httpx.get(f"{TOOL_SERVER}/tools/{name}", params=args, timeout=20).json()
    return httpx.post(f"{TOOL_SERVER}/tools/{name}", json=args, timeout=20).json()


def run(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    for _ in range(6):
        reply = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS
        ).choices[0].message
        messages.append(reply)
        if not reply.tool_calls:
            return reply.content or ""
        for call in reply.tool_calls:
            result = call_tool(call.function.name, json.loads(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )
    return "stopped after too many steps"
