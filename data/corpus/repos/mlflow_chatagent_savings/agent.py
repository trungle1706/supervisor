"""ChatAgent for savings products."""
import json
from typing import Optional
from uuid import uuid4

import mlflow.deployments
from databricks.sdk import WorkspaceClient
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse

from tools import TOOL_SPECS

ENDPOINT = "databricks-claude-3-7-sonnet"
SYSTEM_PROMPT = "Ban la tro ly tiet kiem cua ngan hang. Chi dung cong cu da cho."


class SavingsAgent(ChatAgent):
    def __init__(self):
        self.w = WorkspaceClient()
        self.deploy_client = mlflow.deployments.get_deploy_client("databricks")
        self.tools = {name: t["fn"] for name, t in TOOL_SPECS.items()}
        self.specs = [t["spec"] for t in TOOL_SPECS.values()]

    def _plan(self, messages: list):
        resp = self.w.serving_endpoints.query(
            name=ENDPOINT,
            messages=messages,
        )
        return resp

    def _chat(self, messages: list) -> dict:
        return self.deploy_client.predict(
            endpoint=ENDPOINT,
            inputs={"messages": messages, "tools": self.specs, "max_tokens": 512},
        )

    def predict(
        self,
        messages: list[ChatAgentMessage],
        context=None,
        custom_inputs: Optional[dict] = None,
    ) -> ChatAgentResponse:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        history += [m.model_dump(exclude_none=True) for m in messages]
        for _ in range(5):
            out = self._chat(history)
            msg = out["choices"][0]["message"]
            history.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                args = json.loads(call["function"]["arguments"])
                result = self.tools[call["function"]["name"]](**args)
                history.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
                )
        reply = ChatAgentMessage(id=str(uuid4()), role="assistant", content=msg.get("content", ""))
        return ChatAgentResponse(messages=[reply])

    def plan_only(self, question: str):
        return self._plan([{"role": "user", "content": question}])
