"""Function-calling loop for the payout assistant."""
import json
import os

from openai import OpenAI

from settle import notify_merchant, rollback_note, settle_batch

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ["OPENAI_BASE_URL"])
MODEL = os.environ["PAYOUT_MODEL"]

SCHEMAS = [
    {"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": {}}}}
    for n, d in (
        ("settle_batch", "Pay out a batch"),
        ("rollback_note", "Cancel a draft note"),
        ("notify_merchant", "Text the merchant"),
    )
]
DISPATCH = {"settle_batch": settle_batch, "rollback_note": rollback_note, "notify_merchant": notify_merchant}


def run(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    for _ in range(5):
        msg = client.chat.completions.create(model=MODEL, messages=messages, tools=SCHEMAS).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for call in msg.tool_calls:
            out = DISPATCH[call.function.name](**json.loads(call.function.arguments))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(out)})
    return ""


if __name__ == "__main__":
    print(run("Thanh toan lo B-2024-11 cho nhom cua hang, tong 1500000000 dong"))
