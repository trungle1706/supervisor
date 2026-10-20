"""Task list model (WP30, ADR D30): lifecycle stages, templates, sizing, state machine.

Pure Python. No SQL, no web. The set of tasks of an agent depends on two things: its Decision 33
class (``high_risk``, ``not_high_risk``, or ``unclassified``) and its risk level (the WP29 band,
else the registry risk tier). Both map to an *effective level*: the higher of the band and the
class floor, so a high-risk class never gets the light set. The templates, the floors and the
thresholds live in ``config/tasks.yaml`` and are ILLUSTRATIVE until the bank sets its own.

A lifecycle move is itself a task (``kind move``); it is done only when no required task of the
current stage is open. Tasks of a stage are released when the agent enters the stage (the set is
sized again at that moment, so a class change is picked up for the later stages).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.errors import SupervisorError

STAGES: tuple[str, ...] = (
    "initiation",
    "design",
    "validation",
    "deployment",
    "operation",
    "re_evaluation",
    "retirement",
)
LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")
LEVEL_RANK: dict[str, int] = {lv: i for i, lv in enumerate(LEVELS)}
CLASSES: tuple[str, ...] = ("high_risk", "not_high_risk", "unclassified")
STATUSES: tuple[str, ...] = ("open", "in_progress", "done", "waived")
OPEN_STATUSES: tuple[str, ...] = ("open", "in_progress")
KINDS: tuple[str, ...] = ("task", "move", "custom")
EVIDENCE_KINDS: tuple[str, ...] = ("control", "pack", "document", "none")
OWNER_ROLES: tuple[str, ...] = ("owner", "reviewer", "approver", "admin", "auditor")
ACTIONS: tuple[str, ...] = (
    "generate",
    "start",
    "done",
    "waive_request",
    "waive_approve",
    "waive_reject",
    "resize",
    "overdue",
    "custom",
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "tasks.yaml"
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_REF = re.compile(r"^[A-Za-z0-9_.:@/#-]{1,128}$")
MAX_TITLE = 200
MAX_REASON = 1000
# Launch (the GO into enforcement) needs the agent at this stage or later (review WP30).
LAUNCH_STAGE = "deployment"
# Template roles a person must hold (or be admin) to mark the task done. ``owner`` tasks may be
# done by anyone with tasks.edit (owner, reviewer, admin). Review WP30: the second line's task is
# not done by the first line alone.
ROLE_BOUND: tuple[str, ...] = ("reviewer", "approver", "auditor", "admin")


class TaskError(SupervisorError):
    """Bad task input or a transition the task list refuses (HTTP 400 at a route)."""


class TasksOff(TaskError):
    """CONTROLS_ENABLED is off (HTTP 400)."""


def ensure_on(settings: Any) -> None:
    if not settings.controls_enabled:
        raise TasksOff(
            "The task list is off (CONTROLS_ENABLED=1 turns it on); "
            "python -m supervisor.tasks generate --agent <id> makes the list of an agent"
        )


def check_id(value: Any, what: str = "task id") -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise TaskError(f"{what} must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
    return value


def check_ref(value: Any, what: str = "evidence reference") -> str:
    if not isinstance(value, str) or not _REF.match(value):
        raise TaskError(f"{what} must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ / # -")
    return value


def clean_reason(value: Any, what: str = "reason") -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{what} is required")
    text = value.strip()
    if len(text) > MAX_REASON:
        raise TaskError(f"{what} is longer than {MAX_REASON} characters")
    return text


@dataclass(frozen=True)
class Template:
    id: str
    stage: str
    title: str
    owner_role: str
    due_days: int
    min_level: str = "low"
    required_from: str | None = None  # required when level >= this; None = never required
    classes: tuple[str, ...] | None = None  # None = any class
    evidence_kind: str = "none"
    evidence_ref: str | None = None
    # False = the task is done after the launch (for example "obtain a GO from the launch
    # report"), so it does not hold the launch gate. It still holds the lifecycle move.
    blocks_launch: bool = True

    def applies(self, level: str, cls: str | Iterable[str]) -> bool:
        if LEVEL_RANK[level] < LEVEL_RANK[self.min_level]:
            return False
        classes = {cls} if isinstance(cls, str) else set(cls)
        return self.classes is None or bool(classes & set(self.classes))

    def required(self, level: str) -> bool:
        return (
            self.required_from is not None and LEVEL_RANK[level] >= LEVEL_RANK[self.required_from]
        )


@dataclass(frozen=True)
class TaskConfig:
    templates: tuple[Template, ...]
    class_floor: Mapping[str, str] = field(default_factory=dict)
    move_approval_from: str = "high"
    move_due_days: int = 14
    illustrative: bool = True

    def by_id(self) -> dict[str, Template]:
        return {t.id: t for t in self.templates}


@dataclass(frozen=True)
class Planned:
    template: Template
    required: bool


def effective_level(cfg: TaskConfig, d33_class: str, band: str) -> str:
    """The higher of the risk band and the floor of the Decision 33 class."""
    if band not in LEVELS:
        raise TaskError(f"band must be one of {', '.join(LEVELS)}")
    if d33_class not in CLASSES:
        raise TaskError(f"class must be one of {', '.join(CLASSES)}")
    floor = cfg.class_floor.get(d33_class, "low")
    return band if LEVEL_RANK[band] >= LEVEL_RANK[floor] else floor


def plan(cfg: TaskConfig, d33_class: str, band: str) -> dict[str, list[Planned]]:
    """stage -> the templates that apply, in config order, with their required flag. Pure."""
    level = effective_level(cfg, d33_class, band)
    out: dict[str, list[Planned]] = {s: [] for s in STAGES}
    for t in cfg.templates:
        if t.applies(level, d33_class):
            out[t.stage].append(Planned(t, t.required(level)))
    return out


def plan_at(cfg: TaskConfig, level: str, classes: Iterable[str]) -> dict[str, list[Planned]]:
    """stage -> the templates that apply at an effective level for ANY of the classes. Used for
    an agent whose class or level changed in the middle of its lifecycle: the set is the union
    of what every class it had needs, at the highest level it had, so it never gets lighter."""
    cls = tuple(classes)
    out: dict[str, list[Planned]] = {s: [] for s in STAGES}
    for t in cfg.templates:
        if t.applies(level, cls):
            out[t.stage].append(Planned(t, t.required(level)))
    return out


def next_stage_at(cfg: TaskConfig, current: str, level: str, classes: Iterable[str]) -> str | None:
    p = plan_at(cfg, level, classes)
    after = [s for s in STAGES if p[s] and STAGES.index(s) > STAGES.index(current)]
    return after[0] if after else None


def done_refusal(owner_role: str, roles: Iterable[str]) -> str | None:
    """None when a person with these roles may mark a task of ``owner_role`` done; else the role
    that is needed. ``owner`` tasks: anyone who may edit tasks; a reviewer, approver, auditor or
    admin task: that role or admin."""
    if owner_role not in ROLE_BOUND:
        return None
    held = set(roles)
    if "admin" in held or owner_role in held:
        return None
    return owner_role


def stages_in_use(cfg: TaskConfig, d33_class: str, band: str) -> list[str]:
    """The stages an agent of this class and band passes through, in order. Initiation, and
    every stage with at least one template, count; an optional stage with none is skipped."""
    p = plan(cfg, d33_class, band)
    return [s for s in STAGES if p[s]]


def next_stage(cfg: TaskConfig, current: str, d33_class: str, band: str) -> str | None:
    used = stages_in_use(cfg, d33_class, band)
    after = [s for s in used if STAGES.index(s) > STAGES.index(current)]
    return after[0] if after else None


def move_template_id(to_stage: str) -> str:
    return "MOVE-" + to_stage.upper()


def needs_stage_approval(cfg: TaskConfig, level: str) -> bool:
    """At or above this level a lifecycle move needs an approver (stage approval)."""
    return LEVEL_RANK[level] >= LEVEL_RANK[cfg.move_approval_from]


# ---------------------------------------------------------------------- the two rules


def move_refusal(
    stage_tasks: list[Mapping[str, Any]], level: str, cfg: TaskConfig, can_approve: bool
) -> tuple[str | None, list[str]]:
    """Why the lifecycle move out of a stage is refused: (code, template ids).

    ``required_open`` = a required task of the stage (not the move itself) is open or in
    progress; ``needs_approver`` = at this level the move needs an approver or an admin
    (stage approval) and the person is neither. ``(None, [])`` = the move may be done."""
    blockers = sorted(
        str(t["template_id"])
        for t in stage_tasks
        if t["kind"] != "move"
        and t["required"] in (True, 1, "1", "true", "True")
        and t["status"] in OPEN_STATUSES
    )
    if blockers:
        return "required_open", blockers
    if needs_stage_approval(cfg, level) and not can_approve:
        return "needs_approver", []
    return None, []


def same_person(a: str | None, b: str | None) -> bool:
    """Two user ids name the same person (ids and e-mails are compared without letter case)."""
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


def waive_refusal(requester: str | None, approver: str, kind: str, can_approve: bool) -> str | None:
    """Why a person may not be the second person of a waiver: ``no_request``, ``not_a_person``,
    ``not_approver`` or ``same_person``; None when the waiver may be approved."""
    if not requester:
        return "no_request"
    if kind != "user":
        return "not_a_person"
    if not can_approve:
        return "not_approver"
    if same_person(requester, approver):
        return "same_person"
    return None


def stage_participants(stage_tasks: list[Mapping[str, Any]]) -> set[str]:
    """People (case-folded) who worked on the tasks of one stage of one agent: who marked a task
    done and who asked for a waiver. The system user is not a person here."""
    out: set[str] = set()
    for t in stage_tasks:
        for field_ in ("done_by", "waive_requested_by"):
            who = t.get(field_)
            if who and who != "supervisor-system":
                out.add(str(who).casefold())
    return out


def sod_refusal(stage_tasks: list[Mapping[str, Any]], person: str) -> list[str]:
    """Segregation of duties across a stage: the person who answers a waiver or approves a
    high-level move must not have worked on a task of the same stage for the same agent.
    Returns the template ids that person worked on (empty = allowed)."""
    me = person.casefold()
    return sorted(str(t["template_id"]) for t in stage_tasks if me in stage_participants([t]))


# ---------------------------------------------------------------------- config file


def _level(value: Any, what: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if value not in LEVELS:
        raise TaskError(f"{what} must be one of {', '.join(LEVELS)}")
    return str(value)


def parse_config(doc: Any, name: str = "tasks.yaml") -> TaskConfig:
    if not isinstance(doc, Mapping) or not isinstance(doc.get("templates"), list):
        raise TaskError(f"{name}: expected a mapping with a 'templates' list")
    floor_in = doc.get("class_floor") or {}
    if not isinstance(floor_in, Mapping):
        raise TaskError(f"{name}: class_floor must be a mapping")
    floor: dict[str, str] = {}
    for cls, lv in floor_in.items():
        if cls not in CLASSES:
            raise TaskError(f"{name}: class_floor has an unknown class {cls!r}")
        floor[str(cls)] = str(_level(lv, f"class_floor.{cls}"))
    templates: list[Template] = []
    seen: set[str] = set()
    for i, raw in enumerate(doc["templates"], 1):
        where = f"{name}: template {i}"
        if not isinstance(raw, Mapping):
            raise TaskError(f"{where}: must be a mapping")
        tid = check_id(raw.get("id"), f"{where}: id")
        if tid in seen:
            raise TaskError(f"{where}: id {tid} is used twice")
        seen.add(tid)
        if tid.startswith("MOVE-"):
            raise TaskError(f"{where}: ids starting with MOVE- are made by the system")
        stage = raw.get("stage")
        if stage not in STAGES:
            raise TaskError(f"{where}: stage must be one of {', '.join(STAGES)}")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
            raise TaskError(f"{where}: title is required (at most {MAX_TITLE} characters)")
        role = raw.get("owner_role", "owner")
        if role not in OWNER_ROLES:
            raise TaskError(f"{where}: owner_role must be one of {', '.join(OWNER_ROLES)}")
        due = raw.get("due_days", 14)
        if isinstance(due, bool) or not isinstance(due, int) or not 1 <= due <= 3650:
            raise TaskError(f"{where}: due_days must be a whole number from 1 to 3650")
        classes = raw.get("classes", "any")
        if classes == "any":
            cls_t = None
        elif isinstance(classes, list) and classes and all(c in CLASSES for c in classes):
            cls_t = tuple(classes)
        else:
            raise TaskError(f"{where}: classes must be 'any' or a list of {', '.join(CLASSES)}")
        ev = raw.get("evidence") or {}
        if not isinstance(ev, Mapping):
            raise TaskError(f"{where}: evidence must be a mapping")
        ekind = ev.get("kind", "none")
        if ekind not in EVIDENCE_KINDS:
            raise TaskError(f"{where}: evidence.kind must be one of {', '.join(EVIDENCE_KINDS)}")
        eref = ev.get("ref")
        if ekind != "none":
            check_ref(eref, f"{where}: evidence.ref")
        blocks = raw.get("blocks_launch", True)
        if not isinstance(blocks, bool):
            raise TaskError(f"{where}: blocks_launch must be true or false")
        templates.append(
            Template(
                id=tid,
                stage=str(stage),
                title=title.strip(),
                owner_role=str(role),
                due_days=due,
                min_level=str(_level(raw.get("min_level", "low"), f"{where}: min_level")),
                required_from=_level(
                    raw.get("required_from"), f"{where}: required_from", allow_none=True
                ),
                classes=cls_t,
                evidence_kind=str(ekind),
                evidence_ref=str(eref) if eref else None,
                blocks_launch=blocks,
            )
        )
    move = doc.get("move") or {}
    if not isinstance(move, Mapping):
        raise TaskError(f"{name}: move must be a mapping")
    due_m = move.get("due_days", 14)
    if isinstance(due_m, bool) or not isinstance(due_m, int) or not 1 <= due_m <= 3650:
        raise TaskError(f"{name}: move.due_days must be a whole number from 1 to 3650")
    return TaskConfig(
        templates=tuple(templates),
        class_floor=floor,
        move_approval_from=str(
            _level(move.get("approval_from", "high"), f"{name}: move.approval_from")
        ),
        move_due_days=due_m,
        illustrative=bool(doc.get("illustrative", True)),
    )


def load_config(path: Path | str | None = None) -> TaskConfig:
    """Read ``config/tasks.yaml``. A missing file is a TaskError: there is no safe default set."""
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.is_file():
        raise TaskError(f"{p.name}: the task template file is missing")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TaskError(f"{p.name}: cannot read the task config ({type(exc).__name__})") from None
    return parse_config(doc, p.name)
