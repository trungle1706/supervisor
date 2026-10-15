"""Tac tu khach: goi mo hinh Azure OpenAI va cac cong cu cua may chu MCP."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_KEY"],
    api_version="2024-08-01-preview",
)


async def chay(yeu_cau: str) -> str:
    params = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ds = (await session.list_tools()).tools
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    },
                }
                for t in ds
            ]
            messages = [
                {"role": "system", "content": "Ban la tro ly the cua ngan hang."},
                {"role": "user", "content": yeu_cau},
            ]
            for _ in range(5):
                rep = client.chat.completions.create(
                    model=os.environ["AZURE_DEPLOYMENT"],
                    messages=messages,
                    tools=tools,
                )
                msg = rep.choices[0].message
                if not msg.tool_calls:
                    return msg.content or ""
                messages.append(msg)
                for call in msg.tool_calls:
                    kq = await session.call_tool(
                        call.function.name, json.loads(call.function.arguments)
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": str(kq.content)}
                    )
    return ""


if __name__ == "__main__":
    print(asyncio.run(chay("Khoa the 9704000000000001 cua khach KH000045, mat the")))
