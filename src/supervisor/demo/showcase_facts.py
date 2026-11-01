# ruff: noqa: S311, S608, S105, E501  (deterministic synthetic data, not crypto; SQL text uses schema names and constants only; long fact texts copy the scanner)
"""Synthetic code-scan facts for the showcase portfolio (demo only).

    SHOWCASE_ENABLED=1 python -m supervisor.demo.showcase_facts [--seed N] [--dry-run] [--reset]
                                                                [--demo-dir DIR] [--agents-only]

The showcase portfolio (``showcase_portfolio.py``, 300 systems) has no source code, so the facts
card (``onboard_facts``, flag ``ONBOARD_FACTS``) is empty for all of it and a risk assessment can
only say "not known". This module writes **synthetic** code-scan facts in exactly the shape the
real scanner (Discover and Understand, ``onboard.facts.collect_rows``) writes, so that
``orchestrator.facts_for`` and ``factory.schemas.facts_v1.export_card`` return them like real ones.

What is written, per scanned system (the agent node ``shw_ag_*``; with ``--agents-only`` off, also
the application node of systems in validation or deployment, which have code but no agent yet):

* one ``intake_attempt`` row (attempt 1, ``created_by`` = ``seed.showcase.facts``, status
  ``scrubbed``, a detail note that says there is no stored source tree), so the card has a
  "latest attempt";
* the ``onboard_facts`` rows: purpose, tools (with risk class, approval and reversibility), the
  model call and endpoint, datasets, external addresses, secret use, approval points, autonomy,
  Decision 33, weak spots, personal data field claims (NAMES only, never a value) and a summary row.

How the facts are derived. The generator reads each system record (purpose, type, personal data,
money, credit, human control, autonomy, segment, risk level) and its inventory edges (tools, model
endpoint, datasets), then builds a code picture that agrees with the record, and plants
disagreements at fixed rates (see ``RATES``). A planted disagreement is chosen by a hash rank, so
the same seed gives the same output on every run, and the counts are exact, not random. The planted
patterns are the executive finding keys (``money_tool_no_gate``, ``declared_control_mismatch``,
``personal_data_mismatch``, ``model_unknown``, ``no_tracing``, ``hardcoded_secret``,
``external_endpoint``, ``risk_level_mismatch``, ``pii_export_tool``): the run prints how many
systems carry each key, counted from the written facts with the rules of the key table.

Synthetic marker. ``facts_v1.source`` is an enum (``rule`` or ``model``) and cannot say "synthetic".
So every row carries ``model_id = "synthetic"`` (a free text field the schema allows) and the
summary row detail starts with ``SYNTHETIC DEMO FACTS``; the facts panel shows the pill
``model: synthetic``. Facts are ``source=rule`` (confidence ``high``). File paths are invented
(``code/<slug>/tools.py``); no secret value (a hard-coded secret shows as ``[REDACTED:<kind>]``,
as in the real scrubbed tree) and no personal data value is written.

Safe by default. ``SHOWCASE_ENABLED=1`` is needed. Idempotent: a row whose key exists is skipped;
a node that already has other facts is left alone. ``--reset`` deletes only rows with
``model_id = 'synthetic'`` and the intake rows created by this module. It never touches any other
node (the demo use case ``inv_0d33cdf0bc7aeebb`` is refused by name as well).
``showcase portfolio --remove`` does not know these rows: run ``--reset`` first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.errors import SqlError
from supervisor.demo.session import Echo, default_echo
from supervisor.demo.showcase_portfolio import (
    CREATED_BY,
    ENABLE_VAR,
    NODE_PREFIX,
    PREFIX,
    ShowcaseError,
    Writer,
    _scope_clause,
    check_enabled,
)
from supervisor.onboard.facts import MAX_DETAIL, MAX_QUOTE, SUMMARY, fact_id_for
from supervisor.onboard.scrub import scrub_text

MARK = "seed.showcase.facts"  # intake_attempt.created_by of the rows this module wrote
SYN = "synthetic"  # onboard_facts.model_id of every row this module wrote
BANNER = "SYNTHETIC DEMO FACTS"
DEFAULT_SEED = 7
ATTEMPT = 1
PROTECTED_NODES = frozenset({"inv_0d33cdf0bc7aeebb"})  # the user's demo use case
STAGES_WITH_CODE = ("operation", "re_evaluation", "validation", "deployment")

# Planted pattern rates, as a share of the scanned systems. The count is round(rate * N), picked by
# a hash rank among the systems that can carry the pattern, so the result is exact and repeatable.
RATES: dict[str, float] = {
    "money_ungated_declared": 0.4,  # of money-tool systems that declare a control: share ungated
    "money_ungated_none": 0.55,  # of money-tool systems that declare no control: share ungated
    "pre_approval_ungated": 0.6,  # of systems declaring pre_approval: share with an ungated tool
    "post_review_autonomous_ungated": 0.5,  # of post_review L3/L4 records: share ungated
    "personal_data_mismatch": 0.08,  # record says none, code handles personal data
    "pd_fields_absent": 0.15,  # record says personal data, no field found in code
    "model_unknown": 0.15,  # of LLM-backed systems' count basis: share of all scanned
    "no_tracing": 0.30,
    "hardcoded_secret": 0.03,
    "risk_level_mismatch": 0.03,  # decision33 high_risk, record low or medium
    "external_endpoint": 0.25,
    "loopback_only": 0.35,  # share of the rest with a loopback address
    "placeholder_only": 0.20,  # share of the rest with a FILL-ME placeholder address
    "pii_export_tool": 0.06,
    "unapproved_tool": 0.02,
    "gated_without_declaration": 0.15,  # record says no control, code has an approval step
}

KEYS: tuple[str, ...] = (
    "money_tool_no_gate",
    "declared_control_mismatch",
    "personal_data_fields",
    "personal_data_mismatch",
    "pii_export_tool",
    "model_unknown",
    "no_tracing",
    "hardcoded_secret",
    "external_endpoint",
    "risk_level_mismatch",
)

# ----------------------------------------------------------------------------------- vocabulary

ID_FIELDS = ("ho_ten", "so_dien_thoai", "dia_chi", "so_tai_khoan", "cccd", "ngay_sinh", "email")
PSEUDO_FIELDS = ("ma_khach_hang", "ma_the_token", "so_tai_khoan_hash", "customer_token")
SPECIAL_FIELDS = ("tinh_trang_suc_khoe", "sinh_trac_hoc")
MISMATCH_FIELDS = ("ho_ten", "so_dien_thoai", "dia_chi", "so_tai_khoan", "cccd")

DESTINATION_TOOLS = frozenset({"prepare_transfer", "execute_transfer", "release_payment"})
DESTINATION_TOOLS |= {"place_fx_order"}
WRITE_TOOLS: tuple[tuple[str, str], ...] = (
    ("update_ticket", "ticket"),
    ("update_case_status", "case"),
    ("create_task", "task"),
    ("send_customer_message", "customer_message"),
)
PII_TOOLS: tuple[str, ...] = ("export_customer_profile", "send_statement_email", "add_payee")

REVERSIBILITY = {
    "money": "{n} moves or waives money{e}: not reversible by the agent once executed",
    "credit": "{n} records a credit decision{e}: reversible only by a human process",
    "pii_export": "{n} discloses or stores personal data{e}: disclosure cannot be recalled",
    "read_only": "{n} writes a record{e} although its risk class is read_only: review the class",
}

# model families as the record tag names them -> (family in the facts, provider, via)
FAMILY_MAP: dict[str, tuple[str, str, str]] = {
    "glm": ("glm", "openai", "ChatOpenAI"),
    "qwen": ("qwen", "openai", "ChatOpenAI"),
    "gemma": ("google", "openai", "ChatOpenAI"),
    "llama": ("meta", "openai", "ChatOpenAI"),
    "mistral": ("mistral", "openai", "ChatOpenAI"),
}
VENDOR_FAMILIES = (("openai", "openai", "ChatOpenAI"), ("anthropic", "anthropic", "ChatAnthropic"))
LLM_TAGS = frozenset({*FAMILY_MAP, "vendor_llm"})

EXTERNAL_LLM = ("https://api.vendor-ai.example/v1", "https://llm.gateway-vendor.example/v1")
EXTERNAL_OTHER = (
    "https://ekyc.partner-vn.example/v1/verify",
    "https://sms.provider-vn.example/send",
    "https://crm.vendor-crm.example/hooks/notify",
    "https://scoring.bureau-vn.example/api/v2/score",
)
LOOPBACK_URL = "http://127.0.0.1:8001/v1"
PLACEHOLDER_URLS = (
    "https://FILL-ME-workspace-host/serving-endpoints",
    "https://FILL-ME-llm-gateway-host/v1",
)

NO_TRACING = (
    "No tracing found (no OpenTelemetry or MLflow use): Watch needs the tracing hook from the "
    "onboarding pull request"
)
SECRET_NOTE = (
    "1 secret-looking value(s) found and redacted before analysis; rotate them and move them to a "
    "secret store"
)
MANIFEST = "supervisor.manifest.yaml"


# ----------------------------------------------------------------------------------- helpers


def _h(seed: int, tag: str, key: str) -> int:
    digest = hashlib.sha256(f"{seed}|{tag}|{key}".encode()).hexdigest()
    return int(digest[:12], 16)


def _pick(seed: int, tag: str, key: str, options: Sequence[Any]) -> Any:
    return options[_h(seed, tag, key) % len(options)]


def _top(seed: int, tag: str, pool: Sequence[Any], k: int, key: Any = lambda s: s.sid) -> list[Any]:
    """The ``k`` members of ``pool`` with the lowest hash rank (stable, independent per tag)."""
    ranked = sorted(pool, key=lambda s: (_h(seed, tag, key(s)), key(s)))
    return ranked[: max(0, min(k, len(ranked)))]


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out[:28] or "agent"


def _clean(text: Any, limit: int) -> str:
    raw = "".join(c if c in "\t " or ord(c) >= 32 else " " for c in str(text or ""))
    return scrub_text(raw).text.strip()[:limit]


# ----------------------------------------------------------------------------------- inputs


@dataclass
class SysIn:
    """One system as the generator needs it (read from the database)."""

    sid: str
    node_id: str  # the node the facts attach to: the agent id, or the application node
    on_agent: bool
    rec: Mapping[str, Any]
    tools: list[tuple[str, str]] = field(default_factory=list)  # (name, risk class)
    endpoint: str | None = None
    datasets: list[tuple[str, str]] = field(default_factory=list)  # (name, read|write)

    @property
    def slug(self) -> str:
        return _slug(str(self.rec.get("name") or self.sid)) + "_" + self.sid[-4:]

    @property
    def tag_family(self) -> str:
        tags = self.rec.get("tags") or {}
        if isinstance(tags, str):
            tags = json.loads(tags)
        return str(tags.get("model_family") or "")

    @property
    def tag_vendor(self) -> str:
        tags = self.rec.get("tags") or {}
        if isinstance(tags, str):
            tags = json.loads(tags)
        return str(tags.get("vendor") or "")

    @property
    def llm(self) -> bool:
        return self.tag_family in LLM_TAGS


@dataclass
class ToolSpec:
    name: str
    cls: str  # read_only | pii_export | money | credit
    mutates: tuple[str, ...] = ()
    approved: bool = True

    @property
    def acting(self) -> bool:
        return self.cls in ("money", "credit") or bool(self.mutates)

    @property
    def destination(self) -> bool:
        return self.cls == "money" and self.name in DESTINATION_TOOLS


@dataclass
class Spec:
    """What the generator decided for one system."""

    s: SysIn
    tools: list[ToolSpec] = field(default_factory=list)
    gated: bool = False  # a human approval step in the code, next to the acting tools
    pd_fields: list[str] = field(default_factory=list)
    family: tuple[str, str, str] | None = None  # (family, provider, via) when LLM-backed
    model_unknown: bool = False
    urls: list[tuple[str, str]] = field(default_factory=list)  # (url, file)
    no_tracing: bool = False
    secret: bool = False
    plants: set[str] = field(default_factory=set)


def _rows(executor: Any, model: Any, table: str, where: str) -> list[dict[str, Any]]:
    t = model.table(table)
    sql = f"SELECT * FROM {executor.qualify(table)} WHERE {where}"
    return [dict(r) for r in executor.query(sql, column_types=t.types)]


def load_systems(adapters: Any, *, agents_only: bool = False) -> list[SysIn]:
    """The showcase systems that get facts, with their tools, endpoint and datasets (from the
    inventory edges the portfolio seeder wrote). Sorted by system id."""
    x, model = adapters.executor, adapters.model
    recs = _rows(x, model, "ai_system", f"created_by = '{CREATED_BY}'")
    comps = _rows(x, model, "system_component", _scope_clause("system_id", PREFIX))
    nodes = {
        r["node_id"]: r
        for r in _rows(x, model, "inventory_node", _scope_clause("name", NODE_PREFIX))
    }
    edges = _rows(x, model, "inventory_edge", _scope_clause("evidence_ref", "shw:"))
    out_edges: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        if str(e.get("active", True)).lower() not in ("false", "0"):
            out_edges.setdefault(e["src_id"], []).append(e)
    agent_of: dict[str, str] = {}
    app_node_of: dict[str, str] = {}
    for c in comps:
        if str(c.get("active", True)).lower() in ("false", "0"):
            continue
        if c["ref_kind"] == "agent" and c["role"] == "component_of":
            agent_of[c["system_id"]] = c["ref_id"]
        elif c["ref_kind"] == "node" and c["role"] == "component_of":
            app_node_of[c["system_id"]] = c["ref_id"]
    systems: list[SysIn] = []
    for rec in sorted(recs, key=lambda r: r["system_id"]):
        sid = rec["system_id"]
        if sid in agent_of:
            node_id, on_agent = agent_of[sid], True
        elif (
            not agents_only
            and rec.get("lifecycle_stage") in STAGES_WITH_CODE
            and sid in app_node_of
        ):
            node_id, on_agent = app_node_of[sid], False
        else:
            continue
        if node_id in PROTECTED_NODES:
            continue
        si = SysIn(sid=sid, node_id=node_id, on_agent=on_agent, rec=rec)
        for e in sorted(out_edges.get(app_node_of.get(sid, ""), []), key=lambda e: e["dst_id"]):
            n = nodes.get(e["dst_id"])
            if n is None:
                continue
            attrs = n.get("attrs") or {}
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            if n["kind"] == "tool" and e["kind"] == "uses":
                si.tools.append((str(n["display_name"]), str(attrs.get("risk_class", "read_only"))))
            elif n["kind"] == "model_endpoint" and e["kind"] == "uses" and si.endpoint is None:
                si.endpoint = str(n["display_name"])
            elif n["kind"] == "dataset":
                si.datasets.append(
                    (str(n["display_name"]), "write" if e["kind"] == "writes" else "read")
                )
        si.tools.sort()
        si.datasets.sort()
        systems.append(si)
    return systems


# ----------------------------------------------------------------------------------- planning


def plan(systems: Sequence[SysIn], seed: int) -> dict[str, Spec]:
    """Decide the code picture of every system and plant the disagreements at the RATES."""
    n = len(systems)
    specs: dict[str, Spec] = {s.sid: Spec(s) for s in systems}
    for sp in specs.values():
        _base(sp, seed)
    quota = {k: round(v * n) for k, v in RATES.items()}

    def pool(pred: Any) -> list[Spec]:
        return [sp for sp in specs.values() if pred(sp)]

    def money(sp: Spec) -> bool:
        return any(t.cls == "money" for t in sp.tools)

    # A. money tools without a human approval step
    declared = pool(lambda sp: money(sp) and sp.gated and sp.s.rec["human_control"] != "none")
    for sp in _top(
        seed,
        "money_declared",
        declared,
        round(RATES["money_ungated_declared"] * len(declared)),
        lambda x: x.s.sid,
    ):
        sp.gated = False
        sp.plants.add("money_tool_no_gate")
    # records that declare no control: most money systems have no approval step in code either
    none_money = pool(lambda sp: money(sp) and sp.s.rec["human_control"] == "none")
    for sp in none_money:
        sp.gated = False
    regate = len(none_money) - round(RATES["money_ungated_none"] * len(none_money))
    for sp in _top(seed, "money_none", none_money, regate, lambda x: x.s.sid):
        sp.gated = True
    for sp in none_money:
        if not sp.gated:
            sp.plants.add("money_tool_no_gate")
    # B. a pre_approval record, code with an acting tool and no approval step
    pre = pool(lambda sp: sp.s.rec["human_control"] == "pre_approval" and not money(sp))
    for sp in _top(
        seed,
        "pre_approval",
        pre,
        round(RATES["pre_approval_ungated"] * len(pre)),
        lambda x: x.s.sid,
    ):
        _add_write_tool(sp, seed)
        sp.gated = False
        sp.plants.add("declared_control_mismatch")
    # C. post_review records of autonomous automation: no approval step
    auto = pool(
        lambda sp: (
            sp.s.rec["human_control"] == "post_review"
            and sp.s.rec["autonomy_level"] in ("l3_tool_using_supervised", "l4_autonomous_bounded")
            and sp.gated
            and not money(sp)
        )
    )
    for sp in _top(
        seed,
        "post_review_auto",
        auto,
        round(RATES["post_review_autonomous_ungated"] * len(auto)),
        lambda x: x.s.sid,
    ):
        _add_write_tool(sp, seed)
        sp.gated = False
        sp.plants.add("declared_control_mismatch")
    # H. decision33 high_risk while the record says low or medium
    low = pool(
        lambda sp: (
            sp.s.rec["risk_level"] in ("low", "medium")
            and not any(t.cls in ("money", "credit") for t in sp.tools)
            and sp.s.rec["autonomy_level"] != "l0_rule_based"
        )
    )
    low.sort(key=lambda sp: (sp.s.rec["system_type"] != "automation", sp.s.sid))
    first = [sp for sp in low if sp.s.rec["system_type"] == "automation"]
    chosen = _top(seed, "risk_mismatch", first, quota["risk_level_mismatch"], lambda x: x.s.sid)
    if len(chosen) < quota["risk_level_mismatch"]:
        rest = [sp for sp in low if sp not in chosen]
        chosen += _top(
            seed,
            "risk_mismatch2",
            rest,
            quota["risk_level_mismatch"] - len(chosen),
            lambda x: x.s.sid,
        )
    for sp in chosen:
        sp.tools.append(ToolSpec("execute_transfer", "money"))
        sp.gated = False
        sp.plants.add("risk_level_mismatch")
    # D. personal data in code while the record says none
    nopd = pool(
        lambda sp: sp.s.rec["personal_data"] == "none" and sp.s.rec["system_type"] != "platform"
    )
    for sp in _top(seed, "pd_mismatch", nopd, quota["personal_data_mismatch"], lambda x: x.s.sid):
        k = 1 + _h(seed, "pd_count", sp.s.sid) % 3
        sp.pd_fields = _sample(seed, "pd_mis", sp.s.sid, MISMATCH_FIELDS, k)
        sp.plants.add("personal_data_mismatch")
    # J. personal data export tools (identifiable records)
    ident = pool(lambda sp: sp.s.rec["personal_data"] in ("identifiable", "special"))
    for sp in _top(seed, "pii_tool", ident, quota["pii_export_tool"], lambda x: x.s.sid):
        sp.tools.append(
            ToolSpec(
                _pick(seed, "pii_name", sp.s.sid, PII_TOOLS), "pii_export", ("customer_profile",)
            )
        )
        sp.plants.add("pii_export_tool")
    # K. a tool that is registered but not approved
    for sp in _top(
        seed,
        "unapproved",
        pool(lambda sp: bool(sp.tools)),
        quota["unapproved_tool"],
        lambda x: x.s.sid,
    ):
        sp.tools[_h(seed, "unapp_i", sp.s.sid) % len(sp.tools)].approved = False
    # E. the model family cannot be told
    llm = pool(lambda sp: sp.family is not None)
    for sp in _top(seed, "model_unknown", llm, quota["model_unknown"], lambda x: x.s.sid):
        sp.model_unknown = True
        sp.plants.add("model_unknown")
    # F. no tracing; G. a hard-coded secret
    for sp in _top(
        seed, "no_tracing", list(specs.values()), quota["no_tracing"], lambda x: x.s.sid
    ):
        sp.no_tracing = True
        sp.plants.add("no_tracing")
    for sp in _top(
        seed, "secret", list(specs.values()), quota["hardcoded_secret"], lambda x: x.s.sid
    ):
        sp.secret = True
        sp.plants.add("hardcoded_secret")
    # I. addresses: external first for vendor models and partner segments
    rest = list(specs.values())
    rest.sort(
        key=lambda sp: (
            not (sp.s.tag_family == "vendor_llm"),
            sp.s.rec["user_segment"] != "partner",
            sp.s.sid,
        )
    )
    forced = [sp for sp in rest if sp.s.tag_family == "vendor_llm"]
    others = [sp for sp in rest if sp not in forced]
    need = max(0, quota["external_endpoint"] - len(forced))
    ext = forced + _top(seed, "external", others, need, lambda x: x.s.sid)
    ext_ids = {sp.s.sid for sp in ext}
    for sp in ext:
        sp.plants.add("external_endpoint")
    remaining = [sp for sp in specs.values() if sp.s.sid not in ext_ids]
    loop = _top(
        seed,
        "loopback",
        remaining,
        round(RATES["loopback_only"] * len(remaining)),
        lambda x: x.s.sid,
    )
    loop_ids = {sp.s.sid for sp in loop}
    remaining2 = [sp for sp in remaining if sp.s.sid not in loop_ids]
    ph = _top(
        seed,
        "placeholder",
        remaining2,
        round(RATES["placeholder_only"] * len(remaining)),
        lambda x: x.s.sid,
    )
    ph_ids = {sp.s.sid for sp in ph}
    for sp in specs.values():
        sid = sp.s.sid
        if sid in ext_ids:
            pool_ = EXTERNAL_LLM if sp.family is not None else EXTERNAL_OTHER
            sp.urls.append((_pick(seed, "ext_url", sid, pool_), "config.py"))
            if _h(seed, "ext_two", sid) % 4 == 0 and sp.family is not None:
                sp.urls.append((_pick(seed, "ext_url2", sid, EXTERNAL_OTHER), "settings.yaml"))
        elif sid in loop_ids:
            sp.urls.append((LOOPBACK_URL, "config.py"))
        elif sid in ph_ids:
            sp.urls.append((_pick(seed, "ph_url", sid, PLACEHOLDER_URLS), "app.yaml"))
    return specs


def _sample(seed: int, tag: str, key: str, options: Sequence[str], k: int) -> list[str]:
    ranked = sorted(options, key=lambda o: (_h(seed, f"{tag}:{o}", key), o))
    return sorted(ranked[:k])


def _add_write_tool(sp: Spec, seed: int) -> None:
    if any(t.acting for t in sp.tools):
        return
    name, what = _pick(seed, "write_tool", sp.s.sid, WRITE_TOOLS)
    sp.tools.append(ToolSpec(name, "read_only", (what,)))


def _base(sp: Spec, seed: int) -> None:
    """The code picture that agrees with the record (before any planting)."""
    s, rec = sp.s, sp.s.rec
    auto = rec["autonomy_level"]
    hc = rec["human_control"]
    if auto == "l0_rule_based":
        sp.tools = []
    else:
        sp.tools = [ToolSpec(n, c) for n, c in s.tools]
        if not sp.tools:
            sp.tools = [ToolSpec("lookup_faq", "read_only")]
        if auto in ("l2_workflow_step", "l3_tool_using_supervised", "l4_autonomous_bounded"):
            _add_write_tool(sp, seed)
    # approval step in code
    if hc in ("pre_approval", "post_review"):
        sp.gated = True
    else:
        sp.gated = _h(seed, "gated_none", s.sid) % 100 < round(
            RATES["gated_without_declaration"] * 100
        )
    # model
    if s.tag_family in FAMILY_MAP:
        sp.family = FAMILY_MAP[s.tag_family]
    elif s.tag_family == "vendor_llm":
        sp.family = _pick(seed, "vendor_family", s.sid, VENDOR_FAMILIES)
    # personal data fields
    pd = rec["personal_data"]
    if pd != "none" and _h(seed, "pd_absent", s.sid) % 100 >= round(
        RATES["pd_fields_absent"] * 100
    ):
        if pd == "pseudonymised":
            sp.pd_fields = _sample(
                seed, "pd_ps", s.sid, PSEUDO_FIELDS, 1 + _h(seed, "pd_n", s.sid) % 2
            )
        else:
            k = 2 + _h(seed, "pd_n", s.sid) % 4
            sp.pd_fields = _sample(seed, "pd_id", s.sid, ID_FIELDS, k)
            if pd == "special":
                sp.pd_fields = sorted({*sp.pd_fields, _pick(seed, "pd_sp", s.sid, SPECIAL_FIELDS)})


# ----------------------------------------------------------------------------------- facts


class _Rows:
    def __init__(self, node_id: str, now: dt.datetime) -> None:
        self.node_id, self.now = node_id, now
        self.rows: dict[str, dict[str, Any]] = {}

    def add(self, kind: str, name: str, detail: str, file: str, line: int, quote: str) -> None:
        name_c = _clean(name, 200) or kind
        fid = fact_id_for(self.node_id, ATTEMPT, kind, name_c, file, line)
        if fid in self.rows:
            return
        self.rows[fid] = {
            "fact_id": fid,
            "node_id": self.node_id,
            "attempt_n": ATTEMPT,
            "kind": kind,
            "name": name_c,
            "detail": _clean(detail, MAX_DETAIL),
            "file": file,
            "line": line,
            "quote": _clean(quote, MAX_QUOTE),
            "source": "rule",
            "model_id": SYN,
            "dropped_claims": None,
            "active": True,
            "created_at": self.now,
        }


def _autonomy(tools: Sequence[ToolSpec], gated: bool) -> tuple[str, str, list[str]]:
    if not tools:
        return "L0", "no tools: the agent only answers with text", []
    acting = [t for t in tools if t.acting]
    if not acting:
        return "L1", "every tool only reads", []
    if gated:
        return "L2", "every tool with a side effect has a human approval step in the same code", []
    names = sorted(t.name for t in acting)
    return (
        "L3",
        "tools with side effects and no human approval step in code: " + ", ".join(names),
        names,
    )


def build_rows(sp: Spec, seed: int, now: dt.datetime) -> list[dict[str, Any]]:
    """The fact rows of one system in the shape of ``facts.collect_rows`` plus the summary row."""
    s = sp.s
    out = _Rows(s.node_id, now)
    base = f"code/{s.slug}"
    tools_py, cfg_py, prompts_py = f"{base}/tools.py", f"{base}/config.py", f"{base}/prompts.py"
    line_of = {t.name: 24 + 14 * i for i, t in enumerate(sorted(sp.tools, key=lambda t: t.name))}

    purpose = str(s.rec.get("purpose") or f"Agent {s.sid}")
    out.add("claim", "purpose", purpose, prompts_py, 3, f'SYSTEM_PROMPT = "{purpose[:120]}"')

    for t in sorted(sp.tools, key=lambda t: t.name):
        bits = [f"risk_class={t.cls}", f"approved={'yes' if t.approved else 'no'}"]
        if t.mutates:
            bits.append("side_effects=" + ",".join(sorted(t.mutates)))
        if t.cls != "read_only" or t.mutates:
            eff = f" (changes {', '.join(t.mutates)})" if t.mutates else ""
            bits.append("reversibility: " + REVERSIBILITY[t.cls].format(n=t.name, e=eff))
        sig = (
            "from_account: str, to_account: str, amount_minor: int"
            if t.destination
            else "request: dict[str, Any]"
        )
        out.add(
            "tool",
            t.name,
            "; ".join(bits),
            tools_py,
            line_of[t.name],
            f"def {t.name}({sig}) -> dict[str, Any]:",
        )

    if sp.family is not None:
        fam, provider, via = sp.family
        fam_out = "unknown" if sp.model_unknown else fam
        ep = s.endpoint or f"{s.tag_family or 'llm'}-endpoint"
        mname = ep.removesuffix("-endpoint")
        if sp.model_unknown:
            mname, ep = "unknown", "llm-gateway-endpoint"
        out.add(
            "model",
            mname,
            f"provider={provider}; family={fam_out}; via={via}",
            f"{base}/planner.py",
            75,
            f"return {via}(",
        )
        out.add(
            "endpoint",
            ep,
            f"family={fam_out}; declared in code",
            cfg_py,
            39,
            f'llm_model=os.environ.get("LLM_MODEL", "{ep}"),',
        )

    for i, (name, direction) in enumerate(s.datasets):
        out.add(
            "dataset",
            name,
            f"direction={direction}; source=code",
            f"{base}/data.py",
            10 + 6 * i,
            f'spark.table("{name}")',
        )

    for i, (url, where) in enumerate(sp.urls):
        file = {
            "config.py": cfg_py,
            "settings.yaml": f"{base}/settings.yaml",
            "app.yaml": "app.yaml",
        }[where]
        line = (38 + i) if where == "config.py" else (22 + i)
        if where == "app.yaml":
            quote = f'value: "{url}"'
        elif where == "settings.yaml":
            quote = f"webhook_url: {url}"
        else:
            quote = f'llm_base_url=os.environ.get("LLM_BASE_URL", "{url}"),'
        out.add(
            "external_url",
            url,
            "an address in the code (query and fragment are not stored)",
            file,
            line,
            quote,
        )

    if sp.secret:
        kind = _pick(seed, "secret_kind", s.sid, ("assigned_secret", "llm_api_key", "bearer_token"))
        out.add(
            "secret_use",
            kind,
            "a secret-looking value is in the code (kind only; the value is never stored)",
            cfg_py,
            12,
            f'LLM_API_KEY = "[REDACTED:{kind}]"',
        )

    # approval steps
    acting = [t for t in sp.tools if t.acting]
    if sp.gated:
        if acting:
            out.add(
                "approval_point",
                "human approval step",
                "a human approval step in the code",
                tools_py,
                12,
                "def request_human_approval(ticket_id: str) -> bool:",
            )
        else:
            out.add(
                "approval_point",
                "human approval step",
                "a human approval step in the code",
                f"{base}/review.py",
                9,
                "def queue_for_human_review(output_id: str) -> None:",
            )

    level, reason, open_names = _autonomy(sp.tools, sp.gated)
    ev_t = acting[0] if acting else None
    if level in ("L2", "L3") and ev_t is not None:
        a_file, a_line, a_quote = tools_py, line_of[ev_t.name], f"def {ev_t.name}("
    else:
        a_file, a_line, a_quote = MANIFEST, 1, "manifest_version: 1"
    out.add("autonomy", level, reason, a_file, a_line, a_quote)

    tx = [t for t in sp.tools if t.destination]
    cr = [t for t in sp.tools if t.cls == "credit"]
    entries: list[tuple[str, bool, str, ToolSpec]] = []
    if tx:
        why = (
            "Tools execute electronic transactions to a destination ("
            + ", ".join(t.name for t in tx)
            + "); "
            + (
                "a human approval step was found in the same code; a reviewer confirms it runs before execution"
                if sp.gated
                else "no human inspection, approval or control before execution was found in code"
            )
        )
        entries.append(("transactions", not sp.gated, why, tx[0]))
    if cr:
        why = (
            "Tools record credit decisions ("
            + ", ".join(t.name for t in cr)
            + "); "
            + (
                "an independent approval step was found in the same code; a reviewer confirms a credit officer approves before the decision takes effect"
                if sp.gated
                else "no independent approval by a credit officer was found in code"
            )
        )
        entries.append(("credit", not sp.gated, why, cr[0]))
    high = any(e[1] for e in entries)
    any_gate = sp.gated and bool(entries)
    anchor = entries[0][3] if entries else None
    d_file, d_line, d_quote = (
        (tools_py, line_of[anchor.name], f"def {anchor.name}(")
        if anchor
        else (MANIFEST, 1, "manifest_version: 1")
    )
    out.add(
        "decision33",
        "high_risk" if high else "not_high_risk",
        f"proposal only, counsel confirms; human_gate_in_code={any_gate}",
        d_file,
        d_line,
        d_quote,
    )
    for entry, triggered, why, t in entries:
        out.add(
            "decision33",
            f"{entry} {'triggered' if triggered else 'not triggered'}",
            why[:500],
            tools_py,
            line_of[t.name],
            f"def {t.name}(",
        )

    for t in sorted(sp.tools, key=lambda t: t.name):
        if not t.approved:
            msg = f"Tool {t.name} is registered in the agent but not approved for its flows; only an external gate can stop a call"
            out.add("weak_spot", msg, msg, tools_py, line_of[t.name], f"def {t.name}(")
    if sp.secret:
        out.add("weak_spot", SECRET_NOTE, SECRET_NOTE, cfg_py, 12, 'LLM_API_KEY = "[REDACTED]"')
    if sp.no_tracing:
        out.add("weak_spot", NO_TRACING, NO_TRACING, MANIFEST, 1, "manifest_version: 1")

    for i, name in enumerate(sp.pd_fields):
        out.add(
            "claim",
            f"Handles personal data field '{name}'",
            "category=personal_data",
            f"{base}/schemas.py",
            8 + 3 * i,
            f"    {name}: str",
        )

    rows = list(out.rows.values())
    rows.append(
        {
            "fact_id": fact_id_for(s.node_id, ATTEMPT, SUMMARY, "build", "", 0),
            "node_id": s.node_id,
            "attempt_n": ATTEMPT,
            "kind": SUMMARY,
            "name": "build",
            "detail": _clean(
                f"{BANNER}: generated by supervisor.demo.showcase_facts (seed {seed}), not a real "
                f"code scan; the paths are invented. facts={len(rows)}; skipped_without_pointer=0; "
                "model_used=no; claims_proposed=0; claims_kept=0; claims_dropped=0",
                MAX_DETAIL,
            ),
            "file": None,
            "line": None,
            "quote": None,
            "source": "rule",
            "model_id": SYN,
            "dropped_claims": 0,
            "active": True,
            "created_at": now,
        }
    )
    return rows


def intake_row(sp: Spec, seed: int, now: dt.datetime, n_rows: int) -> dict[str, Any]:
    s = sp.s
    digest = hashlib.sha256(f"{seed}|intake|{s.node_id}".encode()).hexdigest()
    return {
        "attempt_id": "ita_" + digest[:24],
        "node_id": s.node_id,
        "n": ATTEMPT,
        "source_kind": "upload",
        "source_ref": f"synthetic-{s.slug}.zip",
        "sha256": digest,
        "size_bytes": 4000 + int(digest[:4], 16) % 20000,
        "file_count": 5 + int(digest[4:6], 16) % 8,
        "created_by": MARK,
        "created_at": now,
        "status": "scrubbed",
        "detail": f"{BANNER}: no stored source tree; files=0 redacted={1 if sp.secret else 0}",
    }


# ----------------------------------------------------------------------------------- observe


def observe(rec: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """The finding keys that fire for one system, read from the written facts and the record only."""
    facts = [r for r in rows if r["kind"] != SUMMARY]
    keys: set[str] = set()
    money = [r["name"] for r in facts if r["kind"] == "tool" and "risk_class=money" in r["detail"]]
    open_names: set[str] = set()
    gate_false = False
    for r in facts:
        if r["kind"] == "autonomy" and "no human approval step in code:" in r["detail"]:
            open_names |= {x.strip() for x in r["detail"].split(":", 1)[1].split(",")}
        if (
            r["kind"] == "decision33"
            and r["name"] == "high_risk"
            and "human_gate_in_code=False" in r["detail"]
        ):
            gate_false = True
    if money and (open_names & set(money) or gate_false):
        keys.add("money_tool_no_gate")
    has_gate = any(r["kind"] == "approval_point" for r in facts)
    if rec["human_control"] in ("pre_approval", "post_review") and not has_gate:
        keys.add("declared_control_mismatch")
    pd_rows = [
        r
        for r in facts
        if r["kind"] == "claim" and r["name"].startswith("Handles personal data field")
    ]
    if pd_rows:
        keys.add("personal_data_fields")
        if rec["personal_data"] == "none":
            keys.add("personal_data_mismatch")
    if any(r["kind"] == "tool" and "risk_class=pii_export" in r["detail"] for r in facts):
        keys.add("pii_export_tool")
    if any(r["kind"] in ("model", "endpoint") and "family=unknown" in r["detail"] for r in facts):
        keys.add("model_unknown")
    if any(r["kind"] == "weak_spot" and r["name"].startswith("No tracing found") for r in facts):
        keys.add("no_tracing")
    if any(r["kind"] == "secret_use" for r in facts):
        keys.add("hardcoded_secret")
    for r in facts:
        if r["kind"] == "external_url":
            u = r["name"].lower()
            if "127.0.0.1" not in u and "localhost" not in u and "fill-me" not in u:
                keys.add("external_endpoint")
    if any(r["kind"] == "decision33" and r["name"] == "high_risk" for r in facts) and rec[
        "risk_level"
    ] not in ("high", "prohibited"):
        keys.add("risk_level_mismatch")
    return keys


# ----------------------------------------------------------------------------------- writer


class FactsWriter(Writer):
    """The portfolio ``Writer`` scoped to the rows of this module (not to the ``shw_`` prefix)."""

    SCOPES: dict[str, tuple[str, str]] = {
        "onboard_facts": ("model_id", SYN),
        "intake_attempt": ("created_by", MARK),
    }

    def existing(self, table: str) -> set[tuple[str, ...]]:
        t = self.model.table(table)
        cols = ", ".join(t.primary_key)
        rows = self.x.query(f"SELECT {cols} FROM {self._q(table)}", column_types=t.types)
        return {tuple(str(r[k]) for k in t.primary_key) for r in rows}

    def count(self, table: str) -> int:
        col, prefix = self.SCOPES[table]
        rows = self.x.query(
            f"SELECT COUNT(*) AS n FROM {self._q(table)} WHERE {_scope_clause(col, prefix)}"
        )
        return int(rows[0]["n"]) if rows else 0

    def delete(self, table: str) -> int:
        n = self.count(table)
        col, prefix = self.SCOPES[table]
        self.x.execute(f"DELETE FROM {self._q(table)} WHERE {_scope_clause(col, prefix)}")
        return n


# ----------------------------------------------------------------------------------- run


@dataclass
class Generated:
    seed: int
    systems: list[SysIn]
    specs: dict[str, Spec]
    facts: dict[str, list[dict[str, Any]]]  # node id -> rows
    intake: list[dict[str, Any]]
    keys: dict[str, set[str]]  # system id -> finding keys

    def key_counts(self) -> dict[str, int]:
        c: Counter[str] = Counter()
        for ks in self.keys.values():
            c.update(ks)
        return {k: c.get(k, 0) for k in KEYS}


def generate(
    systems: Sequence[SysIn], seed: int = DEFAULT_SEED, now: dt.datetime | None = None
) -> Generated:
    """Pure generator: every row, no store involved. Same input and seed give the same rows."""
    stamp = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    for s in systems:
        if s.node_id in PROTECTED_NODES:
            raise ShowcaseError(
                f"{s.node_id} is a protected node; the facts generator never writes it"
            )
    specs = plan(systems, seed)
    facts: dict[str, list[dict[str, Any]]] = {}
    intake: list[dict[str, Any]] = []
    keys: dict[str, set[str]] = {}
    for s in systems:
        sp = specs[s.sid]
        rows = build_rows(sp, seed, stamp)
        facts[s.node_id] = rows
        intake.append(intake_row(sp, seed, stamp, len(rows)))
        keys[s.sid] = observe(s.rec, rows)
    return Generated(seed, list(systems), specs, facts, intake, keys)


@dataclass
class Report:
    ok: bool = True
    lines: list[str] = field(default_factory=list)
    written: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    removed: dict[str, int] = field(default_factory=dict)
    nodes_kept: list[str] = field(default_factory=list)
    key_counts: dict[str, int] = field(default_factory=dict)
    scanned: int = 0
    seconds: float = 0.0


def summary_table(gen: Generated) -> list[str]:
    n = len(gen.systems)
    counts = gen.key_counts()
    lines = [
        f"[OK] finding keys over {n} scanned system(s):",
        f"     {'key':<28}{'systems':>8}{'share':>8}",
    ]
    for k in KEYS:
        share = f"{100 * counts[k] / n:.1f}%" if n else "-"
        lines.append(f"     {k:<28}{counts[k]:>8}{share:>8}")
    return lines


def run(
    settings: Any,
    *,
    seed: int = DEFAULT_SEED,
    reset: bool = False,
    dry_run: bool = False,
    agents_only: bool = False,
    echo: Echo = default_echo,
    env: Mapping[str, str] | None = None,
    now: dt.datetime | None = None,
    adapters: Any = None,
) -> Report:
    """Write (or ``reset``) the synthetic facts. Never raises for a refusal: the report carries
    ``[FAIL]`` with the fix."""
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
        if adapters is None:
            if settings is None:
                return fail("no settings")
            from supervisor.adapters.factory import build_adapters

            adapters = build_adapters(settings)
        w = FactsWriter(adapters.executor, adapters.model, stamp)
        say(f"[OK] facts target: {adapters.executor.describe()}")
        if reset:
            for t in ("onboard_facts", "intake_attempt"):
                if dry_run:
                    n = w.count(t)
                    say(f"[SKIP] dry run: {t}: {n} synthetic row(s) would be removed")
                else:
                    n = w.delete(t)
                    say(f"[OK] {t}: {n} synthetic row(s) removed")
                rep.removed[t] = n
            return _finish(rep, say, t0, "synthetic facts removed")
        systems = load_systems(adapters, agents_only=agents_only)
        if not systems:
            return fail("no showcase system found: run 'showcase portfolio' first")
        gen = generate(systems, seed, stamp)
        rep.scanned = len(systems)
        rep.key_counts = gen.key_counts()
        agents = sum(1 for s in systems if s.on_agent)
        say(
            f"[OK] scanned systems: {len(systems)} ({agents} on an agent node, {len(systems) - agents} on an application node)"
        )
        for line in summary_table(gen):
            say(line)
        have = _node_facts(adapters)
        facts_rows: list[dict[str, Any]] = []
        intake_rows: list[dict[str, Any]] = []
        for s, irow in zip(systems, gen.intake, strict=True):
            rows = gen.facts[s.node_id]
            existing = have.get(s.node_id, set())
            ids = {r["fact_id"] for r in rows}
            done = rows[-1]["fact_id"] in existing  # the summary row is the last one written
            if existing and (not existing <= ids or (done and existing != ids)):
                # other facts (another seed, or real): left alone
                rep.nodes_kept.append(s.node_id)
                continue
            facts_rows += rows
            intake_rows.append(irow)
        if rep.nodes_kept:
            say(
                f"[SKIP] {len(rep.nodes_kept)} node(s) already have other facts; left alone (use --reset to redo)"
            )
        if dry_run:
            say(
                f"[SKIP] dry run: {len(facts_rows)} fact row(s) and {len(intake_rows)} intake row(s) would be written"
            )
            return _finish(rep, say, t0, "dry run, nothing written")
        # the intake row first (the card reads it), the facts after; the summary row is last per node
        for table, rows in (("intake_attempt", intake_rows), ("onboard_facts", facts_rows)):
            new, skipped = w.insert(table, rows)
            rep.written[table], rep.skipped[table] = new, skipped
            say(f"[OK] {table}: {new} new, {skipped} existing")
        return _finish(rep, say, t0, f"{BANNER} written for {len(intake_rows)} node(s)")
    except SqlError as exc:
        return fail(
            f"store error ({type(exc).__name__}: {str(exc)[:240]}). Fix: python -m supervisor.jobs.bootstrap_schema, then retry"
        )
    except ShowcaseError as exc:
        return fail(str(exc))
    finally:
        if own and adapters is not None:
            adapters.close()


def _finish(rep: Report, say: Any, t0: float, text: str) -> Report:
    rep.seconds = time.monotonic() - t0
    say(f"[OK] {text} in {rep.seconds:.1f} s")
    return rep


def _node_facts(adapters: Any) -> dict[str, set[str]]:
    t = adapters.model.table("onboard_facts")
    rows = adapters.executor.query(
        f"SELECT fact_id, node_id FROM {adapters.executor.qualify('onboard_facts')}",
        column_types=t.types,
    )
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(str(r["node_id"]), set()).add(str(r["fact_id"]))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.demo.showcase_facts",
        description="Write (or remove) SYNTHETIC code-scan facts for the showcase portfolio, so that "
        "the facts card and the risk assessment agents have facts to read. "
        f"Needs {ENABLE_VAR}=1. Run 'showcase portfolio' first.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="same seed, same facts")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the summary table; write nothing"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete exactly the synthetic facts this tool wrote"
    )
    parser.add_argument(
        "--agents-only",
        action="store_true",
        help="only systems that have an agent (skip validation and deployment systems)",
    )
    parser.add_argument(
        "--demo-dir",
        default=None,
        help="use the SQLite store under this folder instead of the settings",
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
        seed=ns.seed,
        reset=ns.reset,
        dry_run=ns.dry_run,
        agents_only=ns.agents_only,
        echo=default_echo,
    )
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "KEYS",
    "MARK",
    "RATES",
    "SYN",
    "Generated",
    "Report",
    "generate",
    "load_systems",
    "main",
    "observe",
    "run",
]
