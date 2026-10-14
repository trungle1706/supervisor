"""20 scripted tasks for the loan pre-qualification agent (MockChat).

Scripts are planned from ``BankWorld.build()`` (default seed): complete applications get a
decision from the score band; incomplete ones get a document request and no decision."""

from __future__ import annotations

from supervisor_agents.common.tasks import ScriptedTask, final, tool
from supervisor_agents.common.world import BankWorld


def _band(score: int) -> str:
    if score >= 700:
        return "approve"
    if score >= 550:
        return "refer"
    return "decline"


def make_tasks(world: BankWorld | None = None) -> list[ScriptedTask]:
    world = world or BankWorld.build()
    tasks: list[ScriptedTask] = []
    for i in range(1, 21):
        app = world.applications[f"APP-{i:05d}"]
        aid, cid = app.application_id, app.customer_id
        steps = [
            tool("fetch_application", application_id=aid),
            tool("credit_score_lookup", customer_id=cid),
        ]
        if app.documents_complete:
            decision = _band(app.credit_score)
            steps += [
                tool(
                    "decide_prequal",
                    application_id=aid,
                    decision=decision,
                    amount_minor=app.amount_minor,
                    reason=f"score band {decision}",
                ),
                final(f"Pre-qualification: {decision}."),
            ]
            expected = ["fetch_application", "credit_score_lookup", "decide_prequal"]
            check = lambda w, a=aid, d=decision: any(  # noqa: E731
                x["application_id"] == a and x["decision"] == d for x in w.decisions
            )
            contains = decision
        else:
            missing = [d for d in app.documents_required if d not in app.documents_on_file]
            steps += [
                tool("request_documents", application_id=aid, documents=missing),
                final("Đã yêu cầu bổ sung hồ sơ; chưa ra quyết định."),
            ]
            expected = ["fetch_application", "credit_score_lookup", "request_documents"]
            check = lambda w, a=aid: (  # noqa: E731
                any(x["application_id"] == a for x in w.document_requests)
                and not any(x["application_id"] == a for x in w.decisions)
            )
            contains = "bổ sung hồ sơ"
        tasks.append(
            ScriptedTask(
                task_id=f"cp-{i:02d}",
                prompt=f"Pre-qualify loan application {aid}.",
                script=steps,
                expected_tools=expected,
                expected_final_contains=contains,
                world_check=check,
            )
        )
    return tasks


TASKS: list[ScriptedTask] = make_tasks()
