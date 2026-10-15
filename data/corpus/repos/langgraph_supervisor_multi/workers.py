"""The two worker agents of the supervisor graph."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from card_tools import get_card_limit, get_spending_summary
from statement_tools import export_statement

worker_llm = ChatAnthropic(model="claude-3-5-haiku-20241022", temperature=0)

card_agent = create_react_agent(
    worker_llm,
    tools=[get_card_limit, get_spending_summary],
    prompt="You explain card limits and spending to the customer. Answer in Vietnamese.",
)

statement_agent = create_react_agent(
    worker_llm,
    tools=[export_statement],
    prompt="You export account statements as CSV files. Answer in Vietnamese.",
)
