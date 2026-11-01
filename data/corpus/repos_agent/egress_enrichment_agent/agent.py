"""Function-calling loop for the enrichment assistant."""
import json
import sys

from openai import OpenAI

from enrich import CFG, lookup_company, notify_partner

client = OpenAI(base_url=CFG["llm"]["base_url"], api_key="not-needed")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_company",
            "description": "Look up a company profile by tax code.",
            "parameters": {
                "type": "object",
                "properties": {"tax_code": {"type": "string"}},
                "required": ["tax_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_partner",
            "description": "Notify the partner system about a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "ho_ten": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["customer_id", "ho_ten", "message"],
            },
        },
    },
]
HANDLERS = {"lookup_company": lookup_company, "notify_partner": notify_partner}


def run(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    for _ in range(CFG["max_steps"]):
        reply = client.chat.completions.create(
            model=CFG["llm"]["model"], messages=messages, tools=TOOLS
        ).choices[0].message
        messages.append(reply)
        if not reply.tool_calls:
            return reply.content or ""
        for call in reply.tool_calls:
            out = HANDLERS[call.function.name](**json.loads(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(out)}
            )
    return "stopped"


if __name__ == "__main__":
    print(run(sys.argv[1]))
