"""Stage 3 Plan: monitoring plan and remediation playbook from the capability catalogue.

Pure function. Capabilities are selected by the agent's tool risk classes and features
(``Catalogue.select``). Gate-rule capabilities become ``PlannedRule`` specs in the
gateway policy schema (``supervisor.gateway.policy.RuleSpec``); limits come from the
agent manifest, other thresholds from the catalogue defaults. All numbers are integers
(basis points, minor units, seconds, counts). Block and pause rules carry
``FILL-ME-approver`` placeholders: two named people must approve before merge.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from supervisor.catalogue import Catalogue, coverage_rows, load_catalogue
from supervisor.catalogue.model import CapabilityManifest
from supervisor.onboard.discover import RISK_ORDER, record_flag
from supervisor.onboard.models import (
    AgentProfile,
    CapabilityChoice,
    CostPlan,
    Inventory,
    JudgePlan,
    MonitoringPlan,
    PlannedRule,
    PlaybookEntry,
    RemediationPlaybook,
    ToolInfo,
)

APPROVER_PLACEHOLDERS = ["FILL-ME-approver-risk", "FILL-ME-approver-compliance"]
DEFAULT_EVENTS_PER_DAY = 10_000
SLA_MINUTES = {"critical": 5, "high": 30, "medium": 240, "low": 1440}
SLICES = ["segment", "province", "language"]


def rule_prefix(agent_id: str) -> str:
    return "OB-" + re.sub(r"[^A-Z0-9]", "_", agent_id.upper())[:24]


def plan(
    inventory: Inventory,
    profile: AgentProfile,
    catalogue: Catalogue | None = None,
    *,
    events_per_day: int = DEFAULT_EVENTS_PER_DAY,
) -> tuple[MonitoringPlan, RemediationPlaybook]:
    cat = catalogue or load_catalogue()
    plug = "gate_hook" if inventory.plug_point in ("gate_hook", "sdk") else inventory.plug_point
    selection = cat.select(inventory.risk_classes, inventory.features, plug_point=plug)
    choices = [
        CapabilityChoice(id=m.id, name=m.name, kind=m.kind, lane=m.lane, status="on")
        for m in selection.on
    ] + [
        CapabilityChoice(id=m.id, name=m.name, kind=m.kind, lane=m.lane, status="off", reason=r)
        for m, r in selection.off
    ]
    on = {m.id: m for m in selection.on}
    rules = _rules(inventory, on)
    thresholds: dict[str, int] = {}
    for m in selection.on:
        for k, v in sorted(m.default_thresholds.items()):
            thresholds[f"{m.id}.{k}"] = v
    for lim in inventory.limits:
        thresholds[f"limit.{lim.key}"] = lim.value
    judges = [
        JudgePlan(
            id=m.id,
            sample_bp=m.default_thresholds.get("sample_bp", 10000),
            threshold_bp=m.default_thresholds.get(
                "escalate_bp",
                m.default_thresholds.get(
                    "confirm_bp", m.default_thresholds.get("min_groundedness_bp", 5000)
                ),
            ),
            family_must_differ_from=inventory.model_family,
        )
        for m in selection.on
        if m.kind == "judge"
    ]
    sampling = {f"{j.id}_sample_bp": j.sample_bp for j in judges}
    signals = sorted({s for m in selection.on for s in m.signals_needed})
    monitoring = MonitoringPlan(
        agent_id=inventory.agent_id,
        capabilities=choices,
        signals=signals,
        thresholds=thresholds,
        judges=judges,
        slices=SLICES if "fairness_slices" in on else [],
        sampling=sampling,
        cost=_cost(selection.on, sampling, events_per_day),
        rules=rules,
        coverage=coverage_rows(inventory.agent_id, selection, status_on="planned"),
    )
    return monitoring, _playbook(inventory, profile, monitoring, on)


# --------------------------------------------------------------------------- rules


def _base(
    rid: str,
    cap: CapabilityManifest,
    inv: Inventory,
    description: str,
    action: str,
    severity: str,
    risk_class: str,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "id": rid,
        "version": 1,
        "description": description[:500],
        "agent_scope": [inv.agent_id],
        "action": action,
        "severity": severity,
        "risk_class": risk_class,
        "regulation_ref": cap.regulation_refs[0] if cap.regulation_refs else None,
        "owner": inv.owner_team,
    }
    if action in ("block", "pause"):
        spec["approvals"] = list(APPROVER_PLACEHOLDERS)
    return spec


def _evs(*tools: ToolInfo) -> list[Any]:
    return [e for t in tools for e in (t.definition, t.manifest_entry) if e is not None]


def _rules(inv: Inventory, on: dict[str, CapabilityManifest]) -> list[PlannedRule]:
    out: list[PlannedRule] = []
    prefix = rule_prefix(inv.agent_id)

    def add(cap_id: str, spec: dict[str, Any], evidence: Sequence[Any]) -> None:
        out.append(
            PlannedRule(
                rule_id=spec["id"], capability_id=cap_id, spec=spec, evidence=list(evidence)[:6]
            )
        )

    def rid() -> str:
        return f"{prefix}-{len(out) + 1:02d}"

    tools = inv.tools
    by_name = {t.name: t for t in tools}
    per_call = {lim.tool: lim for lim in inv.limits if lim.period == "per_call" and lim.tool}
    daily = {lim.tool: lim for lim in inv.limits if lim.period == "daily" and lim.tool}
    top_class = max((t.risk_class for t in tools), key=lambda c: RISK_ORDER[c], default="read_only")

    if "approved_tools" in on and tools:
        approved = [t.name for t in tools if t.approved]
        unapproved = [t for t in tools if not t.approved]
        spec = _base(
            rid(),
            on["approved_tools"],
            inv,
            f"{inv.name} may call approved tools only"
            + (f" ({', '.join(t.name for t in unapproved)} is not approved)" if unapproved else ""),
            "pause",
            "critical",
            top_class,
        )
        spec["when"] = {"tool": {"not_in": approved or ["__none__"]}}
        add(
            "approved_tools",
            spec,
            [e for t in unapproved for e in (t.approval_evidence, t.manifest_entry) if e]
            or _evs(*tools[:1]),
        )

    money_amount = [t for t in tools if t.risk_class == "money" and t.amount_arg]
    if "amount_valid" in on and money_amount:
        for arg in sorted({t.amount_arg for t in money_amount if t.amount_arg}):
            group = [t for t in money_amount if t.amount_arg == arg]
            spec = _base(
                rid(),
                on["amount_valid"],
                inv,
                f"A money call must state {arg} as a positive integer",
                "block",
                "high",
                "money",
            )
            spec["when"] = {
                "tool": {"in": [t.name for t in group]},
                "any": [{"arg": arg, "op": "absent"}, {"arg": arg, "op": "le", "value": 0}],
            }
            add("amount_valid", spec, _evs(*group))

    if "single_limit" in on:
        for name, lim in sorted(per_call.items()):
            t = by_name.get(name)
            if t is None or not t.amount_arg or t.risk_class not in ("money", "credit"):
                continue
            spec = _base(
                rid(),
                on["single_limit"],
                inv,
                f"Single {name} limit {lim.value} ({lim.key})",
                "block",
                "high",
                t.risk_class,
            )
            spec["when"] = {
                "tool": name,
                "all": [{"arg": t.amount_arg, "op": "gt", "value": lim.value}],
            }
            add("single_limit", spec, [lim.evidence, *_evs(t)])

    if "daily_aggregate" in on:
        n_max = on["daily_aggregate"].default_thresholds.get("max_calls_per_key_per_day", 2)
        window = on["daily_aggregate"].default_thresholds.get("window_s", 86400)
        for t in tools:
            if t.risk_class not in ("money", "credit") or not t.key_args or not t.approved:
                continue
            key = t.key_args[0]
            agg: dict[str, Any] = {
                "window_s": window,
                "group_by": "customer",
                "customer_arg": key,
                "op": "gt",
            }
            if t.name in daily and t.amount_arg:
                lim = daily[t.name]
                agg.update(fn="sum", field=t.amount_arg, limit=lim.value)
                desc, action, sev, ev = (
                    f"Daily {t.name} total per {key} above {lim.value} ({lim.key})",
                    "pause",
                    "critical",
                    [lim.evidence, *_evs(t)],
                )
            elif t.risk_class == "credit" and t.name in per_call and t.amount_arg:
                lim = per_call[t.name]
                agg.update(fn="sum", field=t.amount_arg, limit=lim.value)
                desc, action, sev, ev = (
                    f"Daily {t.name} total per {key} above the ceiling {lim.value} "
                    "(split decisions)",
                    "block",
                    "high",
                    [lim.evidence, *_evs(t)],
                )
            else:
                agg.update(fn="count", limit=n_max)
                desc, action, sev, ev = (
                    f"At most {n_max} {t.name} calls per {key} per day",
                    "block",
                    "high",
                    _evs(t),
                )
            spec = _base(rid(), on["daily_aggregate"], inv, desc, action, sev, t.risk_class)
            spec["when"] = {"tool": t.name}
            spec["aggregate"] = agg
            add("daily_aggregate", spec, ev)

    if "split_payment" in on:
        window = on["split_payment"].default_thresholds.get("window_s", 3600)
        for t in tools:
            if (
                t.risk_class != "money"
                or not t.destination_arg
                or not t.key_args
                or not t.amount_arg
                or t.name not in per_call
                or not t.approved
            ):
                continue
            lim = per_call[t.name]
            spec = _base(
                rid(),
                on["split_payment"],
                inv,
                f"Split payment: {t.name} from one {t.key_args[0]} to one {t.destination_arg} "
                f"within {window} s above the single limit {lim.value}, whichever agent "
                "handed the work over",
                "block",
                "high",
                "money",
            )
            spec["when"] = {"tool": t.name}
            spec["aggregate"] = {
                "fn": "sum",
                "field": t.amount_arg,
                "window_s": window,
                "group_by": "customer",
                "customer_arg": t.key_args[0],
                "also_by": [t.destination_arg],
                "op": "gt",
                "limit": lim.value,
            }
            add("split_payment", spec, [lim.evidence, *_evs(t)])

    decisions = [t for t in tools if t.risk_class == "credit" and "decision" in t.args]
    reads = [t for t in tools if t.risk_class in ("read_only", "pii_export")]
    approve_word = next(
        (
            v
            for vals in inv.constants.values()
            for v in vals
            if v.lower() in ("approve", "approved", "accept")
        ),
        None,
    )
    if "system_of_record" in on:
        for d in decisions:
            ids = [a for a in d.args if a.endswith("_id")]
            for r in reads:
                flag = record_flag(r)
                shared = [a for a in ids if a in r.args]
                if not flag or not shared:
                    continue
                source = shared[0][: -len("_id")]
                preds: list[dict[str, Any]] = []
                if approve_word:
                    preds.append({"arg": "decision", "op": "eq", "value": approve_word})
                preds.append({"arg": f"fact.{source}.{flag}", "op": "ne", "value": True})
                spec = _base(
                    rid(),
                    on["system_of_record"],
                    inv,
                    f"{d.name} may approve only when the system of record says "
                    f"{source}.{flag} is true",
                    "block",
                    "high",
                    "credit",
                )
                spec["when"] = {"tool": d.name, "all": preds}
                add("system_of_record", spec, _evs(d, r))
                break

    if "prior_read" in on:
        within = on["prior_read"].default_thresholds.get("within_s", 86400)
        for d in decisions:
            ids = [a for a in d.args if a.endswith("_id")]
            r = next(
                (r for r in reads if r.risk_class == "pii_export" and set(ids) & set(r.args)),
                None,
            ) or next((r for r in reads if set(ids) & set(r.args)), None)
            if r is None:
                continue
            match = sorted(set(ids) & set(r.args))[:1]
            spec = _base(
                rid(),
                on["prior_read"],
                inv,
                f"{d.name} needs {r.name} of the same {match[0]} first (same agent)",
                "block",
                "high",
                "credit",
            )
            spec["when"] = {"tool": d.name}
            spec["prior"] = {
                "tool": r.name,
                "within_s": within,
                "match_args": match,
                "mode": "absent",
                "same_agent": True,
            }
            add("prior_read", spec, _evs(d, r))

    if "pii_bulk_read" in on:
        pii = [t.name for t in tools if t.risk_class == "pii_export" and t.approved]
        if pii:
            th = on["pii_bulk_read"].default_thresholds
            spec = _base(
                rid(),
                on["pii_bulk_read"],
                inv,
                f"At most {th.get('max_calls_per_agent_per_hour', 20)} personal-data tool "
                "calls per agent per hour (bulk export pattern)",
                "block",
                "high",
                "pii_export",
            )
            spec["when"] = {"tool": {"in": pii}}
            spec["aggregate"] = {
                "fn": "count",
                "window_s": th.get("window_s", 3600),
                "group_by": "agent",
                "tools": pii,
                "op": "gt",
                "limit": th.get("max_calls_per_agent_per_hour", 20),
            }
            add("pii_bulk_read", spec, _evs(*[by_name[n] for n in pii]))
    return out


# --------------------------------------------------------------------------- cost, playbook


def _cost(
    on: Sequence[CapabilityManifest], sampling: dict[str, int], events_per_day: int
) -> CostPlan:
    tokens = compute = storage = 0
    for m in on:
        share = sampling.get(f"{m.id}_sample_bp", 10000)
        c = m.cost_estimate
        tokens += c.llm_tokens_per_1k_events * events_per_day * share // (1000 * 10000)
        compute += c.compute_ms_per_1k_events * events_per_day * share // (1000 * 10000)
        storage += c.storage_bytes_per_1k_events * events_per_day // 1000
    return CostPlan(
        events_per_day_assumed=events_per_day,
        llm_tokens_per_day=tokens,
        compute_ms_per_day=compute,
        storage_bytes_per_day=storage,
    )


def _playbook(
    inv: Inventory,
    profile: AgentProfile,
    mp: MonitoringPlan,
    on: dict[str, CapabilityManifest],
) -> RemediationPlaybook:
    entries: list[PlaybookEntry] = []
    owner = inv.owner_team
    for r in mp.rules:
        action = r.spec["action"]
        sev = r.spec["severity"]
        steps = [f"Read the case file for {r.rule_id}: rule, arguments digest, evidence hashes."]
        if action == "pause":
            steps += [
                "The agent is paused: non-read-only tools are blocked until resume.",
                "Agent owner and a reviewer check the case; resume needs both (two-person).",
                "If the call was an attack, keep the agent paused and open an incident.",
            ]
        elif action == "block":
            steps += [
                "The call did not run. Contact the customer if a legitimate request was refused.",
                "If blocks repeat for one customer or payee, pause the agent manually.",
            ]
        else:
            steps += ["Review within the SLA; raise to block only by a policy change."]
        steps.append(
            "Decision 33: a pause or block is a safety control, not the pre-execution "
            "human approval the agent workflow needs."
        )
        entries.append(
            PlaybookEntry(
                trigger=r.rule_id,
                kind="rule",
                action=action,
                severity=sev,
                first_responder=owner,
                sla_minutes=SLA_MINUTES[sev],
                steps=steps,
            )
        )
    for cid in sorted(on):
        m = on[cid]
        if m.kind not in ("judge", "monitor"):
            continue
        entries.append(
            PlaybookEntry(
                trigger=cid,
                kind="capability",
                action="alert",
                severity="medium",
                first_responder="Supervisor reviewers",
                sla_minutes=SLA_MINUTES["medium"],
                steps=[
                    f"{m.name} opened a case (advisory: judges and monitors never block).",
                    "A reviewer checks the masked trace and the evidence links.",
                    "If confirmed, the reviewer may pause the agent (human decision) and "
                    "proposes a deterministic rule through a pull request.",
                ],
            )
        )
    return RemediationPlaybook(agent_id=profile.agent_id, entries=entries)
