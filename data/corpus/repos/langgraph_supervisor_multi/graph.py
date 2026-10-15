"""Supervisor graph: routes a request to the card agent or the statement agent."""

from __future__ import annotations

import os
from typing import Annotated, TypedDict

import mlflow
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from workers import card_agent, statement_agent

mlflow.langchain.autolog()

supervisor_llm = ChatAnthropic(model=os.getenv("SUPERVISOR_MODEL"), temperature=0)

ROUTES = ("card_agent", "statement_agent", "FINISH")


class State(TypedDict):
    messages: Annotated[list, add_messages]
    next: str


def supervisor(state: State) -> dict:
    prompt = (
        "Pick the next worker: card_agent (limits, spending), statement_agent "
        "(export a statement), or FINISH. Reply with one word."
    )
    reply = supervisor_llm.invoke([HumanMessage(content=prompt)] + state["messages"])
    choice = str(reply.content).strip()
    return {"next": choice if choice in ROUTES else "FINISH"}


def run_card(state: State) -> dict:
    return card_agent.invoke({"messages": state["messages"]})


def run_statement(state: State) -> dict:
    return statement_agent.invoke({"messages": state["messages"]})


builder = StateGraph(State)
builder.add_node("supervisor", supervisor)
builder.add_node("card_agent", run_card)
builder.add_node("statement_agent", run_statement)
builder.add_edge(START, "supervisor")
builder.add_conditional_edges(
    "supervisor",
    lambda s: s["next"],
    {"card_agent": "card_agent", "statement_agent": "statement_agent", "FINISH": END},
)
builder.add_edge("card_agent", END)
builder.add_edge("statement_agent", END)
graph = builder.compile()


if __name__ == "__main__":
    out = graph.invoke({"messages": [HumanMessage(content="Han muc the 9704000000000018 con bao nhieu?")]})
    print(out["messages"][-1].content)
