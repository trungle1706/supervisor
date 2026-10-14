"""What the console needs at runtime: the process Runtime (store, chain, gateway), the case
service, the inbox and the principal provider. Built once from the app's runtime."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from supervisor.adapters.auth import PrincipalProvider, build_principal_provider, set_provider
from supervisor.adapters.notify import InboxNotifier, build_notifier
from supervisor.cases import CaseService, build_case_service
from supervisor.config import Settings


@dataclass
class ConsoleContext:
    settings: Settings
    runtime: Any  # supervisor.wiring.Runtime
    cases: CaseService
    inbox: InboxNotifier
    provider: PrincipalProvider
    last_verify: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def gateway(self) -> Any:
        return self.runtime.gateway

    @property
    def tables(self) -> Any:
        return self.runtime.adapters.tables

    @property
    def state(self) -> Any:
        return self.runtime.adapters.state

    @property
    def clock(self) -> Any:
        return self.runtime.adapters.clock


def build_context(runtime: Any, provider: PrincipalProvider | None = None) -> ConsoleContext:
    settings = runtime.settings
    provider = provider or build_principal_provider(settings)
    set_provider(provider)
    from supervisor.adapters.factory import make_masker

    masker = make_masker(settings)
    notifier, inbox = build_notifier(
        settings, runtime.adapters.state, runtime.adapters.clock, masker
    )
    cases = build_case_service(
        runtime, system=provider.background(), notifier=notifier, masker=masker
    )
    return ConsoleContext(settings, runtime, cases, inbox, provider)


_lock = threading.RLock()
_ctx: ConsoleContext | None = None


def set_context(ctx: ConsoleContext | None) -> None:
    global _ctx
    with _lock:
        _ctx = ctx


def get_context() -> ConsoleContext:
    """The process-wide context; built from the installed runtime on first use."""
    global _ctx
    with _lock:
        if _ctx is None:
            from supervisor.config import get_settings
            from supervisor.gateway import wiring as gate_wiring

            _ctx = build_context(gate_wiring.install_runtime(get_settings()))
        return _ctx
