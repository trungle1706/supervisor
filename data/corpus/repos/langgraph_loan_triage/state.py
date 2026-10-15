"""Graph state for the loan triage agent."""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class TriageState(TypedDict):
    # Chat history; add_messages appends instead of overwriting.
    messages: Annotated[list, add_messages]
    application_id: str
    steps: int
