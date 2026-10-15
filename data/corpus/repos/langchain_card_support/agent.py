"""Builds the card support agent."""
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from tools import TOOLS

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "Ban la tro ly ho tro the cua ngan hang. Tra loi ngan gon bang tieng Viet."),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ]
)


def build_executor() -> AgentExecutor:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_tool_calling_agent(llm, TOOLS, PROMPT)
    return AgentExecutor(agent=agent, tools=TOOLS, max_iterations=5, verbose=True)
