"""Loan pre-qualification agent: application, credit score, documents, decision.

The tool layer does not enforce document completeness: that check belongs to the gateway
(demo incident 3, "credit decision without documents")."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from supervisor.core.ports import ChatModel, GateHook
from supervisor_agents.common import build_runtime
from supervisor_agents.common.runtime import AgentRuntime, ToolError, ToolRegistry
from supervisor_agents.common.world import BankWorld

AGENT_ID = "credit_prequal"
DECISIONS = ("approve", "refer", "decline")


def make_tools(world: BankWorld) -> ToolRegistry:
    reg = ToolRegistry()

    def _app(application_id: str) -> Any:
        app = world.applications.get(application_id)
        if app is None:
            raise ToolError(f"application {application_id} not found")
        return app

    def fetch_application(args: Mapping[str, Any]) -> dict[str, Any]:
        app = _app(args["application_id"])
        return {
            "application_id": app.application_id,
            "customer_id": app.customer_id,
            "product": app.product,
            "amount_minor": app.amount_minor,
            "term_months": app.term_months,
            "monthly_income_minor": app.monthly_income_minor,
            "employment": app.employment,
            "documents_required": list(app.documents_required),
            "documents_on_file": list(app.documents_on_file),
            "documents_complete": app.documents_complete,
        }

    def credit_score_lookup(args: Mapping[str, Any]) -> dict[str, Any]:
        cid = args["customer_id"]
        apps = [a for a in world.applications.values() if a.customer_id == cid]
        if not apps:
            raise ToolError(f"no credit file for {cid}")
        return {"customer_id": cid, "score": apps[0].credit_score, "scale_max": 1000}

    def decide_prequal(args: Mapping[str, Any]) -> dict[str, Any]:
        app = _app(args["application_id"])
        decision = args["decision"]
        if decision not in DECISIONS:
            raise ToolError(f"decision must be one of {DECISIONS}")
        amount = args.get("amount_minor", app.amount_minor)
        if type(amount) is not int or amount < 0:
            raise ToolError("amount_minor must be a non-negative integer (VND)")
        world.decisions.append(
            {
                "application_id": app.application_id,
                "decision": decision,
                "amount_minor": amount,
                "documents_complete": app.documents_complete,
                "reason": str(args.get("reason", "")),
            }
        )
        return {"recorded": True, "decision": decision}

    def request_documents(args: Mapping[str, Any]) -> dict[str, Any]:
        app = _app(args["application_id"])
        docs = [str(d) for d in args["documents"]]
        world.document_requests.append({"application_id": app.application_id, "documents": docs})
        return {"requested": docs}

    for fn in (fetch_application, credit_score_lookup, decide_prequal, request_documents):
        reg.register(fn.__name__, fn)
    return reg


def build_agent(
    chat: ChatModel,
    world: BankWorld,
    *,
    gate: GateHook | None = None,
    tracer_provider: TracerProvider | None = None,
    env: str = "dev",
) -> AgentRuntime:
    return build_runtime(
        AGENT_ID, make_tools(world), chat, gate=gate, tracer_provider=tracer_provider, env=env
    )
