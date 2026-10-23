"""The agent loop: the model may ask for the tool search_policies; every tool request goes through
the Supervisor gate first. No native function calling is needed: the model writes
<tool_call>{"name": ..., "arguments": {...}}</tool_call> and the app parses it (works on any
OpenAI-compatible endpoint)."""
from __future__ import annotations

import json
import os
import re

from supervisor.gateway.sdk import HttpGate, SupervisorBlocked, set_default_gate, supervised_tool
from supervisor.gateway.ingress_sign import IngressCredential

import llm
from kb import KnowledgeBase

AGENT_ID = os.environ.get("SUPERVISOR_AGENT_ID", "kb_chatbot")
AGENT_VERSION = os.environ.get("AGENT_VERSION", "1")
KB = KnowledgeBase()


def build_gate() -> HttpGate | None:
    url = os.environ.get("SUPERVISOR_GATE_URL", "")
    if not url:
        return None
    secret = os.environ.get("SUPERVISOR_CREDENTIAL", "").strip()
    cred = IngressCredential(AGENT_ID, secret) if secret else None
    return HttpGate(url, timeout_s=float(os.environ.get("SUPERVISOR_TIMEOUT_S", "5")), credential=cred)


GATE = build_gate()
if GATE is not None:
    set_default_gate(GATE)  # no gate configured => supervised_tool fails closed (GATE-MISSING)


@supervised_tool(AGENT_ID, AGENT_VERSION, "search_policies", "read_only")
def search_policies(query: str, top_k: int = 4) -> list[dict]:
    """Search the synthetic bank policy documents. Read only."""
    return [{k: c[k] for k in ("doc_id", "title", "section", "text", "score")} for c in KB.search(query, top_k)]


SYSTEM = """Ban la tro ly hoi dap chinh sach noi bo cua mot ngan hang (du lieu tong hop). Tra loi bang tieng Viet co dau, ngan gon.
Chi dung thong tin trong cac nguon [n] do cong cu search_policies tra ve. Dan nguon dang [1], [2] sau moi y.
Neu nguon khong co thong tin, noi: "Toi khong tim thay noi dung nay trong cac van ban chinh sach." Khong dung kien thuc ben ngoai.
Khong yeu cau va khong lap lai du lieu ca nhan cua khach hang (so CCCD, so tai khoan, so dien thoai).

Cong cu co the dung (moi lan chi mot cong cu):
- search_policies(query: string, top_k: int = 4): tim doan van ban chinh sach.
De goi cong cu, tra loi DUNG MOT dong, khong them chu nao khac:
<tool_call>{"name": "search_policies", "arguments": {"query": "..."}}</tool_call>
Voi moi cau hoi ve chinh sach, hay goi search_policies truoc khi tra loi."""

CALL_RE = re.compile(r"<tool_call>\s*(\{.*\})", re.S)  # closing tag optional: some models stop before it
MAX_STEPS = 3


def _format_sources(results: list[dict]) -> str:
    return "\n\n".join(f"[{i + 1}] ({r['doc_id']} - {r['title']}, {r['section']})\n{r['text']}"
                       for i, r in enumerate(results))


def run_agent(question: str, history: list[dict] | None = None) -> dict:
    messages = [{"role": "system", "content": SYSTEM}]
    for t in (history or [])[-6:]:
        messages.append({"role": t["role"], "content": t["text"][:800]})
    messages.append({"role": "user", "content": question})
    trace: list[dict] = []
    sources: list[dict] = []
    for _ in range(MAX_STEPS):
        reply = llm.chat(messages)
        m = CALL_RE.search(reply)
        if not m:
            return {"answer": reply, "sources": sources, "tool_calls": trace}
        try:
            call = json.loads(m.group(1))
            name, args = str(call.get("name", "")), dict(call.get("arguments") or {})
        except (ValueError, TypeError):
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": "Loi: tool_call khong hop le (JSON)."}]
            continue
        messages.append({"role": "assistant", "content": reply})
        if name == "search_policies":
            try:
                results = search_policies(str(args.get("query", "")), int(args.get("top_k", 4)))
                trace.append({"tool": name, "outcome": "ran", "n_results": len(results)})
                sources = results
                messages.append({"role": "user", "content": "KET QUA search_policies:\n" + (_format_sources(results) or "(khong co ket qua)")})
            except SupervisorBlocked as exc:
                trace.append({"tool": name, "outcome": "refused", "rule_id": exc.decision.get("rule_id")})
                messages.append({"role": "user", "content": "Cong cu bi Supervisor tu choi. Khong the tra cuu."})
        else:
            # Any other tool the model invents: ask the gate (policy refuses it), never run it.
            outcome, rule = "refused", None
            try:
                if GATE is None:
                    raise SupervisorBlocked({"rule_id": "GATE-MISSING"})
                d = GATE.check(AGENT_ID, AGENT_VERSION, name[:64] or "unknown", args, {"declared_risk_class": "read_only"})
                rule = d.get("rule_id")
                outcome = "gate_said_allow_but_not_implemented" if d.get("allow") else "refused"
            except SupervisorBlocked as exc:
                rule = exc.decision.get("rule_id")
            trace.append({"tool": name[:64], "outcome": outcome, "rule_id": rule})
            messages.append({"role": "user", "content": "Cong cu khong ton tai hoac khong duoc phep. Chi co search_policies."})
    return {"answer": "Toi chua the tra loi cau hoi nay.", "sources": sources, "tool_calls": trace}
