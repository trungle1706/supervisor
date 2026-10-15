"""Change control for the tiered judge (WP19): validation gate and re-validation triggers.

Validation gate (``JUDGE_REQUIRE_VALIDATION``, default off)
    ``JudgeService.from_settings`` calls :func:`check_validation_gate` when the setting is on.
    The judge refuses to start (``JudgeNotValidatedError``) unless the ``model_validation``
    table holds a passing record for the current identity (model version, prompt hash,
    rubric version). When the setting is off nothing here runs and no table is read.

    A refused judge means "judge not running": the callers log it and carry on. The agents
    keep running under the deterministic rules. The gate, the pause switch and every agent's
    ``gate_state`` are never touched (judges advise; only rules and humans block or pause).

Re-validation triggers (``python -m supervisor.judge.mrm triggers [--json]``)
    Compare the current identity with the latest ``model_validation`` row (any decision):
    ``prompt_changed``, ``model_version_changed``, ``rubric_changed``, ``golden_set_changed``,
    ``agreement_below_threshold`` and ``new_agent_class_onboarded``. With no row at all the
    single trigger ``never_validated`` fires. Exit code: 0 none fired, 1 any fired, 2 error.
"""

# ruff: noqa: T201 - CLI output

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from supervisor.config import Settings
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import Masker, TableStore
from supervisor.judge.masking import IdentityMasker, mask_version_of
from supervisor.judge.mrm import identity as ident_mod
from supervisor.judge.mrm.identity import JudgeIdentity

VALIDATE_CMD = "python -m supervisor.judge.mrm validate"
TRIGGER_IDS = (
    "never_validated",
    "prompt_changed",
    "model_version_changed",
    "rubric_changed",
    "golden_set_changed",
    "agreement_below_threshold",
    "new_agent_class_onboarded",
)


class JudgeNotValidatedError(SupervisorError):
    """JUDGE_REQUIRE_VALIDATION is on and there is no passing validation for this judge."""


# --------------------------------------------------------------------------- identity


def current_identity(
    service_or_router: Any, settings: Settings, masker: Masker | None = None
) -> JudgeIdentity:
    """Identity of a ``JudgeService`` (its router, masker and thresholds) or a ``JudgeRouter``."""
    router = getattr(service_or_router, "router", service_or_router)
    if masker is None:
        masker = getattr(service_or_router, "masker", None) or IdentityMasker()
    return ident_mod.identity_from_router(
        router,
        t1_threshold_bp=settings.judge_t1_threshold_bp,
        t2_threshold_bp=settings.judge_t2_threshold_bp,
        mask_version=mask_version_of(masker),
    )


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _validations(tables: TableStore) -> list[dict[str, Any]]:
    rows = [dict(r) for r in tables.query("model_validation")]
    rows.sort(key=lambda r: _ts(r["ts"]))
    return rows


def latest_validation(tables: TableStore, ident: JudgeIdentity) -> dict[str, Any] | None:
    """Latest passing ``model_validation`` row for this identity, else None."""
    ok = [r for r in _validations(tables) if ident_mod.matches(r, ident)]
    return ok[-1] if ok else None


def require_validation(tables: TableStore, ident: JudgeIdentity) -> dict[str, Any]:
    rec = latest_validation(tables, ident)
    if rec is None:
        raise JudgeNotValidatedError(
            f"judge not validated: no passing model_validation record for model_version "
            f"{ident.model_version!r}, prompt_hash {ident.prompt_hash[:16]}..., rubric "
            f"{ident.rubric_version!r}. Run: {VALIDATE_CMD}. The judge is not running; "
            "agents continue under the deterministic rules."
        )
    return rec


def check_validation_gate(service: Any, settings: Settings, tables: TableStore | None) -> None:
    """Called by ``JudgeService.from_settings`` when ``judge_require_validation`` is on."""
    if tables is None:
        raise JudgeNotValidatedError(
            "JUDGE_REQUIRE_VALIDATION needs the store to look up model_validation records"
        )
    require_validation(tables, current_identity(service, settings))


# --------------------------------------------------------------------------- triggers


def _trig(tid: str, fired: bool, detail: str) -> dict[str, Any]:
    return {"id": tid, "fired": bool(fired), "detail": detail}


def _short(text: Any) -> str:
    s = str(text)
    return s if len(s) <= 24 else s[:21] + "..."


def _differs(tid: str, label: str, now: Any, then: Any) -> dict[str, Any]:
    if str(now) == str(then):
        return _trig(tid, False, f"{label} unchanged since the last validation")
    return _trig(tid, True, f"{label} changed: validated {_short(then)}, now {_short(now)}")


def _agreement_trigger(settings: Settings, tables: TableStore, since: datetime) -> dict[str, Any]:
    from supervisor.judge.mrm.agreement import agreement_summary

    tid = "agreement_below_threshold"
    min_bp, min_pairs = settings.mrm_min_agreement_bp, settings.mrm_min_agreement_pairs
    day0 = since.replace(hour=0, minute=0, second=0, microsecond=0)
    bad: list[str] = []
    for r in tables.query("oversight_metric"):
        pairs, bp = r.get("judge_human_pairs"), r.get("judge_human_agree_bp")
        if pairs is None or bp is None:
            continue
        if _ts(str(r["metric_date"])[:10] + "T00:00:00+00:00") < day0:
            continue
        if int(pairs) >= min_pairs and int(bp) < min_bp:
            bad.append(
                f"{str(r['metric_date'])[:10]} {r['agent_id']} {int(bp)} bp/{int(pairs)} pairs"
            )
    summ = agreement_summary(tables, since=since, min_pairs=min_pairs)
    if summ["status"] == "ok" and summ["agree_bp"] < min_bp:
        bad.append(f"period {summ['agree_bp']} bp/{summ['pairs']} pairs")
    if bad:
        return _trig(tid, True, f"below {min_bp} bp (min {min_pairs} pairs): " + "; ".join(bad))
    return _trig(
        tid, False, f"{summ['pairs']} pair(s) since the last validation; threshold {min_bp} bp"
    )


def _class_of(agent: Mapping[str, Any]) -> tuple[str, str]:
    return (str(agent.get("risk_tier")), str(agent.get("decision33_class")))


def _new_class_trigger(tables: TableStore, since: datetime) -> dict[str, Any]:
    tid = "new_agent_class_onboarded"
    agents = tables.query("agent")
    old = {_class_of(a) for a in agents if _ts(a["created_at"]) <= since}
    new: dict[tuple[str, str], list[str]] = {}
    for a in agents:
        if _ts(a["created_at"]) > since and _class_of(a) not in old:
            new.setdefault(_class_of(a), []).append(str(a["agent_id"]))
    if not new:
        return _trig(tid, False, "no agent of a new (risk_tier, decision33_class) since then")
    parts = [
        f"(risk_tier={c[0]}, decision33_class={c[1]}): {', '.join(sorted(ids))}"
        for c, ids in sorted(new.items())
    ]
    return _trig(tid, True, "new agent class: " + "; ".join(parts))


PERIODIC_DAYS = 365


def fired_triggers(
    settings: Settings,
    tables: TableStore,
    *,
    router: Any = None,
    now: datetime | None = None,
    masker: Masker | None = None,
) -> dict[str, Any]:
    """``{"checked_at", "last_validation", "triggers": [{id, fired, detail}], "fired": n}``."""
    from supervisor.judge.router import JudgeRouter

    now = now or datetime.now(UTC)
    rows = _validations(tables)
    if not rows:
        trig = [_trig("never_validated", True, f"no model_validation record. Run: {VALIDATE_CMD}")]
        last = None
    else:
        router = router or JudgeRouter.from_settings(settings, tables=tables)
        ident = current_identity(router, settings, masker)
        last = rows[-1]
        since = _ts(last["ts"])
        trig = [
            _differs("prompt_changed", "prompt hash", ident.prompt_hash, last.get("prompt_hash")),
            _differs(
                "model_version_changed",
                "model version",
                ident.model_version,
                last.get("model_version"),
            ),
            _differs("rubric_changed", "rubric", ident.rubric_version, last.get("rubric_version")),
            _differs(
                "golden_set_changed",
                "golden set hash",
                ident.golden_set_hash,
                last.get("golden_set_hash"),
            ),
            _agreement_trigger(settings, tables, since),
            _new_class_trigger(tables, since),
            # Circular 53 Art. 16(2): test at least yearly (also after a serious incident,
            # which a human decides; see docs/judge-mrm.md).
            _trig(
                "periodic_revalidation_due",
                now - since > timedelta(days=PERIODIC_DAYS),
                f"last validation {since.date().isoformat()}; yearly re-test "
                f"(>{PERIODIC_DAYS} days) per Circular 53 Art. 16(2)",
            ),
        ]
    return {
        "checked_at": now.isoformat(),
        "last_validation": None
        if last is None
        else {
            "validation_id": last.get("validation_id"),
            "ts": _ts(last["ts"]).isoformat(),
            "decision": last.get("decision"),
        },
        "triggers": trig,
        "fired": sum(1 for t in trig if t["fired"]),
    }


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.judge.mrm triggers")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        from supervisor.adapters.factory import build_adapters
        from supervisor.config import load_settings
        from supervisor.jobs import bootstrap_schema

        settings = load_settings()
        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                bootstrap_schema.run(settings, adapters)
            result = fired_triggers(settings, adapters.tables)
        finally:
            adapters.close()
    except Exception as exc:  # noqa: BLE001 - any failure is exit 2, never a traceback
        print(_ascii(f"[FAIL] triggers: {type(exc).__name__}: {exc}"))
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for t in result["triggers"]:
            print(_ascii(f"[{'FIRED' if t['fired'] else 'OK'}] {t['id']}: {t['detail']}"))
        n = result["fired"]
        if n:
            print(_ascii(f"[FIRED] {n} trigger(s) fired: re-validate with {VALIDATE_CMD}"))
        else:
            print("[OK] no re-validation trigger fired")
    return 1 if result["fired"] else 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "JudgeNotValidatedError",
    "check_validation_gate",
    "current_identity",
    "fired_triggers",
    "latest_validation",
    "main",
    "require_validation",
]
