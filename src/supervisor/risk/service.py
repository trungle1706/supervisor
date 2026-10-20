"""Risk register service (WP29, ADR D26): store, scoring on read, inheritance, evidence, import.

The one object the routes, the console, the CLI and the job use. It reads and writes the
``risk``, ``risk_link`` and ``risk_evidence`` tables through the state and table ports (SQLite
and Delta alike). Scores are computed when read and never stored.

Extension points for later work packages (see docs/risk-register.md, "For other modules"):

* WP30 control catalogue: ``RiskService.control_links(risk_id)`` returns the (kind, target)
  pairs the evidence rule looks at. A catalogue control that maps to risks adds ``rule``,
  ``pack`` or ``monitor`` links through ``add_link``; nothing else changes.
* WP31 transparency report: ``RiskService.agent_summary(agent_id)`` returns the register view
  of one agent (level, risks with scores, bands, evidence state) as plain data.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, NotFoundError
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import node_id_for
from supervisor.inventory.store import InventoryStore
from supervisor.risk import evidence as ev
from supervisor.risk import inherit
from supervisor.risk.model import (
    BAND_RANK,
    BANDS,
    CATEGORIES,
    CONTROL_KINDS,
    EDITABLE,
    LINK_KINDS,
    RiskConfig,
    RiskError,
    check_id,
    check_target,
    load_config,
    normalise,
    score_of,
)
from supervisor.risk.refs import RefCatalogue, build_catalogue

log = logging.getLogger("supervisor.risk")

MAX_IMPORT_BYTES = 2_000_000
MAX_RISKS = 5000
MAX_LINKS_PER_RISK = 100
TREND_ROWS = 12
FILTERS = ("agent", "category", "band", "owner", "status", "treatment", "q")
RISK_CSV = (
    "risk_id",
    "title",
    "category",
    "agent_id",
    "node_id",
    "treatment",
    "inherent_likelihood",
    "inherent_impact",
    "inherent_score",
    "inherent_band",
    "residual_likelihood",
    "residual_impact",
    "residual_score",
    "residual_band",
    "evidence_state",
    "evidence_reason",
    "owner",
    "review_date",
    "status",
    "agents",
)
LINK_CSV = ("risk_id", "kind", "target")


def csv_cell(value: Any) -> str:
    """A CSV cell safe to open in a spreadsheet (no formula injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def link_id(risk_id: str, kind: str, target: str) -> str:
    return "rl_" + sha256_hex({"risk": risk_id, "kind": kind, "target": target})[:24]


def new_risk_id() -> str:
    return "RSK-" + uuid.uuid4().hex[:10].upper()


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_manual: int = 0
    links_added: int = 0
    links_removed: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _date_str(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return None if value in (None, "") else str(value)[:10]


class RiskService:
    def __init__(
        self,
        state: Any,
        tables: Any,
        clock: Any,
        settings: Any,
        *,
        evidence: Any = None,
        catalogue: RefCatalogue | None = None,
        cfg: RiskConfig | None = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self.catalogue = catalogue or build_catalogue(state, settings)
        self.cfg = cfg or load_config(getattr(settings, "risk_config", None))

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> RiskService:
        return cls(
            adapters.state, adapters.tables, adapters.clock, adapters.settings, evidence=evidence
        )

    # ------------------------------------------------------------------ chain
    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(self.evidence_sink.record(record_type, ref, payload))
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("risk chain record failed")
            return None

    def _changed(self, action: str, row: Mapping[str, Any], actor: str) -> None:
        self._chain(
            "risk_change",
            f"risk:{row['risk_id']}",
            {
                "risk_id": row["risk_id"],
                **({"agent_id": row["agent_id"]} if row.get("agent_id") else {}),
                "action": action,
                "actor": actor,
                "status": row["status"],
                "treatment": row["treatment"],
                "inherent_score": score_of(row["inherent_likelihood"], row["inherent_impact"]),
                "declared_residual_score": score_of(
                    row["residual_likelihood"], row["residual_impact"]
                ),
                "row_hash": sha256_hex(_plain(row)),
                "ts": format_ts(self.clock.now()),
            },
        )

    def _fresh(self) -> RefCatalogue:
        """The catalogue with its per-run cache cleared (the deployed policy can change)."""
        self.catalogue.clear()
        return self.catalogue

    # ------------------------------------------------------------------ links
    def _link_rows(self, risk_id: str) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.state.query("risk_link", {"risk_id": risk_id}) if _on(r["active"])
        ]

    def control_links(self, risk_id: str) -> list[tuple[str, str]]:
        """(kind, target) of the links the evidence rule looks at (rule, pack, monitor).
        Extension point for the WP30 control catalogue."""
        return [
            (r["kind"], r["target"]) for r in self._link_rows(risk_id) if r["kind"] in CONTROL_KINDS
        ]

    def links(self, risk_id: str) -> list[dict[str, Any]]:
        return sorted(
            ({"kind": r["kind"], "target": r["target"]} for r in self._link_rows(risk_id)),
            key=lambda x: (LINK_KINDS.index(x["kind"]), x["target"]),
        )

    def add_link(self, risk_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        check_target(kind, target)
        row = self._need(risk_id)
        self._fresh().check(kind, target)
        lid = link_id(risk_id, kind, target)
        out = {"risk_id": risk_id, "kind": kind, "target": target, "added": True}
        cur = self.state.get("risk_link", {"link_id": lid})
        if cur is not None and _on(cur["active"]):
            return out | {"added": False}
        if cur is None and len(self._link_rows(risk_id)) >= MAX_LINKS_PER_RISK:
            raise RiskError(f"a risk can have at most {MAX_LINKS_PER_RISK} links")
        if cur is None:
            self.state.insert("risk_link", self._link_row(risk_id, kind, target, actor))
        else:
            self.state.update("risk_link", {"link_id": lid}, {"active": True}, cur["row_version"])
        self._changed("link", row, actor)
        return out

    def remove_link(self, risk_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        check_target(kind, target)
        row = self._need(risk_id)
        cur = self.state.get("risk_link", {"link_id": link_id(risk_id, kind, target)})
        out = {"risk_id": risk_id, "kind": kind, "target": target, "removed": True}
        if cur is None or not _on(cur["active"]):
            return out | {"removed": False}
        self.state.update(
            "risk_link", {"link_id": cur["link_id"]}, {"active": False}, cur["row_version"]
        )
        self._changed("unlink", row, actor)
        return out

    def _link_row(self, risk_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        return {
            "link_id": link_id(risk_id, kind, target),
            "risk_id": risk_id,
            "kind": kind,
            "target": target,
            "active": True,
            "created_at": self.clock.now(),
            "created_by": actor,
        }

    # ------------------------------------------------------------------ reads
    def _need(self, risk_id: str) -> dict[str, Any]:
        check_id(risk_id)
        row = self.state.get("risk", {"risk_id": risk_id})
        if row is None:
            raise NotFoundError(f"risk {risk_id} does not exist")
        return dict(row)

    def graph(self) -> Graph:
        try:
            return InventoryStore(self.state, self.clock).load_graph()
        except Exception:  # noqa: BLE001 - an old store without the WP24 tables: no inheritance
            return Graph()

    def _latest_evidence(self, risk_id: str | None = None) -> dict[str, dict[str, Any]]:
        where = {"risk_id": risk_id} if risk_id else None
        rows = self.tables.query("risk_evidence", where, order_by=("-ts",), limit=20000)
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            out.setdefault(str(r["risk_id"]), dict(r))
        return out

    def window_seconds(self) -> int:
        return int(self.settings.risk_evidence_window_days) * 86400

    def effective(
        self, row: Mapping[str, Any], latest: Mapping[str, Any] | None, now: dt.datetime
    ) -> dict[str, Any]:
        """Scores, bands and the evidence state of one risk row (the evidence rule applied)."""
        th = self.cfg.thresholds
        inh = (int(row["inherent_likelihood"]), int(row["inherent_impact"]))
        dec = (int(row["residual_likelihood"]), int(row["residual_impact"]))
        state = latest["state"] if latest is not None else None
        evid_ts = latest["ts"] if latest is not None else None
        if row["treatment"] != "mitigate":
            res, reason = dec, "treatment_declared"
        elif latest is None:
            res, reason = inh, "no_evidence_yet"  # a declared residual is a claim, not a fact
        else:
            end = ev_ts(latest["window_end"])
            if end is None or ev.is_stale(end, self.window_seconds(), now):
                state, reason, res = ev.STATE_NONE, "stale_evidence", inh
            else:
                reason = latest["reason"]
                res = dec if state == ev.STATE_WORKING else inh
        grace = dt.timedelta(days=self.cfg.review_grace_days)
        review = row.get("review_date")
        overdue = bool(
            row["status"] == "active"
            and isinstance(review, dt.date)
            and now.date() > review + grace
        )
        return {
            "inherent_score": score_of(*inh),
            "inherent_band": th.band(score_of(*inh)),
            "declared_residual_score": score_of(*dec),
            "residual_likelihood_effective": res[0],
            "residual_impact_effective": res[1],
            "residual_score": score_of(*res),
            "residual_band": th.band(score_of(*res)),
            "evidence_state": state,
            "evidence_reason": reason,
            "evidence_ts": evid_ts,
            "review_overdue": overdue,
        }

    def _point(self, row: Mapping[str, Any], eff: Mapping[str, Any]) -> inherit.RiskPoint:
        explicit = bool(row.get("node_id"))
        return inherit.RiskPoint(
            risk_id=row["risk_id"],
            anchor=inherit.anchor_for(row.get("agent_id"), row.get("node_id")),
            agent_id=None if explicit else row.get("agent_id"),
            status=row["status"],
            inherent_score=eff["inherent_score"],
            residual_score=eff["residual_score"],
        )

    def _all(self) -> tuple[list[dict[str, Any]], Graph]:
        rows = [dict(r) for r in self.state.query("risk", order_by=("risk_id",))]
        return rows, self.graph()

    def list_risks(self, filters: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """Every risk with scores, bands, evidence state and the agents it applies to."""
        f = {k: v for k, v in (filters or {}).items() if v}
        for k in f:
            if k not in FILTERS:
                raise RiskError(f"unknown filter {k!r}")
        if f.get("category") and f["category"] not in CATEGORIES:
            raise RiskError("unknown category filter")
        if f.get("band") and f["band"] not in BANDS:
            raise RiskError("unknown band filter")
        rows, g = self._all()
        latest = self._latest_evidence()
        now = self.clock.now()
        out = []
        for row in rows:
            eff = self.effective(row, latest.get(row["risk_id"]), now)
            agents = (
                inherit.agents_reached_by(
                    g,
                    inherit.anchor_for(row.get("agent_id"), row.get("node_id")),
                    None if row.get("node_id") else row.get("agent_id"),
                )
                if row["status"] != "retired"
                else []
            )
            item = {**_plain(row), **_plain(eff), "agents": agents}
            if _matches(item, f):
                out.append(item)
        out.sort(key=lambda r: (-r["residual_score"], -r["inherent_score"], r["risk_id"]))
        return out

    def get(self, risk_id: str) -> dict[str, Any]:
        row = self._need(risk_id)
        g = self.graph()
        latest = self._latest_evidence(risk_id).get(risk_id)
        eff = self.effective(row, latest, self.clock.now())
        agents = inherit.agents_reached_by(
            g,
            inherit.anchor_for(row.get("agent_id"), row.get("node_id")),
            None if row.get("node_id") else row.get("agent_id"),
        )
        trend = self.tables.query(
            "risk_evidence", {"risk_id": risk_id}, order_by=("-ts",), limit=TREND_ROWS
        )
        return {
            **_plain(row),
            **_plain(eff),
            "agents": agents if row["status"] != "retired" else [],
            "links": self.links(risk_id),
            "evidence": [_evidence_view(t) for t in trend],
        }

    def agent_levels(self) -> dict[str, inherit.AgentRisk]:
        """Register level of every agent: the maximum band over the risks it reaches."""
        rows, g = self._all()
        latest = self._latest_evidence()
        now = self.clock.now()
        points = [self._point(r, self.effective(r, latest.get(r["risk_id"]), now)) for r in rows]
        known = [str(a["agent_id"]) for a in self.state.query("agent")]
        return inherit.compute(g, points, self.cfg.thresholds, known_agents=known)

    def agent_summary(self, agent_id: str) -> dict[str, Any]:
        """Register view of one agent as plain data (the Risks tab, the WP31 report)."""
        check_id(agent_id, "agent id")
        levels = self.agent_levels()
        lv = levels.get(agent_id.lower())
        risks = {r["risk_id"]: r for r in self.list_risks({"agent": agent_id.lower()})}
        reached = lv.reached if lv else []
        return {
            "agent_id": agent_id,
            "inherent_level": lv.inherent_level if lv else None,
            "residual_level": lv.residual_level if lv else None,
            "inherent_score": lv.inherent_score if lv else 0,
            "residual_score": lv.residual_score if lv else 0,
            "risks": [
                {**risks[x["risk_id"]], "via": x["via"], "own": x["own"]}
                for x in reached
                if x["risk_id"] in risks
            ],
            "thresholds_illustrative": self.cfg.thresholds.illustrative,
        }

    def counts(self) -> dict[str, int]:
        rows = self.list_risks()
        active = [r for r in rows if r["status"] == "active"]
        return {
            "risks": len(rows),
            "active": len(active),
            "high_or_critical": sum(1 for r in active if BAND_RANK[r["residual_band"]] >= 3),
            "review_overdue": sum(1 for r in active if r["review_overdue"]),
        }

    # ------------------------------------------------------------------ writes
    def create(
        self,
        data: Mapping[str, Any],
        actor: str,
        *,
        risk_id: str | None = None,
        source: str = "manual",
        links: Iterable[tuple[str, str]] = (),
    ) -> dict[str, Any]:
        fields = normalise(data, source=source)
        rid = check_id(risk_id) if risk_id else new_risk_id()
        pairs = sorted(set(links))
        cat = self._fresh()
        for kind, target in pairs:
            check_target(kind, target)
            cat.check(kind, target)
        if len(pairs) > MAX_LINKS_PER_RISK:
            raise RiskError(f"a risk can have at most {MAX_LINKS_PER_RISK} links")
        row = {**fields, "risk_id": rid, "created_at": self.clock.now(), "created_by": actor}
        try:
            stored = self.state.insert("risk", row)
        except DuplicateKeyError:
            raise RiskError(f"risk {rid} already exists") from None
        for kind, target in pairs:
            self.state.insert("risk_link", self._link_row(rid, kind, target, actor))
        self._changed("create", dict(stored), actor)
        return self.get(rid)

    def update(
        self,
        risk_id: str,
        changes: Mapping[str, Any],
        actor: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        cur = self._need(risk_id)
        unknown = sorted(set(changes) - set(EDITABLE) - {"row_version"})
        if unknown:
            raise RiskError(f"cannot change: {', '.join(unknown)}")
        merged = {k: cur[k] for k in EDITABLE} | {k: v for k, v in changes.items() if k in EDITABLE}
        fields = normalise(merged, source=cur["source"] if cur["source"] else "manual")
        fields.pop("source", None)
        # The person edited it: a starter or imported risk is now a hand-kept one.
        fields["source"] = "manual"
        version = expected_version if expected_version is not None else cur["row_version"]
        try:
            stored = self.state.update("risk", {"risk_id": risk_id}, fields, int(version))
        except ConcurrencyError:
            raise RiskError("the risk was changed by someone else; reload and try again") from None
        action = (
            "retire" if fields["status"] == "retired" and cur["status"] != "retired" else "update"
        )
        self._changed(action, dict(stored), actor)
        return self.get(risk_id)

    # ------------------------------------------------------------------ evidence
    def collector(self) -> ev.Collector:
        from supervisor.controls.refs import runtime_sources  # WP30; lazy: no import cycle

        return ev.Collector(
            self.tables,
            self.state,
            self._fresh().rule_ids(),
            control_sources=lambda cid: runtime_sources(self.state, cid),
        )

    def run_evidence(self, now: dt.datetime | None = None) -> dict[str, Any]:
        """One evidence pass: a ``risk_evidence`` row and a chain record for every active risk
        that has an agent to look at, for the window that ends at the last full hour."""
        now = now or self.clock.now()
        w = ev.window_for(now, int(self.settings.risk_evidence_window_days))
        rows, g = self._all()
        col = self.collector()
        out = {"risks": 0, "written": 0, "repeat": 0, "working": 0, "failing": 0, "no_evidence": 0}
        for row in rows:
            if row["status"] != "active":
                continue
            out["risks"] += 1
            eid = ev.evidence_id(row["risk_id"], w)
            if self.tables.query("risk_evidence", {"evidence_id": eid}, limit=1):
                out["repeat"] += 1
                continue
            agents = inherit.agents_reached_by(
                g,
                inherit.anchor_for(row.get("agent_id"), row.get("node_id")),
                None if row.get("node_id") else row.get("agent_id"),
            )
            counts = col.count(agents, self.control_links(row["risk_id"]), w)
            inh = (int(row["inherent_likelihood"]), int(row["inherent_impact"]))
            dec = (int(row["residual_likelihood"]), int(row["residual_impact"]))
            d = ev.assess(row["treatment"], inh, dec, counts, self.cfg)
            digest = ev.evidence_digest(row["risk_id"], w, counts, d)
            record = {
                "evidence_id": eid,
                "risk_id": row["risk_id"],
                "ts": now,
                "window_start": w.start,
                "window_end": w.end,
                "state": d.state,
                "reason": d.reason,
                **counts.as_dict(),
                "declared_residual_likelihood": dec[0],
                "declared_residual_impact": dec[1],
                "residual_likelihood": d.residual[0],
                "residual_impact": d.residual[1],
            }
            chain_payload = {
                "risk_id": row["risk_id"],
                **(
                    {"agent_id": row["agent_id"]}
                    if row.get("agent_id") and not row.get("node_id")
                    else {}
                ),
                "window_start": format_ts(w.start),
                "window_end": format_ts(w.end),
                "state": d.state,
                "reason": d.reason,
                **counts.as_dict(),
                "inherent_likelihood": inh[0],
                "inherent_impact": inh[1],
                "declared_residual_likelihood": dec[0],
                "declared_residual_impact": dec[1],
                "residual_likelihood": d.residual[0],
                "residual_impact": d.residual[1],
                "digest": digest,
            }
            chain_hash = self._chain("risk_evidence", f"risk:{row['risk_id']}", chain_payload)
            self.tables.append(
                "risk_evidence", [{**record, "digest": digest, "chain_hash": chain_hash}]
            )
            out["written"] += 1
            out[d.state] += 1
        return out

    # ------------------------------------------------------------------ import
    @staticmethod
    def parse_import(text: str, name: str = "risks") -> list[dict[str, Any]]:
        """Risk documents (flat dicts with ``id`` and ``links``) from one YAML text."""
        if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise RiskError(f"{name}: file is too large")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            raise RiskError(f"{name}: not valid YAML") from None
        if not isinstance(doc, Mapping) or not isinstance(doc.get("risks"), list):
            raise RiskError(f"{name}: expected a mapping with a 'risks' list")
        if len(doc["risks"]) > MAX_RISKS:
            raise RiskError(f"{name}: more than {MAX_RISKS} risks")
        return [RiskService._flat(item, f"{name}[{i}]") for i, item in enumerate(doc["risks"], 1)]

    @staticmethod
    def _flat(item: Any, where: str) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            raise RiskError(f"{where}: a risk must be a mapping")
        out: dict[str, Any] = {"id": item.get("id")}
        for key in ("title", "description", "category", "treatment", "owner", "status"):
            out[key] = item.get(key)
        out["treatment_note"] = item.get("treatment_note")
        out["review_date"] = item.get("review_date")
        if item.get("agent") is not None:
            out["agent_id"] = item["agent"]
        node = item.get("node")
        if node is not None:
            if not isinstance(node, Mapping) or not node.get("kind") or not node.get("name"):
                raise RiskError(f"{where}: node needs kind and name")
            try:
                out["node_id"] = node_id_for(str(node["kind"]), str(node["name"]))
            except ValueError as exc:
                raise RiskError(f"{where}: {exc}") from None
        inh = item.get("inherent") or {}
        res = item.get("residual") or {}
        mar = item.get("marginal") or {}
        if not all(isinstance(x, Mapping) for x in (inh, res, mar)):
            raise RiskError(f"{where}: inherent, residual and marginal are mappings")
        out["inherent_likelihood"] = inh.get("likelihood")
        out["inherent_impact"] = inh.get("impact")
        out["residual_likelihood"] = res.get("likelihood")
        out["residual_impact"] = res.get("impact")
        out["marginal_risk"] = mar.get("score")
        out["marginal_note"] = mar.get("note")
        links = item.get("links") or {}
        if not isinstance(links, Mapping):
            raise RiskError(f"{where}: links is a mapping of kind to a list of targets")
        pairs: list[tuple[str, str]] = []
        for kind, targets in links.items():
            if kind not in LINK_KINDS or not isinstance(targets, list):
                raise RiskError(f"{where}: links.{kind} must be a list ({', '.join(LINK_KINDS)})")
            pairs.extend((str(kind), str(t)) for t in targets)
        out["links"] = sorted(set(pairs))
        return out

    def import_docs(
        self,
        docs: Sequence[Mapping[str, Any]],
        actor: str,
        *,
        source: str = "import",
        dry_run: bool = False,
        overwrite_manual: bool = False,
    ) -> ImportResult:
        """Validate every document, then write all or nothing. A re-import updates risks whose
        source is ``starter`` or ``import``; a risk a person edited (source ``manual``) is left
        alone unless ``overwrite_manual``. Links of a document replace the stored links."""
        res = ImportResult()
        cat = self._fresh()
        plan: list[tuple[str, dict[str, Any], list[tuple[str, str]]]] = []
        seen: dict[str, int] = {}
        keyed: dict[tuple[str, str, str], tuple[str, str]] = {}
        for i, d in enumerate(docs, 1):
            where = f"risk {i}"
            try:
                rid = check_id(d.get("id"), f"{where}: id")
                if rid in seen:
                    raise RiskError(f"{where}: id {rid} is used twice (also in risk {seen[rid]})")
                seen[rid] = i
                fields = normalise(d, source=source)
                links = list(d.get("links") or [])
                for kind, target in links:
                    check_target(kind, target)
                    cat.check(kind, target)
                anchor = (
                    fields["agent_id"] or "",
                    fields["node_id"] or "",
                    fields["title"].lower(),
                )
                prev = keyed.get(anchor)
                if prev and prev[1] != fields["treatment"]:
                    raise RiskError(
                        f"{where}: conflicting treatments for '{fields['title']}' "
                        f"({prev[0]} says {prev[1]}, {rid} says {fields['treatment']})"
                    )
                keyed[anchor] = (rid, fields["treatment"])
                plan.append((rid, fields, links))
            except RiskError as exc:
                res.errors.append(str(exc))
        if res.errors or dry_run:
            return res
        for rid, fields, links in plan:
            cur = self.state.get("risk", {"risk_id": rid})
            if cur is None:
                self.create(_back(fields), actor, risk_id=rid, source=source, links=links)
                res.created += 1
                res.links_added += len(links)
                continue
            if cur["source"] == "manual" and not overwrite_manual:
                res.skipped_manual += 1
                res.notes.append(f"{rid}: edited by hand, left alone")
                continue
            same = all(_plain(cur.get(k)) == _plain(v) for k, v in fields.items() if k != "source")
            if not same:
                self._rewrite(rid, fields, actor)
                res.updated += 1
            else:
                res.unchanged += 1
            added, removed = self._sync_links(rid, links, actor)
            res.links_added += added
            res.links_removed += removed
        return res

    def _rewrite(self, rid: str, fields: Mapping[str, Any], actor: str) -> None:
        cur = self._need(rid)
        stored = self.state.update("risk", {"risk_id": rid}, dict(fields), cur["row_version"])
        self._changed("import", dict(stored), actor)

    def _sync_links(
        self, rid: str, links: Sequence[tuple[str, str]], actor: str
    ) -> tuple[int, int]:
        have = {(r["kind"], r["target"]) for r in self._link_rows(rid)}
        want = set(links)
        for kind, target in sorted(want - have):
            self.add_link(rid, kind, target, actor)
        for kind, target in sorted(have - want):
            self.remove_link(rid, kind, target, actor)
        return len(want - have), len(have - want)

    def import_path(self, path: Path, actor: str, **kw: Any) -> ImportResult:
        """Import one YAML file or every ``*.yaml`` in a folder."""
        p = Path(path)
        files = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
        if not files:
            raise RiskError(f"{p.name}: no .yaml file to import")
        docs: list[dict[str, Any]] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                raise RiskError(f"{f.name}: cannot read the file") from None
            docs.extend(self.parse_import(text, f.name))
        return self.import_docs(docs, actor, **kw)

    # ------------------------------------------------------------------ exports
    def export_json(self) -> dict[str, Any]:
        risks = self.list_risks()
        links = {r["risk_id"]: self.links(r["risk_id"]) for r in risks}
        return {
            "version": 1,
            "thresholds": {
                "low_max": self.cfg.thresholds.low_max,
                "medium_max": self.cfg.thresholds.medium_max,
                "high_max": self.cfg.thresholds.high_max,
                "illustrative": self.cfg.thresholds.illustrative,
            },
            "risks": [{**r, "links": links[r["risk_id"]]} for r in risks],
        }

    def export_csv(self) -> tuple[str, str]:
        """(risks.csv, risk_links.csv)."""
        risks = self.list_risks()
        rb = io.StringIO()
        w = csv.writer(rb, lineterminator="\n")
        w.writerow(RISK_CSV)
        for r in risks:
            w.writerow(
                [csv_cell("|".join(r["agents"]) if k == "agents" else r.get(k)) for k in RISK_CSV]
            )
        lb = io.StringIO()
        w = csv.writer(lb, lineterminator="\n")
        w.writerow(LINK_CSV)
        for r in risks:
            for lk in self.links(r["risk_id"]):
                w.writerow([csv_cell(r["risk_id"]), csv_cell(lk["kind"]), csv_cell(lk["target"])])
        return rb.getvalue(), lb.getvalue()

    def write_exports(self, out_dir: Path, fmt: str = "both") -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        if fmt in ("json", "both"):
            files["risks.json"] = json.dumps(self.export_json(), indent=2, sort_keys=True) + "\n"
        if fmt in ("csv", "both"):
            risks_csv, links_csv = self.export_csv()
            files["risks.csv"] = risks_csv
            files["risk_links.csv"] = links_csv
        paths = []
        for name, text in files.items():
            p = out_dir / name
            p.write_text(text, encoding="utf-8", newline="\n")
            paths.append(p)
        return paths


# ---------------------------------------------------------------------- helpers


def ev_ts(value: Any) -> dt.datetime | None:
    return ev._ts(value)  # noqa: SLF001 - one parser for stored timestamps


def _plain(value: Any) -> Any:
    """JSON-friendly copy: dates and datetimes as text, containers walked."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dt.datetime):
        return format_ts(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _back(fields: Mapping[str, Any]) -> dict[str, Any]:
    """``normalise`` output as input for ``create`` (dates stay dates; create validates again)."""
    return dict(fields)


def _evidence_view(r: Mapping[str, Any]) -> dict[str, Any]:
    keep = (
        "evidence_id",
        "ts",
        "window_start",
        "window_end",
        "state",
        "reason",
        "agents_n",
        "agents_excluded",
        "rule_links",
        "rule_hits",
        "rule_stops",
        "rules_missing",
        "pack_links",
        "pack_ok",
        "pack_warn",
        "pack_fail",
        "pack_nodata",
        "monitor_links",
        "monitor_ok",
        "monitor_other",
        "controls_working",
        "controls_failing",
        "controls_idle",
        "declared_residual_likelihood",
        "declared_residual_impact",
        "residual_likelihood",
        "residual_impact",
        "digest",
        "chain_hash",
    )
    out = {k: _plain(r.get(k)) for k in keep}
    out["residual_score"] = score_of(int(r["residual_likelihood"]), int(r["residual_impact"]))
    return out


def _matches(item: Mapping[str, Any], f: Mapping[str, str]) -> bool:
    if f.get("agent") and f["agent"].lower() not in {a.lower() for a in item["agents"]}:
        return False
    if f.get("category") and item["category"] != f["category"]:
        return False
    if f.get("band") and item["residual_band"] != f["band"]:
        return False
    if f.get("owner") and item["owner"] != f["owner"]:
        return False
    if f.get("status") and item["status"] != f["status"]:
        return False
    if f.get("treatment") and item["treatment"] != f["treatment"]:
        return False
    if f.get("q"):
        hay = f"{item['risk_id']} {item['title']} {item.get('description') or ''}".lower()
        if f["q"].lower() not in hay:
            return False
    return True
