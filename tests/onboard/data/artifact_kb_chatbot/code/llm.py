"""OpenAI-compatible chat client (httpx). Base URL, model and key come from the environment.
On Databricks the base URL is https://<host>/serving-endpoints and the key is an OAuth token.
This is the only network call besides the Supervisor gate."""
from __future__ import annotations

import os
import re

import httpx


def settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "qwen3.8-27b-int4"),
        "api_key": os.environ.get("LLM_API_KEY", "none"),
    }


def chat(messages: list[dict], max_tokens: int = 700, temperature: float = 0.1) -> str:
    s = settings()
    body = {"model": s["model"], "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    r = httpx.post(f"{s['base_url']}/chat/completions", json=body,
                   headers={"Authorization": f"Bearer {s['api_key']}"}, timeout=120)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
