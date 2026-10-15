"""LangChain agent loop for bill payment."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from tools import list_bills, pay_bill, save_payee

TOOLS = [list_bills, pay_bill, save_payee]
BY_NAME = {t.name: t for t in TOOLS}

llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(TOOLS)


def chat(question: str, max_rounds: int = 5) -> str:
    messages = [
        SystemMessage(content="You help customers pay bills. Answer in Vietnamese."),
        HumanMessage(content=question),
    ]
    for _ in range(max_rounds):
        ai = llm_with_tools.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return str(ai.content)
        for call in ai.tool_calls:
            out = BY_NAME[call["name"]].invoke(call["args"])
            messages.append(ToolMessage(content=str(out), tool_call_id=call["id"]))
    return "Too many tool rounds."


if __name__ == "__main__":
    print(chat("Tien dien thang nay cua khach KH0001 la bao nhieu?"))
