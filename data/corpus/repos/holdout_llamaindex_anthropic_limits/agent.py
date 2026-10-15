"""Tac tu goi y va ap dung han muc the, dung LlamaIndex."""
import asyncio

from llama_index.core.agent import FunctionCallingAgent
from llama_index.llms.anthropic import Anthropic
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from tools import TOOLS

trace.set_tracer_provider(TracerProvider())

llm = Anthropic(model="claude-3-5-haiku-latest", max_tokens=1024)

agent = FunctionCallingAgent.from_tools(
    TOOLS,
    llm=llm,
    system_prompt="Ban ho tro can bo xem xet han muc the. Luon de xuat truoc khi ap dung.",
    verbose=False,
)


async def main(customer_id: str) -> None:
    ket_qua = await agent.achat(f"Xem xet tang han muc cho khach hang {customer_id}")
    print(str(ket_qua))


if __name__ == "__main__":
    asyncio.run(main("KH000123"))
