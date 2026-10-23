"""What the console needs at runtime: the process Runtime (store, chain, gateway), the case
service, the inbox and the principal provider. Built once from the app's runtime."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from supervisor.adapters.auth import PrincipalProvider, build_principal_provider, set_provider
from supervisor.adapters.notify import InboxNotifier, build_notifier
from supervisor.cases import CaseService, build_case_service
from supervisor.config import Settings
from supervisor.console.onboard_runs import OnboardRunner

log = logging.getLogger("supervisor.console")


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
    degraded_until: float = 0.0  # WP-P5: monotonic time of the next SP retry; 0 = healthy

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
    def controls(self) -> Any:
        """The control catalogue service (WP30, ADR D30). Changes and status go on the chain."""
        from supervisor.controls.service import ControlService

        svc = getattr(self, "_controls", None)
        if svc is None:
            svc = ControlService(
                self.state, self.tables, self.clock, self.settings, evidence=self.runtime.chain
            )
            self._controls = svc
        return svc

    @property
    def tasks(self) -> Any:
        """The task list service (WP30, ADR D30). Every change goes on the chain."""
        from supervisor.tasks.service import TaskService

        svc = getattr(self, "_tasks", None)
        if svc is None:
            svc = TaskService(
                self.state,
                self.tables,
                self.clock,
                self.settings,
                evidence=self.runtime.chain,
                controls=self.controls,
            )
            self._tasks = svc
        return svc

    @property
    def systems(self) -> Any:
        """The AI system service (WP-G0, docs/governance.md). Every change goes on the chain."""
        from supervisor.governance.systems import SystemService

        svc = getattr(self, "_systems", None)
        if svc is None:
            svc = SystemService(
                self.state, self.tables, self.clock, self.settings, evidence=self.runtime.chain
            )
            self._systems = svc
        return svc

    @property
    def rules(self) -> Any:
        """The assignment rules service (WP-G2, docs/assignment-rules.md). Runs go on the chain."""
        from supervisor.governance.rules_service import RulesService

        svc = getattr(self, "_rules", None)
        if svc is None:
            svc = RulesService(
                self.state, self.tables, self.clock, self.settings, evidence=self.runtime.chain
            )
            self._rules = svc
        return svc

    @property
    def guardians(self) -> Any:
        """The per-system guardian bindings service (WP-S1, docs/guardian-bindings.md). Every
        change goes on the chain as ``binding_change``."""
        from supervisor.governance.guardians import GuardianService

        svc = getattr(self, "_guardians", None)
        if svc is None:
            svc = GuardianService(
                self.state, self.tables, self.clock, self.settings, evidence=self.runtime.chain
            )
            self._guardians = svc
        return svc

    @property
    def classification(self) -> Any:
        """The Decision 33 classification service (WP-G2, docs/decision33.md). The chat model is
        built only when CLASSIFIER_AI_PREFILL is on; the service never applies by itself."""
        from supervisor.governance.classification import ClassificationService

        svc = getattr(self, "_classification", None)
        if svc is None:
            chat = masker = None
            if self.settings.classifier_ai_prefill:
                from supervisor.adapters.factory import make_chat_model, make_masker

                chat = make_chat_model(self.settings)
                masker = make_masker(self.settings)
            svc = ClassificationService(
                self.state,
                self.tables,
                self.clock,
                self.settings,
                evidence=self.runtime.chain,
                chat=chat,
                masker=masker,
            )
            self._classification = svc
        return svc

    @property
    def lifecycle(self) -> Any:
        """Stage approvals and the lifecycle move of an AI system (WP-G1). Shares the system
        service, so every change goes on the chain."""
        from supervisor.governance.lifecycle import LifecycleService

        svc = getattr(self, "_lifecycle", None)
        if svc is None:
            svc = LifecycleService(self.systems)
            self._lifecycle = svc
        return svc

    @property
    def reviews(self) -> Any:
        """Reviews of an AI system (WP-G1)."""
        from supervisor.governance.reviews import ReviewService

        svc = getattr(self, "_reviews", None)
        if svc is None:
            svc = ReviewService(self.systems)
            self._reviews = svc
        return svc

    @property
    def incidents(self) -> Any:
        """Incidents of the governance loop (WP-G5). Scoped by the system service; every change
        goes on the chain."""
        from supervisor.governance.incidents import IncidentService

        svc = getattr(self, "_incidents", None)
        if svc is None:
            svc = IncidentService(
                self.state,
                self.clock,
                self.settings,
                evidence=self.runtime.chain,
                systems=self.systems,
            )
            self._incidents = svc
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

            settings = get_settings()
            try:
                _ctx = build_context(gate_wiring.install_runtime(settings))
            except Exception as exc:
                if not settings.sql_user_token_forward:
                    raise
                # WP-P5: the SP cannot build the runtime (no SQL grant yet). Serve reads as the
                # signed-in user; gate and chain paths answer HTTP 400. Retried every 60 s.
                from supervisor.wiring import build_degraded_runtime

                log.warning(
                    "[WARN] SP has no SQL access (%s); console runs degraded: reads run as the "
                    "signed-in user, gateway and evidence chain answer 400 until the service "
                    "principal is granted",
                    type(exc).__name__,
                )
                _ctx = build_context(build_degraded_runtime(settings))
                _ctx.degraded_until = time.monotonic() + 60.0
        elif _ctx.degraded_until and time.monotonic() > _ctx.degraded_until:
            _ctx = _retry_degraded(_ctx)
        return _ctx


def _retry_degraded(ctx: ConsoleContext) -> ConsoleContext:
    """WP-P5: try the SP runtime build again; keep the degraded context while it fails."""
    from supervisor.config import get_settings
    from supervisor.gateway import wiring as gate_wiring

    try:
        new = build_context(gate_wiring.install_runtime(get_settings()))
    except Exception:  # noqa: BLE001 - still no grant
        ctx.degraded_until = time.monotonic() + 60.0
        return ctx
    try:  # the old degraded adapters are not used any more
        ctx.runtime.adapters.close()
    except Exception:  # noqa: BLE001, S110
        pass
    return new
