"""Control catalogue service (WP30, ADR D30): store, map, evidence status, compliance, import.

The one object the routes, the console, the CLI and the job use. It reads and writes the
``control``, ``control_map`` and ``control_status`` tables through the state and table ports
(SQLite and Delta alike). Status is computed from runtime facts by ``controls.evidence`` and the
WP29 collector; it is never typed in.

Extension points for later work packages (see docs/controls.md, "For other modules"):

* WP31 transparency report: ``ControlService.agent_compliance(agent_id)`` returns the controls in
  scope of one agent with their evidence status, the integer compliance bp and the obligations
  they cover, as plain data. ``export_json()`` returns the whole catalogue.
* ``ControlService.obligation_coverage(agent_id)`` answers "which controls hold this obligation,
  and do they work for this agent" for the compliance matrix pages.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.controls import evidence as cev
from supervisor.controls.model import (
    ANY_AGENT,
    CONTROL_TYPES,
    COVER_KINDS,
    EDITABLE,
    EVIDENCE_KINDS,
    EVIDENCE_STATUSES,
    IMPLEMENTERS,
    MAP_KINDS,
    MAX_MAPS,
    RUNTIME_KINDS,
    STATUS_NO_DATA,
    STATUSES,
    ControlError,
    actor_ref,
    check_id,
    check_target,
    normalise,
)
from supervisor.controls.refs import ControlRefs, build_refs
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, NotFoundError
from supervisor.risk import evidence as ev

log = logging.getLogger("supervisor.controls")

MAX_IMPORT_BYTES = 2_000_000
MAX_CONTROLS = 2000
FILTERS = ("type", "implemented_by", "status", "owner", "agent", "q")
CONTROL_CSV = (
    "control_id",
    "title",
    "control_type",
    "implemented_by",
    "owner",
    "status",
    "review_date",
    "agents",
    "matrix_n",
    "risk_n",
    "sources_n",
)
MAP_CSV = ("control_id", "kind", "target")


def csv_cell(value: Any) -> str:
    """A CSV cell safe to open in a spreadsheet (no formula injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def map_id(control_id: str, kind: str, target: str) -> str:
    return "cm_" + sha256_hex({"control": control_id, "kind": kind, "target": target})[:24]


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


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_manual: int = 0
    maps_added: int = 0
    maps_removed: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class ControlService:
    def __init__(
        self,
        state: Any,
        tables: Any,
        clock: Any,
        settings: Any,
        *,
        evidence: Any = None,
        refs: ControlRefs | None = None,
        risks: Any = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self.refs = refs or build_refs(state, settings)
        self._risks = risks

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> ControlService:
        return cls(
            adapters.state, adapters.tables, adapters.clock, adapters.settings, evidence=evidence
        )

    # ------------------------------------------------------------------ plumbing
    def risk_service(self) -> Any:
        """The WP29 service, or None while the risk register is off (no link is written)."""
        if self._risks is None and getattr(self.settings, "risk_register_enabled", False):
            from supervisor.risk.service import RiskService

            self._risks = RiskService(
                self.state,
                self.tables,
                self.clock,
                self.settings,
                evidence=self.evidence_sink,
                catalogue=self.refs.catalogue,
            )
        return self._risks

    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(self.evidence_sink.record(record_type, ref, payload))
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("control chain record failed")
            return None

    def _changed(self, action: str, row: Mapping[str, Any], actor: str) -> None:
        maps = self._map_rows(row["control_id"])
        self._chain(
            "control_change",
            f"control:{row['control_id']}",
            {
                "control_id": row["control_id"],
                "action": action,
                "actor_ref": actor_ref(self.settings, actor),
                "status": row["status"],
                "control_type": row["control_type"],
                "implemented_by": row["implemented_by"],
                "cover_n": sum(1 for m in maps if m["kind"] in COVER_KINDS),
                "evidence_n": sum(1 for m in maps if m["kind"] in EVIDENCE_KINDS),
                "row_hash": sha256_hex(_plain(row)),
                "map_hash": sha256_hex(sorted(f"{m['kind']}:{m['target']}" for m in maps)),
                "ts": format_ts(self.clock.now()),
            },
        )

    def _fresh(self) -> ControlRefs:
        self.refs.clear()
        return self.refs

    # ------------------------------------------------------------------ maps
    def _map_rows(self, control_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.state.query("control_map", {"control_id": control_id})
            if _on(r["active"])
        ]

    def maps(self, control_id: str) -> dict[str, list[str]]:
        """kind -> sorted targets, only the kinds that have a target."""
        out: dict[str, list[str]] = {}
        for r in self._map_rows(control_id):
            out.setdefault(r["kind"], []).append(r["target"])
        return {k: sorted(out[k]) for k in MAP_KINDS if k in out}

    def pairs(self, control_id: str) -> list[tuple[str, str]]:
        return sorted((r["kind"], r["target"]) for r in self._map_rows(control_id))

    def _map_row(self, control_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        return {
            "map_id": map_id(control_id, kind, target),
            "control_id": control_id,
            "kind": kind,
            "target": target,
            "active": True,
            "created_at": self.clock.now(),
            "created_by": actor,
        }

    def add_map(self, control_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        check_target(kind, target)
        row = self._need(control_id)
        if row["status"] == "retired":
            raise ControlError(f"control {control_id} is retired; it cannot be changed")
        self._fresh().check(kind, target)
        self._check_scope_for(row, [(kind, target)])
        out = {"control_id": control_id, "kind": kind, "target": target, "added": True}
        mid = map_id(control_id, kind, target)
        cur = self.state.get("control_map", {"map_id": mid})
        if cur is not None and _on(cur["active"]):
            return out | {"added": False}
        if cur is None and len(self._map_rows(control_id)) >= MAX_MAPS:
            raise ControlError(f"a control can have at most {MAX_MAPS} map entries")
        if cur is None:
            self.state.insert("control_map", self._map_row(control_id, kind, target, actor))
        else:
            self.state.update("control_map", {"map_id": mid}, {"active": True}, cur["row_version"])
        self._after_map(row, kind, target, actor, add=True)
        self._changed("map", row, actor)
        return out

    def remove_map(self, control_id: str, kind: str, target: str, actor: str) -> dict[str, Any]:
        check_target(kind, target)
        row = self._need(control_id)
        mid = map_id(control_id, kind, target)
        cur = self.state.get("control_map", {"map_id": mid})
        out = {"control_id": control_id, "kind": kind, "target": target, "removed": True}
        if cur is None or not _on(cur["active"]):
            return out | {"removed": False}
        if row["status"] == "active":  # an active control keeps what it covers and its proof
            rest = [m for m in self._map_rows(control_id) if m["map_id"] != mid]
            self._check_active_shape(rest)
        self.state.update("control_map", {"map_id": mid}, {"active": False}, cur["row_version"])
        self._after_map(row, kind, target, actor, add=False)
        self._changed("unmap", row, actor)
        return out

    def _after_map(self, row: Mapping[str, Any], kind: str, target: str, actor: str, *, add: bool):
        """A risk map is also a WP29 link (kind control), so the risk sees this control."""
        if kind != "risk":
            return
        svc = self.risk_service()
        if svc is None:
            return
        try:
            if add:
                svc.add_link(target, "control", row["control_id"], actor)
            else:
                svc.remove_link(target, "control", row["control_id"], actor)
        except Exception as exc:  # noqa: BLE001 - the map is stored; the link is repaired by sync
            log.warning("risk link not written for %s: %s", target, type(exc).__name__)

    # ------------------------------------------------------------------ rules of shape
    @staticmethod
    def _check_active_shape(rows: Iterable[Mapping[str, Any]]) -> None:
        kinds = {m["kind"] for m in rows}
        if not kinds & set(COVER_KINDS):
            raise ControlError("an active control must cover at least one obligation or risk")
        if not kinds & set(EVIDENCE_KINDS):
            raise ControlError(
                "an active control needs at least one evidence source "
                "(rule, pack, monitor, detector or document)"
            )

    def _check_scope_for(self, row: Mapping[str, Any], pairs: Iterable[tuple[str, str]]) -> None:
        """A rule that is limited to some agents cannot be the proof for another agent."""
        scope = _scope_list(row)
        for kind, target in pairs:
            if kind != "rule":
                continue
            rule_scope = self.refs.scopes().get(target)
            if rule_scope in (None, "*"):
                continue
            allowed = {str(a).lower() for a in rule_scope}
            if scope == [ANY_AGENT]:
                raise ControlError(
                    f"rule {target} is limited to {', '.join(sorted(allowed))}; "
                    "set agents on the control to those agents"
                )
            outside = [a for a in scope if a not in allowed]
            if outside:
                raise ControlError(f"rule {target} is not in scope for {', '.join(outside)}")

    # ------------------------------------------------------------------ reads
    def _need(self, control_id: str) -> dict[str, Any]:
        check_id(control_id)
        row = self.state.get("control", {"control_id": control_id})
        if row is None:
            raise NotFoundError(f"control {control_id} does not exist")
        return dict(row)

    def _view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        out = _plain(dict(row))
        out["agents"] = _scope_list(row)
        out.pop("scope_agents", None)
        return out

    def list_controls(self, filters: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """Every control with its map counts, sorted by id."""
        f = {k: v for k, v in (filters or {}).items() if v}
        for k in f:
            if k not in FILTERS:
                raise ControlError(f"unknown filter {k!r}")
        if f.get("status") and f["status"] not in STATUSES:
            raise ControlError("unknown status filter")
        if f.get("type") and f["type"] not in CONTROL_TYPES:
            raise ControlError("unknown type filter")
        if f.get("implemented_by") and f["implemented_by"] not in IMPLEMENTERS:
            raise ControlError("unknown implemented_by filter")
        if f.get("agent"):
            check_id(f["agent"], "agent")
        by_control: dict[str, list[dict[str, Any]]] = {}
        for m in self.state.query("control_map"):
            if _on(m["active"]):
                by_control.setdefault(m["control_id"], []).append(m)
        out = []
        for row in self.state.query("control", order_by=("control_id",)):
            mp = by_control.get(row["control_id"], [])
            item = self._view(row)
            item["matrix_n"] = sum(1 for m in mp if m["kind"] == "matrix")
            item["risk_n"] = sum(1 for m in mp if m["kind"] == "risk")
            item["sources_n"] = sum(1 for m in mp if m["kind"] in EVIDENCE_KINDS)
            if _matches(item, f):
                out.append(item)
        return out

    def get(self, control_id: str) -> dict[str, Any]:
        row = self._need(control_id)
        rows = self.tables.query(
            "control_status", {"control_id": control_id}, order_by=("-ts",), limit=2000
        )
        latest: dict[str, dict[str, Any]] = {}
        for r in rows:
            latest.setdefault(str(r["agent_id"]), dict(r))
        item = self._view(row)
        item["maps"] = self.maps(control_id)
        item["status_by_agent"] = [
            _status_view(latest[a], self._stale(latest[a])) for a in sorted(latest)
        ]
        return item

    def counts(self) -> dict[str, int]:
        rows = self.list_controls()
        active = [r for r in rows if r["status"] == "active"]
        today = self.clock.now().date()
        return {
            "controls": len(rows),
            "active": len(active),
            "review_overdue": sum(
                1 for r in active if r.get("review_date") and r["review_date"] < today.isoformat()
            ),
        }

    # ------------------------------------------------------------------ writes
    def create(
        self,
        data: Mapping[str, Any],
        actor: str,
        *,
        control_id: str | None = None,
        source: str = "manual",
        maps: Iterable[tuple[str, str]] = (),
    ) -> dict[str, Any]:
        fields = normalise(data, source=source)
        cid = check_id(control_id if control_id else data.get("control_id"))
        pairs = sorted(set(maps))
        refs = self._fresh()
        for kind, target in pairs:
            check_target(kind, target)
            refs.check(kind, target)
        if len(pairs) > MAX_MAPS:
            raise ControlError(f"a control can have at most {MAX_MAPS} map entries")
        row_in = {**fields, "scope_agents": json.dumps(fields["scope_agents"])}
        self._check_scope_for(row_in, pairs)
        if fields["status"] == "active":
            self._check_active_shape([{"kind": k} for k, _ in pairs])
        row = {**row_in, "control_id": cid, "created_at": self.clock.now(), "created_by": actor}
        try:
            stored = self.state.insert("control", row)
        except DuplicateKeyError:
            raise ControlError(f"control {cid} already exists") from None
        for kind, target in pairs:
            self.state.insert("control_map", self._map_row(cid, kind, target, actor))
        for kind, target in pairs:
            self._after_map(stored, kind, target, actor, add=True)
        self._changed("create", dict(stored), actor)
        return self.get(cid)

    def update(
        self,
        control_id: str,
        changes: Mapping[str, Any],
        actor: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        cur = self._need(control_id)
        unknown = sorted(set(changes) - set(EDITABLE) - {"row_version"})
        if unknown:
            raise ControlError(f"cannot change: {', '.join(unknown)}")
        if cur["status"] == "retired":
            raise ControlError(f"control {control_id} is retired; it cannot be changed")
        base = {k: cur[k] for k in EDITABLE if k != "agents"} | {"agents": _scope_list(cur)}
        merged = base | {k: v for k, v in changes.items() if k in EDITABLE}
        fields = normalise(merged, source="manual")
        fields["scope_agents"] = json.dumps(fields["scope_agents"])
        self._fresh()
        pairs = self.pairs(control_id)
        self._check_scope_for(fields | {"scope_agents": fields["scope_agents"]}, pairs)
        if fields["status"] == "active":
            self._check_active_shape([{"kind": k} for k, _ in pairs])
        version = expected_version if expected_version is not None else cur["row_version"]
        try:
            stored = self.state.update("control", {"control_id": control_id}, fields, int(version))
        except ConcurrencyError:
            raise ControlError(
                "the control was changed by someone else; reload and retry"
            ) from None
        retire = fields["status"] == "retired" and cur["status"] != "retired"
        if retire:
            for kind, target in pairs:
                if kind == "risk":
                    self._after_map(stored, kind, target, actor, add=False)
        self._changed("retire" if retire else "update", dict(stored), actor)
        return self.get(control_id)

    # ------------------------------------------------------------------ scope
    def agent_rows(self) -> dict[str, dict[str, Any]]:
        """lower-case agent id -> agent row, for agents that are not RETIRED."""
        return {
            str(a["agent_id"]).lower(): dict(a)
            for a in self.state.query("agent")
            if a.get("gate_state") != "RETIRED"
        }

    def controls_for(self, agent_id: str, rows: Sequence[Mapping[str, Any]] | None = None):
        """Active controls in scope of the agent, by id."""
        a = agent_id.lower()
        rows = rows if rows is not None else self.state.query("control", order_by=("control_id",))
        out = []
        for r in rows:
            if r["status"] != "active":
                continue
            scope = _scope_list(r)
            if scope == [ANY_AGENT] or a in scope:
                out.append(dict(r))
        return out

    # ------------------------------------------------------------------ status pass
    def window(self, now: dt.datetime | None = None) -> ev.Window:
        return ev.window_for(now or self.clock.now(), int(self.settings.risk_evidence_window_days))

    def collector(self) -> ev.Collector:
        from supervisor.controls.refs import runtime_sources

        return ev.Collector(
            self.tables,
            self.state,
            self._fresh().rule_ids(),
            control_sources=lambda cid: runtime_sources(self.state, cid),
        )

    def run_status(self, now: dt.datetime | None = None) -> dict[str, Any]:
        """One status pass: a ``control_status`` row for every active control in scope of every
        agent that is not RETIRED, for the window that ends at the last full hour, and one chain
        record per agent with the compliance bp. A second run in the same window writes nothing."""
        now = now or self.clock.now()
        w = self.window(now)
        col = self.collector()
        controls = [dict(r) for r in self.state.query("control", order_by=("control_id",))]
        pairs = {r["control_id"]: self.pairs(r["control_id"]) for r in controls}
        bases = self.bases()
        w_pack = ev.window_for(now, int(self.settings.controls_pack_window_days))
        out = {"agents": 0, "controls": 0, "written": 0, "repeat": 0}
        out.update({s: 0 for s in EVIDENCE_STATUSES})
        for agent in sorted(self.agent_rows().values(), key=lambda r: str(r["agent_id"])):
            aid = str(agent["agent_id"])
            scope = self.controls_for(aid, controls)
            if not scope:
                continue
            out["agents"] += 1
            new_rows: list[dict[str, Any]] = []
            tally = dict.fromkeys(EVIDENCE_STATUSES, 0)
            digests: list[str] = []
            for c in scope:
                out["controls"] += 1
                sid = cev.status_id(c["control_id"], aid, w, bases[c["control_id"]])
                done = self.tables.query("control_status", {"status_id": sid}, limit=1)
                if done:
                    out["repeat"] += 1
                    tally[done[0]["status"]] += 1
                    digests.append(str(done[0]["digest"]))
                    continue
                res = cev.evaluate(col, aid, pairs[c["control_id"]], w, w_pack)
                digest = cev.status_digest(c["control_id"], aid, w, res)
                tally[res.status] += 1
                digests.append(digest)
                out[res.status] += 1
                new_rows.append(
                    {
                        "status_id": sid,
                        "control_id": c["control_id"],
                        "agent_id": aid,
                        "ts": now,
                        "window_start": w.start,
                        "window_end": w.end,
                        "status": res.status,
                        "reason": res.reason,
                        **res.counts(),
                        "digest": digest,
                    }
                )
            if not new_rows:
                continue
            chain_hash = self._chain(
                "control_status",
                f"agent:{aid}",
                {
                    "agent_id": aid,
                    "window_start": format_ts(w.start),
                    "window_end": format_ts(w.end),
                    "in_scope": len(scope),
                    "working": tally["working"],
                    "failing": tally["failing"],
                    "no_data": tally[STATUS_NO_DATA],
                    "written": len(new_rows),
                    "compliance_bp": cev.compliance_bp(tally["working"], len(scope)) or 0,
                    "digest": sha256_hex(sorted(digests)),
                },
            )
            self.tables.append(
                "control_status", [{**r, "chain_hash": chain_hash} for r in new_rows]
            )
            out["written"] += len(new_rows)
        return out

    def bases(self) -> dict[str, str]:
        """control id -> map fingerprint (what the evidence of the control depends on)."""
        from supervisor.controls.refs import map_fingerprint

        return {
            str(r["control_id"]): map_fingerprint(self.state, str(r["control_id"]))
            for r in self.state.query("control")
        }

    def _verdict(self, row: Mapping[str, Any], bases: Mapping[str, str]) -> tuple[str, str]:
        """(status, reason) a stored row gives now: stale after two windows, and no longer valid
        after a change to the map, the scope or the status of the control."""
        if self._stale(row):
            return STATUS_NO_DATA, "stale"
        w = ev.Window(ev._ts(row["window_start"]), ev._ts(row["window_end"]))  # noqa: SLF001
        want = cev.status_id(
            str(row["control_id"]), str(row["agent_id"]), w, bases.get(str(row["control_id"]), "")
        )
        if want != row["status_id"]:
            return STATUS_NO_DATA, "changed_since_evidence"
        return str(row["status"]), str(row["reason"])

    def _stale(self, row: Mapping[str, Any]) -> bool:
        end = ev._ts(row["window_end"])  # noqa: SLF001 - one parser for stored timestamps
        if end is None:
            return True
        return ev.is_stale(end, self.window(self.clock.now()).seconds, self.clock.now())

    # ------------------------------------------------------------------ compliance
    def _latest_for_agent(self, agent_id: str) -> dict[str, dict[str, Any]]:
        rows = self.tables.query(
            "control_status", {"agent_id": agent_id}, order_by=("-ts",), limit=20000
        )
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            out.setdefault(str(r["control_id"]), dict(r))
        return out

    def agent_compliance(self, agent_id: str) -> dict[str, Any]:
        """Controls in scope of one agent, their status, and the compliance bp: controls with
        working evidence over controls in scope, in integer basis points (None = no control in
        scope). A status older than two windows counts as no_data. Plain data for WP31."""
        check_id(agent_id, "agent id")
        agents = self.agent_rows()
        a = agents.get(agent_id.lower())
        aid = str(a["agent_id"]) if a else agent_id
        scope = self.controls_for(aid) if a else []
        latest = self._latest_for_agent(aid)
        bases = self.bases()
        items = []
        tally = dict.fromkeys(EVIDENCE_STATUSES, 0)
        for c in scope:
            row = latest.get(c["control_id"])
            if row is None:
                status, reason, ts, stale = STATUS_NO_DATA, "not_evaluated", None, False
            else:
                status, reason = self._verdict(row, bases)
                ts, stale = row["window_end"], reason in ("stale", "changed_since_evidence")
            tally[status] += 1
            maps = self.maps(c["control_id"])
            items.append(
                {
                    "control_id": c["control_id"],
                    "title": c["title"],
                    "control_type": c["control_type"],
                    "implemented_by": c["implemented_by"],
                    "owner": c["owner"],
                    "status": status,
                    "reason": reason,
                    "window_end": _plain(ts),
                    "stale": stale,
                    "matrix": maps.get("matrix", []),
                    "risks": maps.get("risk", []),
                }
            )
        product = [i for i in items if i["implemented_by"] == "product"]
        product_working = sum(1 for i in product if i["status"] == "working")
        return {
            "agent_id": aid,
            "known_agent": a is not None,
            "in_scope": len(scope),
            "working": tally["working"],
            "failing": tally["failing"],
            "no_data": tally[STATUS_NO_DATA],
            "compliance_bp": cev.compliance_bp(tally["working"], len(scope)),
            # Controls the bank owns cannot be observed by the product: shown apart, so the
            # figure above is not read as "the bank is non-compliant".
            "product_in_scope": len(product),
            "product_working": product_working,
            "product_bp": cev.compliance_bp(product_working, len(product)),
            "bank_in_scope": len(items) - len(product),
            "controls": items,
        }

    def compliance_all(self) -> dict[str, int | None]:
        """agent id -> compliance bp for every agent that is not RETIRED."""
        return {
            str(a["agent_id"]): self.agent_compliance(str(a["agent_id"]))["compliance_bp"]
            for a in sorted(self.agent_rows().values(), key=lambda r: str(r["agent_id"]))
        }

    def obligation_coverage(self, agent_id: str) -> list[dict[str, Any]]:
        """For each obligation covered by a control in scope of the agent: the controls and the
        best status among them (working beats no_data; failing is shown when none works)."""
        comp = self.agent_compliance(agent_id)
        by_obl: dict[str, list[dict[str, Any]]] = {}
        for c in comp["controls"]:
            for o in c["matrix"]:
                by_obl.setdefault(o, []).append(c)
        out = []
        for o in sorted(by_obl):
            sts = {c["status"] for c in by_obl[o]}
            best = (
                "working" if "working" in sts else "failing" if "failing" in sts else STATUS_NO_DATA
            )
            out.append(
                {
                    "obligation": o,
                    "status": best,
                    "controls": sorted(c["control_id"] for c in by_obl[o]),
                }
            )
        return out

    def status_summary(self) -> dict[str, dict[str, int]]:
        """control id -> {working, failing, no_data}: the newest status of the control for each
        agent (a status older than two windows counts as no_data). One query; for the list page."""
        rows = self.tables.query("control_status", order_by=("-ts",), limit=20000)
        bases = self.bases()
        seen: set[tuple[str, str]] = set()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            key = (str(r["control_id"]), str(r["agent_id"]))
            if key in seen:
                continue
            seen.add(key)
            st = self._verdict(r, bases)[0]
            bucket = out.setdefault(key[0], dict.fromkeys(EVIDENCE_STATUSES, 0))
            bucket[st] += 1
        return out

    def uncovered_risks(self) -> list[str]:
        """Active risks no active control maps to (needs the risk register)."""
        try:
            risks = [r["risk_id"] for r in self.state.query("risk") if r["status"] == "active"]
        except Exception:  # noqa: BLE001
            return []
        covered = {
            m["target"]
            for m in self.state.query("control_map", {"kind": "risk"})
            if _on(m["active"])
        }
        return sorted(set(risks) - covered)

    # ------------------------------------------------------------------ import
    @staticmethod
    def parse_import(text: str, name: str = "controls") -> list[dict[str, Any]]:
        """Control documents (flat dicts with ``id`` and ``maps``) from one YAML text."""
        if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ControlError(f"{name}: file is too large")
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            raise ControlError(f"{name}: not valid YAML") from None
        if not isinstance(doc, Mapping) or not isinstance(doc.get("controls"), list):
            raise ControlError(f"{name}: expected a mapping with a 'controls' list")
        if len(doc["controls"]) > MAX_CONTROLS:
            raise ControlError(f"{name}: more than {MAX_CONTROLS} controls")
        return [
            ControlService._flat(item, f"{name}[{i}]") for i, item in enumerate(doc["controls"], 1)
        ]

    @staticmethod
    def _flat(item: Any, where: str) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            raise ControlError(f"{where}: a control must be a mapping")
        out: dict[str, Any] = {
            "id": item.get("id"),
            "title": item.get("title"),
            "objective": item.get("objective"),
            "control_type": item.get("type"),
            "implemented_by": item.get("implemented_by"),
            "owner": item.get("owner"),
            "status": item.get("status", "draft"),
            "review_date": item.get("review_date"),
            "agents": item.get("agents"),
        }
        pairs: list[tuple[str, str]] = []
        for section, kinds in (("covers", COVER_KINDS), ("evidence", EVIDENCE_KINDS)):
            block = item.get(section) or {}
            if not isinstance(block, Mapping):
                raise ControlError(f"{where}: {section} is a mapping of kind to a list of targets")
            for kind, targets in block.items():
                if kind not in kinds or not isinstance(targets, list):
                    raise ControlError(
                        f"{where}: {section}.{kind} must be a list ({', '.join(kinds)})"
                    )
                pairs.extend((str(kind), str(t)) for t in targets)
        out["maps"] = sorted(set(pairs))
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
        """Validate every document, then write all or nothing. A re-import updates controls whose
        source is ``starter`` or ``import``; a control a person edited (source ``manual``) is
        left alone unless ``overwrite_manual``. The map of a document replaces the stored map."""
        res = ImportResult()
        refs = self._fresh()
        plan: list[tuple[str, dict[str, Any], list[tuple[str, str]]]] = []
        seen: dict[str, int] = {}
        for i, d in enumerate(docs, 1):
            where = f"control {i}"
            try:
                cid = check_id(d.get("id"), f"{where}: id")
                if cid in seen:
                    raise ControlError(
                        f"{where}: id {cid} is used twice (also in control {seen[cid]})"
                    )
                seen[cid] = i
                fields = normalise(d, source=source)
                maps = list(d.get("maps") or [])
                for kind, target in maps:
                    check_target(kind, target)
                    refs.check(kind, target)
                row_in = {**fields, "scope_agents": json.dumps(fields["scope_agents"])}
                self._check_scope_for(row_in, maps)
                if fields["status"] == "active":
                    self._check_active_shape([{"kind": k} for k, _ in maps])
                plan.append((cid, fields, maps))
            except ControlError as exc:
                res.errors.append(str(exc))
        if res.errors or dry_run:
            return res
        for cid, fields, maps in plan:
            cur = self.state.get("control", {"control_id": cid})
            if cur is None:
                self.create(_data_of(fields), actor, control_id=cid, source=source, maps=maps)
                res.created += 1
                res.maps_added += len(maps)
                continue
            if cur["source"] == "manual" and not overwrite_manual:
                res.skipped_manual += 1
                res.notes.append(f"{cid}: edited by hand, left alone")
                continue
            stored = {**fields, "scope_agents": json.dumps(fields["scope_agents"])}
            same = all(_plain(cur.get(k)) == _plain(v) for k, v in stored.items() if k != "source")
            if not same:
                self._rewrite(cid, stored, actor)
                res.updated += 1
            else:
                res.unchanged += 1
            added, removed = self._sync_maps(cid, maps, actor)
            res.maps_added += added
            res.maps_removed += removed
        return res

    def _rewrite(self, cid: str, fields: Mapping[str, Any], actor: str) -> None:
        cur = self._need(cid)
        stored = self.state.update("control", {"control_id": cid}, dict(fields), cur["row_version"])
        self._changed("import", dict(stored), actor)

    def _sync_maps(self, cid: str, maps: Sequence[tuple[str, str]], actor: str) -> tuple[int, int]:
        have = {(r["kind"], r["target"]) for r in self._map_rows(cid)}
        want = set(maps)
        row = self._need(cid)
        for kind, target in sorted(want - have):
            mid = map_id(cid, kind, target)
            cur = self.state.get("control_map", {"map_id": mid})
            if cur is None:
                self.state.insert("control_map", self._map_row(cid, kind, target, actor))
            else:
                self.state.update(
                    "control_map", {"map_id": mid}, {"active": True}, cur["row_version"]
                )
            self._after_map(row, kind, target, actor, add=True)
        for kind, target in sorted(have - want):
            mid = map_id(cid, kind, target)
            cur = self.state.get("control_map", {"map_id": mid})
            if cur is not None:
                self.state.update(
                    "control_map", {"map_id": mid}, {"active": False}, cur["row_version"]
                )
            self._after_map(row, kind, target, actor, add=False)
        if want != have:
            self._changed("map", row, actor)
        return len(want - have), len(have - want)

    def import_path(self, path: Path, actor: str, **kw: Any) -> ImportResult:
        """Import one YAML file or every ``*.yaml`` in a folder."""
        p = Path(path)
        files = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
        if not files:
            raise ControlError(f"{p.name}: no .yaml file to import")
        docs: list[dict[str, Any]] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                raise ControlError(f"{f.name}: cannot read the file") from None
            docs.extend(self.parse_import(text, f.name))
        return self.import_docs(docs, actor, **kw)

    # ------------------------------------------------------------------ exports
    def export_json(self) -> dict[str, Any]:
        controls = self.list_controls()
        return {
            "version": 1,
            "controls": [{**c, "maps": self.maps(c["control_id"])} for c in controls],
        }

    def export_csv(self) -> tuple[str, str]:
        """(controls.csv, control_maps.csv)."""
        controls = self.list_controls()
        cb = io.StringIO()
        w = csv.writer(cb, lineterminator="\n")
        w.writerow(CONTROL_CSV)
        for c in controls:
            w.writerow(
                [
                    csv_cell("|".join(c["agents"]) if k == "agents" else c.get(k))
                    for k in CONTROL_CSV
                ]
            )
        mb = io.StringIO()
        w = csv.writer(mb, lineterminator="\n")
        w.writerow(MAP_CSV)
        for c in controls:
            for kind, targets in self.maps(c["control_id"]).items():
                for t in targets:
                    w.writerow([csv_cell(c["control_id"]), csv_cell(kind), csv_cell(t)])
        return cb.getvalue(), mb.getvalue()

    def write_exports(self, out_dir: Path, fmt: str = "both") -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        if fmt in ("json", "both"):
            files["controls.json"] = json.dumps(self.export_json(), indent=2, sort_keys=True) + "\n"
        if fmt in ("csv", "both"):
            controls_csv, maps_csv = self.export_csv()
            files["controls.csv"] = controls_csv
            files["control_maps.csv"] = maps_csv
        paths = []
        for name, text in files.items():
            p = out_dir / name
            p.write_text(text, encoding="utf-8", newline="\n")
            paths.append(p)
        return paths


# ---------------------------------------------------------------------- helpers


def _scope_list(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("scope_agents")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        value = json.loads(raw) if raw else [ANY_AGENT]
    except (TypeError, ValueError):
        return [ANY_AGENT]
    return [str(x) for x in value] if isinstance(value, list) and value else [ANY_AGENT]


def _data_of(fields: Mapping[str, Any]) -> dict[str, Any]:
    """``normalise`` output as input for ``create`` (which validates again)."""
    out = {k: v for k, v in fields.items() if k not in ("scope_agents", "source")}
    out["agents"] = list(fields["scope_agents"])
    return out


def _status_view(r: Mapping[str, Any], stale: bool) -> dict[str, Any]:
    keep = (
        "status_id",
        "agent_id",
        "ts",
        "window_start",
        "window_end",
        "status",
        "reason",
        "sources_n",
        "working_n",
        "failing_n",
        "idle_n",
        "refs_n",
        "digest",
        "chain_hash",
    )
    out = {k: _plain(r.get(k)) for k in keep}
    out["stale"] = stale
    return out


def _matches(item: Mapping[str, Any], f: Mapping[str, str]) -> bool:
    if f.get("type") and item["control_type"] != f["type"]:
        return False
    if f.get("implemented_by") and item["implemented_by"] != f["implemented_by"]:
        return False
    if f.get("status") and item["status"] != f["status"]:
        return False
    if f.get("owner") and item["owner"] != f["owner"]:
        return False
    if f.get("agent"):
        scope = item["agents"]
        if scope != [ANY_AGENT] and f["agent"].lower() not in scope:
            return False
    if f.get("q"):
        hay = f"{item['control_id']} {item['title']} {item.get('objective') or ''}".lower()
        if f["q"].lower() not in hay:
            return False
    return True


__all__ = [
    "ControlService",
    "ImportResult",
    "RUNTIME_KINDS",
    "csv_cell",
    "map_id",
]
