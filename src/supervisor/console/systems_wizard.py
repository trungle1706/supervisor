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

import concurrent.futures
import logging
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.console import systems_views
from supervisor.console.listing import ListingError
from supervisor.core import rbac
from supervisor.governance import model as gm
from supervisor.governance.systems import ALL

log = logging.getLogger("supervisor.console")
_NODE_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")

MAX_PATH = 512
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="wizard-advisor")
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
    """Autonomy levels the form offers (WP-G2 ``governance.model.AUTONOMY_LEVELS``, without
    "unspecified": a blank choice means not set)."""
    return tuple(x for x in gm.AUTONOMY_LEVELS if x != "unspecified")


def form_view(ctx: Any, me: Any, from_node: str = "") -> dict[str, Any]:
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
        "from_node": _node_id(from_node),
    }


def _node_id(raw: Any) -> str:
    """A scanned-object id from ``?from=`` (kept through the three steps), or ''."""
    text = str(raw or "").strip()
    return text if text and len(text) <= 128 and _NODE_ID.match(text) else ""


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


_ADVISOR_LOCK = threading.Lock()
ADVISOR_TIMEOUT_S = 30


def allowed_roots(settings: Any) -> list[Path]:
    """Folders the wizard may scan: ``ONBOARD_ALLOWED_ROOTS`` (real paths). Empty = none."""
    raw = str(getattr(settings, "onboard_allowed_roots", "") or "")
    return [
        Path(os.path.realpath(x.strip())) for x in raw.replace(";", ",").split(",") if x.strip()
    ]


def _run_advisor(target: Path) -> Any:
    from supervisor.advisory.integration.advise import advise

    try:
        return advise(target, chat=None).report  # chat=None: no model, no narrative
    finally:
        _ADVISOR_LOCK.release()


def readiness(me: Any, raw_path: str, settings: Any = None) -> dict[str, Any]:
    """The integration readiness advisor on a repository folder, in process and read only. No
    folder: not available. The advisor needs the same right as starting an onboarding run, runs
    only inside ``ONBOARD_ALLOWED_ROOTS`` (empty: off), one at a time, and for 30 s at most."""
    path = (raw_path or "").strip()
    if not path:
        return {"total": None, "na": "ux4b_na_no_repo"}
    if len(path) > MAX_PATH:
        raise ListingError("repository folder is too long")
    if not rbac.allowed(me.roles, "onboard.start"):
        raise ListingError("running the readiness advisor needs the right to start onboarding")
    roots = allowed_roots(settings)
    if not roots:
        return {"total": None, "na": "ux4b_na_repo_disabled"}
    from supervisor.console.onboard_runs import resolve_target

    target = resolve_target(path)
    if not any(target == r or r in target.parents for r in roots):
        raise ListingError("the folder is outside ONBOARD_ALLOWED_ROOTS")
    return scan_folder(target)


def scan_folder(target: Path) -> dict[str, Any]:
    """The advisor on a resolved folder: one at a time, 30 s at most. Shared by ``readiness`` and
    the pre-deploy assessment (WP-O3), which scans the stored intake tree (not a folder in a
    repository, not inside ``ONBOARD_ALLOWED_ROOTS``: the server wrote that tree itself)."""
    if not _ADVISOR_LOCK.acquire(blocking=False):
        raise ListingError("a check is already running; try again in a moment")
    try:
        # WP-P5: the advisor scans repo files only and never touches SQL, so the forwarded
        # user token is deliberately not propagated into this pool.
        future = _POOL.submit(_run_advisor, target)  # the worker releases the lock
    except BaseException:
        _ADVISOR_LOCK.release()
        raise
    try:
        report = future.result(timeout=ADVISOR_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        return {"total": None, "na": "ux4b_na_time_limit"}  # lock held until the scan ends
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
    """Decision 33 proposal from the declared fields: money movement or a credit decision without
    a human approval before the action is high risk. A declared approval is not proof (a human
    step counts only when it is in code, docs/onboard.md), and declared fields alone never show
    "not high risk": those cases stay unclassified for a person. Applied nowhere."""
    flags = [k for k in ("money_movement", "credit_decision") if f.get(k)]
    if flags and f.get("human_control") != "pre_approval":
        return {"d33": "high_risk", "level": "high", "reasons": flags, "source": "declared"}
    note = "ux4b_class_approval_unchecked" if flags else "ux4b_class_none_declared"
    return {
        "d33": "unclassified",
        "level": None,
        "reasons": flags,
        "source": "declared",
        "note": note,
    }


def _facts_of(f: Mapping[str, Any]) -> dict[str, Any]:
    """The facts the G2 rules see for a system that is not stored yet: its fields only (no
    parts), made by the function the rules engine uses for a stored system."""
    from supervisor.governance import rules as R

    return R.facts_of(f, str(f.get("risk_level") or "unspecified"), {}, [])


def _class_preview(ctx: Any, f: Mapping[str, Any]) -> dict[str, Any] | None:
    """The Decision 33 draft of the declared system, by the code path of
    ``ClassificationService.draft`` (``decision33.derive`` then ``decide`` over the flow) without
    storing a row, because the system does not exist yet. None if the flow cannot be read."""
    try:
        from supervisor.governance import decision33 as d33

        flow = ctx.classification.flow()
        dec = d33.decide(flow, d33.derive(flow, _facts_of(f)))
    except Exception:  # noqa: BLE001 - a flow problem must not stop the wizard
        log.warning("wizard: Decision 33 draft failed", exc_info=True)
        return None
    return {
        "d33": dec.outcome,
        "level": "high" if dec.outcome == "high_risk" else None,
        "reasons": [],
        "source": "rules",
        "why": dec.reason,
        "note": "" if dec.outcome == "high_risk" else "ux4b_class_open_questions",
    }


def _floor_preview(ctx: Any, f: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """The guardian floor the assignment rules give the declared system (``[{slug, rules}]``, the
    shape of ``RulesService.guardian_floor``), evaluated without storing anything."""
    try:
        from supervisor.governance import rules as R

        ev = R.evaluate(ctx.rules.ruleset(), _facts_of(f), ctx.rules.catalogue())
        return sorted(
            (
                {"slug": a.ref_id, "rules": sorted(rid for rid, _ in a.rules)}
                for a in ev.of("guardian")
            ),
            key=lambda r: r["slug"],
        )
    except Exception:  # noqa: BLE001 - rules file problem: the floor is not available
        log.warning("wizard: guardian floor failed", exc_info=True)
        return None


def checks(ctx: Any, me: Any, form: Mapping[str, str]) -> dict[str, Any]:
    """The preliminary checks of a draft, for the result page. Writes nothing."""
    draft, fields = validate(ctx, me, form)
    full = {**fields, "owner_user": draft["owner_user"]}
    cls = _class_preview(ctx, full) or declared_class(full)
    floor = _floor_preview(ctx, full)
    svc = ctx.systems
    return {
        "draft": full,
        "form": {
            **{k: v for k, v in draft.items() if k != "tags"},
            **(
                {"from_node": _node_id(form.get("from_node"))}
                if _node_id(form.get("from_node"))
                else {}
            ),
        },
        "scoped": svc.scope_for(me) is not ALL,
        "repo": (form.get("repo_path") or "").strip(),
        "ready": readiness(me, form.get("repo_path", ""), ctx.settings),
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


def missing_tasks(ctx: Any, system_id: str) -> list[str]:
    """Intake template ids that have no task on the system yet."""
    have = {t["template_id"] for t in ctx.state.query("task", {"agent_id": system_id})}
    return [tid for tid, _ in TASKS if tid not in have]


def register(ctx: Any, me: Any, form: Mapping[str, str]) -> dict[str, Any]:
    """Register the draft (status draft, stage initiation) and open the initiation tasks. The
    classification and the floor are not applied: they stay proposals on the result page."""
    svc = ctx.systems
    draft = draft_of(form, me, svc)
    out = svc.register(draft, str(me.user_id), for_user=me)
    node = _node_id(form.get("from_node"))
    if node:  # H5b: link the scanned object so the candidate leaves the list
        try:
            svc.link(
                out["system_id"],
                "node",
                node,
                str(me.user_id),
                source="workspace_scan",
                for_user=me,
            )
        except Exception:  # noqa: BLE001 - the system exists; the Components tab can link later
            log.exception("wizard: could not link the scanned object")
    out["tasks_opened"] = open_tasks(ctx, out["system_id"], str(me.user_id))
    out["tasks_missing"] = missing_tasks(ctx, out["system_id"])
    # the Decision 33 draft, by the Classification tab's own code path; never applied
    try:
        ctx.classification.draft(out["system_id"], str(me.user_id))
        out["classification_draft"] = True
    except Exception:  # noqa: BLE001 - the tab can make the draft later
        log.exception("wizard: could not make the classification draft")
        out["classification_draft"] = False
    return out  # type: ignore[no-any-return]
