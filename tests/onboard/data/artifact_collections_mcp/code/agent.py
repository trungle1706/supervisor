"""Collections reminder agent (synthetic LangGraph artifact)."""

from databricks_langchain import ChatDatabricks
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

llm = ChatDatabricks(endpoint="databricks-claude-3-7-sonnet")


@tool
def lookup_account(account_id: str) -> dict:
    """Read the overdue state of an account."""
    return spark.sql("SELECT days_overdue FROM main.collections.overdue").first().asDict()


@tool
def send_payment_reminder(customer_id: str, channel: str, phone: str) -> str:
    """Send a reminder message."""
    return "sent"


@tool
def waive_late_fee(account_id: str, amount_minor: int) -> str:
    """Waive a late fee."""
    request_officer_approval(account_id, amount_minor)
    spark.sql("UPDATE main.collections.fees SET waived = true")
    return "waived"


def request_officer_approval(account_id: str, amount_minor: int) -> None:
    return None


agent = create_react_agent(llm, [lookup_account, send_payment_reminder, waive_late_fee])
