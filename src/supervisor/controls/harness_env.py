"""A temporary store for the WP30 harness and tests: the WP29 environment plus the control and
task services. No model, no network. Not used by the app."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from supervisor.controls.refs import ControlRefs
from supervisor.controls.service import ControlService
from supervisor.risk.harness import _Env
from supervisor.risk.refs import RefCatalogue
from supervisor.tasks.model import TaskConfig, load_config
from supervisor.tasks.service import TaskService


class CtlEnv(_Env):
    """SQLite store with agents, runtime rows, a risk service, a control service and a task
    service. The reference catalogue is small and fixed: obligation OB-1 and OB-2, rules PAY-02
    and PAY-03 (scoped to the agent ``pay``), SVC-01 (scoped to ``svc``), packs pack_a and
    pack_b, the monitor ``oversight`` and ``drift``."""

    RULE_SCOPES = {"PAY-02": ["pay"], "PAY-03": ["pay"], "SVC-01": ["svc"]}

    def __init__(self, cfg: TaskConfig | None = None, sink: Any = None) -> None:
        super().__init__()
        self.settings.controls_enabled = True
        self.settings.risk_register_enabled = True
        self.rules = {"PAY-02", "PAY-03", "SVC-01"}
        cat = RefCatalogue(
            obligations=lambda: ["OB-1", "OB-2"],
            rules=lambda: self.rules,
            packs=lambda: ["pack_a", "pack_b"],
            monitors=lambda: ["oversight", "drift"],
            case_exists=lambda c: False,
            controls=lambda: [
                r["control_id"]
                for r in self.adapters.state.query("control")
                if r["status"] != "retired"
            ],
        )
        self.svc.catalogue = cat
        self.svc.evidence_sink = sink
        self.refs = ControlRefs(
            cat,
            risks=lambda: [r["risk_id"] for r in self.adapters.state.query("risk")],
            rule_scopes=lambda: self.RULE_SCOPES,
        )
        self.controls = ControlService(
            self.adapters.state,
            self.adapters.tables,
            self.adapters.clock,
            self.settings,
            evidence=sink,
            refs=self.refs,
            risks=self.svc,
        )
        self.tasks = TaskService(
            self.adapters.state,
            self.adapters.tables,
            self.adapters.clock,
            self.settings,
            evidence=sink,
            cfg=cfg or load_config(self.settings.tasks_config),
            controls=self.controls,
            risks=self.svc,
        )

    def classify(self, agent_id: str, d33_class: str | None, tier: str = "high") -> None:
        row = self.adapters.state.get("agent", {"agent_id": agent_id})
        self.adapters.state.update(
            "agent",
            {"agent_id": agent_id},
            {"decision33_class": d33_class, "risk_tier": tier},
            row["row_version"],
        )

    def control(
        self,
        control_id: str,
        evidence: Sequence[tuple[str, str]] = (("rule", "PAY-02"),),
        covers: Sequence[tuple[str, str]] = (("matrix", "OB-1"),),
        **kw: Any,
    ) -> dict[str, Any]:
        data = {
            "title": f"Control {control_id}",
            "objective": "Hold a risk down.",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "ops",
            "status": "active",
            "review_date": "2027-04-20",
            "agents": ["pay"],
        } | kw
        return self.controls.create(
            data, "harness", control_id=control_id, maps=[*covers, *evidence]
        )
