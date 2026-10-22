"""Task list service (WP30, ADR D30): generate, move through the lifecycle, close, waive.

Reads and writes ``task`` (state) and ``task_event`` (append-only) through the state and table
ports. Every change writes one ``task_event`` row and one ``task_change`` chain record that
carry hashes and integers, never the text of a reason (rule R2).

Extension point for WP31 (transparency report): ``TaskService.agent_summary(agent_id)`` returns
the stage, the sizing inputs, the counts and the tasks of one agent as plain data.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core import rbac
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, NotFoundError
from supervisor.tasks.model import (
    CLASSES,
    KINDS,
    LEVEL_RANK,
    LEVELS,
    OPEN_STATUSES,
    OWNER_ROLES,
    STAGES,
    STATUSES,
    TaskConfig,
    TaskError,
    check_id,
    check_ref,
    clean_reason,
    done_refusal,
    effective_level,
    load_config,
    move_refusal,
    move_template_id,
    needs_stage_approval,
    next_stage_at,
    plan,
    plan_at,
    same_person,
    sod_refusal,
    stages_in_use,
    waive_refusal,
)

log = logging.getLogger("supervisor.tasks")

FILTERS = ("agent", "stage", "status", "required", "overdue", "q")
MAX_CUSTOM_PER_AGENT = 200
MAX_EXPORT_ROWS = 5000
MAX_TITLE = 200
TASK_CSV = (
    "task_id",
    "agent_id",
    "template_id",
    "kind",
    "stage",
    "title",
    "owner_role",
    "required",
    "status",
    "due_at",
    "evidence_kind",
    "level",
    "d33_class",
)


def task_id_for(agent_id: str, template_id: str) -> str:
    return "tsk_" + sha256_hex({"agent": agent_id.lower(), "template": template_id})[:20]


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dt.datetime):
        return format_ts(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _ts(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def _roles(actor: Any) -> frozenset[str]:
    return frozenset(getattr(actor, "roles", ()) or ())


class TaskService:
    def __init__(
        self,
        state: Any,
        tables: Any,
        clock: Any,
        settings: Any,
        *,
        evidence: Any = None,
        cfg: TaskConfig | None = None,
        controls: Any = None,
        risks: Any = None,
    ) -> None:
        self.state = state
        self.tables = tables
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self.cfg = cfg or load_config(getattr(settings, "tasks_config", None))
        self._controls = controls
        self._risks = risks

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None, **kw: Any) -> TaskService:
        return cls(
            adapters.state,
            adapters.tables,
            adapters.clock,
            adapters.settings,
            evidence=evidence,
            **kw,
        )

    # ------------------------------------------------------------------ plumbing
    def controls(self) -> Any:
        if self._controls is None:
            from supervisor.controls.service import ControlService

            self._controls = ControlService(
                self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
            )
        return self._controls

    def risks(self) -> Any:
        if self._risks is None and getattr(self.settings, "risk_register_enabled", False):
            from supervisor.risk.service import RiskService

            self._risks = RiskService(
                self.state, self.tables, self.clock, self.settings, evidence=self.evidence_sink
            )
        return self._risks

    def _chain(self, record_type: str, ref: str, payload: Mapping[str, Any]) -> str | None:
        if self.evidence_sink is None:
            return None
        try:
            return str(self.evidence_sink.record(record_type, ref, payload))
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("task chain record failed")
            return None

    def _event(
        self,
        row: Mapping[str, Any],
        action: str,
        actor: str,
        from_status: str | None,
        reason: str | None = None,
    ) -> None:
        now = self.clock.now()
        row_hash = sha256_hex(_plain(row))
        reason_hash = sha256_hex(reason) if reason else None
        chain_hash = self._chain(
            "task_change",
            f"task:{row['task_id']}",
            {
                "task_id": row["task_id"],
                "agent_id": row["agent_id"],
                "action": action,
                "actor_ref": actor_ref(self.settings, actor, "task"),
                "template_id": row["template_id"],
                "kind": row["kind"],
                "stage": row["stage"],
                "required": 1 if _on(row["required"]) else 0,
                "from_status": from_status or "",
                "to_status": row["status"],
                "level": row["level"],
                "d33_class": row["d33_class"],
                **({"reason_sha256": reason_hash} if reason_hash else {}),
                "row_hash": row_hash,
                "ts": format_ts(now),
            },
        )
        self.tables.append(
            "task_event",
            [
                {
                    "event_id": "te_" + uuid.uuid4().hex,
                    "task_id": row["task_id"],
                    "agent_id": row["agent_id"],
                    "ts": now,
                    "action": action,
                    "actor": actor,
                    "from_status": from_status,
                    "to_status": row["status"],
                    "reason_sha256": reason_hash,
                    "row_hash": row_hash,
                    "chain_hash": chain_hash,
                }
            ],
        )

    def _update(
        self, row: Mapping[str, Any], fields: Mapping[str, Any], expected: int | None = None
    ) -> dict[str, Any]:
        version = expected if expected is not None else row["row_version"]
        try:
            return dict(
                self.state.update("task", {"task_id": row["task_id"]}, dict(fields), int(version))
            )
        except ConcurrencyError:
            raise TaskError("the task was changed by someone else; reload and try again") from None

    # ------------------------------------------------------------------ inputs
    def _agent(self, agent_id: str) -> dict[str, Any]:
        check_id(agent_id, "agent id")
        for a in self.state.query("agent"):
            if str(a["agent_id"]).lower() == agent_id.lower():
                return dict(a)
        raise NotFoundError(f"agent {agent_id} does not exist")

    def agent_inputs(self, agent_id: str) -> dict[str, str]:
        """Class, band, band source and effective level that size the task set of an agent."""
        a = self._agent(agent_id)
        cls = str(a.get("decision33_class") or "unclassified")
        if cls not in CLASSES:
            cls = "unclassified"
        band: str | None = None
        source = "default"
        linked = self._linked_sizing(str(a["agent_id"]))  # WP-G1: None unless linked to a system
        svc = self.risks()
        reg: str | None = None
        if svc is not None:
            try:
                lv = svc.agent_levels().get(str(a["agent_id"]).lower())
            except Exception:  # noqa: BLE001 - a register problem must not stop the task list
                lv = None
            if lv is not None and lv.inherent_level in LEVELS:
                reg = lv.inherent_level
        if linked is not None:
            # WP-G1: the higher of the band of the system and the register band (never lighter)
            band, source = linked.band, "system"
            if reg is not None and LEVEL_RANK[reg] > LEVEL_RANK[band]:
                band, source = reg, "risk_register"
        else:
            if reg is not None:
                band, source = reg, "risk_register"
            if band is None and a.get("risk_tier") in LEVELS:
                band, source = str(a["risk_tier"]), "risk_tier"
            if band is None:
                band = "high"  # unknown risk is sized as high: more governance, never less
        out = {
            "agent_id": str(a["agent_id"]),
            "d33_class": cls,
            "band": band,
            "band_source": source,
            "level": effective_level(self.cfg, cls, band),
            "gate_state": str(a.get("gate_state") or ""),
        }
        if linked is not None:  # WP-G1: only for a linked agent; an unlinked one is as before
            out["system_level"] = linked.system_level
            out["system_ids"] = ",".join(linked.system_ids)
            # only when the level is still low after the class floor and the register band
            if linked.initiation_only and out["level"] == "low":
                out["initiation_only"] = "1"
        return out

    def _linked_sizing(self, agent_id: str) -> Any:
        """WP-G1: the sizing of an agent that is linked to an AI system (docs/governance.md),
        or None (governance off, or no active link): then the sizing is the one before WP-G1."""
        if not getattr(self.settings, "governance_enabled", False):
            return None
        from supervisor.governance.sizing import linked_sizing

        try:
            return linked_sizing(self.state, self.tables, self.clock, self.settings, agent_id)
        except Exception:  # noqa: BLE001 - a system problem must not stop the task list
            log.exception("system sizing failed; the agent is sized as an unlinked agent")
            return None

    def _next_stage(
        self, stage: str, level: str, classes: Any, inputs: Mapping[str, str]
    ) -> str | None:
        """The stage after ``stage``. WP-G1: an agent of a system whose risk level is still
        unspecified gets the initiation set only, so it does not move on until a person sets
        the level of the system."""
        if stage == "initiation" and inputs.get("initiation_only") == "1" and level == "low":
            return None
        return next_stage_at(self.cfg, stage, level, classes)

    def sizing(self, agent_id: str, inputs: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
        """(level, classes) the task list of the agent is sized with: the highest effective
        level and every Decision 33 class the agent has had in its task list, plus today's. A
        class or band that goes down in the middle of the lifecycle therefore never removes a
        task, a stage or the stage approval; a person waives what no longer applies (two people).
        Review WP30."""
        rows = self.rows_of(agent_id)
        levels = [inputs["level"], *(str(r["level"]) for r in rows if r.get("level") in LEVELS)]
        level = max(levels, key=lambda lv: LEVEL_RANK[lv])
        classes = {inputs["d33_class"], *(str(r["d33_class"]) for r in rows)} & set(CLASSES)
        return level, tuple(sorted(classes))

    # ------------------------------------------------------------------ reads
    def _need(self, task_id: str) -> dict[str, Any]:
        check_id(task_id)
        row = self.state.get("task", {"task_id": task_id})
        if row is None:
            raise NotFoundError(f"task {task_id} does not exist")
        return dict(row)

    def rows_of(self, agent_id: str) -> list[dict[str, Any]]:
        check_id(agent_id, "agent id")
        try:
            aid = str(self._agent(agent_id)["agent_id"])
        except NotFoundError:  # an agent not registered yet has no tasks, which is not an error
            aid = agent_id
        rows = [dict(r) for r in self.state.query("task", {"agent_id": aid})]
        rows.sort(key=lambda r: (STAGES.index(r["stage"]), r["kind"] == "move", r["template_id"]))
        return rows

    def current_stage(self, agent_id: str) -> str | None:
        """The stage of the agent: the target of the newest done move; initiation when it has
        tasks but never moved; None when no task list was generated."""
        rows = self.rows_of(agent_id)
        if not rows:
            return None
        moves = [r for r in rows if r["kind"] == "move" and r["status"] == "done"]
        if not moves:
            return "initiation"
        newest = max(
            moves, key=lambda r: _ts(r["done_at"]) or dt.datetime.min.replace(tzinfo=dt.UTC)
        )
        return str(newest["target_stage"])

    def open_required(self, agent_id: str) -> list[dict[str, Any]]:
        """Required tasks of the current stage that are not done or waived (the gate reads this)."""
        stage = self.current_stage(agent_id)
        if stage is None:
            return []
        return [
            r
            for r in self.rows_of(agent_id)
            if r["stage"] == stage and _on(r["required"]) and r["status"] in OPEN_STATUSES
        ]

    def overdue(self, row: Mapping[str, Any], now: dt.datetime | None = None) -> bool:
        due = _ts(row.get("due_at"))
        return bool(
            due is not None and row["status"] in OPEN_STATUSES and (now or self.clock.now()) > due
        )

    def _view(self, row: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
        out = _plain(dict(row))
        out["required"] = _on(row["required"])
        out["overdue"] = self.overdue(row, now)
        out["waive_pending"] = (
            bool(row.get("waive_requested_by") and not row.get("waive_approved_by"))
            and row["status"] in OPEN_STATUSES
        )
        return out

    def list_tasks(self, filters: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        f = {k: v for k, v in (filters or {}).items() if v}
        for k in f:
            if k not in FILTERS:
                raise TaskError(f"unknown filter {k!r}")
        if f.get("stage") and f["stage"] not in STAGES:
            raise TaskError("unknown stage filter")
        if f.get("status") and f["status"] not in STATUSES:
            raise TaskError("unknown status filter")
        now = self.clock.now()
        out = []
        for r in self.state.query("task", order_by=("agent_id", "task_id")):
            item = self._view(r, now)
            if _matches(item, f):
                out.append(item)
        out.sort(
            key=lambda r: (
                not r["overdue"],
                r["agent_id"],
                STAGES.index(r["stage"]),
                r["kind"] == "move",
                r["template_id"],
            )
        )
        return out

    def get(self, task_id: str) -> dict[str, Any]:
        row = self._need(task_id)
        now = self.clock.now()
        events = self.tables.query("task_event", {"task_id": task_id}, order_by=("-ts",), limit=50)
        item = self._view(row, now)
        item["events"] = [
            {
                k: _plain(e.get(k))
                for k in (
                    "event_id",
                    "ts",
                    "action",
                    "actor",
                    "from_status",
                    "to_status",
                    "reason_sha256",
                    "row_hash",
                    "chain_hash",
                )
            }
            for e in events
        ]
        return item

    def events(self, agent_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        where = {"agent_id": self._agent(agent_id)["agent_id"]} if agent_id else None
        return [
            _plain(dict(e))
            for e in self.tables.query("task_event", where, order_by=("-ts",), limit=limit)
        ]

    def agent_summary(self, agent_id: str) -> dict[str, Any]:
        """Stage, sizing inputs, counts and tasks of one agent as plain data (tab, WP31)."""
        inputs = self.agent_inputs(agent_id)
        rows = self.rows_of(agent_id)
        level, classes = self.sizing(inputs["agent_id"], inputs)
        now = self.clock.now()
        stage = self.current_stage(agent_id)
        views = [self._view(r, now) for r in rows]
        in_stage = [v for v in views if v["stage"] == stage and v["kind"] != "move"]
        required = [v for v in in_stage if v["required"]]
        closed = [v for v in required if v["status"] in ("done", "waived")]
        return {
            **inputs,
            "level_now": inputs["level"],
            "level": level,  # what the list is sized with (never lower than before)
            "classes_seen": list(classes),
            "stage": stage,
            "generated": bool(rows),
            "counts": {s: sum(1 for v in views if v["status"] == s) for s in STATUSES},
            "required_open": sum(1 for v in required if v["status"] in OPEN_STATUSES),
            "required_total": len(required),
            "stage_done_bp": (len(closed) * 10000 // len(required)) if required else 10000,
            "overdue": sum(1 for v in views if v["overdue"] and v["required"]),
            "next_stage": self._next_stage(stage, level, classes, inputs) if stage else None,
            "stages_in_use": [s for s, v in plan_at(self.cfg, level, classes).items() if v],
            "illustrative": self.cfg.illustrative,
            "tasks": views,
        }

    def counts(self) -> dict[str, int]:
        now = self.clock.now()
        rows = [self._view(r, now) for r in self.state.query("task")]
        return {
            "tasks": len(rows),
            "open": sum(1 for r in rows if r["status"] in OPEN_STATUSES),
            "required_open": sum(1 for r in rows if r["required"] and r["status"] in OPEN_STATUSES),
            "overdue": sum(1 for r in rows if r["overdue"] and r["required"]),
            "waive_pending": sum(1 for r in rows if r["waive_pending"]),
        }

    def preview(self, d33_class: str, band: str) -> dict[str, Any]:
        """The whole planned set for a class and a band (no store needed): used by the docs,
        the harness and ``python -m supervisor.tasks plan``."""
        level = effective_level(self.cfg, d33_class, band)
        p = plan(self.cfg, d33_class, band)
        return {
            "d33_class": d33_class,
            "band": band,
            "level": level,
            "stages": stages_in_use(self.cfg, d33_class, band),
            "tasks": {
                s: [{"id": x.template.id, "required": x.required} for x in p[s]] for s in STAGES
            },
            "required_n": sum(1 for s in STAGES for x in p[s] if x.required),
            "total_n": sum(len(p[s]) for s in STAGES),
        }

    # ------------------------------------------------------------------ generate
    def _row_for(
        self,
        agent_id: str,
        stage: str,
        *,
        template_id: str,
        kind: str,
        title: str,
        owner_role: str,
        required: bool,
        due_days: int,
        evidence_kind: str,
        evidence_ref: str | None,
        level: str,
        d33_class: str,
        actor: str,
        target_stage: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.clock.now()
        return {
            "task_id": task_id or task_id_for(agent_id, template_id),
            "agent_id": agent_id,
            "template_id": template_id,
            "kind": kind,
            "stage": stage,
            "target_stage": target_stage,
            "title": title,
            "owner_role": owner_role,
            "required": required,
            "status": "open",
            "due_at": now + dt.timedelta(days=due_days),
            "evidence_kind": evidence_kind,
            "evidence_ref": evidence_ref,
            "level": level,
            "d33_class": d33_class,
            "created_at": now,
            "created_by": actor,
        }

    def _release(
        self, agent_id: str, stage: str, inputs: Mapping[str, str], actor: str
    ) -> list[dict[str, Any]]:
        """Create the tasks of ``stage`` (and the move out of it) that do not exist yet, sized by
        ``sizing()`` (never lighter than what the agent had before)."""
        level, classes = self.sizing(agent_id, inputs)
        p = plan_at(self.cfg, level, classes)[stage]
        cls = inputs["d33_class"]
        created: list[dict[str, Any]] = []
        for x in p:
            t = x.template
            row = self._row_for(
                agent_id,
                stage,
                template_id=t.id,
                kind="task",
                title=t.title,
                owner_role=t.owner_role,
                required=x.required,
                due_days=t.due_days,
                evidence_kind=t.evidence_kind,
                evidence_ref=t.evidence_ref,
                level=level,
                d33_class=cls,
                actor=actor,
            )
            created += self._insert(row, actor)
        nxt = self._next_stage(stage, level, classes, inputs)
        if nxt is not None:
            row = self._row_for(
                agent_id,
                stage,
                template_id=move_template_id(nxt),
                kind="move",
                title=f"Move the agent to the {nxt.replace('_', ' ')} stage",
                owner_role="approver" if needs_stage_approval(self.cfg, level) else "owner",
                required=True,
                due_days=self.cfg.move_due_days,
                evidence_kind="none",
                evidence_ref=None,
                level=level,
                d33_class=cls,
                actor=actor,
                target_stage=nxt,
            )
            created += self._insert(row, actor)
        return created

    def _insert(self, row: dict[str, Any], actor: str) -> list[dict[str, Any]]:
        try:
            stored = dict(self.state.insert("task", row))
        except DuplicateKeyError:
            return []
        self._event(stored, "generate", actor, None)
        return [stored]

    def generate(self, agent_id: str, actor: Any) -> dict[str, Any]:
        """Make (or complete) the task list of the current stage of an agent, sized by its
        Decision 33 class and band now. Safe to run again: it adds what is missing, makes a
        task required when the new size says so, and never removes, relaxes or reopens a task.
        A class or level change in the middle of the lifecycle is therefore additive: stricter
        at once, never silently looser (a person waives what no longer applies)."""
        who = _name(actor)
        inputs = self.agent_inputs(agent_id)
        aid = inputs["agent_id"]
        stage = self.current_stage(aid) or "initiation"
        created = self._release(aid, stage, inputs, who)
        resized = self._resize(aid, stage, inputs, who)
        return {
            "agent_id": aid,
            "stage": stage,
            "d33_class": inputs["d33_class"],
            "band": inputs["band"],
            "band_source": inputs["band_source"],
            "level": self.sizing(aid, inputs)[0],
            "created": [r["task_id"] for r in created],
            "created_n": len(created),
            "made_required": resized,
        }

    def _resize(self, agent_id: str, stage: str, inputs: Mapping[str, str], who: str) -> int:
        level, classes = self.sizing(agent_id, inputs)
        planned = {x.template.id: x for x in plan_at(self.cfg, level, classes)[stage]}
        made = 0
        changed = False
        nxt = self._next_stage(stage, level, classes, inputs)
        for row in self.rows_of(agent_id):
            if row["stage"] != stage or row["status"] not in OPEN_STATUSES:
                continue
            fields: dict[str, Any] = {}
            # Only ever up: the stored level and class are what the row was sized with, and
            # they feed sizing() (review WP30: a downgrade must not drop the stage approval).
            if LEVEL_RANK.get(str(row["level"]), -1) < LEVEL_RANK[level]:
                fields["level"] = level
            if row["kind"] == "task" and row["template_id"] in planned:
                if planned[row["template_id"]].required and not _on(row["required"]):
                    fields["required"] = True
                    made += 1
            if row["kind"] == "move":
                tgt = str(row["target_stage"] or "")
                if nxt is not None and tgt in STAGES and STAGES.index(nxt) < STAGES.index(tgt):
                    # a stage was added in between (never skipped): the move goes there first
                    fields["target_stage"] = nxt
                    fields["template_id"] = move_template_id(nxt)  # task_id stays the same
                    fields["title"] = f"Move the agent to the {nxt.replace('_', ' ')} stage"
                role = "approver" if needs_stage_approval(self.cfg, level) else "owner"
                if row["owner_role"] != role and role == "approver":
                    fields["owner_role"] = role
            if fields:
                stored = self._update(row, fields)
                self._event(stored, "resize", who, row["status"])
                changed = True
        if changed:
            self._chain(
                "task_resize",
                f"agent:{agent_id}",
                {
                    "agent_id": agent_id,
                    "stage": stage,
                    "level": level,
                    "d33_class": inputs["d33_class"],
                    "made_required": made,
                    "actor_ref": actor_ref(self.settings, who, "task"),
                    "ts": format_ts(self.clock.now()),
                },
            )
        return made

    # ------------------------------------------------------------------ transitions
    def start(self, task_id: str, actor: Any) -> dict[str, Any]:
        row = self._need(task_id)
        if row["status"] != "open":
            raise TaskError(f"task {task_id} is {row['status']}; only an open task can be started")
        stored = self._update(row, {"status": "in_progress"})
        self._event(stored, "start", _name(actor), row["status"])
        return self.get(task_id)

    def _evidence_problem(self, row: Mapping[str, Any]) -> str | None:
        """Why the evidence of a control or pack task is not there; None when it is."""
        kind, ref = row["evidence_kind"], row["evidence_ref"]
        if kind == "control":
            comp = self.controls().agent_compliance(row["agent_id"])
            item = next((c for c in comp["controls"] if c["control_id"] == ref), None)
            if item is None:
                return f"control {ref} is not active for this agent"
            if item["status"] != "working":
                return f"control {ref} is {item['status']} ({item['reason']}) for this agent"
            return None
        if kind == "pack":
            rows = self.tables.query(
                "eval_result",
                {"target_kind": "agent", "target_id": row["agent_id"], "pack_id": ref},
                order_by=("-ts",),
                limit=50,
            )
            from supervisor.risk import evidence as rev

            if ref in rev.JUDGED_PACKS and not getattr(
                self.settings, "risk_evidence_judged_packs", False
            ):
                return (
                    f"pack {ref} is scored by a judge; it is a reference, not evidence "
                    "(RISK_EVIDENCE_JUDGED_PACKS=1 allows it)"
                )
            real = [r for r in rows if not r.get("is_mock")]
            if not real:
                return f"pack {ref} has no real (non-mock) result for this agent"
            if real[0]["status"] != "ok":
                return f"the newest real result of pack {ref} is {real[0]['status']}"
            ts = _ts(real[0]["ts"])
            days = int(getattr(self.settings, "controls_pack_window_days", 30))
            if ts is None or self.clock.now() - ts > dt.timedelta(days=days):
                return f"the newest real result of pack {ref} is older than {days} days"
            return None
        return None

    def done(self, task_id: str, actor: Any, evidence_ref: str | None = None) -> dict[str, Any]:
        row = self._need(task_id)
        who = _name(actor)
        if row["status"] not in OPEN_STATUSES:
            raise TaskError(f"task {task_id} is {row['status']}; it cannot be marked done")
        fields: dict[str, Any] = {
            "status": "done",
            "done_by": who,
            "done_at": self.clock.now(),
            "waive_requested_by": None,
            "waive_reason": None,
        }
        if row["kind"] == "move":
            self._check_move(row, actor)
        else:
            # Review WP30: the template role decides who may close the task (a second-line
            # review is not closed by the first line alone).
            need = done_refusal(str(row["owner_role"]), _roles(actor))
            if need:
                raise TaskError(
                    f"task {task_id} belongs to role {need}: a person with role {need} or admin "
                    "marks it done"
                )
            if row["evidence_kind"] == "document":
                fields["evidence_ref"] = check_ref(evidence_ref, "document reference")
            elif row["evidence_kind"] in ("control", "pack"):
                problem = self._evidence_problem(row)
                if problem:
                    raise TaskError(f"task {task_id} cannot be done: {problem}")
        stored = self._update(row, fields)
        self._event(stored, "done", who, row["status"])
        if row["kind"] == "move":
            inputs = self.agent_inputs(row["agent_id"])
            self._release(inputs["agent_id"], row["target_stage"], inputs, who)
        return self.get(task_id)

    def approve(self, task_id: str, actor: Any, evidence_ref: str | None = None) -> dict[str, Any]:
        """The approver's way to close a lifecycle move or an approver task (route
        ``POST /v1/tasks/<id>/approve``, permission tasks.approve). Same rules as ``done``."""
        row = self._need(task_id)
        if row["kind"] != "move" and row["owner_role"] != "approver":
            raise TaskError(
                f"task {task_id} is not a lifecycle move or an approver task; use /done"
            )
        return self.done(task_id, actor, evidence_ref)

    def launch_blockers(self, agent_id: str) -> tuple[list[dict[str, Any]], bool, str | None]:
        """(tasks that hold Launch, whether the agent has a task list, its stage). A task holds
        Launch when it is required, open, in the current stage, not the move out of the stage
        and not marked ``blocks_launch: false`` (done after the launch, like DEP-LAUNCH)."""
        stage = self.current_stage(agent_id)
        if stage is None:
            return [], False, None
        by_id = self.cfg.by_id()
        rows = [
            r
            for r in self.open_required(agent_id)
            if r["kind"] != "move"
            and (r["template_id"] not in by_id or by_id[r["template_id"]].blocks_launch)
        ]
        return rows, True, stage

    def _check_move(self, row: Mapping[str, Any], actor: Any) -> None:
        """The lifecycle move is a gate: no required task of the stage may be open."""
        stage_rows = [r for r in self.rows_of(row["agent_id"]) if r["stage"] == row["stage"]]
        code, blockers = move_refusal(
            stage_rows, row["level"], self.cfg, rbac.allowed(_roles(actor), "tasks.approve")
        )
        if code == "required_open":
            raise TaskError(
                f"the move to {row['target_stage']} is refused: required task(s) of the "
                f"{row['stage']} stage are open: {', '.join(blockers)}"
            )
        if code == "needs_approver":
            raise TaskError(
                f"a move at level {row['level']} needs an approver or an admin (stage approval)"
            )
        if needs_stage_approval(self.cfg, row["level"]):
            self._check_sod(stage_rows, _name(actor), "approve this move")

    def _check_sod(self, stage_rows: list[dict[str, Any]], who: str, what: str) -> None:
        """Segregation of duties across the stage (review WP30): see ``tm.sod_refusal``."""
        worked = sod_refusal([r for r in stage_rows if r["kind"] != "move"], who)
        if worked:
            raise TaskError(
                f"segregation of duties: {who} worked on task(s) {', '.join(worked)} of this "
                f"stage for this agent and cannot {what}"
            )

    def request_waive(self, task_id: str, actor: Any, reason: str) -> dict[str, Any]:
        row = self._need(task_id)
        text = clean_reason(reason, "waive reason")
        if row["kind"] == "move":
            raise TaskError("a lifecycle move cannot be waived; it is the gate")
        if row["status"] not in OPEN_STATUSES:
            raise TaskError(f"task {task_id} is {row['status']}; only an open task can be waived")
        if row.get("waive_requested_by"):
            raise TaskError(
                f"a waiver is already waiting for a second person ({row['waive_requested_by']})"
            )
        stored = self._update(
            row,
            {
                "waive_reason": text,
                "waive_requested_by": _name(actor),
                "waive_approved_by": None,
            },
        )
        self._event(stored, "waive_request", _name(actor), row["status"], text)
        return self.get(task_id)

    def approve_waive(self, task_id: str, actor: Any) -> dict[str, Any]:
        row = self._need(task_id)
        who = _name(actor)
        if row["status"] not in OPEN_STATUSES:
            raise TaskError(f"task {task_id} has no waiver waiting for a second person")
        code = waive_refusal(
            row.get("waive_requested_by"),
            who,
            str(getattr(actor, "kind", "user")),
            rbac.allowed(_roles(actor), "tasks.approve"),
        )
        if code == "no_request":
            raise TaskError(f"task {task_id} has no waiver waiting for a second person")
        if code == "not_a_person":
            raise TaskError("a waiver needs a signed-in person as the second person")
        if code == "not_approver":
            raise TaskError(f"{who} cannot approve a waiver: needs role approver or admin")
        if code == "same_person":
            raise TaskError(
                f"{who} asked for this waiver; the second person must be a different person"
            )
        self._check_sod(
            [
                r
                for r in self.rows_of(row["agent_id"])
                if r["stage"] == row["stage"] and r["task_id"] != row["task_id"]
            ],
            who,
            "answer this waiver",
        )
        stored = self._update(row, {"status": "waived", "waive_approved_by": who})
        self._event(stored, "waive_approve", who, row["status"])
        return self.get(task_id)

    def reject_waive(self, task_id: str, actor: Any, reason: str) -> dict[str, Any]:
        row = self._need(task_id)
        who = _name(actor)
        text = clean_reason(reason, "reason")
        if not rbac.allowed(_roles(actor), "tasks.approve"):
            raise TaskError(f"{who} cannot reject a waiver: needs role approver or admin")
        if not row.get("waive_requested_by") or row["status"] not in OPEN_STATUSES:
            raise TaskError(f"task {task_id} has no waiver waiting for a second person")
        self._check_sod(
            [
                r
                for r in self.rows_of(row["agent_id"])
                if r["stage"] == row["stage"] and r["task_id"] != row["task_id"]
            ],
            who,
            "answer this waiver",
        )
        stored = self._update(
            row, {"waive_requested_by": None, "waive_reason": None, "waive_approved_by": None}
        )
        self._event(stored, "waive_reject", who, row["status"], text)
        return self.get(task_id)

    def add_custom(
        self,
        agent_id: str,
        title: str,
        actor: Any,
        *,
        owner_role: str = "owner",
        required: bool = False,
        due_days: int = 14,
    ) -> dict[str, Any]:
        """A task a person adds by hand. It never closes by itself."""
        inputs = self.agent_inputs(agent_id)
        aid = inputs["agent_id"]
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
            raise TaskError(f"title is required (at most {MAX_TITLE} characters)")
        if owner_role not in OWNER_ROLES:
            raise TaskError(f"owner_role must be one of {', '.join(OWNER_ROLES)}")
        if isinstance(due_days, bool) or not isinstance(due_days, int) or not 1 <= due_days <= 3650:
            raise TaskError("due_days must be a whole number from 1 to 3650")
        stage = self.current_stage(aid)
        if stage is None:
            raise TaskError("generate the task list of the agent first")
        if sum(1 for r in self.rows_of(aid) if r["kind"] == "custom") >= MAX_CUSTOM_PER_AGENT:
            raise TaskError(f"an agent can have at most {MAX_CUSTOM_PER_AGENT} custom tasks")
        tid = (
            "tsk_"
            + sha256_hex(
                {"agent": aid.lower(), "custom": title.strip(), "ts": format_ts(self.clock.now())}
            )[:20]
        )
        row = self._row_for(
            aid,
            stage,
            template_id="CUSTOM-" + tid[4:12].upper(),
            kind="custom",
            title=title.strip(),
            owner_role=owner_role,
            required=bool(required),
            due_days=due_days,
            evidence_kind="none",
            evidence_ref=None,
            level=inputs["level"],
            d33_class=inputs["d33_class"],
            actor=_name(actor),
            task_id=tid,
        )
        created = self._insert(row, _name(actor))
        if not created:
            raise TaskError("that task already exists")
        return self.get(created[0]["task_id"])

    # ------------------------------------------------------------------ jobs
    def sync(self, agent_id: str | None = None) -> dict[str, int]:
        """Close, as the system, the template tasks whose evidence is now there (a control that
        works, a real pack that passed). Document and custom tasks are never closed here."""
        from supervisor.cases.service import SystemActor

        system = SystemActor()
        agents = (
            [self._agent(agent_id)["agent_id"]]
            if agent_id
            else sorted({str(r["agent_id"]) for r in self.state.query("task")})
        )
        closed = checked = 0
        for aid in agents:
            for row in self.open_required(aid) + [
                r
                for r in self.rows_of(aid)
                if r["status"] in OPEN_STATUSES and not _on(r["required"])
            ]:
                if row["kind"] != "task" or row["evidence_kind"] not in ("control", "pack"):
                    continue
                checked += 1
                if self._evidence_problem(row) is None:
                    self._update(
                        row,
                        {
                            "status": "done",
                            "done_by": system.user_id,
                            "done_at": self.clock.now(),
                        },
                    )
                    fresh = self._need(row["task_id"])
                    self._event(fresh, "done", system.user_id, row["status"])
                    closed += 1
        return {"checked": checked, "closed": closed}

    def run_due(self, cases: Any = None) -> dict[str, int]:
        """Open one case for every overdue required task that has none yet. ``cases`` is a
        ``CaseService``; without it nothing is opened (the count is still returned)."""
        now = self.clock.now()
        overdue = [
            r
            for r in self.state.query("task", order_by=("task_id",))
            if _on(r["required"]) and self.overdue(r, now)
        ]
        out = {"overdue": len(overdue), "cases_opened": 0}
        if cases is None:
            return out
        for r in overdue:
            if str(r["agent_id"]).startswith("sys_"):
                # WP-G3 review M1: a task of an AI system (not an agent) has no evidence lane to
                # open a case on. One "overdue" task event is its notice (the Tasks tab shows
                # the overdue flag); it is written once.
                seen = self.tables.query("task_event", {"task_id": r["task_id"]}, limit=50)
                if not any(e["action"] == "overdue" for e in seen):
                    self._event(r, "overdue", "supervisor-system", r["status"])
                continue
            if cases.linked_case("task", r["task_id"]) is not None:
                continue
            severity = "medium" if LEVEL_RANK.get(r["level"], 0) >= LEVEL_RANK["high"] else "low"
            cases.open_case(
                agent_id=r["agent_id"],
                severity=severity,
                summary=(
                    f"Required task {r['template_id']} of the {r['stage']} stage "
                    f"is overdue ({r['task_id']})"
                ),
                source_kind="task",
                source_ref=r["task_id"],
            )
            self._event(r, "overdue", "supervisor-system", r["status"])
            out["cases_opened"] += 1
        return out

    # ------------------------------------------------------------------ integrity
    def integrity_problems(self) -> list[str]:
        """Rows that break the rules (a waived task with no second person, a done move with a
        required task open in its stage). The harness and a test call this; it is also a cheap
        audit query."""
        problems: list[str] = []
        rows = [dict(r) for r in self.state.query("task")]
        for r in rows:
            if r["status"] == "waived":
                if not r.get("waive_requested_by") or not r.get("waive_approved_by"):
                    problems.append(f"{r['task_id']}: waived without two people")
                elif same_person(r["waive_requested_by"], r["waive_approved_by"]):
                    problems.append(f"{r['task_id']}: waived by the same person twice")
            if r["status"] == "done" and not r.get("done_by"):
                problems.append(f"{r['task_id']}: done without a person")
        return problems

    # ------------------------------------------------------------------ export
    def export_csv(
        self, agent_id: str | None = None, limit: int = MAX_EXPORT_ROWS
    ) -> tuple[str, bool]:
        """(tasks.csv text, truncated). Formula-safe cells; at most ``MAX_EXPORT_ROWS`` rows."""
        import csv
        import io

        from supervisor.controls.service import csv_cell

        rows = self.list_tasks({"agent": agent_id} if agent_id else None)
        cap = max(1, min(int(limit), MAX_EXPORT_ROWS))
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(TASK_CSV)
        for r in rows[:cap]:
            w.writerow([csv_cell(r.get(k)) for k in TASK_CSV])
        return buf.getvalue(), len(rows) > cap

    def export_json(self, agent_id: str | None = None) -> dict[str, Any]:
        rows = self.list_tasks({"agent": agent_id} if agent_id else None)
        return {"version": 1, "illustrative": self.cfg.illustrative, "tasks": rows}


# ---------------------------------------------------------------------- helpers


def _name(actor: Any) -> str:
    if isinstance(actor, str):
        return actor
    return str(actor.user_id)


def _matches(item: Mapping[str, Any], f: Mapping[str, str]) -> bool:
    if f.get("agent") and item["agent_id"].lower() != f["agent"].lower():
        return False
    if f.get("stage") and item["stage"] != f["stage"]:
        return False
    if f.get("status") and item["status"] != f["status"]:
        return False
    if f.get("required") and str(item["required"]).lower() != f["required"].lower():
        return False
    if f.get("overdue") and str(item["overdue"]).lower() != f["overdue"].lower():
        return False
    if f.get("q"):
        hay = f"{item['task_id']} {item['template_id']} {item['title']}".lower()
        if f["q"].lower() not in hay:
            return False
    return True


def launch_tasks_for(settings: Any, agent_id: str) -> tuple[list[dict[str, Any]], bool, str | None]:
    """``TaskService.launch_blockers`` read from the configured store: (tasks that hold Launch,
    whether the agent has a task list, its stage). Used by the launch gate
    (``assurance.gates.task_launch_items``); it opens and closes its own adapters. Raises when
    the store cannot be read: a gate must not pass on an unknown."""
    from supervisor.adapters.factory import build_adapters

    adapters = build_adapters(settings)
    try:
        return TaskService.from_adapters(adapters).launch_blockers(agent_id)
    finally:
        adapters.close()


__all__ = ["KINDS", "TASK_CSV", "TaskService", "launch_tasks_for", "task_id_for"]
