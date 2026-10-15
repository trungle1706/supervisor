"""Gates built on assurance results (WP17): Launch NO-GO items and judge enablement.

Both are deterministic: the same inputs give the same list, in the same order.

Launch (``assurance_launch_items``)
    For every result of a pack whose manifest says ``launch_gate: required``:
    ``fail`` -> one reason per failing metric (``assurance pack <id> failed: <metric>
    <value> vs no-go <no_go>``); ``error`` -> ``assurance pack <id> errored: <reason>``;
    ``skip`` -> ``assurance pack <id> skipped (required): <reason>`` (never a silent
    pass), except a skip because the target lacks a capability the pack needs (reason
    contains ``lacks capability``, e.g. a credit-decision pack on a payments agent): the
    pack does not apply to that agent, so it is a note, not a NO-GO. ``warn`` results
    and packs with ``advisory`` or ``off`` never give NO-GO; they
    are returned by ``assurance_launch_notes``.

Judge enablement (``judge_enablement_problems``)
    A non-mock judge may run only when each pack with ``judge_gate: true`` has a latest
    stored ``eval_result`` row, status ``ok`` or ``warn``, not from a mock run, for the
    manifest's current ``version``. Match rule: the row's ``target_kind`` is ``judge`` and
    its ``target_id`` is ``judge:<model_id of the tier-1 primary judge>`` (the id the
    judge targets in ``assurance.targets`` use). Mock judges are exempt (phase-1
    behaviour, labelled mock).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.assurance.loader import PACKS_DIR, load_packs
from supervisor.assurance.model import EvalPack, PackResult
from supervisor.assurance.results import latest_results
from supervisor.core.errors import ConfigError

OK_STATUSES = ("ok", "warn")
NOT_APPLICABLE_MARK = "lacks capability"


def not_applicable(d: Mapping[str, Any]) -> bool:
    """A skip that means 'this pack does not apply to this target' (not 'no data')."""
    return d.get("status") == "skip" and any(NOT_APPLICABLE_MARK in r for r in d["reasons"])


class JudgeNotValidatedError(ConfigError):
    """A non-mock judge was asked to run without passing its judge packs."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__(
            "judge not enabled: its validation packs are missing or failed: "
            + "; ".join(self.problems)
        )


def _row(r: PackResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(r, Mapping):
        d = dict(r)
    else:
        d = {
            "pack_id": r.pack_id,
            "status": r.status,
            "metrics": dict(r.metrics),
            "metric_status": dict(r.metric_status),
            "reasons": list(r.reasons),
            "target_id": r.target_id,
        }
    reasons = d.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [x for x in reasons.split("; ") if x]
    d["reasons"] = [str(x) for x in reasons]
    return d


def _sort_key(d: Mapping[str, Any]) -> tuple[str, str]:
    return str(d.get("pack_id")), str(d.get("target_id", ""))


def assurance_launch_items(
    results: Sequence[PackResult | Mapping[str, Any]], packs: Sequence[EvalPack]
) -> list[str]:
    """NO-GO reasons from results of packs with ``launch_gate: required`` (see module doc)."""
    by_id = {p.id: p for p in packs}
    out: list[str] = []
    for d in sorted((_row(r) for r in results), key=_sort_key):
        pack = by_id.get(str(d.get("pack_id")))
        if pack is None or pack.launch_gate != "required":
            continue
        status = d.get("status")
        reasons = d["reasons"]
        if status == "fail":
            failing = [
                m.name for m in pack.metrics if (d.get("metric_status") or {}).get(m.name) == "fail"
            ]
            lines = []
            for name in failing:
                thr = pack.threshold(name)
                no_go = thr.no_go if thr else "-"
                lines.append(
                    f"assurance pack {pack.id} failed: {name} "
                    f"{(d.get('metrics') or {}).get(name)} vs no-go {no_go}"
                )
            out += lines or [
                f"assurance pack {pack.id} failed: {'; '.join(reasons) or 'no reason'}"
            ]
        elif status == "error":
            out.append(f"assurance pack {pack.id} errored: {reasons[0] if reasons else 'error'}")
        elif status == "skip" and not not_applicable(d):
            why = reasons[0] if reasons else "skipped"
            out.append(f"assurance pack {pack.id} skipped (required): {why}")
    return list(dict.fromkeys(out))


def assurance_launch_notes(
    results: Sequence[PackResult | Mapping[str, Any]], packs: Sequence[EvalPack]
) -> list[str]:
    """Findings that do not block Launch: warn on a required pack, any problem on an
    advisory pack. Listed in the report, never a NO-GO reason."""
    by_id = {p.id: p for p in packs}
    out: list[str] = []
    for d in sorted((_row(r) for r in results), key=_sort_key):
        pack = by_id.get(str(d.get("pack_id")))
        status = d.get("status")
        if pack is None or pack.launch_gate == "off" or status in ("ok", None):
            continue
        if pack.launch_gate == "required" and status != "warn" and not not_applicable(d):
            continue
        why = d["reasons"][0] if d["reasons"] else ""
        out.append(f"assurance pack {pack.id} ({pack.launch_gate}): {status} {why}".rstrip())
    return list(dict.fromkeys(out))


def judge_target_id(router: Any) -> str:
    """The target id that judge validation results carry for this router."""
    return f"judge:{router.t1.model_id}"


def judge_enablement_problems(
    tables: Any, router: Any, packs: Sequence[EvalPack] | None = None
) -> list[str]:
    """Why a non-mock judge may not run yet; ``[]`` when it may (see module doc)."""
    if router.t1.is_mock and router.t2.is_mock:
        return []  # mock judges are exempt and stay labelled mock
    gated = [p for p in (packs if packs is not None else load_packs(PACKS_DIR)) if p.judge_gate]
    if not gated:
        return []
    target_id = judge_target_id(router)
    if tables is None:
        return [f"no table store: cannot read the validation results of {target_id}"]
    rows = {r["pack_id"]: r for r in latest_results(tables, "judge", target_id)}
    problems: list[str] = []
    for pack in gated:
        row = rows.get(pack.id)
        run_hint = (
            f"run: python -m supervisor.assurance run {pack.id} --target judge --judge settings"
        )
        if row is None:
            problems.append(f"pack {pack.id}: no result for {target_id} ({run_hint})")
        elif row.get("status") not in OK_STATUSES:
            problems.append(
                f"pack {pack.id}: latest status is {row.get('status')} (needs ok or warn)"
            )
        elif int(row.get("pack_version") or 0) != pack.version:
            problems.append(
                f"pack {pack.id}: result is for version {row.get('pack_version')}, "
                f"the manifest is version {pack.version} ({run_hint})"
            )
        elif row.get("is_mock"):
            problems.append(f"pack {pack.id}: the result is from a mock run, not this judge")
    return problems


def require_judge_validated(
    tables: Any, router: Any, packs: Sequence[EvalPack] | None = None
) -> None:
    problems = judge_enablement_problems(tables, router, packs)
    if problems:
        raise JudgeNotValidatedError(problems)


__all__ = [
    "JudgeNotValidatedError",
    "assurance_launch_items",
    "assurance_launch_notes",
    "judge_enablement_problems",
    "judge_target_id",
    "require_judge_validated",
]
