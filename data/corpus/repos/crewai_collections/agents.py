"""Agents of the collections crew."""
from crewai import LLM, Agent

from tools import GuiNhacNoSmsTool, TraCuuKhoanVayTool, record_payment_plan

claude = LLM(model="anthropic/claude-3-5-sonnet-20241022", temperature=0.1)

analyst = Agent(
    role="Overdue loan analyst",
    goal="Find overdue loans and rank them by days overdue",
    backstory="You work in the early collections team of a Vietnamese retail bank.",
    tools=[TraCuuKhoanVayTool()],
    llm=claude,
    allow_delegation=False,
)

collector = Agent(llm="gpt-4o",
    role="Collections officer",
    goal="Remind borrowers politely and agree a repayment plan",
    backstory="You speak Vietnamese, you are calm and you never threaten borrowers.",
    tools=[GuiNhacNoSmsTool(), record_payment_plan],
    allow_delegation=False,
)
