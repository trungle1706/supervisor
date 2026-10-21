"""Risk register CLI (WP29). ASCII output.

  python -m supervisor.risk list [--agent A] [--band B] [--category C]  risks with scores
  python -m supervisor.risk import PATH --by USER [--dry-run] [--source starter]  import YAML
  python -m supervisor.risk score [--agent A]                           agent levels (inheritance)
  python -m supervisor.risk export --out DIR [--format json|csv|both]   risks.json, CSV files

``import`` has no login: it runs with the operator's own shell and store access, so it needs
``--by`` (your own user id). The id is written to a ``console_action`` row (permission
``risks.edit``, method CLI) and, as a keyed hash, to every ``risk_change`` chain record.
Needs RISK_REGISTER_ENABLED=1. The evidence pass is ``python -m supervisor.jobs.risk_evidence``.
The starter risks are in config/risks/*.yaml; the bank's own register is imported the same way
(docs/risk-register.md).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402

if TYPE_CHECKING:
    from supervisor.risk.service import RiskService


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def _by(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,64}", value):
        raise argparse.ArgumentTypeError(
            "--by must be 1 to 64 characters from A-Z a-z 0-9 _ . @ + -"
        )
    return value


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "~"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.risk", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--agent", default="")
    p.add_argument("--band", default="")
    p.add_argument("--category", default="")
    p.add_argument("--owner", default="")
    p = sub.add_parser("import")
    p.add_argument("path", type=Path)
    p.add_argument(
        "--by",
        required=True,
        type=_by,
        help="who runs this import (your own user id); recorded in the audit row and the chain",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--overwrite-manual", action="store_true")
    p.add_argument("--source", choices=("import", "starter"), default="import")
    p = sub.add_parser("score")
    p.add_argument("--agent", default="")
    p = sub.add_parser("export")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--format", choices=("json", "csv", "both"), default="both")
    args = ap.parse_args(argv)

    from supervisor.config import load_settings
    from supervisor.risk.model import RiskError
    from supervisor.risk.service import RiskService

    try:
        settings = load_settings()
        if not settings.risk_register_enabled:
            _say("[SKIP] risk register is off (RISK_REGISTER_ENABLED=1 turns it on)")
            return 0
        if args.cmd == "import":
            # a write: the changes go on the evidence chain, so open the chain writer too
            # (single writer per lane: stop the app first, see docs/risk-register.md)
            from supervisor.monitors.jobctx import standalone

            with standalone(settings) as (_, adapters, ctx):
                svc = RiskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
                return _do(args, svc)
        from supervisor.adapters.factory import build_adapters
        from supervisor.jobs import bootstrap_schema

        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                bootstrap_schema.run(settings, adapters)
            return _do(args, RiskService.from_adapters(adapters))
        finally:
            adapters.close()
    except (SupervisorError, RiskError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1


def _audit_import(svc: RiskService, by: str, res: object) -> None:
    from supervisor.adapters.auth.audit import write_action

    write_action(
        svc.tables,
        svc.clock,
        request_id=None,
        actor=None,
        actor_fallback=(by, "operator", "cli"),
        permission="risks.edit",
        method="CLI",
        path="supervisor.risk import",
        outcome="ok",
        target_kind="risk",
        detail="import",
    )


def _do(args: argparse.Namespace, svc: RiskService) -> int:
    if args.cmd == "list":
        rows = svc.list_risks(
            {"agent": args.agent, "band": args.band, "category": args.category, "owner": args.owner}
        )
        _say(f"{'ID':14} {'INH':>7} {'RES':>7} {'BAND':9} {'EVIDENCE':11} {'STATUS':8} TITLE")
        for r in rows:
            inh = f"{r['inherent_score']:>2} {r['inherent_band'][:3]}"
            res = f"{r['residual_score']:>2} {r['residual_band'][:3]}"
            _say(
                f"{r['risk_id']:14} {inh:>7} {res:>7} {r['residual_band']:9} "
                f"{(r['evidence_state'] or '-'):11} {r['status']:8} {_cut(r['title'], 50)}"
            )
        _say(f"[OK] {len(rows)} risk(s)")
    elif args.cmd == "import":
        res = svc.import_path(
            args.path,
            args.by,
            source=args.source,
            dry_run=args.dry_run,
            overwrite_manual=args.overwrite_manual,
        )
        for e in res.errors:
            _say(f"[FAIL] {e}")
        for n in res.notes:
            _say(f"[SKIP] {n}")
        if res.errors:
            _say("[FAIL] nothing was imported")
            return 1
        if not args.dry_run:
            _audit_import(svc, args.by, res)
        tag = "dry run: " if args.dry_run else ""
        _say(
            f"[OK] {tag}created={res.created} updated={res.updated} unchanged={res.unchanged} "
            f"skipped_manual={res.skipped_manual} links_added={res.links_added} "
            f"links_removed={res.links_removed}"
        )
    elif args.cmd == "score":
        _say(f"{'AGENT':20} {'INHERENT':>12} {'RESIDUAL':>12} RISKS (own/inherited)")
        for name, lv in sorted(svc.agent_levels().items()):
            if args.agent and name != args.agent.lower():
                continue
            own = sum(1 for x in lv.reached if x["own"])
            inh = f"{lv.inherent_score:>2} {lv.inherent_level or '-'}"
            res = f"{lv.residual_score:>2} {lv.residual_level or '-'}"
            _say(f"{name:20} {inh:>12} {res:>12} {own}/{len(lv.reached) - own}")
        c = svc.counts()
        _say(
            f"[OK] bands are ILLUSTRATIVE; {c['active']} active risk(s), "
            f"{c['review_overdue']} overdue"
        )
    else:
        for path in svc.write_exports(args.out, args.format):
            _say(f"[OK] wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
