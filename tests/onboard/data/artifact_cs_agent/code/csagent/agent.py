"""The graph. Pattern from the LangGraph customer-support tutorial, part 3 ("Conditional
Interrupt"): an assistant node, a `safe_tools` node and a `sensitive_tools` node, and
`interrupt_before=["sensitive_tools"]` so a person decides before a sensitive tool runs.

Changes from the tutorial (see README): bank domain instead of airline; Anthropic model replaced by
the OpenAI-compatible client (llm.py); the sensitive tool is `waive_fee`; the resume injects the
approval id of the human decision into the tool call; every tool node runs behind the Supervisor
tool-call middleware.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from .tools import SAFE_TOOLS, SENSITIVE_TOOLS, model_tool_specs

PROMPT_FILE = Path(__file__).with_name("prompts") / "system.txt"
SENSITIVE_NAMES = {t.name for t in SENSITIVE_TOOLS}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class Assistant:
    """Calls the model; re-asks once when the answer is empty (as in the tutorial)."""

    def __init__(self, runnable: Any):
        self.runnable = runnable

    def __call__(self, state: State) -> dict[str, Any]:
        for _ in range(2):
            result = self.runnable.invoke(state)
            if result.tool_calls or (result.content and str(result.content).strip()):
                break
            state = {**state, "messages": state["messages"] + [("user", "Respond with a real output.")]}
        return {"messages": result}


def route_tools(state: State) -> str:
    nxt = tools_condition(state)
    if nxt == END:
        return END
    calls = state["messages"][-1].tool_calls
    # any sensitive call in the message sends the whole message to the interrupted node
    return "sensitive_tools" if any(c["name"] in SENSITIVE_NAMES for c in calls) else "safe_tools"


def build_graph(llm: Any, guard: Any, checkpointer: Any | None = None) -> Any:
    prompt = ChatPromptTemplate.from_messages(
        [("system", PROMPT_FILE.read_text(encoding="utf-8")), ("placeholder", "{messages}")]
    ).partial(time=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    runnable = prompt | llm.bind_tools(model_tool_specs())

    wrap = guard.wrap_tool_call if guard is not None else None
    b = StateGraph(State)
    b.add_node("assistant", Assistant(runnable))
    b.add_node("safe_tools", ToolNode(SAFE_TOOLS, wrap_tool_call=wrap))
    b.add_node("sensitive_tools", ToolNode(SENSITIVE_TOOLS, wrap_tool_call=wrap))
    b.add_edge(START, "assistant")
    b.add_conditional_edges("assistant", route_tools, ["safe_tools", "sensitive_tools", END])
    b.add_edge("safe_tools", "assistant")
    b.add_edge("sensitive_tools", "assistant")
    # The graph always halts before "sensitive_tools": a person approves or rejects (approval in code).
    return b.compile(checkpointer=checkpointer or InMemorySaver(), interrupt_before=["sensitive_tools"])


def with_approval(graph: Any, config: dict, approval_id: str) -> None:
    """Resume step 1: put the approval id into the pending waive_fee call(s). The model never
    sees or writes this id (it is an InjectedToolArg); it is the key of the Supervisor fact
    `fact.approval.approved`."""
    state = graph.get_state(config)
    last = state.values["messages"][-1]
    calls = []
    for c in last.tool_calls:
        c = dict(c)
        if c["name"] == "waive_fee":
            c["args"] = {**c["args"], "approval_id": approval_id}
        calls.append(c)
    graph.update_state(config, {"messages": [AIMessage(content=last.content, tool_calls=calls, id=last.id)]})


def reject(graph: Any, config: dict, note: str) -> None:
    """Resume step 1 for a rejection: answer the pending calls with an error and go on."""
    last = graph.get_state(config).values["messages"][-1]
    msgs = [ToolMessage(content=f"REJECTED by the human approver. {note}", tool_call_id=c["id"],
                        name=c["name"], status="error") for c in last.tool_calls]
    graph.update_state(config, {"messages": msgs}, as_node="sensitive_tools")
