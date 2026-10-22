"""Register wizard of the AI system (WP-UX4b): ``/console/systems/new``.

Two steps and one result page:

1. the intake form (the fields of WP-G0, ``autonomy_level`` when the column exists, and an
   optional repository folder);
2. the **preliminary checks**, run in this process and read only: the integration readiness
   advisor (``docs/INTEGRATION_GUIDE.md`` section 6) when a folder is given, the assurance packs
   that apply to the declared system, the Decision 33 class proposal and the mandatory guardian
   floor. The result page shows them all; **nothing is applied**. A button then registers the
   system as a draft and opens the initiation tasks.

Scoping rules are applied before anything runs: a scoped person registers for themselves and
only for a team they already work in. A bad input is HTTP 400 with the reason. Nothing is
invented: a figure that cannot be computed is ``None`` with a reason key.

WP-G2 (rules engine, Decision 33 classification, ``autonomy_level``) merges in parallel. Every
use of it is guarded with ``getattr`` or ``try`` so the wizard works with or without it."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping
from typing import Any

from supervisor.console import systems_views
from supervisor.console.listing import ListingError
from supervisor.core import rbac
from supervisor.governance import model as gm
from supervisor.governance.systems import ALL

log = logging.getLogger("supervisor.console")

MAX_PATH = 512
# docs/INTEGRATION_GUIDE.md section 6: the bands of the readiness score (advice, not approval)
BANDS: tuple[tuple[int, str], ...] = (
    (80, "ux4b_band_ready"),
    (50, "ux4b_band_patches"),
    (0, "ux4b_band_work"),
)
# Declared fields -> assurance dimensions. The rows of INTEGRATION_GUIDE section 7, decided from
# the declared system instead of a code scan. Pack dimension names (assurance/model.py).
DIMENSIONS: tuple[str, ...] = (
    "accuracy",
    "hallucination",
    "bias_fairness",
    "dependency",
    "security",
    "robustness",
)
TASKS: tuple[tuple[str, str], ...] = (
    ("SYS-INTAKE-CONFIRM", "Confirm the intake answers of the new system"),
    ("SYS-INTAKE-CHECKS", "Review the preliminary checks and the classification proposal"),
)
TASK_DUE_DAYS = 14


# ---------------------------------------------------------------------------- the form


def autonomy_choices() -> tuple[str, ...]:
    """Autonomy levels the form offers: only when WP-G2 made ``autonomy_level`` an editable
    field. The vocabulary is the one of the onboarding profile (``onboard.autonomy.LEVELS``)."""
    if "autonomy_level" not in getattr(gm, "EDITABLE", ()):  # WP-G2 adds the column and the field
        return ()
    try:
        from supervisor.onboard.autonomy import LEVELS

        return tuple(LEVELS)
    except Exception:  # noqa: BLE001 - no vocabulary, no choice
        return ()


def form_view(ctx: Any, me: Any) -> dict[str, Any]:
    svc = ctx.systems
    scoped = svc.scope_for(me) is not ALL
    return {
        "choices": {
            k: [(v, f"sy_{k}_{v}") for v in vs] for k, vs in systems_views.REGISTER_CHOICES.items()
        },
        "autonomy": [(v, f"ux4b_autonomy_{v}") for v in autonomy_choices()],
        "scoped": scoped,
        "teams": sorted(svc.teams_of(str(me.user_id))) if scoped else [],
        "can_repo": rbac.allowed(me.roles, "onboard.start"),
        "values": {},
    }


def draft_of(form: Mapping[str, str], me: Any, svc: Any) -> dict[str, Any]:
    """The intake draft: the form fields only. A scoped person registers for themselves."""
    draft = systems_views.draft_from_form(form, me)
    level = form.get("autonomy_level", "")
    if level and autonomy_choices():
        draft["autonomy_level"] = level
    if svc.scope_for(me) is not ALL:
        draft["owner_user"] = str(me.user_id)
    return draft


def validate(ctx: Any, me: Any, form: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(raw draft, normalised row fields). SystemsError (HTTP 400) on any bad value, a name
    already used, or a team outside the scope of a scoped person. Writes nothing."""
    svc = ctx.systems
    draft = draft_of(form, me, svc)
    fields = gm.normalise_draft(draft)
    svc._check_team_in_scope(me, fields["owner_team"])  # noqa: SLF001 - the one scope rule
    svc._unique_name(fields["name"])  # noqa: SLF001
    return draft, fields


# ---------------------------------------------------------------------------- the checks


def band_of(total: int) -> str:
    for low, key in BANDS:
        if total >= low:
            return key
    return BANDS[-1][1]


def readiness(me: Any, raw_path: str) -> dict[str, Any]:
    """The integration readiness advisor on a repository folder, in process and read only. No
    folder: not available. The advisor needs the same right as starting an onboarding run."""
    path = (raw_path or "").strip()
    if not path:
        return {"total": None, "na": "ux4b_na_no_repo"}
    if len(path) > MAX_PATH:
        raise ListingError("repository folder is too long")
    if not rbac.allowed(me.roles, "onboard.start"):
        raise ListingError("running the readiness advisor needs the right to start onboarding")
    from supervisor.console.onboard_runs import resolve_target

    target = resolve_target(path)
    from supervisor.advisory.integration.advise import advise

    try:
        report = advise(target, chat=None).report  # chat=None: no model, no narrative
    except Exception as exc:  # noqa: BLE001 - an advisor failure is a reason on the page
        log.warning("wizard: readiness advisor failed (%s)", type(exc).__name__)
        return {"total": None, "na": "ux4b_na_advisor_failed"}
    r = report.readiness
    return {
        "total": int(r.total),
        "band": band_of(int(r.total)),
        "areas": [{"id": a.id, "points": a.points, "weight": a.weight} for a in r.areas],
        "tools": len(report.found.tools),
        "patches": len(report.patches),
        "folder": target.name,
        "na": "",
    }


def dimensions_for(f: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(pack dimension, reason key) that apply to the declared system."""
    kind = f["system_type"]
    sens = f["personal_data"] in ("identifiable", "special")
    rows = [
        ("accuracy", kind in ("assistant", "decision", "automation", "feature"), "acts"),
        ("hallucination", kind in ("assistant", "feature"), "text"),
        ("bias_fairness", bool(f["credit_decision"]) or kind == "decision" or sens, "bias"),
        ("dependency", True, "dep"),
        ("security", True, "sec"),
        ("robustness", kind in ("automation", "platform", "decision"), "rob"),
    ]
    return [(d, f"ux4b_dim_{why}") for d, ok, why in rows if ok]


def packs_for(f: Mapping[str, Any]) -> dict[str, Any]:
    """Assurance packs that can target an agent, for the dimensions that apply."""
    try:
        from supervisor.assurance.loader import load_packs
        from supervisor.assurance.registry import select

        packs = load_packs()
    except Exception:  # noqa: BLE001 - unreadable manifests: a reason, not a failure
        return {"rows": [], "na": "ux4b_na_packs"}
    rows = []
    for dim, why in dimensions_for(f):
        for p in select(packs, dim, "agent"):
            rows.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "dimension": dim,
                    "why": why,
                    "gate": p.launch_gate,
                }
            )
    return {"rows": rows, "na": "" if rows else "ux4b_na_packs"}


def declared_class(f: Mapping[str, Any]) -> dict[str, Any]:
    """Decision 33 proposal from the declared fields (docs/phase4 plan, WP-G2 item 4): money
    movement or a credit decision without a human approval before the action is high risk. A
    proposal for a person to confirm; it is applied nowhere."""
    reasons = []
    if f.get("human_control") != "pre_approval":
        if f.get("money_movement"):
            reasons.append("money_movement")
        if f.get("credit_decision"):
            reasons.append("credit_decision")
    if reasons:
        return {"d33": "high_risk", "level": "high", "reasons": reasons, "source": "declared"}
    return {"d33": "not_high_risk", "level": None, "reasons": [], "source": "declared"}


def _g2_module(name: str) -> Any:
    try:
        return importlib.import_module(f"supervisor.governance.{name}")
    except ImportError:  # WP-G2 not merged
        return None


def _g2_class(f: Mapping[str, Any]) -> dict[str, Any] | None:
    """The WP-G2 classification draft for a system that does not exist yet, when the module
    offers one. None while WP-G2 is not merged or has no such function."""
    mod = _g2_module("classification")
    fn = getattr(mod, "propose", None) or getattr(mod, "classify_draft", None)
    if fn is None:
        return None
    try:
        out = fn(dict(f))
        outcome = out.get("outcome") if isinstance(out, Mapping) else getattr(out, "outcome", None)
    except Exception:  # noqa: BLE001 - a rules problem must not stop the wizard
        log.warning("wizard: G2 classification draft failed")
        return None
    if outcome not in gm.DECISION33_CLASSES:
        return None
    return {
        "d33": outcome,
        "level": "high" if outcome == "high_risk" else None,
        "reasons": [],
        "source": "rules",
    }


def _g2_floor(f: Mapping[str, Any]) -> list[dict[str, str]] | None:
    """The guardian floor the WP-G2 rules assign to the declared system: ``[{slug, rule}]``.
    None while WP-G2 is not merged or exposes nothing."""
    mod = _g2_module("rules")
    fn = getattr(mod, "evaluate", None)
    if fn is None:
        return None
    try:
        res = fn(dict(f))
        raw = getattr(res, "guardian_floor", None)
        if raw is None and isinstance(res, Mapping):
            raw = res.get("guardian_floor")
        if raw is None:
            return None
        out = []
        for x in raw:
            if isinstance(x, Mapping):
                out.append(
                    {
                        "slug": str(x.get("slug") or x.get("ref_id")),
                        "rule": str(x.get("rule") or x.get("rule_id") or ""),
                    }
                )
            else:
                out.append(
                    {"slug": str(getattr(x, "slug", x)), "rule": str(getattr(x, "rule_id", ""))}
                )
        return sorted(out, key=lambda r: r["slug"])
    except Exception:  # noqa: BLE001
        log.warning("wizard: G2 guardian floor failed")
        return None


def checks(ctx: Any, me: Any, form: Mapping[str, str]) -> dict[str, Any]:
    """The preliminary checks of a draft, for the result page. Writes nothing."""
    draft, fields = validate(ctx, me, form)
    full = {**fields, "owner_user": draft["owner_user"]}
    cls = _g2_class(full) or declared_class(full)
    floor = _g2_floor(full)
    svc = ctx.systems
    return {
        "draft": full,
        "form": {k: v for k, v in draft.items() if k != "tags"},
        "scoped": svc.scope_for(me) is not ALL,
        "repo": (form.get("repo_path") or "").strip(),
        "ready": readiness(me, form.get("repo_path", "")),
        "cls": cls,
        "packs": packs_for(full),
        "floor": floor,
        "floor_na": "" if floor is not None else "ux4b_na_no_rules",
        "applied": False,
    }


# --------------------------------------------------------------------------- register


def open_tasks(ctx: Any, system_id: str, actor: str) -> list[str]:
    """The initiation tasks of a new draft: tasks of the system itself (agent id = system id),
    as the workspace scan does ("Confirm context"). A repeat is a no-op."""
    tasks = ctx.tasks
    made = []
    for template_id, title in TASKS:
        try:
            row = tasks._row_for(  # noqa: SLF001 - same one place as inventory.autoregister
                system_id,
                "initiation",
                template_id=template_id,
                kind="custom",
                title=title,
                owner_role="owner",
                required=True,
                due_days=TASK_DUE_DAYS,
                evidence_kind="none",
                evidence_ref=None,
                level="low",
                d33_class="unclassified",
                actor=actor,
            )
            if tasks._insert(row, actor):  # noqa: SLF001
                made.append(template_id)
        except Exception:  # noqa: BLE001 - a draft without its task is still a draft
            log.exception("wizard: could not open initiation task %s", template_id)
    return made


def register(ctx: Any, me: Any, form: Mapping[str, str]) -> dict[str, Any]:
    """Register the draft (status draft, stage initiation) and open the initiation tasks. The
    classification and the floor are not applied: they stay proposals on the result page."""
    svc = ctx.systems
    draft = draft_of(form, me, svc)
    out = svc.register(draft, str(me.user_id), for_user=me)
    out["tasks_opened"] = open_tasks(ctx, out["system_id"], str(me.user_id))
    return out  # type: ignore[no-any-return]
