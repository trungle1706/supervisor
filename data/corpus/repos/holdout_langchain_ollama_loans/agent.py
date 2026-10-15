"""Tac tu cho vay: mo hinh chay noi bo bang Ollama."""
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from tools import ALL_TOOLS

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "Ban la tro ly xu ly khoan vay cua ngan hang. Tra loi bang tieng Viet."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

llm = ChatOllama(model="qwen2.5:7b", base_url="http://ollama.example.vn:11434", temperature=0)

agent = create_tool_calling_agent(llm, ALL_TOOLS, PROMPT)
executor = AgentExecutor(agent=agent, tools=ALL_TOOLS, max_iterations=6, verbose=False)


def xu_ly(yeu_cau: str) -> str:
    ket_qua = executor.invoke({"input": yeu_cau})
    return ket_qua["output"]


if __name__ == "__main__":
    print(xu_ly("Giai ngan 50000000 dong cho hop dong HD-2024-0007 vao tai khoan 0123456789"))
