"""``GET /v1/portfolio`` (WP-C4): the data of the two portfolio blocks of My overview as integers.
Mounted by ``app.py`` with CONSOLE_OVERVIEW_V4=1; answers HTTP 400 ``overview_portfolio_off`` until
OVERVIEW_PORTFOLIO=1 (and GOVERNANCE_ENABLED). Permission: systems.view. Read only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.console import portfolio
from supervisor.console.context import ConsoleContext, get_context

api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)


@api_router.get("/portfolio", dependencies=[Depends(needs("systems.view"))])
def get_portfolio(ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    return portfolio.api_body(ctx, me)
