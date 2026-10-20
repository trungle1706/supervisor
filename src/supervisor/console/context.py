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
from supervisor.console.onboard_runs import OnboardRunner


@dataclass
class ConsoleContext:
    settings: Settings
    runtime: Any  # supervisor.wiring.Runtime
    cases: CaseService
    inbox: InboxNotifier
    provider: PrincipalProvider
    last_verify: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    onboard: OnboardRunner = field(default_factory=OnboardRunner)

    @property
    def alerts(self) -> Any:
        """The alert service (WP21): reads and acknowledges ``alert`` rows. Sending is the
        scheduler job's work, so this one has no routes."""
        from supervisor.alerts import AlertService

        svc = getattr(self, "_alerts", None)
        if svc is None:
            svc = AlertService(self.state, self.clock, self.runtime.chain)
            self._alerts = svc
        return svc

    @property
    def risks(self) -> Any:
        """The risk register service (WP29, ADR D26). Changes and evidence go on the chain."""
        from supervisor.risk.service import RiskService

        svc = getattr(self, "_risks", None)
        if svc is None:
            svc = RiskService(
                self.state, self.tables, self.clock, self.settings, evidence=self.runtime.chain
            )
            self._risks = svc
        return svc

    @property
    def transparency(self) -> Any:
        """The transparency report service (WP31, ADR D31). Signed reports go on the chain."""
        from supervisor.transparency.service import TransparencyService

        svc = getattr(self, "_transparency", None)
        if svc is None:
            svc = TransparencyService.from_context(self)
            self._transparency = svc
        return svc

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


def peek_context() -> ConsoleContext | None:
    """The process-wide context if one exists; never builds one."""
    with _lock:
        return _ctx


def get_context() -> ConsoleContext:
    """The process-wide context; built from the installed runtime on first use."""
    global _ctx
    with _lock:
        if _ctx is None:
            from supervisor.config import get_settings
            from supervisor.gateway import wiring as gate_wiring

            _ctx = build_context(gate_wiring.install_runtime(get_settings()))
        return _ctx
