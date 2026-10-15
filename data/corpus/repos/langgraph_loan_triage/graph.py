"""Builds the triage StateGraph: model node <-> ToolNode loop."""
from databricks_langchain import ChatDatabricks
from langchain_core.messages import SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from state import TriageState
from tools import ALL_TOOLS

SYSTEM = SystemMessage(
    content=(
        "You triage loan applications. Read the application, check the bureau score, "
        "then record a pre-approval decision with the record_preapproval_decision tool."
    )
)

llm = ChatDatabricks(endpoint="databricks-meta-llama-3-3-70b-instruct", temperature=0)
model = llm.bind_tools(ALL_TOOLS)
tool_node = ToolNode(ALL_TOOLS)


def call_model(state: TriageState) -> dict:
    reply = model.invoke([SYSTEM] + state["messages"])
    return {"messages": [reply], "steps": state.get("steps", 0) + 1}


def route(state: TriageState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state.get("steps", 0) < 8:
        return "tools"
    return END


def build_graph():
    g = StateGraph(TriageState)
    g.add_node("agent", call_model)
    g.add_node("tools", tool_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()
