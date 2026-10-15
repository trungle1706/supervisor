"""Operations agent: the model picks a tool, the loop runs it."""
import json

import requests
import yaml

from loader import ALL_TOOLS

with open("config.yaml", encoding="utf-8") as fh:
    cfg = yaml.safe_load(fh)


def ask_model(messages: list[dict]) -> dict:
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0,
    }
    resp = requests.post(f"{cfg['llm_base_url']}/chat/completions", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def run(task: str) -> str:
    system = "Use one tool per step. Tools: " + ", ".join(sorted(ALL_TOOLS))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    for _ in range(cfg.get("max_steps", 5)):
        msg = ask_model(messages)
        call = json.loads(msg["content"])
        if "tool" not in call:
            return msg["content"]
        result = ALL_TOOLS[call["tool"]](**call.get("args", {}))
        messages.append({"role": "assistant", "content": msg["content"]})
        messages.append({"role": "user", "content": json.dumps(result)})
    return "stopped"
