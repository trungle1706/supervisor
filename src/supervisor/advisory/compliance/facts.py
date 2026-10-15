"""Product facts (WP14): build a ``ProductProfile`` from an onboarded product or a questionnaire.

Rules kept here:
- A fact the code cannot prove stays ``None`` (or an incomplete set); it becomes a question.
- Every derived fact gets a ``Pointer`` in ``provenance`` (file:line, rule id, manifest key,
  plan, questionnaire field).
- Money is integer VND.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from supervisor.advisory.compliance.model import (
    LimitFact,
    Pointer,
    ProductControls,
    ProductProfile,
    RuleFact,
)
from supervisor.onboard.models import AgentProfile, Evidence, Inventory, MonitoringPlan, ToolInfo
from supervisor.onboard.understand import autonomy_level
from supervisor.regkb.loader import REPO_ROOT

__all__ = [
    "ProfileInputError",
    "apply_answers",
    "from_onboard",
    "from_questionnaire",
    "load_profile_input",
    "policy_facts",
    "standard_controls",
]

CONTROLS_YAML = REPO_ROOT / "regulations" / "schema" / "controls.yaml"
AUTONOMY_MAP = {"L0": "advisory", "L1": "advisory", "L2": "acts_with_approval"}  # L3 = autonomous
# Catalogue capability id -> controls.yaml monitor name. Checked against controls.yaml in tests.
# groundedness (kind judge) is scored by supervisor.monitors.quality (groundedness_bp).
CAPABILITY_MONITOR = {
    "fairness_slices": "fairness",
    "drift_band": "drift",
    "groundedness": "quality",
}
# Evidence ids every supervised product has (Supervisor writes them for each registered agent).
# Not in this list on purpose: fairness_slice needs the fairness monitor; oversight_metric needs
# the oversight monitor (a daily job, METRICS_ENABLED, off by default, so it is not assumed);
# verdict_log needs a judge capability. The plan or the questionnaire must say so.
SUPERVISED_EVIDENCE = (
    "agent_event_log",
    "agent_registry",
    "agent_version",
    "audit_pack",
    "case_file",
    "chain_verify_report",
    "coverage_rows",
    "evidence_chain",
    "policy_baseline",
    "signoff_record",
)


class ProfileInputError(ValueError):
    """An input file for the advisor is missing or unreadable (message is safe to show)."""


# ----------------------------------------------------------------------------- controls.yaml


def _controls_yaml() -> dict[str, Any]:
    data = yaml.safe_load(CONTROLS_YAML.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _evidence_pointer(eid: str, spec: Mapping[str, Any], note: str) -> Pointer:
    if "table" in spec:
        return Pointer("table", str(spec["table"]), note)
    module = str(spec.get("module", eid))
    return Pointer("file", "src/" + module.replace(".", "/") + ".py", note)


def standard_controls(
    *,
    basis: str,
    supervised: bool,
    catalogue_on: Sequence[str] = (),
    rules: Sequence[RuleFact] = (),
    monitors: Iterable[str] = (),
    evidence: Iterable[str] = (),
    policy_files: Sequence[str] = (),
    extra_pointers: Mapping[str, Pointer] | None = None,
    judge_on: bool = False,
) -> ProductControls:
    """Assemble ``ProductControls``; a supervised product gets the standard evidence ids and
    every console screen of controls.yaml. Every present control gets a pointer
    (``extra_pointers`` wins over the generic one)."""
    spec = _controls_yaml()
    ev_spec: Mapping[str, Any] = spec.get("evidence", {})
    console_spec: Mapping[str, Any] = spec.get("console", {})
    ev_ids = set(evidence)
    console: tuple[str, ...] = ()
    pointers: dict[str, Pointer] = {}
    note = (
        "planned: present after the onboarding pull request merges"
        if basis == "planned"
        else "Supervisor records this for every registered agent"
    )
    if supervised:
        ev_ids |= set(SUPERVISED_EVIDENCE)
        console = tuple(sorted(console_spec))
        for name in console:
            pointers[f"console:{name}"] = Pointer("console", str(console_spec[name]["path"]), note)
    if judge_on:
        ev_ids.add("verdict_log")
    for eid in sorted(ev_ids):
        pointers[f"evidence:{eid}"] = _evidence_pointer(eid, ev_spec.get(eid, {}), note)
    mons = sorted(set(monitors))
    for cid in catalogue_on:
        pointers[f"catalogue:{cid}"] = Pointer("plan", cid, f"capability {cid} is on ({basis})")
    for r in rules:
        pointers[f"rule:{r.id}"] = r.pointer
    for m in mons:
        pointers[f"monitor:{m}"] = Pointer("catalogue", m, "monitor named in the input")
    pointers.update(extra_pointers or {})
    return ProductControls(
        known=True,
        basis=basis,
        supervised=supervised,
        catalogue_on=tuple(catalogue_on),
        rules=tuple(rules),
        monitors=tuple(mons),
        evidence=tuple(sorted(ev_ids)),
        console=console,
        pointers=pointers,
        policy_files=tuple(policy_files),
    )


# ----------------------------------------------------------------------------- policy


def _rule_line(text: str, rule_id: str) -> int | None:
    rx = re.compile(rf"^\s*-\s*id:\s*['\"]?{re.escape(rule_id)}['\"]?\s*(#.*)?$")
    for i, line in enumerate(text.splitlines(), start=1):
        if rx.match(line):
            return i
    return None


def _tools_of(when: Any) -> tuple[str, ...]:
    tool = when.get("tool") if isinstance(when, dict) else None
    if isinstance(tool, str):
        return (tool,)
    if isinstance(tool, dict) and isinstance(tool.get("in"), list):
        return tuple(str(t) for t in tool["in"])
    return ()


def _is_int(v: Any) -> bool:
    return type(v) is int


def policy_facts(
    policy_texts: Iterable[tuple[str, str]], agent_id: str
) -> tuple[tuple[RuleFact, ...], tuple[LimitFact, ...]]:
    """Rules scoped to ``agent_id`` (or unscoped) and the money limits they set.

    ``policy_texts`` = (name, yaml text) pairs; ``name`` is the file label used in pointers
    (``policies/baseline.yaml:139``). A limit is a gate rule on a money or credit tool with
    ``when.all`` ``amount_minor gt N`` (per transaction) or an ``aggregate`` sum of
    ``amount_minor`` over 86400 s (daily). Integer VND only.
    """
    rules: list[RuleFact] = []
    limits: list[LimitFact] = []
    for name, text in policy_texts:
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ProfileInputError(f"policy {name} is not valid YAML: {exc}") from None
        if not isinstance(doc, dict):
            raise ProfileInputError(f"policy {name} must be a YAML mapping")
        classes = doc.get("tools") if isinstance(doc.get("tools"), dict) else {}
        for raw in doc.get("rules") or []:
            if not isinstance(raw, dict) or "id" not in raw:
                continue
            scope = raw.get("agent_scope")
            if scope and agent_id not in scope:
                continue
            rid = str(raw["id"])
            line = _rule_line(text, rid)
            ptr = Pointer("rule", f"{name}:{line}" if line else name, rid)
            rules.append(RuleFact(rid, str(raw.get("description", "")).strip(), ptr))
            when = raw.get("when") if isinstance(raw.get("when"), dict) else {}
            tools = _tools_of(when)
            kinds = {classes.get(t, raw.get("risk_class")) for t in tools}
            if not tools or not kinds & {"money", "credit"}:
                continue
            rc = "credit" if kinds <= {"credit"} else ("money" if kinds <= {"money"} else "")
            agg = raw.get("aggregate")
            if isinstance(agg, dict):
                if (
                    agg.get("fn") == "sum"
                    and agg.get("field") == "amount_minor"
                    and agg.get("window_s") == 86400
                    and agg.get("op") in ("gt", "ge")
                    and _is_int(agg.get("limit"))
                    and not agg.get("also_by")
                ):
                    who = {"customer": "per_customer", "agent": "per_agent"}.get(
                        str(agg.get("group_by")), "unknown"
                    )
                    limits.append(
                        LimitFact(rid, "rule", "daily", who, agg["limit"], tools, ptr, rc)
                    )
                continue
            for cond in when.get("all") or []:
                if (
                    isinstance(cond, dict)
                    and cond.get("arg") == "amount_minor"
                    and cond.get("op") in ("gt", "ge")
                    and _is_int(cond.get("value"))
                ):
                    limits.append(
                        LimitFact(
                            rid, "rule", "per_transaction", "unknown", cond["value"], tools, ptr, rc
                        )
                    )
    return tuple(rules), tuple(limits)


# ----------------------------------------------------------------------------- onboard


def _ref(ev: Evidence | None, prefix: str) -> str | None:
    return None if ev is None else f"{prefix}{ev.ref()}"


def _tool_ptr(t: ToolInfo, prefix: str, note: str) -> Pointer:
    ref = _ref(t.definition, prefix) or _ref(t.manifest_entry, prefix)
    if ref:
        return Pointer("file", ref, f"{t.name}: {note}")
    return Pointer("profile", f"tool:{t.name}", note)


def _is_payment(t: ToolInfo) -> bool:
    """A payment tool = a money tool with a destination argument (a chosen account)."""
    return t.risk_class == "money" and bool(t.destination_arg)


def _covers(lim: LimitFact, tool: str) -> bool:
    return not lim.tools or tool in lim.tools


def _lowest(items: Iterable[LimitFact]) -> LimitFact | None:
    return min(items, key=lambda x: (x.value_vnd, x.id), default=None)


def _tool_max(
    limits: Sequence[LimitFact], tools: Sequence[ToolInfo]
) -> tuple[int | None, tuple[LimitFact, ...]]:
    """Largest amount any of the tools may carry: per tool the smallest per-transaction limit
    that covers it. None when one tool has no limit (a question, not 'unlimited')."""
    if not tools:
        return None, ()
    best: list[int] = []
    used: list[LimitFact] = []
    for t in tools:
        low = _lowest(x for x in limits if x.period == "per_transaction" and _covers(x, t.name))
        if low is None:
            return None, ()
        best.append(low.value_vnd)
        used.append(low)
    return max(best), tuple(used)


def _tool_class(inv: Inventory, tool: str | None) -> str:
    t = inv.tool(tool) if tool else None
    return t.risk_class if t is not None and t.risk_class in ("money", "credit") else ""


def _manifest_limits(inv: Inventory, prefix: str) -> list[LimitFact]:
    out: list[LimitFact] = []
    for lim in inv.limits:
        period = "daily" if lim.period == "daily" else "per_transaction"
        # The manifest line itself must say "per customer"; otherwise the scope stays unknown.
        per_customer = period == "daily" and "per customer" in lim.evidence.quote
        out.append(
            LimitFact(
                lim.key,
                "manifest",
                period,
                "per_customer" if per_customer else "unknown",
                lim.value,
                (lim.tool,) if lim.tool else (),
                Pointer("manifest", f"{prefix}{lim.evidence.ref()}", lim.key),
                _tool_class(inv, lim.tool),
            )
        )
    return out


def from_onboard(
    inventory: Inventory,
    agent_profile: AgentProfile,
    *,
    plan: MonitoringPlan | None = None,
    policy_texts: Iterable[tuple[str, str]] = (),
    answers: Mapping[str, Any] | None = None,
    basis: str = "planned",
    file_prefix: str = "",
    artefacts: Iterable[str] = (),
    base_dir: Path | None = None,
) -> ProductProfile:
    """Facts from Discover + Understand (+ Plan, + policy). Code gives lower bounds for the
    sets; what code cannot prove is None. ``policy_texts`` = (file label, yaml text) pairs.
    ``artefacts`` names onboarding files that exist next to the profile (``launch_report``,
    ``handover``). ``file_prefix`` is put before every file:line pointer."""
    inv, prof, px = inventory, agent_profile, file_prefix
    prov: dict[str, tuple[Pointer, ...]] = {}
    texts = tuple(policy_texts)

    pay = [t for t in inv.tools if _is_payment(t)]
    credit = [t for t in inv.tools if t.risk_class == "credit"]
    classes: list[str] = []
    ptrs: list[Pointer] = []
    if pay:
        classes.append("payment")
        ptrs += [_tool_ptr(t, px, "money tool with a destination argument") for t in pay]
    if credit:
        classes.append("credit_decision")
        ptrs += [_tool_ptr(t, px, "credit decision tool") for t in credit]
    if "free_text_output" in inv.features:
        classes.append("customer_facing")
        ptrs.append(Pointer("profile", "features:free_text_output", "the agent writes free text"))
    prov["agent_classes"] = tuple(ptrs)

    data: list[str] = []
    dptrs: list[Pointer] = []
    pii = {**inv.pii_fields, **inv.pii_identifiers}
    exp = [t for t in inv.tools if t.risk_class == "pii_export"]
    if pii or exp:
        data.append("personal")
        dptrs += [
            Pointer("file", f"{px}{ev.ref()}", f"personal data field {k}") for k, ev in pii.items()
        ]
        dptrs += [_tool_ptr(t, px, "pii_export tool") for t in exp]
    fin = [t for t in inv.tools if t.risk_class in ("money", "credit")]
    if fin:
        data.append("financial")
        dptrs += [_tool_ptr(t, px, f"{t.risk_class} tool") for t in fin]
    prov["data_classes"] = tuple(dptrs)

    level, reason = (prof.autonomy, prof.autonomy_reason) if prof.autonomy else autonomy_level(inv)
    autonomy = AUTONOMY_MAP.get(level, "acts_autonomously")
    prov["autonomy"] = (Pointer("profile", f"profile.json#autonomy={level}", reason),)

    # Decision 33 facts come from the onboard entries (not re-derived here).
    entries = {e.entry: e for e in prof.decision33.entries}
    tx, cr = entries.get("transactions"), entries.get("credit")
    d33_ptr = Pointer("profile", "profile.json#decision33", "onboard Decision 33 entries")

    def ev_ptrs(entry: Any) -> tuple[Pointer, ...]:
        return (d33_ptr, *(Pointer("file", f"{px}{e.ref()}", entry.entry) for e in entry.evidence))

    approval = indep = None
    prov["executes_payments"] = ev_ptrs(tx) if tx else (d33_ptr,)
    if tx:
        approval = not tx.triggered
        prov["human_approval_before_execution"] = ev_ptrs(tx)
    prov["credit_decisions"] = ev_ptrs(cr) if cr else (d33_ptr,)
    if cr:
        indep = not cr.triggered
        prov["independent_credit_approval"] = ev_ptrs(cr)

    limits: list[LimitFact] = []
    rules: tuple[RuleFact, ...] = ()
    if texts:
        rules, policy_limits = policy_facts(texts, inv.agent_id)
        limits += policy_limits
    limits += _manifest_limits(inv, px)
    max_tx, tx_used = _tool_max(limits, pay)
    max_cr, cr_used = _tool_max(limits, credit)
    low_daily = _lowest(x for x in limits if x.period == "daily" and x.scope == "per_customer")
    for name, used in (("max_transaction_vnd", tx_used), ("max_credit_vnd", cr_used)):
        if used:
            prov[name] = tuple(x.pointer for x in used if x.pointer)
    if low_daily and low_daily.pointer:
        prov["max_daily_vnd"] = (low_daily.pointer,)

    controls = ProductControls(basis=basis)
    if plan is not None or texts:
        on = tuple(plan.on_ids) if plan else ()
        monitor_of = {c: CAPABILITY_MONITOR[c] for c in on if c in CAPABILITY_MONITOR}
        evidence = {"onboard_profile"}
        if plan:
            evidence.add("onboard_plan")
        evidence |= set(artefacts) & {"launch_report", "handover"}
        if "fairness" in monitor_of.values():
            evidence.add("fairness_slice")
        extra = {
            f"catalogue:{c}": Pointer("plan", f"plan.json#{c}", f"capability {c} is on ({basis})")
            for c in on
        }
        extra |= {
            f"monitor:{m}": Pointer("plan", f"plan.json#{c}", f"capability {c} is on ({basis})")
            for c, m in monitor_of.items()
        }
        for eid, ref in (("onboard_profile", "profile.json"), ("onboard_plan", "plan.json")):
            extra[f"evidence:{eid}"] = Pointer("file", ref, "onboarding artefact")
        for eid in set(artefacts) & {"launch_report", "handover"}:
            extra[f"evidence:{eid}"] = Pointer("file", f"{eid}.json", "onboarding artefact")
        controls = standard_controls(
            basis=basis,
            supervised=True,
            catalogue_on=on,
            rules=rules,
            monitors=monitor_of.values(),
            evidence=evidence,
            policy_files=tuple(n for n, _ in texts),
            extra_pointers=extra,
            judge_on=bool(plan)
            and any(c.kind == "judge" for c in plan.capabilities if c.status == "on"),
        )
        prov["controls"] = (Pointer("plan", "plan.json", f"basis {basis}"),) if plan else ()

    product = ProductProfile(
        product_id=inv.agent_id,
        name=inv.name,
        source="onboard",
        version=inv.version,
        owner_team=inv.owner_team,
        purpose=prof.purpose.claim,
        agent_classes=tuple(classes),
        data_classes=tuple(data),
        autonomy=autonomy,
        roles=("deployer",),
        executes_payments=tx is not None,
        human_approval_before_execution=approval,
        credit_decisions=cr is not None,
        independent_credit_approval=indep,
        max_transaction_vnd=max_tx,
        max_daily_vnd=low_daily.value_vnd if low_daily else None,
        max_credit_vnd=max_cr,
        limits=tuple(limits),
        controls=controls,
        provenance=prov,
        onboard_decision33=prof.decision33.model_dump(mode="json"),
    )
    return apply_answers(product, answers, base_dir=base_dir) if answers else product


# ----------------------------------------------------------------------------- answers

_SETS = {
    "agent_classes": "agent_classes_complete",
    "data_classes": "data_classes_complete",
    "roles": "roles_complete",
    "customer_types": "customer_types_complete",
}
_SCALARS = (
    "name",
    "version",
    "owner_team",
    "purpose",
    "autonomy",
    "cross_border",
    "model_hosting",
    "customer_facing",
    "decisions_affecting_customers",
    "executes_payments",
    "human_approval_before_execution",
    "credit_decisions",
    "independent_credit_approval",
    "max_transaction_vnd",
    "max_daily_vnd",
    "max_credit_vnd",
    "in_operation_since",
)


def _qptr(field_name: str) -> Pointer:
    return Pointer("questionnaire", f"product.yaml#{field_name}")


def _read_policy_files(files: Sequence[str], base_dir: Path | None) -> list[tuple[str, str]]:
    base = (base_dir or Path.cwd()).resolve()
    out: list[tuple[str, str]] = []
    for rel in files:
        path = Path(rel) if Path(rel).is_absolute() else base / rel
        try:
            out.append((rel, path.read_text(encoding="utf-8")))
        except OSError as exc:
            raise ProfileInputError(
                f"cannot read policy file {rel}: {type(exc).__name__}"
            ) from None
    return out


def apply_answers(
    product: ProductProfile,
    answers: Mapping[str, Any] | None,
    *,
    base_dir: Path | None = None,
) -> ProductProfile:
    """Answers override or fill any fact. A set given by answers is complete. Each answered
    field gets a questionnaire pointer. ``answers`` is validated first (QuestionnaireError)."""
    from supervisor.advisory.compliance.questionnaire import validate_answers

    if not answers:
        return product
    data = validate_answers(answers)
    changes: dict[str, Any] = {}
    prov = dict(product.provenance)
    for name, flag in _SETS.items():
        if name in data:
            changes[name] = tuple(data[name])
            changes[flag] = True
            prov[name] = (_qptr(name),)
    for name in _SCALARS:
        if name in data:
            changes[name] = data[name]
            prov[name] = (_qptr(name),)
    limits = list(product.limits)
    for key, period in (
        ("max_transaction_vnd", "per_transaction"),
        ("max_daily_vnd", "daily"),
        ("max_credit_vnd", "per_transaction"),
    ):
        if key in data:
            who = "per_customer" if period == "daily" else "unknown"
            tools = ("credit",) if key == "max_credit_vnd" else ()
            limits.append(
                LimitFact(
                    key,
                    "questionnaire",
                    period,
                    who,
                    data[key],
                    tools,
                    _qptr(key),
                    "credit" if key == "max_credit_vnd" else "money",
                )
            )
    controls = product.controls
    ctl = data.get("controls")
    if ctl:
        pol = _read_policy_files(ctl.get("policy_files", []), base_dir)
        rules = {r.id: r for r in controls.rules}
        if pol:
            pid = str(data.get("product_id", product.product_id))
            pol_rules, pol_limits = policy_facts(pol, pid)
            rules.update({r.id: r for r in pol_rules})
            limits += pol_limits
            low = _lowest(
                x for x in pol_limits if x.period == "daily" and x.scope == "per_customer"
            )
            if low and "max_daily_vnd" not in data and product.max_daily_vnd is None:
                changes["max_daily_vnd"] = low.value_vnd
                prov["max_daily_vnd"] = (low.pointer,) if low.pointer else ()
        for r in ctl.get("rules", []):
            rules[r["id"]] = RuleFact(r["id"], r.get("description", ""), _qptr("controls.rules"))
        extra = dict(controls.pointers)
        for kind, key in (
            ("catalogue", "catalogue"),
            ("monitor", "monitors"),
            ("evidence", "evidence"),
        ):
            for cid in ctl.get(key, []):
                extra.setdefault(f"{kind}:{cid}", _qptr(f"controls.{key}"))
        supervised = ctl.get("supervised", controls.supervised)
        controls = standard_controls(
            basis=controls.basis if controls.known else "declared",
            supervised=bool(supervised),
            catalogue_on=tuple(dict.fromkeys([*controls.catalogue_on, *ctl.get("catalogue", [])])),
            rules=tuple(rules.values()),
            monitors=[*controls.monitors, *ctl.get("monitors", [])],
            evidence=[*controls.evidence, *ctl.get("evidence", [])],
            policy_files=[*controls.policy_files, *ctl.get("policy_files", [])],
            extra_pointers=extra,
        )
        if supervised is None:
            controls = dataclasses.replace(controls, supervised=None)
        prov["controls"] = (_qptr("controls"),)
    return dataclasses.replace(
        product, **changes, limits=tuple(limits), controls=controls, provenance=prov
    )


# ----------------------------------------------------------------------------- questionnaire


def from_questionnaire(
    data_or_path: Mapping[str, Any] | str | Path, *, base_dir: Path | None = None
) -> ProductProfile:
    """Product facts from a product.yaml (dict or path). Blank = unknown = question."""
    from supervisor.advisory.compliance.questionnaire import load_answers_file, validate_answers

    if isinstance(data_or_path, str | Path):
        path = Path(data_or_path)
        raw = load_answers_file(path)
        base = base_dir or path.resolve().parent
    else:
        raw, base = dict(data_or_path), base_dir
    data = validate_answers(raw, require_identity=True)
    blank = ProductProfile(product_id=data["product_id"], name=data["name"], source="questionnaire")
    return apply_answers(blank, data, base_dir=base)


def load_profile_input(
    path: str | Path,
    *,
    answers: Mapping[str, Any] | str | Path | None = None,
    policy_files: Sequence[str | Path] = (),
) -> ProductProfile:
    """Load a product from an onboard ``profile.json`` (siblings ``inventory.json``,
    ``plan.json``, ``policy.yaml`` are used when present) or from a ``product.yaml``."""
    from supervisor.advisory.compliance.questionnaire import load_answers_file

    p = Path(path)
    if not p.is_file():
        raise ProfileInputError(f"input file not found: {p.name}")
    ans = load_answers_file(Path(answers)) if isinstance(answers, str | Path) else answers
    try:
        extra = [(str(f), Path(f).read_text(encoding="utf-8")) for f in policy_files]
    except OSError as exc:
        raise ProfileInputError(f"cannot read a policy file: {type(exc).__name__}") from None
    if p.suffix.lower() != ".json":
        product = from_questionnaire(p)
        if extra:
            _, plimits = policy_facts(extra, product.product_id)
            product = dataclasses.replace(product, limits=product.limits + plimits)
        return apply_answers(product, ans, base_dir=p.parent) if ans else product
    try:
        profile = AgentProfile.model_validate_json(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ProfileInputError(
            f"{p.name} is not an onboard AgentProfile: {type(exc).__name__}"
        ) from None
    inv_path = p.with_name("inventory.json")
    if not inv_path.is_file():
        raise ProfileInputError("inventory.json must sit next to profile.json")
    try:
        inventory = Inventory.model_validate(json.loads(inv_path.read_text(encoding="utf-8")))
        plan_path = p.with_name("plan.json")
        plan = (
            MonitoringPlan.model_validate(json.loads(plan_path.read_text(encoding="utf-8")))
            if plan_path.is_file()
            else None
        )
    except (ValueError, OSError) as exc:
        raise ProfileInputError(
            f"inventory.json or plan.json is invalid: {type(exc).__name__}"
        ) from None
    texts: list[tuple[str, str]] = []
    pol = p.with_name("policy.yaml")
    if pol.is_file():
        texts.append(("policy.yaml", pol.read_text(encoding="utf-8")))
    texts += extra
    names = [n for n in ("launch_report", "handover") if p.with_name(f"{n}.json").is_file()]
    return from_onboard(
        inventory,
        profile,
        plan=plan,
        policy_texts=texts,
        answers=ans,
        artefacts=names,
        base_dir=p.parent,
    )
