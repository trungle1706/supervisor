"""ReportBuilder (WP31): collect the sections of one agent's report from read-only facts.

``build_full`` makes the superset (every field every variant could show). ``build`` projects it
through the allow-list of one variant (``allowlist.py``), checks the result (the customer
variant gets a second, independent check) and adds the "what this report does not show" section.

A collector that fails does not stop the report: its section says ``source_error`` and the
reason is listed in the not-shown section. The builder holds no SQL; reads are the methods of
``Facts`` and the read services of other packages. WP30 adds the ``controls`` section with
``ReportBuilder.register("controls", fn)`` (see docs/transparency-report.md, "Hooks").
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from supervisor.core.canonical import canonical_json, format_ts, sha256_hex
from supervisor.risk.evidence import EVIDENCE_MONITORS  # noqa: E402
from supervisor.transparency import allowlist
from supervisor.transparency.facts import Facts, fmt_day
from supervisor.transparency.model import (
    GENERATOR,
    MAX_BACKLOG_ROWS,
    MAX_ROWS,
    SCHEMA_VERSION,
    SECTIONS,
    TransparencyError,
    UnknownAgent,
    assert_plain,
    check_agent,
    check_variant,
)

log = logging.getLogger("supervisor.transparency")

Collector = Callable[["Ctx"], dict[str, Any]]
D33_PREFIX = "VN-QD33-2026"
BANDS = ("low", "medium", "high", "critical")
KINDS = ("payment", "credit_decision", "customer_facing", "internal_tool")


def na(reason: str, ref: str | None = None) -> dict[str, Any]:
    """A section that has no data; ``ref`` names the flag or source (fixed words)."""
    return {"available": False, "reason": reason, "ref": ref, "illustrative": False, "data": {}}


def ok(data: Mapping[str, Any], illustrative: bool = False) -> dict[str, Any]:
    return {
        "available": True,
        "reason": None,
        "ref": None,
        "illustrative": illustrative,
        "data": dict(data),
    }


def _cap(rows: list[Any]) -> tuple[list[Any], int]:
    return rows[:MAX_ROWS], max(0, len(rows) - MAX_ROWS)


class Ctx:
    """What a collector sees: the agent, the facts, and a cache of the matrix."""

    def __init__(
        self, facts: Facts, agent_id: str, row: dict[str, Any], fresh_verify: bool = False
    ) -> None:
        self.fresh_verify = fresh_verify
        self.facts = facts
        self.agent_id = agent_id
        self.row = row
        self._matrix: dict[str, Any] | None = None
        self._matrix_err: str | None = None

    @property
    def settings(self) -> Any:
        return self.facts.settings

    def matrix(self) -> dict[str, Any] | None:
        if self._matrix is None and self._matrix_err is None:
            from supervisor.console.compliance_view import ComplianceInputError

            try:
                self._matrix = self.facts.matrix(self.agent_id)
            except ComplianceInputError:
                self._matrix_err = "no_matrix"
        return self._matrix


# --------------------------------------------------------------------------- collectors


def c_identity(c: Ctx) -> dict[str, Any]:
    f, r = c.facts, c.row
    m = c.matrix()
    prod = (m or {}).get("product") or {}
    classes = [x for x in (prod.get("agent_classes") or []) if x in KINDS]
    kind = classes[0] if classes else "other"
    return ok(
        {
            "agent_id": c.agent_id,
            "display_name": f.mask(r.get("name") or c.agent_id, 80),
            "owner_team": f.mask(r.get("owner_team"), 80),
            "owner_user": f.mask(r.get("owner_user"), 80),
            "business_owner": f.mask(r.get("business_owner"), 80),
            "host_type": r.get("host_type"),
            "plug_point": r.get("plug_point"),
            "model_family": r.get("model_family"),
            "risk_tier": r.get("risk_tier"),
            "status": r.get("status"),
            "gate_state": r.get("gate_state"),
            "registered_day": fmt_day(r.get("created_at")),
            "kind": kind,
            "purpose": f.mask(prod.get("purpose"), 320) if prod.get("purpose") else "",
            "oversight": {
                k: prod.get(k)
                for k in (
                    "executes_payments",
                    "human_approval_before_execution",
                    "credit_decisions",
                    "independent_credit_approval",
                )
            },
        }
    )


def c_classification(c: Ctx) -> dict[str, Any]:
    f = c.facts
    m = c.matrix()
    registry = c.row.get("decision33_class")
    proposal = f.d33_proposal(c.agent_id)
    matrix_cls = ((m or {}).get("decision33") or {}).get("classification")
    if registry:
        cls, src = str(registry), "registry"
    elif proposal:
        cls, src = proposal, "proposal"
    elif matrix_cls:
        cls, src = str(matrix_cls), "matrix"
    else:
        return na("no_data", "decision33")
    entries = []
    for e in ((m or {}).get("decision33") or {}).get("entries") or []:
        entries.append(
            {
                "entry": e.get("entry"),
                "triggered": e.get("triggered"),
                "obligation_ids": sorted(e.get("obligation_ids") or []),
            }
        )
    d33_ids = sorted(
        {str(i) for e in entries for i in e["obligation_ids"] if str(i).startswith(D33_PREFIX)}
    )
    return ok(
        {
            "decision33_class": cls,
            "class_source": src,
            "matrix_class": matrix_cls,
            "entries": entries,
            "d33_obligation_ids": d33_ids,
        }
    )


def c_inventory(c: Ctx) -> dict[str, Any]:
    inv = c.facts.inventory(c.agent_id)
    if inv is None:
        return na("flag_off", "INVENTORY_ENABLED")
    if not inv.get("found"):
        return na("not_in_inventory", "inventory")
    links, groups = [], Counter()
    for group, items in sorted((inv.get("links") or {}).items()):
        groups[group] += len(items)
        for it in items:
            links.append(
                {
                    "group": group,
                    "name": c.facts.mask(it.get("name"), 80),
                    "own_risk": it.get("own_risk"),
                    "effective_risk": it.get("effective_risk"),
                    "source": it.get("source"),
                    "evidence_ref": c.facts.mask(it.get("evidence_ref"), 120),
                }
            )
    shown, more = _cap(links)
    return ok(
        {
            "own_risk": inv.get("own_risk"),
            "effective_risk": inv.get("effective_risk"),
            "node_count": int(inv.get("node_count", 0)),
            "groups": [{"group": g, "count": n} for g, n in sorted(groups.items())],
            "links": shown,
            "more": more,
        }
    )


def c_compliance(c: Ctx) -> dict[str, Any]:
    m = c.matrix()
    if m is None:
        return na("no_matrix", "compliance")
    rows = [r for r in (m.get("rows") or []) if isinstance(r, dict)]
    summ = m.get("summary") or {}
    present = {str(r.get("obligation_id")) for r in rows}
    cited = {
        str(i)
        for e in ((m.get("decision33") or {}).get("entries") or [])
        for i in (e.get("obligation_ids") or [])
        if str(i).startswith(D33_PREFIX)
    }
    d33 = [
        {
            "obligation_id": r["obligation_id"],
            "article_ref": r.get("article_ref"),
            "status": r.get("status"),
            "applies": r.get("applies"),
        }
        for r in rows
        if str(r.get("obligation_id", "")).startswith(D33_PREFIX)
    ]
    gaps = [
        {
            "obligation_id": r["obligation_id"],
            "instrument_id": r.get("instrument_id"),
            "status": r.get("status"),
        }
        for r in rows
        if r.get("applies") == "yes" and r.get("status") in ("gap", "partial", "needs_answer")
    ]
    gaps_shown, gaps_more = _cap(gaps)
    hdr = m.get("header") or {}
    return ok(
        {
            "source_kind": m.get("source_kind"),
            "as_of": hdr.get("as_of"),
            "regkb_version": hdr.get("regkb_version"),
            "obligations_total": len(rows),
            "by_status": {k: int(v) for k, v in sorted((summ.get("by_status") or {}).items())},
            "by_applies": {k: int(v) for k, v in sorted((summ.get("by_applies") or {}).items())},
            "questions_open": int(summ.get("questions", len(m.get("questions") or []))),
            "threshold_gaps": int(summ.get("threshold_gaps", 0)),
            "threshold_exceeds": int(summ.get("threshold_exceeds", 0)),
            "d33_rows": d33[:MAX_ROWS],
            "d33_ids_missing": sorted(cited - present),
            "gaps": gaps_shown,
            "gaps_more": gaps_more,
        }
    )


def _placeholder(value: Any) -> bool:
    return not value or str(value).startswith("FILL-ME")


def c_cards(c: Ctx) -> dict[str, Any]:
    f = c.facts
    m = c.matrix()
    agent_card: dict[str, Any] | None = None
    if m is not None:
        p = m.get("product") or {}
        limits = [
            {
                "id": x.get("id"),
                "period": x.get("period"),
                "scope": x.get("scope"),
                "value_vnd": x.get("value_vnd"),
                "ref": (x.get("pointer") or {}).get("ref"),
            }
            for x in (p.get("limits") or [])
        ]
        shown, more = _cap(limits)
        agent_card = {
            "version": p.get("version"),
            "purpose": f.mask(p.get("purpose"), 320),
            "agent_classes": sorted(p.get("agent_classes") or []),
            "autonomy": p.get("autonomy"),
            "data_classes": sorted(p.get("data_classes") or []),
            "roles": sorted(p.get("roles") or []),
            "customer_types": sorted(p.get("customer_types") or []),
            "limits": shown,
            "limits_more": more,
            "provenance_n": len(p.get("provenance") or []),
        }
    jc = f.judge_card()
    ident, metrics, roles = jc["identity"], jc["metrics"], jc["roles"]
    judge_card = {
        "judge_id": ident["judge_id"],
        "is_mock": bool(ident["is_mock"]),
        "prompt_version": ident["prompt_version"],
        "rubric_version": ident["rubric_version"],
        "mask_version": ident["mask_version"],
        "model_version": ident["model_version"],
        "tiers": {
            t: {k: v[k] for k in ("model_id", "family", "kind")} for t, v in ident["tiers"].items()
        },
        "metrics_status": metrics.get("status"),
        "metrics_mock": bool(metrics.get("mock")),
        "catch_rate_bp": metrics.get("catch_rate_bp"),
        "false_alarm_bp": metrics.get("false_alarm_bp"),
        "heldout_split": metrics.get("split"),
        "roles_assigned": sum(1 for v in roles.values() if not _placeholder(v)),
        "roles_total": len(roles),
        "role_names": {k: f.mask(v, 80) for k, v in sorted(roles.items())},
        "failure_modes_n": len(jc.get("known_failure_modes") or []),
    }
    return ok({"agent_card": agent_card, "judge_card": judge_card}, illustrative=True)


def c_assurance(c: Ctx) -> dict[str, Any]:
    rows = c.facts.assurance_latest(c.agent_id)
    if not rows:
        return na("no_data", "assurance")
    counts = Counter(str(r.get("status")) for r in rows)
    packs = [
        {
            "pack_id": r["pack_id"],
            "dimension": r.get("dimension"),
            "status": r.get("status"),
            "day": fmt_day(r.get("ts")),
            "is_mock": bool(r.get("is_mock")),
            "n_items": int(r.get("n_items") or 0),
            "metrics": {k: v for k, v in sorted((r.get("metrics") or {}).items()) if _isint(v)},
        }
        for r in rows
    ]
    shown, more = _cap(packs)
    return ok(
        {
            "packs_total": len(rows),
            "by_status": dict(sorted(counts.items())),
            "mock_n": sum(1 for p in packs if p["is_mock"]),
            "packs": shown,
            "more": more,
        },
        illustrative=True,
    )


def _isint(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def c_judge_mrm(c: Ctx) -> dict[str, Any]:
    f = c.facts
    rows = f.validations()
    jc = f.judge_card()
    latest = [
        {
            "day": fmt_day(r.get("ts")),
            "decision": r.get("decision"),
            "passed": bool(r.get("passed")),
            "is_mock": bool(r.get("is_mock")),
            "model_version": f.mask(r.get("model_version"), 120),
        }
        for r in rows
    ]
    return ok(
        {
            "judge_is_mock": bool(jc["identity"]["is_mock"]),
            "validations_n": len(rows),
            "latest": latest,
            "validation_required": bool(c.settings.judge_require_validation),
            "latest_decision": latest[0]["decision"] if latest else None,
        },
        illustrative=True,
    )


def c_masking(c: Ctx) -> dict[str, Any]:
    s = c.settings
    version = getattr(c.facts.src.masker, "mask_version", None)
    return ok(
        {
            "masker_kind": s.masker_kind,
            "masking_on": s.masker_kind != "none",
            "mask_version": str(version) if version else None,
            "capture_level": s.capture_default_level,
            "amounts_masked": bool(s.mask_amounts),
        }
    )


def c_monitors(c: Ctx) -> dict[str, Any]:
    s = c.settings
    res = c.facts.monitor_bindings(c.agent_id)

    def b(x: Any) -> dict[str, Any]:
        return {"bound": bool(x.bound), "source": x.source, "gap": x.gap}

    latest = c.facts.oversight_latest(c.agent_id)
    return ok(
        {
            "flags": {
                "drift": bool(s.drift_enabled),
                "fairness": bool(s.fairness_enabled),
                "quality": bool(s.quality_enabled),
                "multiagent": bool(s.multiagent_enabled),
                "metrics": bool(s.metrics_enabled),
            },
            "bindings": {
                "quality": b(res.quality),
                "fairness": b(res.fairness),
                "split": b(res.split),
                "drift": {"bound": res.drift is not None},
            },
            "oversight_day": fmt_day(latest["metric_date"]) if latest else None,
            "coverage_bp": latest.get("coverage_bp") if latest else None,
            "events_seen": latest.get("events_seen") if latest else None,
            "events_gated": latest.get("events_gated") if latest else None,
        }
    )


def c_risks(c: Ctx) -> dict[str, Any]:
    summ = c.facts.risk_summary(c.agent_id)
    if summ is None:
        return na("flag_off", "RISK_REGISTER_ENABLED")
    risks = list(summ.get("risks") or [])
    by_band = Counter(str(r.get("residual_band")) for r in risks)
    by_cat = Counter(str(r.get("category")) for r in risks)
    ev = Counter(str(r.get("evidence_state") or "none") for r in risks)
    top = [
        {
            "risk_id": r["risk_id"],
            "title": c.facts.mask(r.get("title"), 100),
            "category": r.get("category"),
            "inherent_score": int(r["inherent_score"]),
            "residual_score": int(r["residual_score"]),
            "residual_band": r.get("residual_band"),
            "evidence_state": r.get("evidence_state"),
            "evidence_reason": r.get("evidence_reason"),
            **c.facts.risk_link_counts(r["risk_id"]),
            "treatment": r.get("treatment"),
            "owner": c.facts.mask(r.get("owner"), 60),
            "via": r.get("via"),
            "own": bool(r.get("own")),
            "review_overdue": bool(r.get("review_overdue")),
        }
        for r in risks[:10]
    ]
    return ok(
        {
            "inherent_level": summ.get("inherent_level"),
            "residual_level": summ.get("residual_level"),
            "inherent_score": int(summ.get("inherent_score") or 0),
            "residual_score": int(summ.get("residual_score") or 0),
            "risks_n": len(risks),
            "by_band": {b: by_band.get(b, 0) for b in BANDS},
            "by_category": dict(sorted(by_cat.items())),
            "by_evidence": dict(sorted(ev.items())),
            "evidence_monitors": list(EVIDENCE_MONITORS),
            "top": top,
            "more": max(0, len(risks) - len(top)),
        },
        illustrative=bool(summ.get("thresholds_illustrative", True)),
    )


def c_controls(_c: Ctx) -> dict[str, Any]:
    """WP30 hook: replaced by ``ReportBuilder.register("controls", ...)``."""
    return na("not_built", "WP30")


def c_evidence(c: Ctx) -> dict[str, Any]:
    f = c.facts
    lane = f.chain_lane(c.agent_id)
    verify = f.verify(c.agent_id, fresh=c.fresh_verify)
    root = f.chain_root()
    return ok(
        {
            "lane": lane,
            "root": root,
            "anchored": f.anchored(),
            "verify": verify,
        }
    )


def c_cases(c: Ctx) -> dict[str, Any]:
    f = c.facts
    rows = f.cases(c.agent_id)
    op = [r for r in rows if r["status"] in ("open", "triaged", "contained")]
    now = f.now()
    oldest = max(((now - r["opened_at"]).total_seconds() for r in op), default=0)
    items = [
        {
            "case_id": r["case_id"],
            "severity": r["severity"],
            "status": r["status"],
            "opened_day": fmt_day(r["opened_at"]),
            "summary": f.mask(r.get("summary"), 120),
        }
        for r in sorted(op, key=lambda r: (str(r["opened_at"]), str(r["case_id"])))
    ]
    shown, more = _cap(items)
    return ok(
        {
            "total_n": len(rows),
            "open_n": len(op),
            "closed_n": sum(1 for r in rows if r["status"] == "closed"),
            "by_severity": dict(sorted(Counter(str(r["severity"]) for r in op).items())),
            "oldest_open_hours": int(oldest // 3600),
            "items": shown,
            "more": more,
        }
    )


def c_backlog(c: Ctx) -> dict[str, Any]:
    rows = c.facts.backlog_rows()
    if rows is None:
        return na("no_data", "BACKLOG.md")
    terms = {c.agent_id.lower()}
    fam = str(c.row.get("model_family") or "").lower()
    if len(fam) >= 4:
        terms.add(fam)
    hits = []
    for item, when in rows:
        words = c.facts.words(item + " " + when)
        if terms & words:
            hits.append({"item": c.facts.mask(item, 220), "returns_when": c.facts.mask(when, 160)})
    shown = hits[:MAX_BACKLOG_ROWS]
    return ok({"matched_n": len(hits), "items": shown, "more": max(0, len(hits) - len(shown))})


COLLECTORS: dict[str, Collector] = {
    "identity": c_identity,
    "classification": c_classification,
    "inventory": c_inventory,
    "compliance": c_compliance,
    "cards": c_cards,
    "assurance": c_assurance,
    "judge_mrm": c_judge_mrm,
    "masking": c_masking,
    "monitors": c_monitors,
    "risks": c_risks,
    "controls": c_controls,
    "evidence": c_evidence,
    "cases": c_cases,
    "backlog": c_backlog,
}


# --------------------------------------------------------------------------- not shown


def not_shown(
    sections: Mapping[str, Mapping[str, Any]], variant: str, extra: Mapping[str, Any]
) -> dict[str, Any]:
    """The "what this report does not show" section: every gap stated by a fixed code."""
    items: list[dict[str, Any]] = []

    def add(code: str, ref: str | None = None, n: int | None = None) -> None:
        item: dict[str, Any] = {"code": code}
        if ref:
            item["ref"] = ref
        if n is not None:
            item["n"] = n
        items.append(item)

    for sid in SECTIONS:
        sec = sections.get(sid)
        if sec is None or sid == "not_shown":
            continue
        if not sec["available"]:
            reason = sec.get("reason") or "no_data"
            add(f"section_{reason}", sid if reason != "flag_off" else sec.get("ref") or sid)
    for sid, sec in sections.items():
        if sec["available"] and sec.get("illustrative"):
            add("illustrative", sid)
    data = lambda sid: sections.get(sid, {}).get("data") or {}  # noqa: E731
    if data("cards").get("judge_card", {}).get("is_mock") or data("judge_mrm").get("judge_is_mock"):
        add("mock_judge", "judge_mrm")
    if sections.get("assurance", {}).get("available") and data("assurance").get("mock_n"):
        add("mock_results", "assurance", int(data("assurance")["mock_n"]))
    ver = (data("evidence").get("verify") or {}).get("state")
    if ver == "not_run":
        add("chain_not_verified", "evidence")
    elif ver == "empty":
        add("chain_empty", "evidence")
    elif ver == "failed":
        add("chain_verify_failed", "evidence")
    if data("compliance").get("d33_ids_missing"):
        add("obligation_missing", "compliance", len(data("compliance")["d33_ids_missing"]))
    for sid, sec in sections.items():
        d = sec.get("data") or {}
        more = int(d.get("more", 0) or 0) + int(d.get("gaps_more", 0) or 0)
        if more:
            add("truncated", sid, more)
    if extra.get("retired"):
        add("agent_retired")
    add("advisory_only", "compliance")
    add("judge_advice_only", "judge_mrm")
    add("no_personal_data")
    if variant != "internal":
        add("variant_limited")
    return {
        "available": True,
        "reason": None,
        "ref": None,
        "illustrative": False,
        "data": {"items": items},
    }


# --------------------------------------------------------------------------- the builder


class ReportBuilder:
    """Builds the report of one agent for one variant from a ``Facts`` object."""

    def __init__(self, facts: Facts, *, fresh_verify: bool = False) -> None:
        self.facts = facts
        self.fresh_verify = fresh_verify
        self.collectors: dict[str, Collector] = dict(COLLECTORS)

    def register(self, section_id: str, fn: Collector) -> None:
        """Hook for another package (WP30: ``controls``). The id must be a known section."""
        if section_id not in SECTIONS or section_id == "not_shown":
            raise TransparencyError(f"unknown section {section_id!r}")
        self.collectors[section_id] = fn

    def build_full(self, agent_id: str) -> dict[str, Any]:
        check_agent(agent_id)
        row = self.facts.agent_row(agent_id)
        if row is None:
            raise UnknownAgent(f"agent {agent_id!r} is not registered")
        ctx = Ctx(self.facts, agent_id, row, self.fresh_verify)
        sections: dict[str, dict[str, Any]] = {}
        for sid in SECTIONS:
            fn = self.collectors.get(sid)
            if fn is None:
                continue
            try:
                sections[sid] = fn(ctx)
            except Exception as exc:  # noqa: BLE001 - one bad source must not hide the report
                log.warning("transparency: section %s failed: %s", sid, type(exc).__name__)
                sections[sid] = na("source_error", type(exc).__name__)
        return {
            "agent_id": agent_id,
            "retired": str(row.get("status")) == "retired",
            "sections": sections,
        }

    def build(
        self, agent_id: str, variant: str, *, version: int = 0, status: str = "preview"
    ) -> dict[str, Any]:
        """The report for ``variant`` (see ``build_pair``)."""
        return self.build_pair(agent_id, variant, version=version, status=status)[0]

    def build_pair(
        self, agent_id: str, variant: str, *, version: int = 0, status: str = "preview"
    ) -> tuple[dict[str, Any], dict[str, set[str]]]:
        """The report for ``variant`` and the strings it must not show: allow-listed sections,
        the not-shown section, the meta block. ``generated_at`` is the clock of the facts; the
        content hash leaves it out."""
        check_variant(variant)
        full = self.build_full(agent_id)
        sections = allowlist.project_sections(full["sections"], variant)
        for sid in SECTIONS:
            if sid == "not_shown":
                continue
            if sid not in sections and variant != "internal":
                sections[sid] = na("not_for_variant", None)
        sections["not_shown"] = allowlist.project_section(
            not_shown(sections, variant, {"retired": full["retired"]}), "not_shown", variant
        )
        ordered = {sid: sections[sid] for sid in SECTIONS if sid in sections}
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "generator": GENERATOR,
            "variant": variant,
            "report_version": int(version),
            "status": status,
            "generated_at": format_ts(self.facts.now()),
            "sections": ordered,
        }
        if variant != "customer":
            report["agent_id"] = agent_id
        assert_plain(report)
        secrets = self.known_secrets(agent_id, full)
        allowlist.guard(report, variant, secrets)
        return report, secrets

    def known_secrets(self, agent_id: str, full: Mapping[str, Any]) -> dict[str, set[str]]:
        """Raw strings a variant must never show: agent ids and people's names (read again from
        the sources, not from the masked report, so a masking gap cannot hide a leak)."""
        f = self.facts
        row = f.agent_row(agent_id) or {}
        team = {str(row["owner_team"])} if row.get("owner_team") else set()
        people = {str(row[k]) for k in ("owner_user", "business_owner") if row.get(k)}
        s = f.settings
        for name in ("mrm_model_owner", "mrm_model_developer", "mrm_validator", "mrm_approver"):
            v = str(getattr(s, name, "") or "")
            if v and not v.startswith("FILL-ME"):
                people.add(v)
        try:
            summary = f.risk_summary(agent_id)
        except Exception:  # noqa: BLE001 - the section already says it failed
            summary = None
        for r in (summary or {}).get("risks") or []:
            if r.get("owner"):
                people.add(str(r["owner"]))
        ids = {agent_id.lower(), *(a.lower() for a in f.agent_ids())}
        people = {p for p in people if len(p) >= 3}
        return {"ids": ids, "people": people | team, "team": team}


# Fields that move with every chain record, including this report's own. They are shown but
# are not part of the change test (else every report would make the next one a new version).
VOLATILE: dict[str, tuple[str, ...]] = {"evidence": ("lane",)}


def stable(report: Mapping[str, Any]) -> dict[str, Any]:
    """The report without time, version, status and the volatile fields."""
    body = {
        k: v for k, v in report.items() if k not in ("generated_at", "report_version", "status")
    }
    secs = {sid: dict(sec) for sid, sec in report["sections"].items()}
    for sid, keys in VOLATILE.items():
        if sid in secs and isinstance(secs[sid].get("data"), dict):
            secs[sid]["data"] = {k: v for k, v in secs[sid]["data"].items() if k not in keys}
    body["sections"] = secs
    return body


def content_hash(report: Mapping[str, Any]) -> str:
    """Hash of the facts only. Same facts, same hash."""
    return sha256_hex(stable(report))


def section_hashes(report: Mapping[str, Any]) -> dict[str, str]:
    return {sid: sha256_hex(sec) for sid, sec in stable(report)["sections"].items()}


def diff_summary(prev: Mapping[str, str] | None, now: Mapping[str, str]) -> dict[str, Any]:
    """Which sections changed since the previous version (ids are fixed words; ints only)."""
    if prev is None:
        return {"first": True, "changed": [], "added": sorted(now), "removed": []}
    return {
        "first": False,
        "changed": sorted(k for k in now if k in prev and prev[k] != now[k]),
        "added": sorted(k for k in now if k not in prev),
        "removed": sorted(k for k in prev if k not in now),
    }


__all__ = [
    "Collector",
    "Ctx",
    "ReportBuilder",
    "canonical_json",
    "content_hash",
    "diff_summary",
    "na",
    "ok",
    "section_hashes",
]
