"""Three synthetic demo agents (customer_service, credit_prequal, payments) for Supervisor.

These are the agents Supervisor watches in tests and in the demo. They are plain Python
tool-calling loops (no framework) over a ``ChatModel`` and a ``GateHook``. All data is
synthetic (``supervisor.data.synthetic``).
"""

AGENT_IDS: tuple[str, ...] = ("customer_service", "credit_prequal", "payments")
