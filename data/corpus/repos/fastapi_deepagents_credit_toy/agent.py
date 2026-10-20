"""Builds the memo agent with deepagents."""
import os

from databricks_langchain import ChatDatabricks
from deepagents import create_deep_agent

from tools import (
    compute_dscr,
    draft_section,
    fetch_financials,
    read_facility,
    save_memo_draft,
    search_policy,
)

ENDPOINT = os.environ.get("MEMO_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")

INSTRUCTIONS = "You write a short credit memo from the tools. Do not invent numbers."


def build_agent():
    llm = ChatDatabricks(endpoint=ENDPOINT, temperature=0)
    return create_deep_agent(
        model=llm,
        tools=[
            read_facility,
            fetch_financials,
            compute_dscr,
            search_policy,
            draft_section,
            save_memo_draft,
        ],
        instructions=INSTRUCTIONS,
    )
