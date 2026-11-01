"""Tool-calling agent for invoices."""
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from tools import list_invoices, pay_invoice

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
TOOLS = [list_invoices, pay_invoice]
prompt = ChatPromptTemplate.from_messages(
    [("system", "Ban ho tro thanh toan hoa don. Tra loi bang tieng Viet."), ("human", "{input}"),
     ("placeholder", "{agent_scratchpad}")]
)
executor = AgentExecutor(agent=create_tool_calling_agent(llm, TOOLS, prompt), tools=TOOLS, max_iterations=5)

if __name__ == "__main__":
    print(executor.invoke({"input": "Thanh toan hoa don INV-0042 cua nha cung cap S-17"}))
