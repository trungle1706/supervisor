"""CLI for the assurance eval packs.

    python -m supervisor.assurance list [--dimension X] [--target-kind K]
    python -m supervisor.assurance run <pack|dimension|all> --target <spec> --out DIR
        [--repo PATH] [--judge mock|settings] [--data auto|synthetic|bank|vendored]
        [--max-items N] [--no-store]
    python -m supervisor.assurance report --in DIR | --run-id ID [--format md|json]

Target spec (comma separated): ``agent:<id>``, ``traces:<id>``, ``judge``, ``demo``.
Output is ASCII (``[OK] [WARN] [FAIL] [SKIP] [ERROR]``). Exit 0 when no pack failed or
errored, 1 when any did, 2 for a usage or configuration error (a message, no traceback).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.assurance.engine import (  # noqa: E402
    execute,
    finish_run,
    new_run_id,
    summary_thresholds,
)
from supervisor.assurance.loader import PACKS_DIR, load_packs  # noqa: E402
from supervisor.assurance.model import EvalPack, PackResult, RunContext  # noqa: E402
from supervisor.assurance.registry import DIMENSIONS, select  # noqa: E402
from supervisor.assurance.report import (  # noqa: E402
    ascii_text,
    render_json,
    render_markdown,
    result_line,
    summary_line,
)
from supervisor.assurance.results import (  # noqa: E402
    load_results_json,
    summary_from_dict,
    summary_from_store,
)
from supervisor.assurance.targets import build_targets, close_targets  # noqa: E402
from supervisor.config import REPO_ROOT, Settings, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402


class UsageError(SupervisorError):
    """Bad command line; exit code 2."""


def _out(text: str = "") -> None:
    print(ascii_text(text))  # noqa: T201


def _err(text: str) -> None:
    print(ascii_text(text), file=sys.stderr)  # noqa: T201


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.assurance", description="Assurance eval packs"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="list the eval packs")
    ls.add_argument("--dimension", choices=DIMENSIONS)
    ls.add_argument("--target-kind", choices=("agent", "traces", "judge"))
    ls.add_argument("--packs-dir", type=Path, default=PACKS_DIR, help=argparse.SUPPRESS)

    run = sub.add_parser("run", help="run packs on one or more targets")
    run.add_argument("selector", help="pack id, dimension name or 'all'")
    run.add_argument("--target", required=True, help="agent:<id>, traces:<id>, judge or demo")
    run.add_argument("--repo", type=Path, help="repo folder of an onboarded agent (agent:<id>)")
    run.add_argument("--judge", choices=("mock", "settings"), default="mock")
    run.add_argument(
        "--judge-tier",
        type=int,
        choices=(1, 2),
        default=1,
        help="with --judge settings: which configured model is evaluated (2 = the tier-2 model)",
    )
    run.add_argument("--data", choices=("auto", "synthetic", "bank", "vendored"), default="auto")
    run.add_argument("--max-items", type=int, help="cap items per pack (fast runs)")
    run.add_argument("--out", type=Path, required=True, help="folder for results.json + report.md")
    run.add_argument("--no-store", action="store_true", help="do not write tables or the chain")
    run.add_argument("--packs-dir", type=Path, default=PACKS_DIR, help=argparse.SUPPRESS)

    rep = sub.add_parser("report", help="print a report of an earlier run")
    src = rep.add_mutually_exclusive_group(required=True)
    src.add_argument("--in", dest="in_dir", type=Path, help="folder with results.json")
    src.add_argument("--run-id", help="run id in the configured store")
    rep.add_argument("--format", choices=("md", "json"), default="md")
    return p


def _load(packs_dir: Path) -> list[EvalPack]:
    return load_packs(packs_dir)


def _cmd_list(args: argparse.Namespace) -> int:
    packs = _load(args.packs_dir)
    if args.dimension:
        packs = [p for p in packs if p.dimension == args.dimension]
    if args.target_kind:
        packs = [p for p in packs if args.target_kind in p.targets]
    header = ("id", "dimension", "licence", "data modes", "targets", "launch_gate", "judge_gate")
    short = {"synthetic": "syn", "bank_supplied_path": "bank", "vendored_sample": "vend"}
    rows = [
        (
            p.id,
            p.dimension,
            p.licence,
            ",".join(short[m] for m in p.data_modes),
            ",".join(p.targets),
            p.launch_gate,
            "yes" if p.judge_gate else "no",
        )
        for p in packs
    ]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
        for i in range(7)
    ]
    for row in (header, *rows):
        _out("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())
    _out(f"{len(rows)} pack(s)")
    return 0


def tool_baseline_of(tables: Any, agent_id: str) -> str | None:
    """Latest registered ``agent_version.tool_manifest_hash`` of an agent, if the store has one."""
    if tables is None:
        return None
    try:
        rows = tables.query("agent_version", {"agent_id": agent_id}, order_by=["-deployed_at"])
    except Exception:  # noqa: BLE001 - no registry rows: the pack uses its own baseline
        return None
    for row in rows:
        if row.get("tool_manifest_hash"):
            return str(row["tool_manifest_hash"])
    return None


def _context(
    settings: Settings,
    target: Any,
    args: argparse.Namespace,
    *,
    out_dir: Path | None = None,
    tables: Any = None,
) -> RunContext:
    allow = tuple(x.strip() for x in settings.assurance_licence_allow.split(",") if x.strip())
    extras: dict[str, Any] = {}
    if out_dir is not None:
        extras["out_dir"] = str(out_dir)
    if getattr(target, "kind", None) == "agent":
        baseline = tool_baseline_of(tables, str(target.target_id))
        if baseline:
            extras["tool_baseline"] = baseline
    return RunContext(
        target=target,
        repo_root=REPO_ROOT,
        data_root=settings.assurance_data_dir,
        data_mode=args.data,
        max_items=args.max_items,
        osv_db_path=settings.osv_db_path,
        licence_allow=allow,
        extras=extras,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    if args.max_items is not None and args.max_items < 1:
        raise UsageError("--max-items must be 1 or more")
    packs = _load(args.packs_dir)
    chosen = select(packs, args.selector)  # unknown selector -> error with the valid list
    settings = load_settings()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    adapters = None
    chain = None
    tables = None
    if not args.no_store:
        from supervisor.adapters.factory import build_adapters
        from supervisor.evidence.chain import build_chain_writer

        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                from supervisor.jobs import bootstrap_schema

                bootstrap_schema.run(settings, adapters)
            chain = build_chain_writer(settings, adapters.tables, adapters.clock)
        except BaseException:
            adapters.close()
            raise
        tables = adapters.tables

    targets: list[Any] = []
    ok = False
    try:
        targets = build_targets(
            args.target,
            settings,
            out_dir / "work",
            repo=args.repo,
            judge=args.judge,
            adapters=adapters,
            judge_tier=args.judge_tier,
        )
        clock = adapters.clock if adapters is not None else None
        from supervisor.adapters.clock import SystemClock

        clock = clock or SystemClock()
        run_id = new_run_id(clock)
        live_thr = {p.id: summary_thresholds(p) for p in chosen}
        started = clock.now()
        results: list[PackResult] = []
        for target in targets:
            ctx = _context(settings, target, args, out_dir=out_dir, tables=tables)
            pack_results = execute(
                chosen,
                target,
                ctx,
                run_id,
                clock,
                on_result=lambda r, _p: _out(result_line(r, live_thr)),
            )
            results += pack_results
        if not results:
            raise UsageError(
                f"selector {args.selector!r} matches no pack for target {args.target!r} "
                "(check the targets column of 'list')"
            )
        summary = finish_run(
            chosen,
            results,
            run_id,
            started,
            clock,
            target_spec=args.target,
            selector=args.selector,
            tables=tables,
            sink=chain,
            out_dir=out_dir,
            packs_dir=args.packs_dir,
        )
        ok = True
    finally:
        close_targets(targets)
        if chain is not None:
            chain.close(seal=ok)
        if adapters is not None:
            adapters.close()
    _out(summary_line(summary))
    _out(f"[OK] wrote {out_dir / 'results.json'}")
    _out(f"[OK] wrote {out_dir / 'report.md'}")
    if summary.is_mock:
        _out("[MOCK] at least one result comes from a mock model or target")
    return 1 if summary.failed else 0


def _cmd_report(args: argparse.Namespace) -> int:
    if args.in_dir is not None:
        summary = summary_from_dict(load_results_json(args.in_dir))
    else:
        from supervisor.adapters.factory import build_adapters

        adapters = build_adapters(load_settings())
        try:
            summary = summary_from_store(adapters.tables, args.run_id)
        finally:
            adapters.close()
    text = render_json(summary) if args.format == "json" else render_markdown(summary)
    _out(text.rstrip("\n"))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)  # usage errors: argparse prints a message, exit code 2
    try:
        if args.cmd == "list":
            return _cmd_list(args)
        if args.cmd == "run":
            return _cmd_run(args)
        return _cmd_report(args)
    except UsageError as exc:
        _err(f"[FAIL] {exc}")
        return 2
    except SupervisorError as exc:
        # PackError, RegistryError, TargetError, ConfigError, ResultsError ...
        problems = getattr(exc, "problems", None)
        if problems:
            _err("[FAIL] invalid pack manifest(s):")
            for line in problems:
                _err(f"  {line}")
        else:
            _err(f"[FAIL] {exc}")
        return 2
    except OSError as exc:
        _err(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the CLI prints a message, never a traceback
        _err(f"[FAIL] internal error: {type(exc).__name__}: {exc}")
        return 2
