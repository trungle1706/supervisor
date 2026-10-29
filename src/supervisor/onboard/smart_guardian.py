"""The smart guardian (WP-G4, flag ``SMART_GUARDIAN``, docs/smart-guardian.md).

For one AI system it PROPOSES a guardian set, thresholds, autonomy limits and the floor, with the
pointer that justifies each line. Deterministic: a rules table in ``config/smart_guardian.yaml``
and no model call. A person with ``systems.edit`` accepts all or some lines; accepting writes the
bindings through ``GuardianService`` (the floor and the off-request rule stay), the monitor
thresholds into ``policy_threshold`` and the autonomy limits into the system record tag
``autonomy_limits``. Detector settings are recorded in the proposal row as a ready policy snippet
(the per-agent detector override lives in the policy file, which a person changes by pull
request). Nothing here attaches by itself and nothing is scheduled: the pre-deploy test (WP-O3)
is the proof of the fit.

Inputs: the facts v1 of the system, the eight ``risk_dimension_status`` rows, the newest
``assessment_report_v1`` files (findings with verdict and evidence), the classification outcome,
the AI type flags (system tags ``ai_*``) and the autonomy level.

Integers only (no floats). No personal data: a line holds slugs, ids, pointers and numbers.
Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, NotFoundError, SupervisorError
from supervisor.evidence.chain import check_no_floats
from supervisor.governance import model as gm

TABLE = "guardian_proposal"
RECORD_TYPE = "guardian_proposal"
BANNER = "Not legal advice. Bank counsel must confirm."
STATUSES = ("proposed", "accepted", "rejected", "superseded")
GROUPS = ("guardian_set", "thresholds", "autonomy_limits", "floor")
WHY_KINDS = ("finding", "dimension", "fact", "flag", "classification", "system_record", "rule")
MAX_NOTE = 300
MIN_REASON = 20
CONFIG_PATH = Path("config/smart_guardian.yaml")
FLAGS = ("generative", "agentic", "customer_facing", "decides")
_LOCK = threading.RLock()


class SmartGuardianError(SupervisorError):
    """A refusal (HTTP 400). The message starts with ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ------------------------------------------------------------------------------ flag


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "smart_guardian", False)
        and getattr(settings, "governance_enabled", False)
        and getattr(settings, "risk_dimensions", False)
    )


def ensure_on(settings: Any) -> None:
    if not enabled(settings):
        raise SmartGuardianError(
            "smart_guardian_off",
            "the smart guardian is off (SMART_GUARDIAN=1 turns it on; needs GOVERNANCE_ENABLED "
            "and RISK_DIMENSIONS; ONBOARD_ORCHESTRATOR adds the assessment reports)",
        )


# ------------------------------------------------------------------------------ rules table


@dataclass(frozen=True)
class Config:
    illustrative: bool
    patterns: Mapping[str, str]
    rules: tuple[Mapping[str, Any], ...]
    max_lines: int
    sha256: str


_COND_KEYS = (
    "levels",
    "dim",
    "finding",
    "fact_kinds",
    "fact_tool_re",
    "flags_any",
    "money",
    "credit",
    "personal_data",
    "segment",
    "autonomy_gte",
)
_RULE_KEYS = ("id", "group", "when", "any_of", "lines")
_cache: dict[str, tuple[int, Config]] = {}


def _bad(where: str, message: str) -> SupervisorError:
    return SupervisorError(f"config/smart_guardian.yaml {where}: {message}")


def _check_cond(cond: Any, where: str, patterns: Mapping[str, str]) -> None:
    if not isinstance(cond, Mapping) or not cond:
        raise _bad(where, "a condition must be a non-empty mapping")
    for k, v in cond.items():
        if k not in _COND_KEYS:
            raise _bad(where, f"unknown condition key {k!r}")
        if k in ("finding", "dim") and not (isinstance(v, Mapping) and v.get("dimension")):
            raise _bad(where, f"{k} needs a dimension")
        if k == "finding":
            ref = v.get("checklist_re")
            if ref is not None and ref not in patterns:
                raise _bad(where, f"checklist_re {ref!r} is not in patterns")
        if k == "fact_tool_re" and v not in patterns:
            raise _bad(where, f"fact_tool_re {v!r} is not in patterns")
        if k == "autonomy_gte" and v not in gm.AUTONOMY_LEVELS:
            raise _bad(where, f"unknown autonomy level {v!r}")


def parse_config(doc: Any, sha: str = "") -> Config:
    if not isinstance(doc, Mapping) or doc.get("version") != 1:
        raise _bad("", "version must be 1")
    patterns = dict(doc.get("patterns") or {})
    for name, rx in patterns.items():
        try:
            re.compile(str(rx))
        except re.error as exc:
            raise _bad(f"patterns.{name}", f"bad regex ({exc})") from None
    ids: set[str] = set()
    rules: list[Mapping[str, Any]] = []
    for i, rule in enumerate(doc.get("rules") or []):
        where = f"rules[{i}]"
        if not isinstance(rule, Mapping) or set(rule) - set(_RULE_KEYS):
            raise _bad(where, f"a rule has only the keys {', '.join(_RULE_KEYS)}")
        rid = str(rule.get("id") or "")
        if not re.fullmatch(r"SG-[A-Z]-[A-Z0-9-]+", rid) or rid in ids:
            raise _bad(where, "id must look like SG-G-NAME and be unique")
        ids.add(rid)
        if rule.get("group") not in GROUPS[:3]:
            raise _bad(where, "group must be guardian_set, thresholds or autonomy_limits")
        if bool(rule.get("when")) == bool(rule.get("any_of")):
            raise _bad(where, "give either when or any_of")
        for cond in [rule["when"]] if rule.get("when") else list(rule["any_of"]):
            _check_cond(cond, where, patterns)
        lines = rule.get("lines")
        if not isinstance(lines, list) or not lines:
            raise _bad(where, "a rule needs lines")
        for ln in lines:
            if not isinstance(ln, Mapping) or not ln.get("subject"):
                raise _bad(where, "a line needs a subject")
            _no_float(ln, where)
        rules.append(dict(rule))
    limits = doc.get("limits") or {}
    return Config(
        bool(doc.get("illustrative", True)),
        patterns,
        tuple(rules),
        int(limits.get("max_lines", 40)),
        sha,
    )


def _no_float(value: Any, where: str) -> None:
    if isinstance(value, float):
        raise _bad(where, "no floats; use whole numbers")
    if isinstance(value, Mapping):
        for v in value.values():
            _no_float(v, where)
    elif isinstance(value, list):
        for v in value:
            _no_float(v, where)


def load_config(path: Path | str | None = None) -> Config:
    p = Path(path) if path else _default_path()
    key = str(p.resolve())
    mtime = p.stat().st_mtime_ns
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    raw = p.read_bytes()
    cfg = parse_config(yaml.safe_load(raw), hashlib.sha256(raw).hexdigest())
    _cache[key] = (mtime, cfg)
    return cfg


def _default_path() -> Path:
    here = Path(__file__).resolve().parents[3] / CONFIG_PATH
    return here if here.is_file() else CONFIG_PATH


# ------------------------------------------------------------------------------ inputs


@dataclass
class Inputs:
    """Everything the rules read. Built by ``gather`` or by hand in a test."""

    system_id: str
    outcome: str
    autonomy_level: str = "unspecified"
    money: bool = False
    credit: bool = False
    personal_data: str = "none"
    segment: str = "internal"
    flags: Mapping[str, bool] = field(default_factory=dict)
    dim_status: Mapping[str, str] = field(default_factory=dict)
    # report findings: {dimension: [{finding_id, checklist_id, verdict, report_id}]}
    findings: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    facts: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    thresholds: Mapping[str, int] = field(default_factory=dict)
    floor: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    attempt_n: int = 0


def _rank(level: str) -> int:
    return gm.AUTONOMY_LEVELS.index(level) if level in gm.AUTONOMY_LEVELS else 0


def _at_least(level: str, floor: str) -> bool:
    return _rank(level) >= _rank(floor) and _rank(level) > 0


_WHY_RANK = ("finding", "fact", "dimension", "flag", "system_record", "classification", "rule")


def _why(kind: str, ident: str, detail: str = "") -> dict[str, str]:
    return {"kind": kind, "id": ident[:200], "detail": detail[:200]}


def _tools(inp: Inputs, rx: str) -> list[Mapping[str, Any]]:
    pat = re.compile(rx, re.IGNORECASE)
    return [f for f in inp.facts if f.get("kind") == "tool" and pat.search(str(f.get("name", "")))]


def _fact_why(f: Mapping[str, Any]) -> dict[str, str]:
    where = f"{f.get('file')}:{f.get('line')}" if f.get("file") else ""
    return _why("fact", f"fact:{f.get('fact_id')}", f"{f.get('kind')} {f.get('name', '')} {where}")


def _match_one(
    cond: Mapping[str, Any], inp: Inputs, cfg: Config
) -> tuple[dict[str, str], dict[str, Any]] | None:
    """The first justification and the extras (matched tool names) when every key of ``cond``
    holds, else ``None``."""
    whys: list[dict[str, str]] = []
    extra: dict[str, Any] = {}
    for key, want in cond.items():
        if key == "levels":
            if inp.outcome not in want:
                return None
            whys.append(_why("classification", f"outcome:{inp.outcome}", "classification outcome"))
        elif key == "dim":
            st = inp.dim_status.get(want["dimension"], "not_started")
            if st not in want.get("status_in", []):
                return None
            whys.append(_why("dimension", f"risk_dimension:{want['dimension']}", f"status {st}"))
        elif key == "finding":
            rx = (
                re.compile(cfg.patterns[want["checklist_re"]], re.IGNORECASE)
                if want.get("checklist_re")
                else None
            )
            hit = next(
                (
                    f
                    for f in inp.findings.get(want["dimension"], [])
                    if f.get("verdict") == want.get("verdict", "fail")
                    and (rx is None or rx.search(str(f.get("checklist_id", ""))))
                ),
                None,
            )
            if hit is None:
                return None
            whys.append(
                _why(
                    "finding",
                    f"{want['dimension']}/{hit.get('finding_id')}",
                    f"report {hit.get('report_id')} checklist {hit.get('checklist_id')} "
                    f"verdict {hit.get('verdict')}",
                )
            )
        elif key == "fact_kinds":
            hit = next((f for f in inp.facts if f.get("kind") in want), None)
            if hit is None:
                return None
            whys.append(_fact_why(hit))
        elif key == "fact_tool_re":
            tools = _tools(inp, cfg.patterns[want])
            if not tools:
                return None
            extra["matched_tools"] = sorted({str(t["name"])[:80] for t in tools})
            whys.append(_fact_why(tools[0]))
        elif key == "flags_any":
            on = [f for f in want if inp.flags.get(f)]
            if not on:
                return None
            whys.append(_why("flag", f"ai_{on[0]}", "AI type flag"))
        elif key == "money":
            if bool(inp.money) != bool(want):
                return None
            whys.append(_why("system_record", "ai_system:money_movement", "moves money"))
        elif key == "credit":
            if bool(inp.credit) != bool(want):
                return None
            whys.append(_why("system_record", "ai_system:credit_decision", "credit decision"))
        elif key == "personal_data":
            has = inp.personal_data != "none" or any(f.get("kind") == "dataset" for f in inp.facts)
            if has != bool(want):
                return None
            ds = next((f for f in inp.facts if f.get("kind") == "dataset"), None)
            whys.append(
                _fact_why(ds)
                if ds is not None and inp.personal_data == "none"
                else _why("system_record", "ai_system:personal_data", inp.personal_data)
            )
        elif key == "segment":
            if inp.segment not in want:
                return None
            whys.append(_why("system_record", "ai_system:user_segment", inp.segment))
        elif key == "autonomy_gte":
            if not _at_least(inp.autonomy_level, want):
                return None
            whys.append(_why("system_record", "ai_system:autonomy_level", inp.autonomy_level))
    return min(whys, key=lambda w: _WHY_RANK.index(w["kind"])), extra


def _match(rule: Mapping[str, Any], inp: Inputs, cfg: Config) -> tuple[dict, dict] | None:
    for cond in [rule["when"]] if rule.get("when") else rule["any_of"]:
        got = _match_one(cond, inp, cfg)
        if got is not None:
            return got
    return None


def line_id(rule_id: str, subject: str) -> str:
    return "ln_" + hashlib.sha256(f"{rule_id}|{subject}".encode()).hexdigest()[:10]


def _resolve(spec: Mapping[str, Any], inp: Inputs, extra: Mapping[str, Any]) -> tuple[Any, bool]:
    """(value, ok). ``ok`` is false when the value cannot be built (no threshold in the file)."""
    if "value_by_level" in spec:
        val = spec["value_by_level"].get(inp.outcome)
        return val, val is not None
    if "value_from" in spec:
        ref = str(spec["value_from"])
        if ref == "matched_tools":
            tools = list(extra.get("matched_tools") or [])
            return tools, bool(tools)
        if ref.startswith("threshold:"):
            key = ref.split(":", 1)[1]
            seg = inp.segment == "customer"
            name = {
                "per_transaction": "personal_per_transaction_vnd"
                if seg
                else "organisation_per_transaction_vnd",
                "per_day": "personal_per_day_vnd" if seg else "organisation_per_day_vnd",
            }.get(key, key)
            val = inp.thresholds.get(name)
            return val, isinstance(val, int)
        return None, False
    return spec.get("value"), "value" in spec


def evaluate(inp: Inputs, cfg: Config) -> list[dict[str, Any]]:
    """The proposal lines, in rule order (groups first, then the floor). Pure: no I/O."""
    floor_slugs = {str(f["slug"]) for f in inp.floor}
    seen: set[tuple[str, str]] = set()
    lines: list[dict[str, Any]] = []
    for rule in cfg.rules:
        got = _match(rule, inp, cfg)
        if got is None:
            continue
        why, extra = got
        for spec in rule["lines"]:
            subject = str(spec["subject"])
            group = str(rule["group"])
            if (group, subject) in seen:
                continue
            need = spec.get("requires_autonomy_gte")
            if need and not _at_least(inp.autonomy_level, need):
                continue
            if group == "guardian_set" and subject in floor_slugs:
                continue  # the floor already holds it; it shows under floor
            value, ok = _resolve(spec, inp, extra)
            if group != "guardian_set" and not ok:
                continue
            if group == "autonomy_limits" and subject == "max_level":
                if _rank(str(value)) >= _rank(inp.autonomy_level):
                    continue  # the cap would not lower anything
            seen.add((group, subject))
            line: dict[str, Any] = {
                "line_id": line_id(str(rule["id"]), subject),
                "group": group,
                "kind": spec.get("kind") or ("bind" if group == "guardian_set" else "limit"),
                "subject": subject,
                "rule_id": str(rule["id"]),
                "why": why,
                "selectable": True,
                "state": "proposed",
            }
            if group != "guardian_set":
                line["value"] = value
                if spec.get("unit"):
                    line["unit"] = str(spec["unit"])
            else:
                line["stage"] = str(spec.get("stage") or "")
            lines.append(line)
    for f in inp.floor:
        rules = [str(r) for r in f.get("rules", [])]
        lines.append(
            {
                "line_id": line_id("SG-F-FLOOR", str(f["slug"])),
                "group": "floor",
                "kind": "floor",
                "subject": str(f["slug"]),
                "rule_id": "SG-F-FLOOR",
                "why": _why("rule", rules[0] if rules else "guardian_floor", "assignment rule"),
                "rules": rules,
                "selectable": False,
                "state": "locked",
            }
        )
    return lines[: cfg.max_lines + len(inp.floor)]


# ------------------------------------------------------------------------------ the proposal


@dataclass
class Proposal:
    system_id: str
    attempt_n: int
    outcome: str
    lines: list[dict[str, Any]]
    inputs: dict[str, Any]
    config_sha256: str
    illustrative: bool
    generated_at: str

    def counts(self) -> dict[str, int]:
        return {g: sum(1 for ln in self.lines if ln["group"] == g) for g in GROUPS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "banner": BANNER,
            "illustrative": self.illustrative,
            "system_id": self.system_id,
            "attempt_n": self.attempt_n,
            "classification_outcome": self.outcome,
            "generated_at": self.generated_at,
            "config_sha256": self.config_sha256,
            "inputs": self.inputs,
            "counts": self.counts(),
            "lines": self.lines,
        }

    def content_hash(self) -> str:
        """Hash of the lines and the inputs (not the time), so a repeat is recognised."""
        body = {"lines": self.lines, "inputs": self.inputs, "attempt_n": self.attempt_n}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def _flags_of(system: Mapping[str, Any]) -> dict[str, bool]:
    tags = _json(system.get("tags"), {})
    return {f: str(tags.get(f"ai_{f}", "0")) in ("1", "true", "True") for f in FLAGS}


def _reports_of(ctx: Any, system_id: str, attempt_n: int) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if attempt_n < 1:
        return out
    from supervisor.onboard import orchestrator as orch

    for dim in gm_dimensions():
        path = orch.report_path(ctx.settings, system_id, attempt_n, dim)
        if path is None:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[dim] = [
            {
                "finding_id": str(f.get("finding_id", "")),
                "checklist_id": str(f.get("checklist_id", "")),
                "verdict": str(f.get("verdict", "")),
                "report_id": str(doc.get("report_id", "")),
            }
            for f in doc.get("findings", [])
            if isinstance(f, Mapping)
        ]
    return out


def gm_dimensions() -> tuple[str, ...]:
    from supervisor.governance import risk_dimensions as rd

    return tuple(rd.DIMENSION_IDS)


def newest_attempt(ctx: Any, system_id: str) -> int:
    if not getattr(ctx.settings, "onboard_orchestrator", False):
        return 0
    from supervisor.onboard import orchestrator as orch

    run = orch.latest(ctx, system_id)
    return run.attempt_n if run else 0


def gather(ctx: Any, system_id: str) -> Inputs:
    from supervisor.onboard import orchestrator as orch

    system = orch.system_row(ctx, system_id)
    outcome = orch.classification_outcome(ctx, system_id)
    if outcome is None:
        raise SmartGuardianError(
            "classification_required",
            "the AI system has no approved classification; classify and approve it first",
        )
    if outcome in ("prohibited", "not_system"):
        raise SmartGuardianError("plan_blocked", f"the classification outcome is {outcome}")
    if system.get("status") == "archived":
        raise SmartGuardianError("archived", "the AI system is archived; nothing is proposed")
    facts = (
        orch.facts_for(ctx, system_id) if getattr(ctx.settings, "onboard_facts", False) else None
    )
    attempt = newest_attempt(ctx, system_id)
    dims = {
        str(r["dimension_id"]): str(r["status"])
        for r in ctx.state.query("risk_dimension_status", {"system_id": system_id})
    }
    try:
        th = {str(k): int(v) for k, v in ctx.classification_v2.tree().thresholds.items()}
    except Exception:  # noqa: BLE001 - no tree: no money lines, never a crash
        th = {}
    try:
        floor = [dict(f) for f in ctx.rules.guardian_floor(system_id)]
    except Exception:  # noqa: BLE001 - a rules file that cannot be read gives no floor
        floor = []
    return Inputs(
        system_id=system_id,
        outcome=outcome,
        autonomy_level=str(system.get("autonomy_level") or "unspecified"),
        money=bool(system.get("money_movement")),
        credit=bool(system.get("credit_decision")),
        personal_data=str(system.get("personal_data") or "none"),
        segment=str(system.get("user_segment") or "internal"),
        flags=_flags_of(system),
        dim_status=dims,
        findings=_reports_of(ctx, system_id, attempt),
        facts=list((facts or {}).get("facts") or []),
        thresholds=th,
        floor=floor,
        attempt_n=attempt,
    )


def describe(inp: Inputs) -> dict[str, Any]:
    """The inputs as the proposal shows them: counts and enums, no text."""
    return {
        "dimension_status": dict(sorted(inp.dim_status.items())),
        "flags": {f: bool(inp.flags.get(f)) for f in FLAGS},
        "autonomy_level": inp.autonomy_level,
        "money_movement": bool(inp.money),
        "credit_decision": bool(inp.credit),
        "personal_data": inp.personal_data,
        "user_segment": inp.segment,
        "facts_n": len(inp.facts),
        "findings_n": sum(len(v) for v in inp.findings.values()),
        "reports_n": len(inp.findings),
    }


def propose(ctx: Any, system_id: str, cfg: Config | None = None) -> Proposal:
    """Compute the proposal. Reads only; stores nothing."""
    ensure_on(ctx.settings)
    cfg = cfg or load_config()
    inp = gather(ctx, system_id)
    return Proposal(
        system_id=system_id,
        attempt_n=inp.attempt_n,
        outcome=inp.outcome,
        lines=evaluate(inp, cfg),
        inputs=describe(inp),
        config_sha256=cfg.sha256,
        illustrative=cfg.illustrative,
        generated_at=format_ts(ctx.clock.now()),
    )


# ------------------------------------------------------------------------------ storage


def _stamp(value: Any) -> str | None:
    return format_ts(value) if value is not None and not isinstance(value, str) else value


def row_view(row: Mapping[str, Any]) -> dict[str, Any]:
    doc = dict(_json(row.get("proposal_json"), {}))
    return {
        "proposal_id": str(row["proposal_id"]),
        "system_id": str(row["system_id"]),
        "attempt_n": int(row["attempt_n"]),
        "status": str(row["status"]),
        "proposed_at": _stamp(row.get("proposed_at")),
        "proposed_by": str(row.get("proposed_by") or ""),
        "decided_by": row.get("decided_by"),
        "decided_at": _stamp(row.get("decided_at")),
        "note": row.get("note") or "",
        "proposal": doc,
    }


def rows_of(ctx: Any, system_id: str) -> list[dict[str, Any]]:
    rows = [dict(r) for r in ctx.state.query(TABLE, {"system_id": system_id})]
    rows.sort(key=lambda r: (str(_stamp(r["proposed_at"])), str(r["proposal_id"])))
    return rows


def _save(ctx: Any, row: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return dict(
            ctx.state.update(
                TABLE, {"proposal_id": row["proposal_id"]}, dict(changes), int(row["row_version"])
            )
        )
    except ConcurrencyError:
        raise SmartGuardianError(
            "changed", "the proposal was changed by someone else; reload and try again"
        ) from None


def _chain(ctx: Any, row: Mapping[str, Any], status: str, actor: str, n_accepted: int = 0) -> None:
    sink = getattr(getattr(ctx, "runtime", None), "chain", None)
    if sink is None:
        return
    doc = _json(row.get("proposal_json"), {})
    counts = doc.get("counts") or {}
    payload = {
        "proposal_id": str(row["proposal_id"]),
        "system_id": str(row["system_id"]),
        "attempt_n": int(row["attempt_n"]),
        "status": status,
        "proposal_sha256": hashlib.sha256(
            json.dumps(doc.get("lines", []), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "n_guardian_set": int(counts.get("guardian_set", 0)),
        "n_thresholds": int(counts.get("thresholds", 0)),
        "n_autonomy_limits": int(counts.get("autonomy_limits", 0)),
        "n_floor": int(counts.get("floor", 0)),
        "n_accepted": int(n_accepted),
        "actor_ref": actor_ref(ctx.settings, actor, "system"),
        "ts": format_ts(ctx.clock.now()),
    }
    try:
        check_no_floats(payload)
        sink.record(RECORD_TYPE, f"system:{row['system_id']}", payload)
    except Exception:  # noqa: BLE001 - the row is stored; go on
        import logging

        logging.getLogger(__name__).exception("guardian_proposal chain record failed")


def supersede_stale(ctx: Any, system_id: str) -> None:
    """A proposal that is still open when a newer assessment run exists is superseded."""
    newest = newest_attempt(ctx, system_id)
    for r in rows_of(ctx, system_id):
        if r["status"] == "proposed" and int(r["attempt_n"]) < newest:
            saved = _save(ctx, r, {"status": "superseded"})
            _chain(ctx, saved, "superseded", "rule:smart_guardian")


def open_row(ctx: Any, system_id: str) -> dict[str, Any] | None:
    supersede_stale(ctx, system_id)
    rows = [r for r in rows_of(ctx, system_id) if r["status"] == "proposed"]
    return rows[-1] if rows else None


def current(ctx: Any, system_id: str) -> dict[str, Any] | None:
    """The open proposal, else the newest one of any status, else ``None``."""
    ensure_on(ctx.settings)
    op = open_row(ctx, system_id)
    if op is not None:
        return row_view(op)
    rows = rows_of(ctx, system_id)
    return row_view(rows[-1]) if rows else None


def create(ctx: Any, system_id: str, actor: str) -> dict[str, Any]:
    """Compute and store the proposal. An open proposal with the same content is returned as it
    is; an open one with other content is superseded."""
    ensure_on(ctx.settings)
    _person(actor)
    with _LOCK:
        prop = propose(ctx, system_id)
        existing = open_row(ctx, system_id)
        if existing is not None:
            old = _json(existing["proposal_json"], {})
            same = (
                Proposal(
                    system_id,
                    int(existing["attempt_n"]),
                    prop.outcome,
                    old.get("lines", []),
                    old.get("inputs", {}),
                    prop.config_sha256,
                    prop.illustrative,
                    "",
                ).content_hash()
                == prop.content_hash()
            )
            if same:
                return row_view(existing)
            saved = _save(ctx, existing, {"status": "superseded"})
            _chain(ctx, saved, "superseded", actor)
        pid = (
            "gp_"
            + hashlib.sha256(
                f"{system_id}|{prop.attempt_n}|{ctx.clock.now().isoformat()}|{prop.content_hash()}".encode()
            ).hexdigest()[:20]
        )
        row = ctx.state.insert(
            TABLE,
            {
                "proposal_id": pid,
                "system_id": system_id,
                "attempt_n": prop.attempt_n,
                "proposal_json": prop.to_dict(),
                "status": "proposed",
                "proposed_at": ctx.clock.now(),
                "proposed_by": actor,
                "decided_by": None,
                "decided_at": None,
                "note": None,
            },
        )
        _chain(ctx, row, "proposed", actor)
        return row_view(row)


def _person(actor: str) -> None:
    if not isinstance(actor, str) or not actor:
        raise SmartGuardianError("actor_required", "a signed-in person is needed")


def clean_note(value: Any, minimum: int = 0, what: str = "note") -> str:
    from supervisor.governance.triage import scrub

    text = value.strip() if isinstance(value, str) else ""
    if len(text) < minimum:
        raise SmartGuardianError(
            "reason_too_short", f"the {what} needs at least {minimum} characters"
        )
    if len(text) > MAX_NOTE:
        raise SmartGuardianError(
            "note_too_long", f"the {what} is longer than {MAX_NOTE} characters"
        )
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise SmartGuardianError("bad_text", f"the {what} has control characters")
    return scrub(text)


def _need_open(ctx: Any, system_id: str, proposal_id: str | None) -> dict[str, Any]:
    from supervisor.governance.model import check_system_id

    check_system_id(system_id)
    if ctx.state.get("ai_system", {"system_id": system_id}) is None:
        raise NotFoundError(f"AI system {system_id} does not exist")
    row = open_row(ctx, system_id)
    if row is None:
        raise SmartGuardianError(
            "no_open_proposal",
            "there is no open proposal; make one first (or a new run replaced it)",
        )
    if proposal_id and proposal_id != row["proposal_id"]:
        raise SmartGuardianError("changed", "the proposal was replaced; reload the page")
    return row


def reject(
    ctx: Any, system_id: str, actor: str, reason: Any, proposal_id: str | None = None
) -> dict[str, Any]:
    ensure_on(ctx.settings)
    _person(actor)
    note = clean_note(reason, MIN_REASON, "reason")
    with _LOCK:
        row = _need_open(ctx, system_id, proposal_id)
        saved = _save(
            ctx,
            row,
            {
                "status": "rejected",
                "decided_by": actor,
                "decided_at": ctx.clock.now(),
                "note": note,
            },
        )
        _chain(ctx, saved, "rejected", actor)
        return row_view(saved)


# ------------------------------------------------------------------------------ accept


def accept(
    ctx: Any,
    system_id: str,
    actor: str,
    line_ids: Any,
    note: Any = None,
    proposal_id: str | None = None,
) -> dict[str, Any]:
    """Accept the chosen lines. The bindings go through ``GuardianService`` (the floor and the
    off-request rule stay), the monitor thresholds into ``policy_threshold`` and the autonomy
    limits into the system tag ``autonomy_limits``. A line the service refuses is listed in
    ``decision.results`` with its message; the others still apply."""
    ensure_on(ctx.settings)
    _person(actor)
    text = clean_note(note, 0) if note else ""
    if not isinstance(line_ids, list) or not line_ids:
        raise SmartGuardianError("no_lines", "choose at least one line to accept")
    with _LOCK:
        row = _need_open(ctx, system_id, proposal_id)
        doc = dict(_json(row["proposal_json"], {}))
        by_id = {ln["line_id"]: ln for ln in doc.get("lines", [])}
        chosen: list[dict[str, Any]] = []
        for lid in dict.fromkeys(str(x) for x in line_ids):
            ln = by_id.get(lid)
            if ln is None:
                raise SmartGuardianError("unknown_line", f"line {lid[:40]} is not in the proposal")
            if not ln.get("selectable"):
                raise SmartGuardianError(
                    "floor_line",
                    f"{ln['subject']} is in the guardian floor; it is always on and not accepted",
                )
            chosen.append(ln)
        if any(ln["group"] == "guardian_set" for ln in chosen):
            from supervisor.governance.guardians import ensure_bindings_on

            ensure_bindings_on(ctx.settings)  # 400 bindings_off before anything is written
        claimed = _save(
            ctx,
            row,
            {
                "status": "accepted",
                "decided_by": actor,
                "decided_at": ctx.clock.now(),
                "note": text or None,
            },
        )
        results = _apply(ctx, system_id, actor, chosen)
        ids = {ln["line_id"] for ln in chosen}
        for ln in doc.get("lines", []):
            if ln["line_id"] in ids:
                ln["state"] = "accepted"
            elif ln.get("selectable"):
                ln["state"] = "not_accepted"
        doc["decision"] = {
            "decided_by": actor,
            "accepted": sorted(ids),
            "results": results["results"],
            "detector_overrides": results["detector_overrides"],
            "policy_snippet": results["policy_snippet"],
            "next": "run_predeploy",
        }
        saved = _save(ctx, claimed, {"proposal_json": doc})
        _chain(ctx, saved, "accepted", actor, n_accepted=len(ids))
        return row_view(saved)


def _agents_of(ctx: Any, system_id: str) -> list[str]:
    comps = ctx.state.query("system_component", {"system_id": system_id})
    return sorted({str(c["ref_id"]) for c in comps if c["ref_kind"] == "agent"})


def _apply(
    ctx: Any, system_id: str, actor: str, lines: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    overrides: dict[str, dict[str, dict[str, Any]]] = {}
    limits: dict[str, Any] = {}
    agents = _agents_of(ctx, system_id)
    for ln in lines:
        rec: dict[str, Any] = {
            "line_id": ln["line_id"],
            "subject": ln["subject"],
            "group": ln["group"],
        }
        try:
            if ln["group"] == "guardian_set":
                got = ctx.guardians.set(system_id, ln["subject"], "on", actor)
                rec["result"] = "applied" if got.get("state") == "on" else "refused"
                rec["instance_on"] = bool(got.get("instance_on"))
            elif ln.get("kind") == "monitor_threshold":
                if not agents:
                    rec["result"] = "skipped"
                    rec["message"] = "no agent is linked to the system"
                else:
                    for a in agents:
                        _put_threshold(ctx, a, ln, actor)
                    rec["result"] = "applied"
                    rec["agents_n"] = len(agents)
            elif ln.get("kind") == "detector_setting":
                slug, _, setting = str(ln["subject"]).partition(".")
                for a in agents or ["*"]:
                    overrides.setdefault(a, {}).setdefault(slug, {})[setting] = ln["value"]
                rec["result"] = "recorded"
            else:  # autonomy_limits
                limits[str(ln["subject"])] = ln["value"]
                rec["result"] = "applied"
        except SupervisorError as exc:
            rec["result"] = "refused"
            rec["message"] = str(exc)[:300]
        results.append(rec)
    if limits:
        _write_limits(ctx, system_id, actor, limits, results)
    return {
        "results": results,
        "detector_overrides": overrides,
        "policy_snippet": _snippet(overrides),
    }


def _put_threshold(ctx: Any, agent: str, ln: Mapping[str, Any], actor: str) -> None:
    key = {"agent_id": agent, "metric": str(ln["subject"])}
    fields = {
        "threshold": int(ln["value"]),
        "unit": str(ln.get("unit") or "count"),
        "owner": actor,
        "note": f"smart guardian {ln['rule_id']}",
        "effective_from": ctx.clock.now(),
    }
    cur = ctx.state.get("policy_threshold", key)
    if cur is None:
        ctx.state.insert("policy_threshold", {**key, **fields})
    else:
        ctx.state.update("policy_threshold", key, fields, cur["row_version"])


def _write_limits(
    ctx: Any, system_id: str, actor: str, limits: Mapping[str, Any], results: list[dict[str, Any]]
) -> None:
    system = ctx.systems.get(system_id)
    tags = {str(k): str(v) for k, v in dict(system.get("tags") or {}).items()}
    old = _json(tags.get("autonomy_limits"), {})
    merged = {**(old if isinstance(old, dict) else {}), **limits}
    tags["autonomy_limits"] = json.dumps(merged, sort_keys=True, separators=(",", ":"))
    try:
        ctx.systems.update_fields(system_id, {"tags": tags}, actor)
    except SupervisorError as exc:
        for r in results:
            if r["group"] == "autonomy_limits":
                r["result"] = "refused"
                r["message"] = str(exc)[:300]


def _snippet(overrides: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> str:
    """The ``agents.<id>.detectors.settings`` block of the policy file, as text for a PR."""
    if not overrides:
        return ""
    doc = {
        "agents": {
            a: {"detectors": {"settings": {s: dict(v) for s, v in per.items()}}}
            for a, per in sorted(overrides.items())
        }
    }
    return yaml.safe_dump(doc, sort_keys=True, default_flow_style=False)


__all__ = [
    "Config",
    "Inputs",
    "Proposal",
    "SmartGuardianError",
    "accept",
    "create",
    "current",
    "enabled",
    "ensure_on",
    "evaluate",
    "load_config",
    "propose",
    "reject",
]
