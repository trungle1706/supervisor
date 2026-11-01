"""Builds the KYC agent with LangChain."""
from databricks_langchain import ChatDatabricks
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool

from tools import TOOLS

llm = ChatDatabricks(endpoint="databricks-meta-llama-3-3-70b-instruct", temperature=0)
tools = [StructuredTool.from_function(f) for f in TOOLS]
prompt = ChatPromptTemplate.from_messages(
    [("system", "Ban la nhan vien KYC. Tra loi bang tieng Viet."), ("human", "{input}"),
     ("placeholder", "{agent_scratchpad}")]
)
executor = AgentExecutor(
    agent=create_tool_calling_agent(llm, tools, prompt), tools=tools, max_iterations=6
)

if __name__ == "__main__":
    print(executor.invoke({"input": "Xac minh ho so KH0900 cccd 079000000009 Nguyen Van An 01/01/1990"}))
