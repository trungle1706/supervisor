"""Model card for the tiered judge (WP19).

``python -m supervisor.judge.mrm card --out DIR`` writes ``judge_model_card.json`` and
``judge_model_card.md``. The JSON is deterministic for the same settings, eval report,
store rows and ``--now``. Integers, strings and booleans only.

TODO: Vietnamese headings (English only for now).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT, Settings, load_settings
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import TableStore
from supervisor.judge.mrm._common import (
    ascii_safe,
    identity_for,
    parse_now,
    router_factory,
    utc_now,
)
from supervisor.judge.mrm.identity import RUBRIC_VERSION
from supervisor.judge.prompts import PROMPT_VERSION

DEFAULT_EVAL_REPORT = REPO_ROOT / "data" / "golden" / "eval_report.json"
CARD_VERSION = 1
TIER_DESCRIPTION = "tiered: Tier 1 monitor 100 % + Tier 2 judge on flag/sample"

# Static change log: one entry per prompt / rubric version. Add a line when either changes.
CHANGELOG: list[dict[str, str]] = [
    {
        "prompt_version": PROMPT_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "change": "Tiered judge with injection-hardened prompts, canary check, "
        "held-out eval split, family-independence rule (ADR D06, WP5).",
    },
    {
        "prompt_version": PROMPT_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "change": "Model-risk pack: identity key, validation record, GO/NO-GO report (WP19).",
    },
]

INTENDED_USE = [
    "Advisory only: the judge never blocks or pauses an agent. Only deterministic rules do.",
    "Judges traces of the supervised agents; a verdict opens a case or raises its severity.",
    "Languages: Vietnamese and English.",
    "Not for credit decisions or any decision about a customer.",
    "Mock judge numbers prove plumbing only, not model quality.",
]

FAILURE_MODES = [
    "Judge injection: text in a trace tries to steer the judge (prompt guard + canary check).",
    "Canary exfiltration: the judge repeats the secret canary; the verdict is discarded.",
    "Output invalid: the reply fails the schema; the trace is treated as suspicious.",
    "Judge unavailable: the trace is a coverage gap, not a pass.",
    "Truncation of long traces: events beyond the budget are not seen by the judge.",
    "Language gap: weaker catch rate in one language than the other is possible.",
    "Position and length bias: untested.",
    "Mock judge is not a model: its metrics say nothing about real judge quality.",
    "Kappa is a placeholder until the bank supplies human labels.",
]


def _load_report(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _metrics_block(m: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "n",
        "catch_rate_bp",
        "false_alarm_bp",
        "by_language",
        "injection_detect_bp",
        "injection_lowered_bp",
        "canary_leak_bp",
        "stability",
    )
    return {k: m.get(k) for k in keys}


def _validation_rows(tables: TableStore | None) -> list[dict[str, Any]]:
    if tables is None:
        return []
    try:
        rows = tables.query("model_validation", order_by=("-ts",), limit=5)
    except Exception:  # store without the table: no history to show
        return []
    out = []
    for r in rows:
        ts = r.get("ts")
        out.append(
            {
                "ts": ts.isoformat() if isinstance(ts, datetime) else str(ts),
                "decision": str(r.get("decision")),
                "model_version": str(r.get("model_version")),
                "validation_id": str(r.get("validation_id")),
            }
        )
    return out


def build_card(
    settings: Settings,
    *,
    eval_report_path: Path = DEFAULT_EVAL_REPORT,
    now: datetime | None = None,
    tables: TableStore | None = None,
) -> dict[str, Any]:
    router = router_factory(settings, "settings")()
    ident = identity_for(settings, router)
    desc = router.describe()
    tiers = {}
    for tier in ("t1", "t2"):
        d = desc[tier]
        tiers[tier] = {
            "model_id": d["model_id"],
            "model_version": d["model_version"],
            "family": d["family"],
            "kind": "mock" if d["is_mock"] else "model",
        }
    report = _load_report(eval_report_path)
    data_block: dict[str, Any] = {"golden_set_hash": ident.golden_set_hash}
    metrics: dict[str, Any] = {"status": "no_eval_report"}
    if report:
        data_block["heldout_digest"] = report.get("heldout", {}).get("digest")
        data_block["heldout_n_items"] = report.get("heldout", {}).get("n_items")
        by_split = report.get("metrics", {})
        split = "heldout" if "heldout" in by_split else ("dev" if "dev" in by_split else None)
        if split:
            metrics = {
                "status": "ok",
                "split": split,
                "mock": bool(report.get("mock")),
                "runs": report.get("runs"),
                "generated_at": report.get("generated_at"),
                **_metrics_block(by_split[split]),
                "kappa_bp": (report.get("kappa") or {}).get("value_bp"),
            }
            data_block["item_counts"] = by_split[split].get("n")
    return {
        "card_version": CARD_VERSION,
        "generated_at": utc_now(now).isoformat(),
        "identity": {
            "judge_id": ident.judge_id,
            "description": TIER_DESCRIPTION,
            "is_mock": ident.is_mock,
            "tiers": tiers,
            "prompt_version": ident.prompt_version,
            "t1_prompt_hash": ident.t1_prompt_hash,
            "t2_prompt_hash": ident.t2_prompt_hash,
            "prompt_hash": ident.prompt_hash,
            "rubric_version": ident.rubric_version,
            "mask_version": ident.mask_version,
            "model_version": ident.model_version,
        },
        "roles": {
            "owner": settings.mrm_model_owner,
            "developer": settings.mrm_model_developer,
            "validator": settings.mrm_validator,
            "approver": settings.mrm_approver,
        },
        # Circular 53 Art. 4(5) inventory fields the bank fills (not in settings yet).
        "inventory": {
            "risk_level": "FILL-ME-risk-level (bank classification, Art. 4)",
            "provider": "FILL-ME-judge-model-provider",
            "approval_document": "FILL-ME-approval-document-ref",
        },
        "intended_use": list(INTENDED_USE),
        "data": data_block,
        "metrics": metrics,
        "known_failure_modes": list(FAILURE_MODES),
        "changelog": [dict(c) for c in CHANGELOG],
        "validations": _validation_rows(tables),
    }


def render_card_md(card: dict[str, Any]) -> str:
    i = card["identity"]
    lines = [
        "# Judge model card",
        "",
        f"Generated: {card['generated_at']}",
        "",
        "## Identity",
        "",
        f"- judge: {i['judge_id']} ({i['description']})",
        f"- kind: {'MOCK' if i['is_mock'] else 'model'}",
    ]
    for t in ("t1", "t2"):
        d = i["tiers"][t]
        lines.append(
            f"- {t.upper()}: {d['model_id']} (version {d['model_version']}, "
            f"family {d['family']}, {d['kind']})"
        )
    lines += [
        f"- prompt version: {i['prompt_version']}",
        f"- prompt hash (composite): {i['prompt_hash']}",
        f"- T1 prompt hash: {i['t1_prompt_hash']}",
        f"- T2 prompt hash: {i['t2_prompt_hash']}",
        f"- rubric version: {i['rubric_version']}",
        f"- mask version: {i['mask_version']}",
        "",
        "## Roles",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in card["roles"].items()]
    lines += ["", "## Inventory (Circular 53 Art. 4(5))", ""]
    lines += [f"- {k}: {v}" for k, v in card["inventory"].items()]
    lines += ["", "## Intended use and limits", ""] + [f"- {x}" for x in card["intended_use"]]
    d = card["data"]
    lines += ["", "## Data used", "", f"- golden set hash: {d['golden_set_hash']}"]
    if d.get("heldout_digest"):
        lines.append(f"- held-out digest: {d['heldout_digest']} ({d.get('heldout_n_items')} items)")
    if d.get("item_counts"):
        lines.append(f"- item counts: {json.dumps(d['item_counts'], sort_keys=True)}")
    m = card["metrics"]
    lines += ["", "## Metrics", ""]
    if m["status"] != "ok":
        lines.append("- no eval report found; run python -m supervisor.judge.eval")
    else:
        lines.append(
            f"Split {m['split']}, {'MOCK run' if m['mock'] else 'real run'}, "
            f"runs {m['runs']}. Values in basis points (10000 = 100 %)."
        )
        lines += ["", "| metric | value |", "|---|---|"]
        for k in (
            "catch_rate_bp",
            "false_alarm_bp",
            "injection_detect_bp",
            "injection_lowered_bp",
            "canary_leak_bp",
        ):
            lines.append(f"| {k} | {m[k]} |")
        for lang in ("vi", "en"):
            bl = (m.get("by_language") or {}).get(lang, {})
            lines.append(
                f"| {lang} catch / false alarm | {bl.get('catch_rate_bp')} / "
                f"{bl.get('false_alarm_bp')} |"
            )
        st = m.get("stability") or {}
        lines.append(f"| stability max range | {st.get('max_range_bp')} |")
        lines.append(f"| kappa | {m.get('kappa_bp')} (placeholder until human labels) |")
    lines += ["", "## Known failure modes", ""] + [f"- {x}" for x in card["known_failure_modes"]]
    lines += ["", "## Change log", ""]
    lines += [
        f"- {c['prompt_version']} / {c['rubric_version']}: {c['change']}" for c in card["changelog"]
    ]
    if card["validations"]:
        lines += ["", "### Latest validations", ""]
        lines += [
            f"- {v['ts']} {v['decision']} {v['model_version']} ({v['validation_id']})"
            for v in card["validations"]
        ]
    lines += ["", "TODO: Vietnamese headings", ""]
    return ascii_safe("\n".join(lines))


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m supervisor.judge.mrm card")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--eval-report", type=Path, default=DEFAULT_EVAL_REPORT)
    p.add_argument("--now", default=None, help=argparse.SUPPRESS)
    p.add_argument("--no-store", action="store_true", help="do not read past validations")
    args = p.parse_args(argv)
    try:
        settings = load_settings()
        now = parse_now(args.now)
        tables, adapters = None, None
        if not args.no_store:
            from supervisor.adapters.factory import build_adapters

            adapters = build_adapters(settings)
            tables = adapters.tables
        try:
            card = build_card(settings, eval_report_path=args.eval_report, now=now, tables=tables)
        finally:
            if adapters is not None:
                adapters.close()
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        (out / "judge_model_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        (out / "judge_model_card.md").write_text(render_card_md(card), encoding="utf-8")
    except (SupervisorError, ValueError, OSError) as exc:
        print(ascii_safe(f"[FAIL] judge model card: {exc}"))  # noqa: T201
        return 2
    print(ascii_safe(f"[OK] model card written to {out}"))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
