"""Own agent loop on the internal OpenAI-compatible server."""
import json

import requests

from tools import REGISTRY, SPECS

SYSTEM = (
    "Ban la tro ly hau cap thu hoi no. Khi can dung cong cu, tra loi JSON "
    '{"tool": ten, "args": {...}}. Cong cu: ' + json.dumps(SPECS)
)


def ask(messages: list[dict]) -> str:
    resp = requests.post(
        "https://llm.nganhang.internal/v1/chat/completions",
        json={"model": "llama-3.3-70b-instruct", "messages": messages, "temperature": 0},
        timeout=60,
    )
    return resp.json()["choices"][0]["message"]["content"]


def run(question: str) -> str:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for _ in range(5):
        reply = ask(messages)
        try:
            call = json.loads(reply)
        except ValueError:
            return reply
        result = REGISTRY[call["tool"]](**call["args"])
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": json.dumps(result)})
    return "stopped"


if __name__ == "__main__":
    print(run("Xoa 5000000 dong no cua hop dong HD-77 vi khach da mat"))
