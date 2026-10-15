"""Assembles the ReAct agent."""
from llama_index.core.agent import ReActAgent
from llama_index.core.tools import FunctionTool, QueryEngineTool
from llama_index.llms.openai import OpenAI

from index import build_query_engine
from tools import tinh_ngay_hieu_luc, tra_cuu_bieu_phi


def build_agent() -> ReActAgent:
    llm = OpenAI(model="gpt-4o-mini", temperature=0)
    query_engine = build_query_engine()
    policy_tool = QueryEngineTool.from_defaults(query_engine=query_engine, name="chinh_sach_noi_bo", description="Tra cuu quy dinh noi bo")
    fee_tool = FunctionTool.from_defaults(
        fn=tra_cuu_bieu_phi,
        name="tra_cuu_phi_the",
        description="Tra phi thuong nien theo loai the.",
    )
    date_tool = FunctionTool.from_defaults(fn=tinh_ngay_hieu_luc)
    return ReActAgent.from_tools([policy_tool, fee_tool, date_tool], llm=llm, verbose=True)
