"""Function-calling loop for the FX desk assistant."""
import json
import os
import sys

from openai import OpenAI

from tools import lay_ty_gia, luu_bao_gia, thuc_hien_chuyen_tien

MODEL = "gpt-4o-2024-08-06"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lay_ty_gia",
            "description": "Get the current FX rate for a currency pair.",
            "parameters": {
                "type": "object",
                "properties": {"base": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["base", "quote"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dat_bao_gia",
            "description": "Book an FX quote for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "base": {"type": "string"},
                    "quote": {"type": "string"},
                    "amount": {"type": "number"},
                    "rate": {"type": "number"},
                },
                "required": ["customer_id", "base", "quote", "amount", "rate"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "chuyen_tien_ngoai_te",
            "description": "Execute an FX transfer to a beneficiary account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string"},
                    "so_tai_khoan": {"type": "string"},
                    "payee_name": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["quote_id", "so_tai_khoan", "payee_name", "amount"],
            },
        },
    },
]

# schema name -> implementation
DISPATCH = {
    "lay_ty_gia": lay_ty_gia,
    "dat_bao_gia": luu_bao_gia,
    "chuyen_tien_ngoai_te": thuc_hien_chuyen_tien,
}

SYSTEM = "Ban la tro ly phong giao dich ngoai hoi. Tra loi ngan gon bang tieng Viet."


def run(question: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
        )
        msg = response.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            result = DISPATCH[call.function.name](**args)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )


if __name__ == "__main__":
    print(run(sys.argv[1]))
