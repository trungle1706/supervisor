"""The eight risk types of Circular 53 Art. 14(3) as one status row per AI system (WP-C2).

Flag ``RISK_DIMENSIONS`` (needs ``GOVERNANCE_ENABLED``). Off: nothing here reads the table and
every route answers HTTP 400 ``risk_dimensions_off``.

* ``load_config`` reads ``config/risk_dimensions.yaml`` with strict keys: exactly the eight fixed
  ids, no float, ``extra_dimensions`` empty (owner decision 2, 2026-10-28).
* ``ensure_rows`` creates the eight ``risk_dimension_status`` rows the first time a system is read.
* ``propose`` is the rule-only initial fill from pack results and monitors. It is shown, a person
  confirms (``confirm_proposal``). No model sets a status.
* ``set_status`` and ``waive`` change a row. ``pass`` needs an evidence pointer; ``waived`` needs a
  reason of 20 characters or more and a person who is not the owner of the system. Every change
  writes a ``risk_dimension_status`` chain record (ids, hashes and integers only) and the caller
  puts ``before>after`` in the audit row.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.errors import ConcurrencyError, SupervisorError

log = logging.getLogger(__name__)

DIMENSION_IDS: tuple[str, ...] = (
    "model",
    "data_governance",
    "cybersecurity",
    "legal_compliance",
    "ethics",
    "third_party",
    "supply_chain",
    "reputation",
)
STATUSES: tuple[str, ...] = (
    "not_started",
    "in_progress",
    "pass",
    "fail",
    "waived",
    "not_applicable",
)
SETTABLE: tuple[str, ...] = tuple(s for s in STATUSES if s != "waived")
BANNER = "Not legal advice. Bank counsel must confirm."
MIN_REASON = 20
MAX_NOTE = 300
MAX_POINTERS = 10
RECORD_TYPE = "risk_dimension_status"
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "risk_dimensions.yaml"
MONITOR_TABLES = {"fairness": "fairness_slice", "oversight": "oversight_metric"}

_POINTER = re.compile(
    r"^(pack|fact|doc|monitor|case|report|task|control|risk):[A-Za-z0-9_.:@/-]{1,150}$"
)
_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_REF = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_ENUM = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_KEYS = ("version", "illustrative", "proposal", "extra_dimensions", "dimensions")
_DIM_KEYS = (
    "id",
    "label_en",
    "label_vi",
    "articles",
    "definition_en",
    "criteria",
    "measure",
    "threshold",
    "review_days",
    "controls",
    "measured_by",
    "risk_categories",
    "applies_to",
    "agent_slot",
)
_PROPOSAL = {
    "pass_when": "all_required_ok",
    "fail_when": "any_required_failed",
    "otherwise": "not_started",
}


class RiskDimensionError(SupervisorError):
    """A refusal (HTTP 400). The message starts with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ------------------------------------------------------------------------------ flag


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "risk_dimensions", False)
        and getattr(settings, "governance_enabled", False)
    )


def tab_enabled(settings: Any) -> bool:
    """The console tab also needs the Systems pages."""
    return enabled(settings) and bool(getattr(settings, "console_systems_enabled", False))


def ensure_on(settings: Any) -> None:
    if not enabled(settings):
        raise RiskDimensionError(
            "risk_dimensions_off",
            "risk dimensions are off (RISK_DIMENSIONS=1 turns them on; needs GOVERNANCE_ENABLED)",
        )


# ------------------------------------------------------------------------------ the config


@dataclass(frozen=True)
class Measure:
    kind: str  # pack | monitor
    id: str
    required: bool


@dataclass(frozen=True)
class Dimension:
    id: str
    label_en: str
    label_vi: str
    articles: tuple[str, ...]
    definition_en: str
    criteria: tuple[str, ...]
    measure: str
    threshold: Mapping[str, Any]
    review_days: int
    controls: tuple[str, ...]
    measured_by: tuple[Measure, ...]
    risk_categories: tuple[str, ...]
    applies_to: str
    agent_slot: str


@dataclass(frozen=True)
class Config:
    dimensions: tuple[Dimension, ...]
    illustrative: bool
    sha256: str

    def get(self, dim_id: str) -> Dimension:
        for d in self.dimensions:
            if d.id == dim_id:
                return d
        raise RiskDimensionError(
            "unknown_dimension", f"dimension must be one of {', '.join(DIMENSION_IDS)}"
        )


def _cfg_error(where: str, message: str) -> SupervisorError:
    from supervisor.core.errors import ConfigError

    return ConfigError(f"risk_dimensions.yaml {where}: {message}")


def _strict(item: Any, allowed: tuple[str, ...], where: str) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise _cfg_error(where, "must be an object")
    unknown = sorted(str(k) for k in set(item) - set(allowed))
    if unknown:
        raise _cfg_error(where, f"unknown key: {', '.join(unknown)}")
    missing = [k for k in allowed if k not in item]
    if missing:
        raise _cfg_error(where, f"missing key: {', '.join(missing)}")
    return item


def _text(value: Any, where: str, limit: int = 600, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit:
        raise _cfg_error(where, f"must be text of {0 if empty else 1} to {limit} characters")
    return " ".join(value.split())


def _strings(value: Any, where: str, pattern: re.Pattern[str] | None = None) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _cfg_error(where, "must be a list")
    out = tuple(_text(v, where, 300) for v in value)
    if pattern is not None:
        for v in out:
            if not pattern.match(v):
                raise _cfg_error(where, f"bad id {v!r}")
    return out


def check_threshold(value: Any, where: str = "threshold") -> dict[str, Any]:
    """A threshold is a small mapping of ids to integers, booleans or short enums. No float."""
    if not isinstance(value, Mapping) or len(value) > 12:
        raise RiskDimensionError(
            "bad_threshold", f"{where} must be an object of at most 12 entries"
        )
    out: dict[str, Any] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not _ID.match(k):
            raise RiskDimensionError("bad_threshold", f"{where}: bad key {str(k)[:40]!r}")
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, int):
            if abs(v) > 10**9:
                raise RiskDimensionError("bad_threshold", f"{where}.{k}: integer too large")
            out[k] = v
        elif isinstance(v, str) and _ENUM.match(v):
            out[k] = v
        else:
            raise RiskDimensionError(
                "bad_threshold", f"{where}.{k}: only integers, booleans and short enums (no float)"
            )
    return out


def _dimension(raw: Any, i: int) -> Dimension:
    where = f"dimensions[{i}]"
    d = _strict(raw, _DIM_KEYS, where)
    measured = d["measured_by"]
    if not isinstance(measured, list):
        raise _cfg_error(f"{where}.measured_by", "must be a list")
    items: list[Measure] = []
    for j, m in enumerate(measured):
        mm = _strict(m, ("kind", "id", "required"), f"{where}.measured_by[{j}]")
        if mm["kind"] not in ("pack", "monitor"):
            raise _cfg_error(f"{where}.measured_by[{j}]", "kind must be pack or monitor")
        if not isinstance(mm["id"], str) or not _ID.match(mm["id"]):
            raise _cfg_error(f"{where}.measured_by[{j}]", "bad id")
        if mm["kind"] == "monitor" and mm["id"] not in MONITOR_TABLES:
            raise _cfg_error(
                f"{where}.measured_by[{j}]", f"monitor must be one of {', '.join(MONITOR_TABLES)}"
            )
        if not isinstance(mm["required"], bool):
            raise _cfg_error(f"{where}.measured_by[{j}]", "required must be true or false")
        items.append(Measure(mm["kind"], mm["id"], mm["required"]))
    days = d["review_days"]
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 3650:
        raise _cfg_error(f"{where}.review_days", "must be an integer from 0 to 3650")
    if d["applies_to"] not in ("any", "bank"):
        raise _cfg_error(f"{where}.applies_to", "must be any or bank")
    slot = d["agent_slot"]
    if not isinstance(slot, str) or (slot and not _REF.match(slot)):
        raise _cfg_error(f"{where}.agent_slot", "must be empty or an agent id")
    try:
        threshold = check_threshold(d["threshold"], f"{where}.threshold")
    except RiskDimensionError as exc:
        raise _cfg_error(f"{where}.threshold", str(exc)) from None
    return Dimension(
        id=str(d["id"]),
        label_en=_text(d["label_en"], f"{where}.label_en", 200),
        label_vi=_text(d["label_vi"], f"{where}.label_vi", 200),
        articles=_strings(d["articles"], f"{where}.articles"),
        definition_en=_text(d["definition_en"], f"{where}.definition_en"),
        criteria=_strings(d["criteria"], f"{where}.criteria"),
        measure=_text(d["measure"], f"{where}.measure"),
        threshold=threshold,
        review_days=days,
        controls=_strings(d["controls"], f"{where}.controls", _ID),
        measured_by=tuple(items),
        risk_categories=_strings(d["risk_categories"], f"{where}.risk_categories", _ID),
        applies_to=str(d["applies_to"]),
        agent_slot=slot,
    )


def parse_config(data: Any, sha: str = "") -> Config:
    top = _strict(data, _KEYS, "file")
    if top["version"] != 1:
        raise _cfg_error("version", "must be 1")
    if top["extra_dimensions"] != []:
        raise _cfg_error(
            "extra_dimensions",
            "must stay empty: exactly the eight types of Circular 53 Art. 14(3) (owner decision 2)",
        )
    if dict(top["proposal"] or {}) != _PROPOSAL:
        raise _cfg_error("proposal", f"must be {_PROPOSAL}")
    raw = top["dimensions"]
    if not isinstance(raw, list):
        raise _cfg_error("dimensions", "must be a list")
    dims = tuple(_dimension(r, i) for i, r in enumerate(raw))
    ids = tuple(d.id for d in dims)
    if ids != DIMENSION_IDS:
        raise _cfg_error(
            "dimensions", f"the ids must be exactly, in order: {', '.join(DIMENSION_IDS)}"
        )
    return Config(dims, bool(top["illustrative"]), sha)


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> Config:
    raw = Path(path).read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise _cfg_error("file", f"not valid YAML ({type(exc).__name__})") from None
    return parse_config(data, hashlib.sha256(raw).hexdigest())


def load_config(path: Path | str | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        raise _cfg_error("file", "cannot be read") from None
    return _load_cached(str(p.resolve()), mtime)


# ------------------------------------------------------------------------------ environment


@dataclass(frozen=True)
class Env:
    state: Any
    tables: Any
    clock: Any
    settings: Any
    sink: Any
    cfg: Config

    @classmethod
    def from_console(cls, ctx: Any, cfg: Config | None = None) -> Env:
        return cls(
            ctx.state,
            ctx.tables,
            ctx.clock,
            ctx.settings,
            getattr(ctx.runtime, "chain", None),
            cfg or load_config(),
        )


# ------------------------------------------------------------------------------ rows


def status_id(system_id: str, dim_id: str) -> str:
    return hashlib.sha256(f"{system_id}|{dim_id}".encode()).hexdigest()[:24]


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def _row(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row["evidence"] = [str(x) for x in _json(row.get("evidence_json"), [])]
    row["threshold"] = dict(_json(row.get("threshold_json"), {}))
    return row


def _now(env: Env) -> dt.datetime:
    now: dt.datetime = env.clock.now()
    return now


def rows_of(env: Env, system_id: str) -> list[dict[str, Any]]:
    """The rows of the system, in the order of the eight types."""
    found = {
        r["dimension_id"]: _row(r)
        for r in env.state.query("risk_dimension_status", {"system_id": system_id})
    }
    return [found[d.id] for d in env.cfg.dimensions if d.id in found]


def ensure_rows(env: Env, system: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create the eight rows once. A repeat changes nothing."""
    ensure_on(env.settings)
    sid = str(system["system_id"])
    have = {r["dimension_id"] for r in env.state.query("risk_dimension_status", {"system_id": sid})}
    for d in env.cfg.dimensions:
        if d.id in have:
            continue
        if env.state.get("risk_dimension_status", {"status_id": status_id(sid, d.id)}) is not None:
            continue
        env.state.insert(
            "risk_dimension_status",
            {
                "status_id": status_id(sid, d.id),
                "system_id": sid,
                "dimension_id": d.id,
                "status": "not_started",
                "owner_team": str(system.get("owner_team") or "") or None,
                "assessed_by": None,
                "report_ref": None,
                "evidence_json": [],
                "threshold_json": dict(d.threshold),
                "note": None,
                "updated_by": "rule:risk_dimensions",
                "valid_until": None,
            },
        )
    return rows_of(env, sid)


# ------------------------------------------------------------------------------ the proposal


def system_agents(env: Env, system_id: str) -> list[str]:
    comps = env.state.query("system_component", {"system_id": system_id})
    return sorted(
        {
            str(c["ref_id"])
            for c in comps
            if c["ref_kind"] == "agent" and str(c.get("active", True)).lower() not in ("false", "0")
        }
    )


def _pack_versions() -> dict[str, int]:
    from supervisor.assurance.loader import load_packs

    return {p.id: int(p.version) for p in load_packs()}


def _check_pack(
    env: Env, m: Measure, agents: list[str], versions: Mapping[str, int]
) -> dict[str, Any]:
    """ok when every agent has an ok result at the current version; fail when one failed."""
    current = versions.get(m.id)
    pointers: list[str] = []
    states: list[str] = []
    for agent in agents:
        rows = env.tables.query(
            "eval_result",
            {"target_kind": "agent", "target_id": agent, "pack_id": m.id},
            order_by=["-ts"],
            limit=1,
        )
        if not rows:
            states.append("missing")
            continue
        r = rows[0]
        if current is None or int(r["pack_version"]) != current:
            states.append("stale")
            continue
        status = str(r["status"])
        states.append("ok" if status == "ok" else "fail" if status in ("fail", "error") else "weak")
        pointers.append(f"pack:{m.id}:{r['run_id']}:{agent}"[:158])
    if not states:
        state = "missing"
    elif "fail" in states:
        state = "fail"
    elif all(s == "ok" for s in states):
        state = "ok"
    else:
        state = next((x for x in ("weak", "stale") if x in states), "missing")
    return {
        "kind": "pack",
        "id": m.id,
        "required": m.required,
        "state": state,
        "pointers": pointers,
    }


def _check_monitor(env: Env, m: Measure, agents: list[str]) -> dict[str, Any]:
    table = MONITOR_TABLES[m.id]
    pointers: list[str] = []
    ok = bool(agents)
    for agent in agents:
        store = env.tables if table == "fairness_slice" else env.state  # append-only | state
        rows = store.query(table, {"agent_id": agent}, limit=1)
        if rows:
            pointers.append(f"monitor:{m.id}:{agent}"[:158])
        else:
            ok = False
    return {
        "kind": "monitor",
        "id": m.id,
        "required": m.required,
        "state": "ok" if ok else "missing",
        "pointers": pointers,
    }


def propose(env: Env, system_id: str, dim_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Rule-only proposal per type: ``{status, evidence, checks}``. ``pass`` when every required
    item is ok at the current pack version for every agent of the system; ``fail`` when a required
    item failed; else ``not_started``. Nothing is stored."""
    agents = system_agents(env, system_id)
    versions = _pack_versions()
    out: dict[str, dict[str, Any]] = {}
    for d in env.cfg.dimensions:
        if dim_id and d.id != dim_id:
            continue
        checks = [
            _check_pack(env, m, agents, versions)
            if m.kind == "pack"
            else _check_monitor(env, m, agents)
            for m in d.measured_by
        ]
        required = [c for c in checks if c["required"]]
        if any(c["state"] == "fail" for c in required):
            status = "fail"
        elif required and agents and all(c["state"] == "ok" for c in required):
            status = "pass"
        else:
            status = "not_started"
        pointers = sorted({p for c in checks if c["state"] == "ok" for p in c["pointers"]})
        out[d.id] = {
            "status": status,
            "evidence": pointers[:MAX_POINTERS] if status == "pass" else [],
            "checks": checks,
            "n_required": len(required),
        }
    return out


# ------------------------------------------------------------------------------ changes


def clean_pointers(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [p for p in re.split(r"[\s,]+", value) if p]
    if not isinstance(value, list):
        raise RiskDimensionError("bad_evidence", "evidence must be a list of pointers")
    out: list[str] = []
    for p in value:
        if not isinstance(p, str) or not _POINTER.match(p.strip()):
            raise RiskDimensionError(
                "bad_evidence",
                "an evidence pointer looks like pack:<pack>:<run>:<agent>, fact:<id> or doc:<id>",
            )
        if p.strip() not in out:
            out.append(p.strip())
    if len(out) > MAX_POINTERS:
        raise RiskDimensionError("bad_evidence", f"at most {MAX_POINTERS} evidence pointers")
    return out


def clean_text(value: Any, what: str, minimum: int = 0) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if len(text) < minimum:
        raise RiskDimensionError("reason_too_short", f"{what} needs at least {minimum} characters")
    if len(text) > MAX_NOTE:
        raise RiskDimensionError("note_too_long", f"{what} is longer than {MAX_NOTE} characters")
    if _CTRL_CHARS.search(text):
        raise RiskDimensionError("bad_text", f"{what} has control characters")
    from supervisor.governance.triage import scrub

    return scrub(text)


def is_owner(system: Mapping[str, Any], user: str) -> bool:
    from supervisor.governance.lifecycle import same

    if same(str(system.get("owner_user") or ""), user):
        return True
    return any(
        same(str(m.get("user_id") or ""), user) and m.get("team_role") == "system_owner"
        for m in system.get("team") or []
        if m.get("active", True)
    )


def _evidence_hash(pointers: Iterable[str]) -> str:
    return hashlib.sha256(canonical_json(sorted(pointers)).encode("utf-8")).hexdigest()


def _actor_ref(actor: str) -> str:
    return "p-" + hashlib.sha256(actor.encode("utf-8")).hexdigest()[:16]


def _record(
    env: Env, system_id: str, dim_id: str, before: str, after: str, actor: str, pointers: list[str]
) -> None:
    if env.sink is None:
        return
    now = _now(env)
    try:
        env.sink.record(
            RECORD_TYPE,
            f"risk_dimension:{system_id}:{dim_id}:{format_ts(now)}",
            {
                "system_id": system_id,
                "dimension_id": dim_id,
                "from": before,
                "to": after,
                "actor_ref": _actor_ref(actor),
                "evidence_hash": _evidence_hash(pointers),
                "evidence_n": len(pointers),
                "ts": format_ts(now),
            },
        )
    except Exception:  # noqa: BLE001 - the row is stored; log and go on
        log.exception("risk dimension chain record failed")


def _need_row(env: Env, system: Mapping[str, Any], dim_id: str) -> dict[str, Any]:
    ensure_rows(env, system)
    env.cfg.get(dim_id)
    raw = env.state.get(
        "risk_dimension_status", {"status_id": status_id(str(system["system_id"]), dim_id)}
    )
    if raw is None:
        raise RiskDimensionError("unknown_dimension", "no such row")
    return _row(raw)


def _store(env: Env, row: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
    try:
        env.state.update(
            "risk_dimension_status",
            {"status_id": row["status_id"]},
            dict(changes),
            int(row["row_version"]),
        )
    except ConcurrencyError:
        raise RiskDimensionError(
            "changed", f"{row['dimension_id']} was changed by someone else; reload"
        ) from None


def _need_open(system: Mapping[str, Any]) -> None:
    if system.get("status") == "archived":
        raise RiskDimensionError("archived", "the AI system is archived; it cannot be changed")


def _valid_until(env: Env, dim: Dimension, status: str, given: Any) -> str | None:
    if given not in (None, ""):
        try:
            return dt.date.fromisoformat(str(given)[:10]).isoformat()
        except ValueError:
            raise RiskDimensionError("bad_date", "valid_until must be a date YYYY-MM-DD") from None
    if status == "pass" and dim.review_days:
        return (_now(env).date() + dt.timedelta(days=dim.review_days)).isoformat()
    return None


def set_status(
    env: Env,
    actor: str,
    system: Mapping[str, Any],
    dim_id: str,
    status: Any,
    *,
    evidence: Any = None,
    note: Any = None,
    threshold: Any = None,
    valid_until: Any = None,
    report_ref: Any = None,
) -> dict[str, Any]:
    """Set the status of one type. ``waived`` goes through ``waive``."""
    ensure_on(env.settings)
    _need_open(system)
    if status == "waived":
        raise RiskDimensionError(
            "use_waive", "a waiver has its own action: it needs a reason and a second person"
        )
    if status not in SETTABLE:
        raise RiskDimensionError("bad_status", f"status must be one of {', '.join(SETTABLE)}")
    dim = env.cfg.get(dim_id)
    row = _need_row(env, system, dim_id)
    pointers = clean_pointers(evidence) if evidence not in (None, "") else list(row["evidence"])
    if status == "pass" and not pointers:
        raise RiskDimensionError("evidence_required", "pass needs at least one evidence pointer")
    text = clean_text(note, "the note", 20 if status == "not_applicable" else 0)
    changes: dict[str, Any] = {
        "status": status,
        "evidence_json": pointers,
        "assessed_by": f"person:{actor}"[:128],
        "updated_by": actor,
        "valid_until": _valid_until(env, dim, status, valid_until),
    }
    if text or note is not None:
        changes["note"] = text or None
    if threshold is not None:
        changes["threshold_json"] = check_threshold(threshold)
    if report_ref not in (None, ""):
        if not isinstance(report_ref, str) or not _REF.match(report_ref):
            raise RiskDimensionError("bad_report_ref", "report_ref must be a report id")
        changes["report_ref"] = report_ref
    _store(env, row, changes)
    _record(env, str(system["system_id"]), dim_id, str(row["status"]), status, actor, pointers)
    return {
        "dimension_id": dim_id,
        "from": row["status"],
        "to": status,
        "evidence_n": len(pointers),
    }


def confirm_proposal(
    env: Env, actor: str, system: Mapping[str, Any], dim_id: str
) -> dict[str, Any]:
    """A person confirms the rule proposal: its status and its evidence pointers are stored."""
    ensure_on(env.settings)
    prop = propose(env, str(system["system_id"]), dim_id)[dim_id]
    if prop["status"] == "not_started":
        raise RiskDimensionError("no_proposal", "the rules have no proposal for this type yet")
    out = set_status(
        env,
        actor,
        system,
        dim_id,
        prop["status"],
        evidence=prop["evidence"] or None,
        note="from rule proposal, confirmed by a person",
    )
    out["from_proposal"] = True
    return out


def waive(
    env: Env, actor: str, system: Mapping[str, Any], dim_id: str, reason: Any
) -> dict[str, Any]:
    """Waive one type. Reason of 20 characters or more; not by the owner of the system."""
    ensure_on(env.settings)
    _need_open(system)
    text = clean_text(reason, "the waiver reason", MIN_REASON)
    if is_owner(system, actor):
        raise RiskDimensionError(
            "owner_cannot_waive",
            "the owner of a system cannot waive a risk type of the own system; "
            "a second person with approval rights does it",
        )
    row = _need_row(env, system, dim_id)
    if row["status"] == "waived":
        raise RiskDimensionError("already_waived", f"{dim_id} is already waived")
    _store(
        env,
        row,
        {
            "status": "waived",
            "note": text,
            "assessed_by": f"person:{actor}"[:128],
            "updated_by": actor,
            "valid_until": None,
        },
    )
    _record(
        env, str(system["system_id"]), dim_id, str(row["status"]), "waived", actor, row["evidence"]
    )
    return {
        "dimension_id": dim_id,
        "from": row["status"],
        "to": "waived",
        "evidence_n": len(row["evidence"]),
    }


# ------------------------------------------------------------------------------ views


def view(env: Env, system: Mapping[str, Any]) -> dict[str, Any]:
    """The eight rows with their definitions and the rule proposal (creates the rows once)."""
    rows = ensure_rows(env, system)
    props = propose(env, str(system["system_id"]))
    today = _now(env).date().isoformat()
    out = []
    for r in rows:
        d = env.cfg.get(r["dimension_id"])
        until = str(r.get("valid_until") or "")[:10]
        out.append(
            {
                "dimension_id": d.id,
                "label_en": d.label_en,
                "label_vi": d.label_vi,
                "articles": list(d.articles),
                "status": r["status"],
                "owner_team": r.get("owner_team") or "",
                "assessed_by": r.get("assessed_by") or "",
                "report_ref": r.get("report_ref") or "",
                "evidence": r["evidence"],
                "threshold": r["threshold"],
                "note": r.get("note") or "",
                "updated_by": r.get("updated_by") or "",
                "valid_until": until,
                "expired": bool(r["status"] == "pass" and until and until < today),
                "applies_to": d.applies_to,
                "risk_categories": list(d.risk_categories),
                "proposal": props[d.id],
                "agent_slot": d.agent_slot,
            }
        )
    return {
        "system_id": str(system["system_id"]),
        "banner": BANNER,
        "illustrative": env.cfg.illustrative,
        "dimensions": out,
        "counts": counts(out),
    }


def counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    c = dict.fromkeys(STATUSES, 0)
    for r in rows:
        c[str(r["status"])] = c.get(str(r["status"]), 0) + 1
    return c


def summary(env: Env, system_ids: Iterable[str]) -> dict[str, Any]:
    """Portfolio counts per type and status for the given systems. Read-only: a system without
    rows counts as not_started for every type (the rows are made when the system is read)."""
    ids = list(system_ids)
    by_dim = {d.id: dict.fromkeys(STATUSES, 0) for d in env.cfg.dimensions}
    for sid in ids:
        have = {
            r["dimension_id"]: r["status"]
            for r in env.state.query("risk_dimension_status", {"system_id": sid})
        }
        for d in env.cfg.dimensions:
            st = str(have.get(d.id, "not_started"))
            by_dim[d.id][st] = by_dim[d.id].get(st, 0) + 1
    return {
        "systems": len(ids),
        "dimensions": [
            {"dimension_id": d.id, "label_en": d.label_en, **by_dim[d.id]}
            for d in env.cfg.dimensions
        ],
        "statuses": list(STATUSES),
    }
