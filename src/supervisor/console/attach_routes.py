"""Attach view routes (WP-O4, ``ONBOARD_ATTACH_VIEW``): the Attach panel of an agent and a
candidate. The router is always mounted; with the flag off every route answers HTTP 400
``attach_off`` (nothing is read or written).

* ``GET  /console/attach/{node_id}``        the panel (an htmx fragment; a full page without htmx),
                                            ``systems.view``
* ``POST /console/attach/{node_id}/check``  **Check now**: reads the gate state and the last
                                            evidence again and returns the refreshed panel
                                            (``systems.edit``, htmx only, two audit rows). It does
                                            not call the candidate.

The wiring picture is laid out here (coordinates only, all integers); the template draws it. See
``supervisor.console.attach_view`` for the data and ``docs/guardian-bindings.md`` "Attach view"."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import agent_detail, attach_view
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.routes import _call, _htmx_only, audited, message_html, render
from supervisor.core.errors import SupervisorError
from supervisor.onboard import intake

router = APIRouter(prefix="/console", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)

FLAG_TEXT = "the attach view is off (ONBOARD_ATTACH_VIEW=1 turns it on)"
PER_ROW = 9  # circles in one row of a group box
STEP_X, STEP_Y = 20, 22


class AttachError(SupervisorError):
    """A refused request. ``code`` is the stable machine word; the message starts with it."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


def require_on(settings: Any) -> None:
    if not settings.onboard_attach_view:
        raise AttachError("attach_off", FLAG_TEXT)


def _short(text: str, limit: int = 20) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def layout(model: dict[str, Any]) -> dict[str, Any]:
    """Integer coordinates of the wiring picture: three boxes on the left (agent, plug point, gate)
    and one box per guardian group on the right, one circle per item inside it."""
    gx, gw = 590, 200
    y = 10
    groups = []
    for g in model["groups"]:
        n = len(g["items"])
        rows = max(1, -(-n // PER_ROW))
        h = 32 + rows * STEP_Y
        circles = [
            {
                "cx": gx + 16 + (i % PER_ROW) * STEP_X,
                "cy": y + 40 + (i // PER_ROW) * STEP_Y,
                "item": item,
            }
            for i, item in enumerate(g["items"])
        ]
        groups.append(
            {
                "key": g["key"],
                "x": gx,
                "y": y,
                "w": gw,
                "h": h,
                "circles": circles,
                "mid": y + h // 2,
            }
        )
        y += h + 10
    height = max(y, 120)
    mid = height // 2
    box_h = 56
    boxes = {
        "agent": {"x": 10, "w": 150},
        "plug": {"x": 200, "w": 160},
        "gate": {"x": 400, "w": 150},
    }
    for b in boxes.values():
        b["y"], b["h"], b["mid"] = mid - box_h // 2, box_h, mid
    return {
        "w": 800,
        "h": height,
        "boxes": boxes,
        "groups": groups,
        "mid": mid,
        "agent_label": _short(model["agent_id"]),
    }


def panel_data(
    ctx: ConsoleContext, me: AuthPrincipal, node_id: str, checked: bool = False
) -> dict[str, Any]:
    """Template variables of the Attach panel (``_attach_panel.html``). ``checked`` is true after
    Check now: only then the panel shows the read time (a plain GET stays the same text twice)."""
    model = attach_view.attach_model(ctx, node_id)
    return {
        "at": {
            "node_id": node_id,
            "m": model,
            "svg": layout(model),
            "how": attach_view.how_to_attach(ctx, node_id, model["plug"]["kind"]),
            "can_edit": agent_detail.can(me, "systems.edit"),
            "checked": checked,
        }
    }


@router.get(
    "/attach/{node_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.view"))],
)
async def attach_panel(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    intake.check_node_id(node_id)
    data = await _call(panel_data, ctx, me, node_id)
    if request.headers.get("hx-request") == "true":
        return render(request, ctx, me, "_attach_panel.html", **data)
    return render(request, ctx, me, "attach.html", section="candidates", **data)


def _reread(ctx: ConsoleContext, node_id: str) -> None:
    """Drop the cached gate state of the agent so the next read comes from the store."""
    try:
        ctx.gateway.states.invalidate(node_id)
    except Exception:  # noqa: BLE001, S110 - no gateway state machine: the model reads what it can
        pass


@router.post(
    "/attach/{node_id}/check",
    response_class=HTMLResponse,
    dependencies=[Depends(needs("systems.edit"))],
)
@audited("systems.edit")
async def attach_check(
    node_id: str, request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    _htmx_only(request)
    require_on(ctx.settings)
    intake.check_node_id(node_id)
    await _call(_reread, ctx, node_id)
    data = await _call(panel_data, ctx, me, node_id, True)
    counts = data["at"]["m"]["counts"]
    request.state.audit_detail = f"lit={counts['lit']} items={counts['total']}"
    resp = render(request, ctx, me, "_attach_panel.html", **data)
    note = f"{node_id}: checked now, {counts['lit']} of {counts['total']} guardians have evidence"
    resp.body = resp.body + message_html(note, ok=True, oob=True).encode()
    resp.headers["content-length"] = str(len(resp.body))
    return resp
