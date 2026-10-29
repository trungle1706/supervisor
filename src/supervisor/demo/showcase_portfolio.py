# ruff: noqa: S311, S608  (seeded synthetic data, not crypto; SQL text uses schema names and constants only)
"""Showcase portfolio seeder (WP-D1): 300 synthetic AI systems in the database.

    python -m supervisor.demo.showcase portfolio --systems 300 [--seed N] [--remove] [--dry-run]

Act 1 of ``docs/showcase/SHOWCASE_PLAN.md``. The seeder writes metadata rows straight to the tables
of the configured SQL backend (SQLite or Delta, through the same ``SqlExecutor``), in batches. It
does not call the services, so it writes no evidence-chain record and no case event: nothing
append-only is written and ``--remove`` can delete every row it made.

Tags. Tables with a tag field carry ``demo:showcase`` (``ai_system.tags``, ``inventory_node.attrs``,
and the text of the notes, summaries and reasons). Every other row has an id (or an owner id) that
starts with ``shw_`` (or a node name that starts with ``shw-`` and an edge reference that starts
with ``shw:``). ``--remove`` deletes by those prefixes and nothing else. Tables whose id is a hash
that the product re-computes on read (task, obligation_status, risk_dimension_status, assignment,
system_component) keep the product's own id; their rows are found by the ``shw_`` system id.

Gate rollups: ``decision_daily`` rows of dimension ``agent`` (one per showcase agent and day). The
``total`` dimension is not written: the rollup job owns it and a seeded value would mix with real
traffic.

Safe by default: ``SHOWCASE_ENABLED=1`` is required (also in a Databricks App). Synthetic only;
teams and users are role names. Same seed gives the same ids; an existing row is skipped.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT, Settings
from supervisor.core.canonical import sha256_hex
from supervisor.core.errors import SqlError
from supervisor.demo import showcase_portfolio_data as D
from supervisor.demo.session import Echo, default_echo

TAG = "demo:showcase"
PREFIX = "shw_"
NODE_PREFIX = "shw-"
EDGE_PREFIX = "shw:"
ENABLE_VAR = "SHOWCASE_ENABLED"
CREATED_BY = "seed.showcase"
DEFAULT_SYSTEMS = 300
DEFAULT_SEED = 1
DAYS = 30
BANNER = "Not legal advice. Bank counsel must confirm."

CLASSES: tuple[str, ...] = (
    "prohibited",
    "high_certify",
    "high_self",
    "medium",
    "low",
    "not_system",
    "none",
)
# SHOWCASE_PLAN.md section 4 (illustrative), for 300 systems
CLASS_COUNTS: dict[str, int] = {
    "prohibited": 2,
    "high_certify": 6,
    "high_self": 38,
    "medium": 96,
    "low": 118,
    "not_system": 12,
    "none": 28,
}
STAGES: tuple[str, ...] = (
    "initiation",
    "design",
    "validation",
    "deployment",
    "operation",
    "re_evaluation",
    "retirement",
)
STAGE_COUNTS: dict[str, int] = {
    "initiation": 30,
    "design": 34,
    "validation": 42,
    "deployment": 36,
    "operation": 140,
    "re_evaluation": 12,
    "retirement": 6,
}
CANDIDATES = 40
LIVE_STAGES = ("operation", "re_evaluation")

# which stages a class may take (the generator falls back to any stage when a quota is used up)
STAGE_RULE: dict[str, tuple[str, ...]] = {
    "prohibited": ("retirement", "initiation"),
    "none": ("initiation", "initiation", "initiation", "design"),
    "high_certify": ("validation", "deployment", "operation"),
    "high_self": ("design", "validation", "deployment", "operation", "re_evaluation"),
    "not_system": ("design", "deployment", "operation", "retirement"),
}
STAGE_AGE: dict[str, tuple[int, int]] = {
    "initiation": (1, 45),
    "design": (20, 120),
    "validation": (60, 260),
    "deployment": (100, 360),
    "operation": (150, 800),
    "re_evaluation": (400, 1000),
    "retirement": (500, 1300),
}
LEVEL_OF_CLASS: dict[str, str] = {
    "prohibited": "prohibited",
    "high_certify": "high",
    "high_self": "high",
    "medium": "medium",
    "low": "low",
    "not_system": "unspecified",
    "none": "unspecified",
}
TIER_OF_CLASS: dict[str, str] = {
    "prohibited": "high",
    "high_certify": "high",
    "high_self": "high",
    "medium": "medium",
    "low": "low",
    "not_system": "low",
    "none": "low",
}
TOOL_RISK = {"read_only": "low", "pii_export": "high", "credit": "high", "money": "critical"}
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
DIMENSIONS: tuple[str, ...] = (
    "model",
    "data_governance",
    "cybersecurity",
    "legal_compliance",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
)
STATUS_WEIGHTS: dict[str, dict[str, int]] = {
    # status -> weight, per stage
    "initiation": {"not_started": 100},
    "design": {"not_started": 86, "in_progress": 14},
    "validation": {"pass": 32, "in_progress": 46, "not_started": 17, "fail": 5},
    "deployment": {"pass": 70, "in_progress": 19, "fail": 6, "waived": 5},
    "operation": {"pass": 84, "fail": 3, "waived": 4, "in_progress": 5, "not_started": 4},
    "re_evaluation": {"pass": 62, "in_progress": 24, "fail": 8, "waived": 6},
    "retirement": {"pass": 70, "waived": 10, "not_applicable": 20},
}
FEATURE_FLOOR = ("dlp_vn", "injection_regex", "session_monitor")

# tables the seeder writes: name -> (scope column, prefix); also the order of writing
SCOPE: dict[str, tuple[str, str]] = {
    "agent": ("agent_id", PREFIX),
    "ai_system": ("system_id", PREFIX),
    "system_team": ("system_id", PREFIX),
    "inventory_node": ("name", NODE_PREFIX),
    "inventory_edge": ("evidence_ref", EDGE_PREFIX),
    "system_component": ("system_id", PREFIX),
    "assignment": ("system_id", PREFIX),
    "classification": ("system_id", PREFIX),
    "classification_v2": ("system_id", PREFIX),
    "risk_dimension_status": ("system_id", PREFIX),
    "obligation_status": ("system_id", PREFIX),
    "task": ("agent_id", PREFIX),
    "stage_approval": ("system_id", PREFIX),
    "guardian_binding": ("system_id", PREFIX),
    "cases": ("case_id", PREFIX),
    "incident": ("incident_id", PREFIX),
    "decision_daily": ("dim_key", PREFIX),
}
TABLE_ORDER: tuple[str, ...] = tuple(SCOPE)


class ShowcaseError(Exception):
    """Refused or failed in a way the user can fix (printed as ``[FAIL]``)."""


# ----------------------------------------------------------------------------------- flag


def check_enabled(env: Mapping[str, str] | None = None) -> str | None:
    """None when allowed, else the message. The flag is needed everywhere; in a Databricks App
    (a demo workspace only) the message says so."""
    env = os.environ if env is None else env
    if str(env.get(ENABLE_VAR, "")).strip() == "1":
        return None
    where = ""
    if str(env.get("SUPERVISOR_MODE", "")).strip() == "databricks_app":
        where = " This is a Databricks App: seed only a demo workspace, never production."
    return (
        f"the showcase seeder is off: set {ENABLE_VAR}=1 to run it (it writes synthetic rows "
        f"tagged '{TAG}' and is for demo workspaces only).{where}"
    )


# ----------------------------------------------------------------------------------- helpers


def apportion(total: int, base: Mapping[str, int]) -> dict[str, int]:
    """Largest-remainder share of ``total`` in the proportions of ``base``."""
    whole = sum(base.values())
    if total == whole:
        return dict(base)
    raw = {k: v * total / whole for k, v in base.items()}
    out = {k: int(x) for k, x in raw.items()}
    rest = total - sum(out.values())
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:rest]:
        out[k] += 1
    return out


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _pick(rng: random.Random, weights: Mapping[str, int]) -> str:
    keys = sorted(weights)
    return rng.choices(keys, [weights[k] for k in keys])[0]


def _days(now: dt.datetime, n: float) -> dt.datetime:
    return now - dt.timedelta(days=n)


def _day_floor(value: dt.datetime) -> dt.datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _hex(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _bool_text(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


# ----------------------------------------------------------------------------------- plan


@dataclass
class Plan:
    """What the generator decided for one system (also the input to the row builders)."""

    idx: int
    system_id: str
    name: str
    arch: dict[str, Any]
    cls: str
    stage: str
    bu: str
    team: str
    owner: str
    biz_owner: str
    reviewer: str
    approver: str
    technical: str
    model: tuple[str, str, str | None, str]
    tools: list[tuple[str, str]]
    datasets: list[str]
    auto: str
    hc: str
    status: str
    age: int  # days since created
    entered: int  # days since the current stage began
    cls_age: int  # days since the classification was approved
    agent_id: str | None = None
    rng: random.Random = field(default_factory=random.Random)
    gaps: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    @property
    def level(self) -> str:
        return LEVEL_OF_CLASS[self.cls]

    @property
    def d33(self) -> str:
        if self.cls in ("high_certify", "high_self"):
            return "high_risk"
        if self.cls == "none":
            return "unclassified"
        return "not_high_risk"

    @property
    def high(self) -> bool:
        return self.cls in ("high_certify", "high_self")

    @property
    def live(self) -> bool:
        return self.stage in LIVE_STAGES


@dataclass
class Portfolio:
    n: int
    seed: int
    rows: dict[str, list[dict[str, Any]]]
    plans: list[Plan]
    candidates: list[str]

    def counts(self) -> dict[str, int]:
        return {t: len(r) for t, r in self.rows.items()}


def _assign(n: int, rng: random.Random) -> list[tuple[str, str]]:
    classes = apportion(n, CLASS_COUNTS)
    slots = Counter(apportion(n, STAGE_COUNTS))
    order = ("prohibited", "none", "high_certify", "high_self", "not_system", "medium", "low")
    out: list[tuple[str, str]] = []
    for cls in order:
        for _ in range(classes[cls]):
            ok = [s for s in STAGE_RULE.get(cls, STAGES) if slots[s] > 0]
            pool = ok or [s for s in STAGES if slots[s] > 0]
            weights = [slots[s] for s in pool]
            stage = rng.choices(pool, weights)[0]
            slots[stage] -= 1
            out.append((cls, stage))
    rng.shuffle(out)
    return out


def _names(rng: random.Random, arch: dict[str, Any], used: set[str]) -> str:
    base = str(arch["name"])
    variants = list(D.VARIANTS)
    rng.shuffle(variants)
    for v in variants:
        name = f"{base} - {v}" if v else base
        if name.lower() not in used:
            used.add(name.lower())
            return name
    k = 2
    while f"{base} {k}".lower() in used:
        k += 1
    name = f"{base} {k}"
    used.add(name.lower())
    return name


def _model_row(name: str) -> tuple[str, str, str | None, str]:
    for m in D.MODELS:
        if m[0] == name:
            return m
    raise ShowcaseError(f"unknown model {name}")


def _plans(n: int, seed: int) -> list[Plan]:
    master = random.Random(f"showcase:{seed}")
    pairs = _assign(n, master)
    used: set[str] = set()
    plans: list[Plan] = []
    for i, (cls, stage) in enumerate(pairs, start=1):
        rng = random.Random(f"showcase:{seed}:{i}")
        band = D.CLASS_BAND[cls]
        pool = D.ARCHETYPES[band]
        weights = [3 if a["seg"] == "customer" else 1 for a in pool] if band == "medium" else None
        arch = rng.choices(pool, weights)[0] if weights else rng.choice(pool)
        name = _names(rng, arch, used)
        bu = str(arch["bu"])
        team = rng.choice(D.TEAMS[bu])
        team_slug = _slug(team.removesuffix(" team"))
        model = _model_row(rng.choice(arch["model"]))
        tools = list(arch["tools"])
        if rng.random() < 0.4:
            extra = rng.choice(D.READ_ONLY_EXTRA)
            if extra not in tools:
                tools.append(extra)
        ds_pool = D.DATASETS[str(arch["data"])]
        datasets = rng.sample(ds_pool, k=min(len(ds_pool), rng.choice((1, 2, 2, 3))))
        lo, hi = STAGE_AGE[stage]
        age = rng.randint(lo, hi)
        # classification age: most are inside the yearly review, a few are past it
        cls_age = rng.randint(370, 520) if rng.random() < 0.12 else rng.randint(5, 340)
        if stage in ("initiation", "design"):
            cls_age = rng.randint(1, max(2, min(age - 1, 60)))
        age = max(age, cls_age + rng.randint(2, 20))
        low_in = {"operation": 35, "re_evaluation": 10}.get(stage, 1)
        entered = rng.randint(min(low_in, age - 2), max(low_in, age - 3))
        status = "active"
        if stage == "initiation" and rng.random() < 0.55:
            status = "draft"
        plans.append(
            Plan(
                idx=i,
                system_id=f"{PREFIX}sys_{i:04d}",
                name=name,
                arch=arch,
                cls=cls,
                stage=stage,
                bu=bu,
                team=team,
                owner=f"owner.{team_slug}",
                biz_owner=f"bizowner.{_slug(bu)}",
                reviewer=f"reviewer.{_slug(bu)}.{rng.randint(1, 3)}",
                approver=f"approver.second-line.{rng.randint(1, 3)}",
                technical=f"techlead.{team_slug}",
                model=model,
                tools=tools,
                datasets=datasets,
                auto=rng.choice(arch["auto"]),
                hc=rng.choice(arch["hc"]),
                status=status,
                age=age,
                entered=entered,
                cls_age=cls_age,
                agent_id=(f"{PREFIX}ag_{i:04d}" if stage in LIVE_STAGES else None),
                rng=rng,
            )
        )
    plans.sort(key=lambda p: p.idx)
    return plans


# ----------------------------------------------------------------------------------- builders


class Builder:
    def __init__(self, n: int, seed: int, now: dt.datetime, kb: Any, tasks_cfg: Mapping[str, Any]):
        self.n, self.seed, self.now = n, seed, now
        self.kb = kb
        self.tasks_cfg = tasks_cfg
        self.rows: dict[str, list[dict[str, Any]]] = {t: [] for t in TABLE_ORDER}
        self.plans = _plans(n, seed)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.sys_node: dict[str, str] = {}
        self.tree_sha = _file_sha(REPO_ROOT / "config" / "classification.yaml")
        self.d33_sha = _file_sha(REPO_ROOT / "config" / "decision33.yaml")

    # -- small ---------------------------------------------------------------------------
    def add(self, table: str, row: dict[str, Any]) -> None:
        self.rows[table].append(row)

    def _stamp(self, p: Plan, days: float) -> dt.datetime:
        return self.now - dt.timedelta(days=days)

    # -- systems -------------------------------------------------------------------------
    def systems(self) -> None:
        from supervisor.governance.systems import component_id

        for p in self.plans:
            a = p.arch
            created = self._stamp(p, p.age)
            tags = {
                TAG: "1",
                "bu": _slug(p.bu),
                "ai_type": "generative" if a["gen"] else ("decision" if a["decides"] else "ml"),
                "model_family": p.model[1],
                "customer_facing": "yes" if a["seg"] == "customer" else "no",
                "agentic": "yes" if a["agentic"] else "no",
                "decides": "yes" if a["decides"] else "no",
                "class": p.cls,
            }
            if p.model[2]:
                tags["vendor"] = p.model[2]
            self.add(
                "ai_system",
                {
                    "system_id": p.system_id,
                    "name": p.name,
                    "owner_user": p.owner,
                    "owner_team": p.team,
                    "business_owner": p.biz_owner,
                    "purpose": a["purpose"],
                    "system_type": a["stype"],
                    "org_role": "provider"
                    if p.model[3] == "onprem" and p.rng.random() < 0.3
                    else "deployer",
                    "user_segment": a["seg"],
                    "personal_data": a["pd"],
                    "money_movement": bool(a["money"]),
                    "credit_decision": bool(a["credit"]),
                    "human_control": p.hc,
                    "lifecycle_stage": p.stage,
                    "risk_level": LEVEL_OF_CLASS[p.cls],
                    "risk_level_source": "classifier" if p.cls != "none" else "manual",
                    "risk_justification": None
                    if p.cls == "none"
                    else f"[{TAG}] Set from the approved classification.",
                    "decision33_class": p.d33,
                    "business_impact": a["impact"],
                    "autonomy_level": p.auto,
                    "status": p.status,
                    "tags": tags,
                    "created_at": created,
                    "created_by": CREATED_BY,
                },
            )
            team_rows = [
                (p.owner, "system_owner"),
                (p.biz_owner, "business_owner"),
                (p.technical, "technical_specialist"),
                (p.reviewer, "reviewer"),
            ]
            if p.live or p.stage == "deployment":
                team_rows.append((f"oversight.{_slug(p.bu)}", "oversight_manager"))
            if a["pd"] != "none":
                team_rows.append((f"steward.data-office.{p.rng.randint(1, 2)}", "data_steward"))
            for uid, role in team_rows:
                self.add(
                    "system_team",
                    {
                        "system_id": p.system_id,
                        "user_id": uid,
                        "team_role": role,
                        "active": True,
                        "added_at": created,
                        "added_by": CREATED_BY,
                    },
                )
            # agent and its link
            if p.agent_id:
                shadow = p.stage == "operation" and p.rng.random() < 0.04
                self.add(
                    "agent",
                    {
                        "agent_id": p.agent_id,
                        "name": f"{p.name} agent",
                        "owner_team": p.team,
                        "owner_user": p.owner,
                        "business_owner": p.biz_owner,
                        "risk_tier": TIER_OF_CLASS[p.cls],
                        "decision33_class": p.d33,
                        "host_type": "app",
                        "plug_point": p.rng.choice(
                            ("fastapi_middleware", "langgraph_middleware", "sdk")
                        ),
                        "model_family": p.model[1],
                        "status": "shadow" if shadow else "enforced",
                        "gate_state": "SHADOW" if shadow else "RUNNING",
                        "created_at": self._stamp(p, p.entered + 5),
                    },
                )
                self.add(
                    "system_component",
                    self._component(
                        p, "agent", p.agent_id, "component_of", "onboarding", created, component_id
                    ),
                )

    def _component(
        self,
        p: Plan,
        kind: str,
        ref: str,
        role: str,
        source: str,
        seen: dt.datetime,
        component_id: Callable[..., str],
    ) -> dict[str, Any]:
        return {
            "component_id": component_id(p.system_id, kind, ref, role),
            "system_id": p.system_id,
            "ref_kind": kind,
            "ref_id": ref,
            "role": role,
            "source": source,
            "evidence_ref": f"{TAG}:{p.system_id}",
            "active": True,
            "first_seen": seen,
            "last_seen": self.now,
        }

    # -- inventory -----------------------------------------------------------------------
    def node(
        self,
        kind: str,
        name: str,
        display: str,
        *,
        status: str = "active",
        own_risk: str | None = None,
        attrs: Mapping[str, Any] | None = None,
        source: str = "manifest",
        seen: dt.datetime | None = None,
        d33: str | None = None,
    ) -> str:
        from supervisor.inventory.model import node_id_for

        canon = f"{NODE_PREFIX}{name}"
        nid = node_id_for(kind, canon)
        if nid not in self.nodes:
            first = seen or self.now
            self.nodes[nid] = {
                "node_id": nid,
                "kind": kind,
                "name": canon.lower(),
                "display_name": display,
                "status": status,
                "own_risk": own_risk,
                "risk_source": "manifest" if own_risk else "none",
                "decision33_class": d33,
                "attrs": {**(attrs or {}), "tag": TAG},
                "evidence": [{"source": source, "ref": "showcase-seed"}],
                "first_seen": first,
                "last_seen": self.now,
            }
        return nid

    def edge(self, src: str, kind: str, dst: str, source: str, ref: str, seen: dt.datetime) -> None:
        from supervisor.inventory.model import edge_id_for

        eid = edge_id_for(src, kind, dst, source)
        if eid not in self.edges:
            self.edges[eid] = {
                "edge_id": eid,
                "src_id": src,
                "dst_id": dst,
                "kind": kind,
                "source": source,
                "evidence_ref": f"{EDGE_PREFIX}{ref}",
                "active": True,
                "first_seen": seen,
                "last_seen": self.now,
            }

    def _model_nodes(self, mname: str, seen: dt.datetime) -> tuple[str, str]:
        _n, family, vendor, hosting = _model_row(mname)
        attrs: dict[str, Any] = {"family": family, "hosting": hosting}
        if vendor:
            attrs["external_providers"] = [vendor]
        mid = self.node("model", mname, mname, attrs=attrs, seen=seen)
        eid = self.node(
            "model_endpoint",
            f"ep-{mname}",
            f"{mname}-endpoint",
            attrs={
                "task": "llm"
                if family in ("glm", "qwen", "llama", "mistral", "gemma", "vendor_llm")
                else "ml"
            },
            seen=seen,
        )
        self.edge(eid, "serves", mid, "manifest", "pool", seen)
        return mid, eid

    def inventory(self) -> None:
        from supervisor.governance.systems import component_id

        for p in self.plans:
            seen = self._stamp(p, p.age)
            sid = self.node(
                "system",
                f"app-{p.system_id}",
                p.name,
                attrs={"role": "agent", "system_id": p.system_id},
                seen=seen,
                d33=p.d33 if p.cls != "none" else None,
            )
            self.sys_node[p.system_id] = sid
            mid, eid = self._model_nodes(p.model[0], seen)
            self.edge(sid, "uses", eid, "manifest", p.system_id, seen)
            tool_ids = []
            for tname, tcls in p.tools:
                tid = self.node(
                    "tool",
                    tname,
                    tname,
                    own_risk=TOOL_RISK[tcls],
                    attrs={"risk_class": tcls},
                    seen=seen,
                )
                tool_ids.append(tid)
                self.edge(sid, "uses", tid, "manifest", p.system_id, seen)
            ds_ids = []
            for dname in p.datasets:
                did = self.node("dataset", dname, dname, attrs={}, seen=seen)
                ds_ids.append(did)
                self.edge(sid, "reads", did, "manifest", p.system_id, seen)
            if p.rng.random() < 0.25 and ds_ids:
                self.edge(sid, "writes", ds_ids[0], "manifest", p.system_id, seen)
            team = self.node(
                "supplier",
                f"team-{_slug(p.team)}",
                p.team,
                attrs={"party": "owner_team"},
                seen=seen,
            )
            self.edge(sid, "owned_by", team, "manifest", p.system_id, seen)
            if p.model[2]:
                vid = self.node(
                    "supplier",
                    f"vendor-{p.model[2]}",
                    D.VENDORS[p.model[2]],
                    attrs={"party": "vendor"},
                    seen=seen,
                )
                self.edge(mid, "owned_by", vid, "manifest", "pool", seen)
            self.add(
                "system_component",
                self._component(p, "node", sid, "component_of", "onboarding", seen, component_id),
            )
            self.add(
                "system_component",
                self._component(p, "node", mid, "built_on", "onboarding", seen, component_id),
            )
            for tid in tool_ids:
                self.add(
                    "system_component",
                    self._component(p, "node", tid, "depends_on", "onboarding", seen, component_id),
                )
        self._candidates()

    def _candidates(self) -> None:
        rng = random.Random(f"showcase:{self.seed}:cand")
        count = (
            min(CANDIDATES, len(D.CANDIDATE_THINGS))
            if self.n >= 100
            else max(4, round(CANDIDATES * self.n / 300))
        )
        things = list(D.CANDIDATE_THINGS)
        rng.shuffle(things)
        chosen = sorted(things[:count])
        gen_models = [
            m
            for m in D.MODELS
            if m[1] in ("glm", "qwen", "llama", "mistral", "gemma", "vendor_llm")
        ]
        for name, kind in chosen:
            seen = self.now - dt.timedelta(days=rng.randint(1, 60))
            ref = f"cand-{name}"
            ntype = {"app": "system", "endpoint": "model_endpoint"}.get(kind, kind)
            attrs: dict[str, Any] = {"workspace_kind": kind}
            if kind == "app":
                attrs["role"] = "databricks_app"
            if kind == "endpoint":
                attrs["agent_endpoint"] = True
                attrs["task"] = "agent"
            nid = self.node(
                ntype,
                f"{kind}-{name}",
                name,
                status="unmanaged",
                attrs=attrs,
                source="workspace_scan",
                seen=seen,
            )
            m = rng.choice(gen_models)
            mid, eid = self._model_nodes(m[0], seen)
            if kind != "endpoint":
                self.edge(nid, "uses", eid, "workspace_scan", ref, seen)
            else:
                self.edge(nid, "uses", mid, "workspace_scan", ref, seen)
            for dname in rng.sample(D.DATASETS["customer"], k=rng.choice((0, 1, 2))):
                did = self.node("dataset", dname, dname, attrs={}, seen=seen)
                self.edge(nid, "reads", did, "workspace_scan", ref, seen)
            if rng.random() < 0.4:
                dname = rng.choice(D.DATASETS["other"])
                did = self.node("dataset", dname, dname, attrs={}, seen=seen)
                self.edge(nid, "reads", did, "workspace_scan", ref, seen)
            if kind in ("app", "endpoint") and rng.random() < 0.35:
                t = rng.choice(D.MONEY_TOOLS + D.CREDIT_TOOLS)
                tid = self.node(
                    "tool",
                    f"cand-{t[0]}",
                    t[0],
                    own_risk=TOOL_RISK[t[1]],
                    attrs={"risk_class": t[1]},
                    seen=seen,
                )
                self.edge(nid, "uses", tid, "workspace_scan", ref, seen)
            if kind == "job" and rng.random() < 0.5:
                dname = rng.choice(D.DATASETS["other"])
                did = self.node("dataset", dname, dname, attrs={}, seen=seen)
                self.edge(nid, "writes", did, "workspace_scan", ref, seen)

    # -- classification ------------------------------------------------------------------
    def _path(self, p: Plan) -> list[dict[str, Any]]:
        def step(
            node: str, answer: str, source: str, nxt: str, ev: str, note: str = ""
        ) -> dict[str, Any]:
            return {
                "node": node,
                "answer": answer,
                "source": source,
                "next": nxt,
                "evidence": ev,
                "note": note or f"[{TAG}] synthetic answer",
            }

        ev = f"system:{p.system_id}"
        s = [
            step(
                "N-SYSTEM",
                "no" if p.cls == "not_system" else "yes",
                "rules",
                "not_system" if p.cls == "not_system" else "N-PROHIBITED",
                ev,
            )
        ]
        if p.cls == "not_system":
            return s
        if p.cls == "prohibited":
            s.append(step("N-PROHIBITED", "yes", "person", "prohibited", ev))
            return s
        s.append(step("N-PROHIBITED", "no", "person", "N-PM-LIST", ev))
        if p.high:
            s.append(step("N-PM-LIST", "high_risk", "decision33", "N-THRESHOLD", ev))
            s.append(step("N-THRESHOLD", "yes", "person", "N-CERT", ev))
            s.append(
                step("N-CERT", "yes" if p.cls == "high_certify" else "no", "person", p.cls, ev)
            )
            return s
        s.append(step("N-PM-LIST", "not_high_risk", "decision33", "N-CONFUSE", ev))
        yes = p.cls == "medium"
        s.append(step("N-CONFUSE", "yes" if yes else "no", "rules" if yes else "person", p.cls, ev))
        return s

    def classification(self) -> None:
        for p in self.plans:
            if p.cls == "none":
                # about a third has a draft waiting for the second person
                if p.rng.random() < 0.3:
                    self._c2(p, p.cls_age, approved=False, outcome="low", path=[])
                continue
            path = self._path(p)
            self._c2(p, p.cls_age, approved=True, outcome=p.cls, path=path)
            if p.stage == "re_evaluation":
                self._c2(p, p.cls_age + 380, approved=True, outcome=p.cls, path=path, n=0)
            self.add(
                "classification",
                {
                    "classification_id": f"{PREFIX}d33_{p.idx:04d}",
                    "system_id": p.system_id,
                    "outcome": p.d33,
                    "answers": {
                        "Q-MONEY": {
                            "answer": "yes" if p.arch["money"] else "no",
                            "source": "rules",
                            "justification": f"[{TAG}] from the intake field",
                        },
                        "Q-CREDIT": {
                            "answer": "yes" if p.arch["credit"] else "no",
                            "source": "rules",
                            "justification": f"[{TAG}] from the intake field",
                        },
                        "Q-PRE-APPROVAL": {
                            "answer": "yes" if p.hc == "pre_approval" else "no",
                            "source": "person",
                            "justification": f"[{TAG}] human control as registered",
                        },
                    },
                    "flow_sha256": self.d33_sha,
                    "status": "applied",
                    "created_by": p.reviewer,
                    "created_at": self._stamp(p, p.cls_age + 1),
                    "applied_by": p.reviewer,
                    "applied_at": self._stamp(p, p.cls_age),
                },
            )

    def _c2(
        self,
        p: Plan,
        age: int,
        *,
        approved: bool,
        outcome: str,
        path: list[dict[str, Any]],
        n: int = 1,
    ) -> None:
        created = self._stamp(p, age + 1)
        appr_at = self._stamp(p, age) if approved else None
        self.add(
            "classification_v2",
            {
                "classification_id": f"{PREFIX}c2_{p.idx:04d}_{n}",
                "system_id": p.system_id,
                "outcome": outcome,
                "path_json": path,
                "tree_sha256": self.tree_sha,
                "path_hash": sha256_hex(
                    [[s["node"], s["answer"], s["source"], s["next"]] for s in path]
                ),
                "decided_by": p.reviewer,
                "approved_by": p.approver if approved else None,
                "approved_at": appr_at,
                "inherited_from_provider": bool(p.model[2] and p.rng.random() < 0.2),
                "valid_until": (appr_at or created) + dt.timedelta(days=365),
                "created_at": created,
            },
        )

    # -- risk dimensions -----------------------------------------------------------------
    def dimensions(self) -> None:
        from supervisor.governance.risk_dimensions import status_id

        for p in self.plans:
            weights = dict(STATUS_WEIGHTS[p.stage])
            vendor = bool(p.model[2])
            for dim in DIMENSIONS:
                w = dict(weights)
                if (
                    p.cls == "prohibited"
                    and dim in ("ethics", "legal_compliance")
                    and p.stage != "initiation"
                ):
                    st = "fail"
                else:
                    if p.cls in ("high_certify", "high_self") and "fail" in w:
                        w["fail"] = w["fail"] * 2
                        w["pass"] = max(1, w["pass"] - w["fail"] // 2)
                    if p.cls == "low" and "pass" in w:
                        w["fail"] = 0 if "fail" in w else w.get("fail", 0)
                        w = {k: v for k, v in w.items() if v}
                    if (
                        dim in ("third_party", "supply_chain")
                        and not vendor
                        and p.stage not in ("initiation", "design")
                    ):
                        w = {"not_applicable": 70, **{k: v // 3 or 1 for k, v in w.items()}}
                    if (
                        dim == "reputation"
                        and p.arch["seg"] != "customer"
                        and p.stage not in ("initiation", "design")
                    ):
                        w["not_applicable"] = w.get("not_applicable", 0) + 40
                    st = _pick(p.rng, w)
                until = None
                evidence: list[str] = []
                if st == "pass":
                    old = p.rng.random() < 0.025 and p.stage in LIVE_STAGES
                    assessed = p.rng.randint(380, 500) if old else p.rng.randint(5, 330)
                    assessed = min(assessed, max(p.age - 1, 1)) if not old else assessed
                    until = (self.now - dt.timedelta(days=assessed) + dt.timedelta(days=365)).date()
                    evidence = [f"shw-pack-{dim}-{p.idx:04d}"]
                note = None
                if st == "fail":
                    note = f"[{TAG}] Open finding, remediation planned."
                elif st == "waived":
                    note = f"[{TAG}] Waived by the second line (synthetic)."
                self.add(
                    "risk_dimension_status",
                    {
                        "status_id": status_id(p.system_id, dim),
                        "system_id": p.system_id,
                        "dimension_id": dim,
                        "status": st,
                        "owner_team": D.DIMENSION_OWNERS[dim],
                        "assessed_by": f"reviewer.{_slug(D.DIMENSION_OWNERS[dim])}"
                        if st in ("pass", "fail", "waived")
                        else None,
                        "report_ref": None,
                        "evidence_json": evidence,
                        "threshold_json": {"max_open_findings": 0 if p.high else 2},
                        "note": note,
                        "updated_by": f"reviewer.{_slug(D.DIMENSION_OWNERS[dim])}",
                        "valid_until": until,
                    },
                )

    # -- duties --------------------------------------------------------------------------
    def duties(self) -> None:
        from supervisor.governance.register_v2.duties import status_id

        pools: dict[str, list[Any]] = {}
        for inst in D.OBLIGATION_INSTRUMENTS:
            pools[inst] = sorted(
                (
                    o
                    for o in self.kb.obligations.values()
                    if o.instrument_id == inst and o.status == "in_force" and o.binding is True
                ),
                key=lambda o: o.id,
            )
        per_level = {"high": 1.0, "medium": 0.6, "low": 0.35, "unspecified": 0.25}
        counts = {
            "VN-AI-2025": 5,
            "VN-DEC142-2026": 5,
            "VN-TT53-2026": 8,
            "VN-QD33-2026": 5,
            "VN-PDPL-2025": 4,
            "VN-CYBER-2025": 3,
            "VN-TT09-2020": 3,
            "VN-TT50-2024": 3,
            "VN-DEC356-2025": 2,
        }
        for p in self.plans:
            if p.cls == "not_system":
                scale = 0.2
            else:
                scale = per_level[p.level if p.level in per_level else "low"]
            chosen: list[tuple[Any, str]] = []
            for inst, pool in pools.items():
                if not pool:
                    continue
                if inst == "VN-QD33-2026" and not p.high:
                    continue
                if inst == "VN-PDPL-2025" and p.arch["pd"] == "none":
                    continue
                k = max(1, round(counts[inst] * scale))
                for o in p.rng.sample(pool, k=min(k, len(pool))):
                    chosen.append((o, inst))
            gaps: dict[tuple[str, str], list[str]] = {}
            for o, inst in chosen:
                cov = _coverage(o)
                applies = "yes"
                if p.rng.random() < 0.04:
                    applies, cov = "needs_answer", "unknown"
                # RegKB maps most duties to partial or no Supervisor control; a duty is closed
                # by a bank control (closing_control) mostly in the operation stage
                close_p = {"full": 0.6, "partial": 0.45, "none": 0.2}.get(cov, 0.0)
                if p.stage != "operation":
                    close_p /= 4
                if applies == "yes" and p.rng.random() < close_p:
                    st = "closed"
                elif p.rng.random() < 0.03:
                    st = "waived"
                else:
                    st = "open"
                if st == "open" and applies == "yes" and cov in ("partial", "none"):
                    gaps.setdefault((inst, cov), []).append(o.id)
                due = None
                if p.rng.random() < 0.25:
                    due = (self.now + dt.timedelta(days=p.rng.randint(-30, 300))).date()
                self.add(
                    "obligation_status",
                    {
                        "status_id": status_id(p.system_id, o.id),
                        "system_id": p.system_id,
                        "obligation_id": o.id,
                        "instrument_id": inst,
                        "applies": applies,
                        "coverage": cov,
                        "status": st,
                        "owner_user": p.owner,
                        "due_date": due,
                        "closing_control": "CTL-BANK-MANUAL" if st == "closed" else None,
                        "note": f"[{TAG}] {BANNER}",
                        "created_at": self._stamp(p, max(p.age - 1, 0)),
                    },
                )
            p.gaps = gaps

    # -- tasks ---------------------------------------------------------------------------
    def tasks(self) -> None:
        from supervisor.tasks.service import task_id_for

        cfg = self.tasks_cfg
        templates = [t for t in cfg.get("templates", []) if t.get("stage") in STAGES]
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        floor = {"high_risk": "high", "unclassified": "medium", "not_high_risk": "low"}
        for p in self.plans:
            base = p.level if p.level in rank else "low"
            level = max(base, floor[p.d33], key=lambda x: rank[x])
            cur = STAGES.index(p.stage)
            # the stage start dates, from the creation of the system to the current stage
            span = max(p.age - p.entered, 1)
            starts = {
                s: p.age - int(span * i / max(cur, 1)) if i < cur else p.entered
                for i, s in enumerate(STAGES[: cur + 1])
            }
            custom = [
                (
                    "SYS-INTAKE-CONFIRM",
                    "Confirm the intake answers of the new system",
                    "initiation",
                ),
                ("SYS-INTAKE-CHECKS", "Run the intake checks of the new system", "initiation"),
            ]
            for tid, title, stage in custom:
                if p.status == "draft":
                    status = "open"
                elif tid == "SYS-INTAKE-CHECKS" and p.stage in ("initiation", "design"):
                    status = "open" if p.rng.random() < 0.6 else "done"
                else:
                    status = "done"
                self._task(
                    p,
                    task_id_for,
                    tid,
                    "custom",
                    stage,
                    title,
                    "owner",
                    True,
                    status,
                    14,
                    "none",
                    None,
                    level,
                    starts.get(stage, p.age),
                    p.owner,
                )
            for t in templates:
                st = str(t["stage"])
                if STAGES.index(st) > cur:
                    continue
                if rank[level] < rank.get(str(t.get("min_level") or "low"), 0):
                    continue
                classes = t.get("classes")
                if classes and p.d33 not in classes:
                    continue
                rf = t.get("required_from")
                required = bool(rf) and rank[level] >= rank[str(rf)]
                ev = t.get("evidence") or {}
                if STAGES.index(st) < cur:
                    status = "done"
                else:
                    r = p.rng.random()
                    if p.stage == "operation":
                        status = "done" if r < 0.93 else ("in_progress" if r < 0.96 else "open")
                    else:
                        status = "done" if r < 0.5 else ("in_progress" if r < 0.75 else "open")
                self._task(
                    p,
                    task_id_for,
                    str(t["id"]),
                    "task",
                    st,
                    str(t["title"]),
                    str(t["owner_role"]),
                    required,
                    status,
                    int(t.get("due_days") or 14),
                    str(ev.get("kind") or "none"),
                    ev.get("ref"),
                    level,
                    starts.get(st, p.age),
                    p.owner,
                )
            # gap tasks from the open duties
            groups = sorted(p.gaps.items())
            if groups and p.stage not in ("initiation", "retirement") and p.rng.random() < 0.7:
                for (inst, cov), ids in groups[:3]:
                    shown = ", ".join(sorted(ids)[:20])
                    n = len(ids)
                    self._task(
                        p,
                        task_id_for,
                        f"DUTY-{inst}-{cov}",
                        "custom",
                        "initiation",
                        f"Close {n} {'duty' if n == 1 else 'duties'} of {inst} (coverage {cov})",
                        "owner",
                        False,
                        "open" if p.rng.random() < 0.85 else "in_progress",
                        14,
                        "none",
                        f"{BANNER} {shown}"[:400],
                        level,
                        p.entered + 2,
                        p.owner,
                    )

    def _task(
        self,
        p: Plan,
        task_id_for: Callable[[str, str], str],
        template: str,
        kind: str,
        stage: str,
        title: str,
        owner_role: str,
        required: bool,
        status: str,
        due_days: int,
        ev_kind: str,
        ev_ref: str | None,
        level: str,
        start_days: float,
        owner: str,
    ) -> None:
        created = self._stamp(p, start_days)
        if status != "done":
            if p.rng.random() < 0.06 and required:  # a few overdue
                created = self.now - dt.timedelta(days=due_days + p.rng.randint(2, 25))
            else:
                created = self.now - dt.timedelta(days=p.rng.uniform(0, max(due_days - 2, 1)))
        due = created + dt.timedelta(days=due_days)
        done_at = done_by = None
        if status == "done":
            done_at = min(created + dt.timedelta(days=p.rng.uniform(0.5, due_days * 1.3)), self.now)
            who = {"reviewer": p.reviewer, "approver": p.approver}.get(owner_role, owner)
            done_by = who
        self.add(
            "task",
            {
                "task_id": task_id_for(p.system_id, template),
                "agent_id": p.system_id,
                "template_id": template,
                "kind": kind,
                "stage": stage,
                "target_stage": None,
                "title": title,
                "owner_role": owner_role,
                "required": required,
                "status": status,
                "due_at": due,
                "evidence_kind": ev_kind
                if ev_kind in ("control", "pack", "document", "none")
                else "none",
                "evidence_ref": ev_ref if status == "done" or kind == "custom" else None,
                "level": level,
                "d33_class": p.d33,
                "waive_reason": None,
                "waive_requested_by": None,
                "waive_approved_by": None,
                "done_by": done_by,
                "done_at": done_at,
                "created_at": created,
                "created_by": CREATED_BY,
            },
        )

    # -- approvals, guardians --------------------------------------------------------------
    def approvals(self) -> None:
        pending = 0
        for p in self.plans:
            cur = STAGES.index(p.stage)
            steps = [("validation", "deployment"), ("deployment", "operation")]
            if p.cls == "none" or p.cls == "prohibited":
                continue
            for i, (frm, to) in enumerate(steps):
                idx_to = STAGES.index(to)
                if idx_to < cur:
                    when = (
                        p.entered + (cur - idx_to) * 20 if p.stage != "retirement" else p.age // 2
                    )
                    status = "approved"
                elif idx_to == cur:
                    when = p.entered
                    status = "approved"
                elif (
                    p.stage == "deployment"
                    and to == "operation"
                    and p.high
                    and pending < max(2, self.n // 60)
                ):
                    pending += 1
                    when = 3
                    status = "pending"
                else:
                    continue
                created = self._stamp(p, when + 2)
                decided = self._stamp(p, when) if status != "pending" else None
                self.add(
                    "stage_approval",
                    {
                        "approval_id": f"{PREFIX}apr_{p.idx:04d}_{i}",
                        "system_id": p.system_id,
                        "from_stage": frm,
                        "to_stage": to,
                        "requested_by": p.owner,
                        "status": status,
                        "decided_by": p.approver if status != "pending" else None,
                        "reason": f"[{TAG}] Criteria met (synthetic)."
                        if status != "pending"
                        else None,
                        "created_at": created,
                        "decided_at": decided,
                        "applied_at": decided,
                    },
                )

    def guardians(self) -> None:
        from supervisor.governance.rules_service import assignment_id

        for p in self.plans:
            if p.stage not in ("deployment", *LIVE_STAGES):
                continue
            a = p.arch
            floor: dict[str, str] = {}
            if a["pd"] in ("identifiable", "special") and a["seg"] == "customer":
                floor["dlp_vn"] = "AR-PDPL-CUSTOMER"
            elif a["pd"] in ("identifiable", "special"):
                floor.setdefault("injection_regex", "AR-PDPL-STAFF")
            if p.high:
                floor["dlp_vn"] = "AR-D33-HIGH"
                floor["injection_regex"] = "AR-D33-HIGH"
            if p.auto in ("l4_autonomous_bounded", "l5_self_directed"):
                floor["session_monitor"] = "AR-AUTONOMY-L4"
            seen = self._stamp(p, p.entered + 2)
            for slug, rule in sorted(floor.items()):
                self.add(
                    "assignment",
                    {
                        "assignment_id": assignment_id(p.system_id, "guardian", slug),
                        "system_id": p.system_id,
                        "rule_id": rule,
                        "kind": "guardian",
                        "ref_id": slug,
                        "active": True,
                        "fired": [{"rule": rule, "fields": ["decision33_class", "autonomy_level"]}],
                        "first_seen": seen,
                        "last_seen": self.now,
                    },
                )
            slugs = dict.fromkeys(floor, True)
            if not slugs:
                slugs["injection_regex"] = False if a["gen"] else False
            if a["gen"]:
                slugs.setdefault("injection_regex", False)
            if p.high or p.rng.random() < 0.3:
                slugs["judge_t2_sample"] = False
            if a["decides"]:
                slugs["monitor_drift"] = False
            if a["credit"]:
                slugs["monitor_fairness"] = False
            for slug, mandatory in sorted(slugs.items()):
                off = (not mandatory) and p.rng.random() < 0.1
                self.add(
                    "guardian_binding",
                    {
                        "system_id": p.system_id,
                        "feature_slug": slug,
                        "state": "off" if off else "on",
                        "mandatory": mandatory,
                        "set_by": p.owner,
                        "set_at": seen,
                        "reason": f"[{TAG}] Not needed for this system (synthetic)."
                        if off
                        else None,
                    },
                )

    # -- gate rollups --------------------------------------------------------------------
    def rollups(self) -> None:
        today = _day_floor(self.now)
        for p in self.plans:
            if not p.agent_id or p.stage != "operation" and p.stage != "re_evaluation":
                continue
            a = p.arch
            r = random.Random(f"showcase:{self.seed}:gate:{p.idx}")
            if a["seg"] == "customer":
                base = r.randint(1500, 6000)
            elif a["money"]:
                base = r.randint(400, 2000)
            else:
                base = r.randint(150, 1400)
            block_bp = {"high": r.randint(20, 80), "medium": r.randint(10, 40)}.get(
                p.level, r.randint(2, 15)
            )
            mask_bp = r.randint(100, 300) if a["pd"] != "none" else r.randint(0, 30)
            pauses_max = 3 if p.auto in ("l3_tool_using_supervised", "l4_autonomous_bounded") else 0
            shadow = any(
                x["agent_id"] == p.agent_id and x["gate_state"] == "SHADOW"
                for x in self.rows["agent"]
            )
            for d in range(DAYS, 0, -1):
                day = (today - dt.timedelta(days=d)).date()
                weekend = day.weekday() >= 5
                req = int(base * (0.35 if weekend else 1.0) * r.uniform(0.8, 1.2))
                blocks = 0 if shadow else int(req * block_bp * r.uniform(0.5, 1.5) / 10000)
                masked = int(req * mask_bp * r.uniform(0.5, 1.5) / 10000)
                pauses = (
                    r.randint(0, pauses_max)
                    if (pauses_max and not shadow and r.random() < 0.3)
                    else 0
                )
                skips = int(req * r.uniform(0, 0.002))
                reports = int(req * r.uniform(0.01, 0.04))
                allows = max(req - blocks - masked - pauses - skips - reports, 0)
                req = allows + blocks + masked + pauses + skips + reports
                self.add(
                    "decision_daily",
                    {
                        "usage_date": day,
                        "dimension": "agent",
                        "dim_key": p.agent_id,
                        "dim_key2": "*",
                        "requests": req,
                        "allows": allows,
                        "reports": reports,
                        "transforms": masked,
                        "pauses": pauses,
                        "blocks": blocks,
                        "skips": skips,
                        "not_evaluated": int(req * r.uniform(0, 0.005)),
                        "p50_us": None,
                        "p95_us": None,
                        "computed_at": datetime_end(day),
                    },
                )

    # -- incidents and cases -------------------------------------------------------------
    def events(self) -> None:
        r = random.Random(f"showcase:{self.seed}:events")
        live = [
            p for p in self.plans if p.agent_id and p.cls in ("high_self", "high_certify", "medium")
        ]
        if not live:
            return
        n_inc = max(1, round(14 * self.n / 300))
        n_case = max(1, round(10 * self.n / 300))
        kinds = ("alert", "gate_stop", "detector_failed", "monitor_failing", "judge_escalation")
        titles = {
            "alert": "Alert raised on {name}",
            "gate_stop": "Gate stopped a risky tool call of {name}",
            "detector_failed": "A detector failed for {name}",
            "monitor_failing": "A monitor is failing for {name}",
            "judge_escalation": "A judge escalated a review of {name}",
        }
        statuses = ["open"] * 5 + ["investigating"] * 3 + ["resolved"] * 4 + ["closed"] * 2
        picked = r.sample(live, k=min(len(live), n_inc + n_case))
        case_ids: list[str] = []
        for i, p in enumerate(picked[:n_case], start=1):
            cid = f"{PREFIX}case_{i:03d}"
            case_ids.append(cid)
            sev = "high" if p.high else r.choice(("medium", "medium", "low"))
            opened = self.now - dt.timedelta(days=r.uniform(0.2, 12))
            self.add(
                "cases",
                {
                    "case_id": cid,
                    "agent_id": p.agent_id,
                    "severity": sev,
                    "status": r.choice(("open", "open", "triaged")),
                    "opened_at": opened,
                    "assignee": p.reviewer,
                    "itsm_ref": None,
                    "regulation_refs": ["VN-TT53-2026 Art. 11(2)"],
                    "summary": f"[{TAG}] {r.choice(CASE_TEXT)}",
                    "report_due_at": None,
                    "closed_at": None,
                    "case_type": r.choice(("rule", "judge", "drift")),
                    "incident_detected_at": None,
                    "urgency_class": None,
                    "prelim_report_due_at": None,
                    "formal_report_due_at": None,
                    "prelim_report_sent_at": None,
                    "formal_report_sent_at": None,
                },
            )
        for i, p in enumerate(picked[:n_inc], start=1):
            kind = kinds[(i - 1) % len(kinds)]
            st = statuses[(i - 1) % len(statuses)]
            opened = self.now - dt.timedelta(days=r.uniform(0.5, 25))
            closed = (
                opened + dt.timedelta(days=r.uniform(0.5, 4))
                if st in ("resolved", "closed")
                else None
            )
            self.add(
                "incident",
                {
                    "incident_id": f"{PREFIX}inc_{i:03d}",
                    "system_id": p.system_id,
                    "agent_id": p.agent_id or "-",
                    "kind": kind,
                    "severity": "high"
                    if p.high and i % 3 == 0
                    else r.choice(("low", "medium", "medium")),
                    "title": titles[kind].format(name=p.name)[:200],
                    "event_ref": f"{kind}:{PREFIX}evt_{i:03d}",
                    "root_cause": f"[{TAG}] Under review (synthetic)." if st != "open" else None,
                    "affected_scope": f"[{TAG}] One agent." if st != "open" else None,
                    "status": st,
                    "opened_at": opened,
                    "closed_at": closed,
                    "closed_by": p.reviewer if closed else None,
                    "case_id": case_ids[(i - 1) % len(case_ids)]
                    if case_ids and i % 3 == 0
                    else None,
                },
            )

    # -- all -----------------------------------------------------------------------------
    def build(self) -> Portfolio:
        self.systems()
        self.inventory()
        self.classification()
        self.dimensions()
        self.duties()
        self.tasks()
        self.approvals()
        self.guardians()
        self.rollups()
        self.events()
        self.rows["inventory_node"] = [self.nodes[k] for k in sorted(self.nodes)]
        self.rows["inventory_edge"] = [self.edges[k] for k in sorted(self.edges)]
        cands = sorted(n["display_name"] for n in self.nodes.values() if n["status"] == "unmanaged")
        return Portfolio(self.n, self.seed, self.rows, self.plans, cands)


CASE_TEXT: tuple[str, ...] = (
    "Reply draft contained a field that should have been masked (synthetic).",
    "Tool call rate rose above the weekly norm (synthetic).",
    "A judge flagged an answer without a source (synthetic).",
    "Drift monitor flagged a shift in the score distribution (synthetic).",
    "Several calls were stopped by the money rule in one hour (synthetic).",
)


def datetime_end(day: dt.date) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, 23, 55, tzinfo=dt.UTC)


def _file_sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


def _coverage(o: Any) -> str:
    cov = [str(c.coverage) for c in o.control_mapping]
    if cov and all(c == "full" for c in cov):
        return "full"
    if any(c in ("full", "partial") for c in cov):
        return "partial"
    return "none"


def build_portfolio(
    n: int = DEFAULT_SYSTEMS,
    seed: int = DEFAULT_SEED,
    *,
    now: dt.datetime | None = None,
    tasks_config: Path | None = None,
) -> Portfolio:
    """Pure generator: every row of the portfolio, no store involved."""
    from supervisor.regkb import load_kb

    if n < 1:
        raise ShowcaseError("--systems must be at least 1")
    stamp = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    cfg_path = tasks_config or (REPO_ROOT / "config" / "tasks.yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return Builder(n, seed, stamp, load_kb(), cfg).build()


# ----------------------------------------------------------------------------------- writer


def _lit(value: Any, typ: str) -> str:
    if value is None:
        return "NULL"
    if typ in ("int", "money"):
        return str(int(value))
    if typ == "float":
        return repr(float(value))
    if typ == "bool":
        return "true" if value else "false"
    if typ == "timestamp":
        v = value.astimezone(dt.UTC)
        return f"TIMESTAMP'{v.strftime('%Y-%m-%d %H:%M:%S.%f')}+00:00'"
    if typ == "date":
        v = value.date() if isinstance(value, dt.datetime) else value
        return f"DATE'{v.isoformat()}'"
    text = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if typ == "json"
        else str(value)
    )
    if "\\" in text or "\x00" in text:
        raise ShowcaseError("a generated text value holds a backslash or NUL; refused")
    return "'" + text.replace("'", "''") + "'"


class Writer:
    """Batch inserts and prefix deletes on a ``SqlExecutor`` (SQLite or Databricks)."""

    DELTA_CHUNK = 150

    def __init__(self, executor: Any, model: Any, now: dt.datetime) -> None:
        self.x = executor
        self.model = model
        self.now = now

    def _q(self, table: str) -> str:
        return str(self.x.qualify(table))

    def existing(self, table: str) -> set[tuple[str, ...]]:
        t = self.model.table(table)
        col, prefix = SCOPE[table]
        cols = ", ".join(t.primary_key)
        sql = f"SELECT {cols} FROM {self._q(table)} WHERE {_scope_clause(col, prefix)}"
        rows = self.x.query(sql, column_types=t.types)
        return {tuple(_key(r[k]) for k in t.primary_key) for r in rows}

    def count(self, table: str) -> int:
        col, prefix = SCOPE[table]
        sql = f"SELECT COUNT(*) AS n FROM {self._q(table)} WHERE {_scope_clause(col, prefix)}"
        rows = self.x.query(sql)
        return int(rows[0]["n"]) if rows else 0

    def delete(self, table: str) -> int:
        n = self.count(table)
        col, prefix = SCOPE[table]
        self.x.execute(f"DELETE FROM {self._q(table)} WHERE {_scope_clause(col, prefix)}")
        return n

    def _complete(self, t: Any, row: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(row)
        if not t.append_only:
            data["row_version"] = 1
            data["updated_at"] = self.now
        unknown = sorted(set(data) - set(t.column_names))
        if unknown:
            raise ShowcaseError(f"{t.name}: unknown columns {unknown}")
        out: dict[str, Any] = {}
        for c in t.columns:
            v = data.get(c.name)
            if v is None and not c.nullable:
                raise ShowcaseError(f"{t.name}.{c.name} is required (NOT NULL)")
            out[c.name] = v
        return out

    def insert(self, table: str, rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
        """Insert the rows whose key is not there yet. Returns (new, skipped)."""
        t = self.model.table(table)
        if t.append_only:
            raise ShowcaseError(f"{table} is append-only; the seeder never writes it")
        have = self.existing(table)
        new: list[dict[str, Any]] = []
        seen: set[tuple[str, ...]] = set()
        for r in rows:
            data = self._complete(t, r)
            key = tuple(_key(data[k]) for k in t.primary_key)
            if key in have or key in seen:
                continue
            seen.add(key)
            new.append(data)
        cols = t.column_names
        target = self._q(table)
        if self.x.dialect == "sqlite":
            per = max(1, self.x.max_params // len(cols))
            for i in range(0, len(new), per):
                batch = new[i : i + per]
                params = {f"{c}_{j}": row[c] for j, row in enumerate(batch) for c in cols}
                values = ", ".join(
                    "(" + ", ".join(f":{c}_{j}" for c in cols) + ")" for j in range(len(batch))
                )
                self.x.execute(f"INSERT INTO {target} ({', '.join(cols)}) VALUES {values}", params)
        else:
            types = t.types
            for i in range(0, len(new), self.DELTA_CHUNK):
                batch = new[i : i + self.DELTA_CHUNK]
                values = ", ".join(
                    "(" + ", ".join(_lit(row[c], types[c]) for c in cols) + ")" for row in batch
                )
                self.x.execute(f"INSERT INTO {target} ({', '.join(cols)}) VALUES {values}")
        return len(new), len(rows) - len(new)


def _scope_clause(col: str, prefix: str) -> str:
    return f"substr({col}, 1, {len(prefix)}) = '{prefix}'"


def _key(v: Any) -> str:
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.UTC).isoformat()
    return str(v)


# ----------------------------------------------------------------------------------- run


@dataclass
class Report:
    ok: bool = True
    lines: list[str] = field(default_factory=list)
    written: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    removed: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    portfolio: Portfolio | None = None


def summarise(pf: Portfolio) -> list[str]:
    cls = Counter(p.cls for p in pf.plans)
    stg = Counter(p.stage for p in pf.plans)
    out = [
        "[OK] classes: " + ", ".join(f"{c} {cls.get(c, 0)}" for c in CLASSES),
        "[OK] stages: " + ", ".join(f"{s} {stg.get(s, 0)}" for s in STAGES),
        f"[OK] unmanaged candidates: {len(pf.candidates)}",
    ]
    return out


def run(
    settings: Settings | None,
    *,
    systems: int = DEFAULT_SYSTEMS,
    seed: int = DEFAULT_SEED,
    remove: bool = False,
    dry_run: bool = False,
    echo: Echo = default_echo,
    env: Mapping[str, str] | None = None,
    now: dt.datetime | None = None,
    adapters: Any = None,
) -> Report:
    """Seed (or remove) the portfolio. Never raises for a refusal or a store problem: the report
    carries ``[FAIL]`` with the fix."""
    rep = Report()
    t0 = time.monotonic()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    def fail(line: str) -> Report:
        rep.ok = False
        say(f"[FAIL] {line}")
        rep.seconds = time.monotonic() - t0
        return rep

    msg = check_enabled(env)
    if msg:
        return fail(msg)
    stamp = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    own = adapters is None
    try:
        if dry_run and not remove:
            pf = build_portfolio(systems, seed, now=stamp)
            rep.portfolio = pf
            for line in summarise(pf):
                say(line)
            for t in TABLE_ORDER:
                say(f"[SKIP] dry run: {t}: {len(pf.rows[t])} row(s) would be written")
            say(f"[OK] dry run: {sum(len(r) for r in pf.rows.values())} row(s), nothing written")
            rep.seconds = time.monotonic() - t0
            return rep
        if adapters is None:
            if settings is None:
                return fail("no settings")
            from supervisor.adapters.factory import build_adapters

            adapters = build_adapters(settings)
        w = Writer(adapters.executor, adapters.model, stamp)
        say(f"[OK] showcase target: {adapters.executor.describe()}")
        if remove:
            for t in reversed(TABLE_ORDER):
                if dry_run:
                    n = w.count(t)
                    say(f"[SKIP] dry run: {t}: {n} row(s) would be removed")
                else:
                    n = w.delete(t)
                    say(f"[OK] {t}: {n} row(s) removed")
                rep.removed[t] = n
            say(f"[OK] showcase removed: {sum(rep.removed.values())} row(s)")
        else:
            pf = build_portfolio(systems, seed, now=stamp)
            rep.portfolio = pf
            for line in summarise(pf):
                say(line)
            for t in TABLE_ORDER:
                new, skipped = w.insert(t, pf.rows[t])
                rep.written[t] = new
                rep.skipped[t] = skipped
                say(f"[OK] {t}: {new} new, {skipped} existing")
            say(
                f"[OK] showcase portfolio: {systems} system(s), "
                f"{sum(rep.written.values())} row(s) written. Every row is synthetic and tagged "
                f"'{TAG}' (or has an id with the prefix '{PREFIX}')"
            )
    except SqlError as exc:
        return fail(
            f"store error ({type(exc).__name__}: {str(exc)[:240]}). "
            "Fix: python -m supervisor.jobs.bootstrap_schema, then retry"
        )
    except ShowcaseError as exc:
        return fail(str(exc))
    finally:
        if own and adapters is not None:
            adapters.close()
    rep.seconds = time.monotonic() - t0
    say(f"[OK] done in {rep.seconds:.1f} s")
    return rep


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.demo.showcase portfolio",
        description="Seed (or remove) the synthetic showcase portfolio of AI systems. "
        f"Needs {ENABLE_VAR}=1.",
    )
    parser.add_argument("--systems", type=int, default=DEFAULT_SYSTEMS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--remove", action="store_true", help="delete exactly the showcase rows")
    parser.add_argument("--dry-run", action="store_true", help="count the rows; write nothing")
    parser.add_argument(
        "--demo-dir",
        default=None,
        help="use a local SQLite store under this folder (laptop demo) instead of the settings",
    )
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    msg = check_enabled()
    if msg:
        default_echo(f"[FAIL] {msg}")
        return 1
    from supervisor.config import load_settings

    try:
        if ns.demo_dir:
            from supervisor.demo.session import demo_settings

            settings = demo_settings(ns.demo_dir)
        else:
            settings = load_settings()
    except Exception as exc:  # noqa: BLE001 - report with the fix, never a traceback
        default_echo(f"[FAIL] settings: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    rep = run(
        settings,
        systems=ns.systems,
        seed=ns.seed,
        remove=ns.remove,
        dry_run=ns.dry_run,
        echo=default_echo,
    )
    return 0 if rep.ok else 1


__all__ = [
    "CLASS_COUNTS",
    "STAGE_COUNTS",
    "TAG",
    "Portfolio",
    "Report",
    "ShowcaseError",
    "build_portfolio",
    "check_enabled",
    "main",
    "run",
]
