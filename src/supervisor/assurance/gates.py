"""Gates built on assurance results (WP17): Launch NO-GO items and judge enablement.

Both are deterministic: the same inputs give the same list, in the same order.

Launch (``assurance_launch_items``)
    For every result of a pack whose manifest says ``launch_gate: required``:
    ``fail`` -> one reason per failing metric (``assurance pack <id> failed: <metric>
    <value> vs no-go <no_go>``); ``error`` -> ``assurance pack <id> errored: <reason>``;
    ``skip`` -> ``assurance pack <id> skipped (required): <reason>`` (never a silent
    pass), except a structured not-applicable skip (``details.not_applicable`` true, set
    by the engine when the target lacks a capability in the pack's ``requires_capabilities``,
    e.g. a credit-decision pack on a payments agent): that is a note, not a NO-GO. Every
    other skip stays NO-GO. With ``expect_target_kind``, a required pack for that kind with
    no result at all gives ``assurance pack <id> has no result (required)``. ``warn``
    results and packs with ``advisory`` or ``off`` never give NO-GO; they are returned by
    ``assurance_launch_notes``.

Mock results (``assurance_mock_state``, ``assurance_mock_items``; W3-assure M1)
    A result with ``is_mock`` comes from a mock model or the mock demo target. If ANY result
    of a run is mock, the Launch reason and the assurance report are labelled MOCK. If every
    evaluated result (status ok, warn or fail; skip and error evaluated nothing) is mock
    ("mock only"), Launch also gets the NO-GO item ``assurance results are mock only``
    unless ``ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH`` is on. A mixed run (some mock, some real)
    keeps the label but gets no such item: its real results carry the decision. A run with
    no evaluated result gets no item here (skips already block through the pack rules).

Judge enablement (``judge_enablement_problems``)
    A non-mock judge may run only when EACH non-mock primary judge (tier 1 and tier 2; the
    ids come from ``judge_gate_targets``) passes every pack with ``judge_gate: true``. For
    each of those judges and packs the latest stored ``eval_result`` row with
    ``target_kind = judge`` and ``target_id = judge:<that model id>`` (the id the judge
    targets in ``assurance.targets`` use) must be:

    * for the manifest's current ``version`` and current manifest hash (a threshold edit
      without a version bump invalidates an old pass);
    * not from a mock run (``is_mock`` false);
    * status ``ok``; ``warn`` counts only when ``ASSURANCE_JUDGE_ALLOW_WARN=1``;
    * ``n_items >= ASSURANCE_JUDGE_MIN_ITEMS`` (default 50): a pass on a handful of items
      is not a validation;
    * ``data_mode`` one of ``synthetic``, ``bank_supplied_path``, ``vendored_sample`` (the
      modes a runner records). A mock is not a data mode (mock runs carry ``is_mock``), so
      the rule is: non-mock row AND a recorded real data mode; an empty or unknown mode
      (e.g. a row that never read a dataset) does not validate. Synthetic data is accepted
      because it is the shipped offline path, but it is labelled in the docs as weaker
      evidence than ``bank_supplied_path``.

    A mock primary judge is exempt and stays labelled mock; a mixed setup (real t1 + mock t2)
    gates only the real model. If t1 and t2 share one model id it is checked once. The
    refusal message names every model id checked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.assurance.loader import PACKS_DIR, load_packs, manifest_sha256, pack_path
from supervisor.assurance.model import EvalPack, PackResult
from supervisor.assurance.results import latest_results
from supervisor.config import load_settings
from supervisor.core.errors import ConfigError

OK_STATUSES = ("ok", "warn")


def not_applicable(d: Mapping[str, Any]) -> bool:
    """A skip that the engine marked 'this pack does not apply to this target'."""
    if d.get("status") != "skip":
        return False
    details = d.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return False
    return isinstance(details, Mapping) and details.get("not_applicable") is True


class JudgeNotValidatedError(ConfigError):
    """A non-mock judge was asked to run without passing its judge packs."""

    def __init__(self, problems: Sequence[str], checked: Sequence[str] = ()) -> None:
        self.problems = list(problems)
        self.checked = list(checked)
        super().__init__(
            "judge not enabled: its validation packs are missing or failed: "
            + "; ".join(self.problems)
            + (f" [checked: {', '.join(self.checked)}]" if self.checked else "")
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
            "details": dict(r.details),
        }
    reasons = d.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [x for x in reasons.split("; ") if x]
    d["reasons"] = [str(x) for x in reasons]
    return d


def _sort_key(d: Mapping[str, Any]) -> tuple[str, str]:
    return str(d.get("pack_id")), str(d.get("target_id", ""))


def assurance_launch_items(
    results: Sequence[PackResult | Mapping[str, Any]],
    packs: Sequence[EvalPack],
    *,
    expect_target_kind: str | None = None,
) -> list[str]:
    """NO-GO reasons from results of packs with ``launch_gate: required`` (see module doc)."""
    by_id = {p.id: p for p in packs}
    out: list[str] = []
    if expect_target_kind is not None:
        have = {str(_row(r).get("pack_id")) for r in results}
        out += [
            f"assurance pack {p.id} has no result (required)"
            for p in sorted(packs, key=lambda p: p.id)
            if p.launch_gate == "required" and expect_target_kind in p.targets and p.id not in have
        ]
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


MOCK_ONLY_ITEM = "assurance results are mock only"
EVALUATED = ("ok", "warn", "fail")


def assurance_mock_state(results: Sequence[PackResult | Mapping[str, Any]]) -> str:
    """``"none"`` (no mock result), ``"mixed"`` (some mock) or ``"all"`` (mock only: at least
    one evaluated result and every evaluated result is mock)."""
    rows = [_row(r) for r in results]
    if not any(r.get("is_mock") for r in rows):
        return "none"
    evaluated = [r for r in rows if r.get("status") in EVALUATED]
    if evaluated and all(r.get("is_mock") for r in evaluated):
        return "all"
    return "mixed"


def assurance_mock_items(
    results: Sequence[PackResult | Mapping[str, Any]], *, accept_mock: bool
) -> list[str]:
    """The mock-only NO-GO item (see module doc); ``[]`` when real results exist or
    ``accept_mock`` (setting ``ASSURANCE_ACCEPT_MOCK_FOR_LAUNCH``) is on."""
    if not accept_mock and assurance_mock_state(results) == "all":
        return [MOCK_ONLY_ITEM]
    return []


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


REAL_DATA_MODES = ("synthetic", "bank_supplied_path", "vendored_sample")


def judge_target_id(router: Any) -> str:
    """The target id that judge validation results carry for the tier-1 judge."""
    return f"judge:{router.t1.model_id}"


def judge_gate_targets(router: Any) -> list[str]:
    """Target ids (``judge:<model_id>``) of the non-mock primary judges, t1 then t2, once each."""
    out: list[str] = []
    for model in (router.t1, router.t2):
        if not model.is_mock and f"judge:{model.model_id}" not in out:
            out.append(f"judge:{model.model_id}")
    return out


def judge_enablement_problems(
    tables: Any,
    router: Any,
    packs: Sequence[EvalPack] | None = None,
    *,
    min_items: int | None = None,
    allow_warn: bool | None = None,
) -> list[str]:
    """Why a non-mock judge may not run yet; ``[]`` when it may (see module doc).
    ``min_items`` / ``allow_warn`` default to the settings."""
    targets = judge_gate_targets(router)
    if not targets:
        return []  # mock judges are exempt and stay labelled mock
    gated = [p for p in (packs if packs is not None else load_packs(PACKS_DIR)) if p.judge_gate]
    if not gated:
        return []
    if min_items is None or allow_warn is None:
        settings = load_settings()
        min_items = settings.assurance_judge_min_items if min_items is None else min_items
        allow_warn = settings.assurance_judge_allow_warn if allow_warn is None else allow_warn
    if tables is None:
        return [f"no table store: cannot read the validation results of {', '.join(targets)}"]
    ok_statuses = OK_STATUSES if allow_warn else ("ok",)
    problems: list[str] = []
    for target_id in targets:
        rows = {r["pack_id"]: r for r in latest_results(tables, "judge", target_id)}
        for pack in gated:
            problems += _pack_problems(
                pack, rows.get(pack.id), target_id, ok_statuses, min_items, allow_warn
            )
    return problems


def _pack_problems(
    pack: EvalPack,
    row: Mapping[str, Any] | None,
    target_id: str,
    ok_statuses: Sequence[str],
    min_items: int,
    allow_warn: bool,
) -> list[str]:
    run_hint = f"run: python -m supervisor.assurance run {pack.id} --target judge --judge settings"
    who = f"pack {pack.id} for {target_id}"
    if row is None:
        return [f"{who}: no result ({run_hint})"]
    status = row.get("status")
    if status not in ok_statuses:
        needs = "ok or warn" if allow_warn else "ok; warn needs ASSURANCE_JUDGE_ALLOW_WARN=1"
        return [f"{who}: latest status is {status} (needs {needs})"]
    if int(row.get("pack_version") or 0) != pack.version:
        return [
            f"{who}: result is for version {row.get('pack_version')}, "
            f"the manifest is version {pack.version} ({run_hint})"
        ]
    if row.get("manifest_sha256") != _current_manifest_hash(pack):
        return [
            f"{who}: the manifest changed since this result (thresholds or "
            f"metrics edited); run it again ({run_hint})"
        ]
    if row.get("is_mock"):
        return [f"{who}: the result is from a mock run, not this judge"]
    if row.get("data_mode") not in REAL_DATA_MODES:
        return [
            f"{who}: data mode {row.get('data_mode') or 'none'!r} is not a validation "
            f"dataset (needs one of {', '.join(REAL_DATA_MODES)})"
        ]
    n_items = int(row.get("n_items") or 0)
    if n_items < min_items:
        return [
            f"{who}: only {n_items} item(s), the gate needs at least {min_items} "
            f"(ASSURANCE_JUDGE_MIN_ITEMS) ({run_hint})"
        ]
    return []


def _current_manifest_hash(pack: EvalPack) -> str | None:
    path = pack_path(pack.id)
    return manifest_sha256(path) if path.is_file() else None


def require_judge_validated(
    tables: Any, router: Any, packs: Sequence[EvalPack] | None = None
) -> None:
    problems = judge_enablement_problems(tables, router, packs)
    if problems:
        raise JudgeNotValidatedError(problems, judge_gate_targets(router))


__all__ = [
    "JudgeNotValidatedError",
    "assurance_launch_items",
    "assurance_launch_notes",
    "assurance_mock_items",
    "assurance_mock_state",
    "judge_enablement_problems",
    "judge_gate_targets",
    "judge_target_id",
    "require_judge_validated",
]
