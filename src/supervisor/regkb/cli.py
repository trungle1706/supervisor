"""CLI: python -m supervisor.regkb {validate,list,show,coverage,diff,export,watch}.

ASCII output only. Every command prints the disclaimer first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT, load_settings
from supervisor.core.errors import SupervisorError
from supervisor.regkb import DISCLAIMER
from supervisor.regkb.errors import RegKBError, UnknownObligationError
from supervisor.regkb.loader import load_kb
from supervisor.regkb.model import Control, KnowledgeBase, Obligation, to_plain

STRIPPED_NOTE = "(diacritics stripped; see file)"
_SPECIAL = str.maketrans(
    {"đ": "d", "Đ": "D", "–": "-", "—": "-", "‘": "'", "’": "'"} | {"“": '"', "”": '"', "…": "..."}
)


def ascii_text(text: str) -> str:
    """Strip diacritics (NFKD) and map d-stroke; anything else non-ASCII becomes '?'."""
    text = text.translate(_SPECIAL)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text.encode("ascii", "replace").decode("ascii")


def out(line: str = "") -> None:
    sys.stdout.write(ascii_text(line) + "\n")


def _internal_dir(arg: str | None) -> Path | None:
    value = arg
    if value is None:
        try:
            value = load_settings().regkb_internal_dir
        except SupervisorError:
            value = os.environ.get("REGKB_INTERNAL_DIR", "")
    value = (value or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else REPO_ROOT / path))


def _kb(args: argparse.Namespace) -> KnowledgeBase:
    return load_kb(args.root, _internal_dir(args.internal_dir))


def _hash12(kb_or_hash: KnowledgeBase | str) -> str:
    return (kb_or_hash if isinstance(kb_or_hash, str) else kb_or_hash.version)[:12]


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        kb = _kb(args)
    except RegKBError as exc:
        for line in exc.errors:
            out(f"[FAIL] {line}")
        return 1
    for w in kb.warnings:
        out(f"[SKIP] warning: {w}")
    out(
        f"[OK] {len(kb.instruments)} instruments, {len(kb.obligations)} obligations, "
        f"version {_hash12(kb)}"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    kb = _kb(args)
    for o in kb.obligations.values():
        if args.jurisdiction and o.jurisdiction != args.jurisdiction:
            continue
        if args.instrument and o.instrument_id != args.instrument:
            continue
        out(f"{o.id}  {o.status}  {o.verification}  {','.join(o.duties)}")
    return 0


def _show_obligation(o: Obligation) -> None:
    plain = to_plain(o)
    stripped = False
    for key, value in plain.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if ascii_text(text) != text:
            stripped = True
        out(f"{key}: {text}")
    if stripped:
        out(STRIPPED_NOTE)


def cmd_show(args: argparse.Namespace) -> int:
    kb = _kb(args)
    if args.id in kb.obligations:
        _show_obligation(kb.obligations[args.id])
        return 0
    try:
        inst = kb.instrument(args.id)
    except UnknownObligationError:
        raise UnknownObligationError(f"no obligation or instrument with id {args.id}") from None
    plain = to_plain(inst)
    stripped = False
    for key, value in plain.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        stripped = stripped or ascii_text(text) != text
        out(f"{key}: {text}")
    out(f"hash: {kb.instrument_hashes[inst.id]}")
    out("obligations:")
    for o in kb.obligations_of(inst.id):
        out(f"  {o.id}  {o.verification}  {o.article_ref}")
    if stripped:
        out(STRIPPED_NOTE)
    return 0


def _table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for n, row in enumerate(rows):
        out("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())
        if n == 0:
            out("  ".join("-" * w for w in widths))


def cmd_coverage(args: argparse.Namespace) -> int:
    kb = _kb(args)
    rows = [
        [
            "instrument",
            "kind",
            "status",
            "binding",
            "obligations",
            "P/S/A",
            "primary text",
            "last checked",
        ]
    ]
    for inst in kb.instruments:
        obs = kb.obligations_of(inst.id)
        v = Counter(o.verification for o in obs)
        rows.append(
            [
                inst.id,
                inst.kind,
                inst.status,
                "yes" if inst.binding else "no",
                str(len(obs)),
                f"{v['VERIFIED_PRIMARY']}/{v['VERIFIED_SECONDARY']}/{v['ASSUMED']}",
                "yes" if inst.primary_text_fetched else "no",
                inst.last_checked,
            ]
        )
    _table(rows)
    tally = Counter(_control_level(o) for o in kb.obligations.values())
    out()
    out("Control coverage (Supervisor controls only; process entries do not count):")
    out(f"  at least one full control: {tally['full']}")
    out(f"  only partial controls:     {tally['partial']}")
    out(f"  none or process only:      {tally['none']}")
    if args.levels:
        _levels(kb)
    out(f"version {kb.version}")
    return 0


def _levels(kb: KnowledgeBase) -> None:
    """Per instrument: obligations by control level (WP-L5). 'Supervisor' counts the entries that
    are not a bank process; 'with process' counts every entry (a process step counts as partial)."""
    rows = [
        [
            "instrument",
            "obligations",
            "Supervisor f/p/n",
            "with process f/p/n",
            "none, named reason",
        ]
    ]
    for inst in kb.instruments:
        obs = kb.obligations_of(inst.id)
        sup = Counter(_control_level(o) for o in obs)
        every = Counter(_best_level(o.control_mapping) for o in obs)
        named = sum(
            1
            for o in obs
            if _control_level(o) == "none"
            and any(
                (c.note or "").startswith(("Manual step:", "No control:"))
                for c in o.control_mapping
            )
        )
        rows.append(
            [
                inst.id,
                str(len(obs)),
                f"{sup['full']}/{sup['partial']}/{sup['none']}",
                f"{every['full']}/{every['partial']}/{every['none']}",
                str(named),
            ]
        )
    out()
    out("Control levels per instrument (f = full, p = partial, n = none):")
    _table(rows)


def _best_level(controls: Iterable[Control]) -> str:
    cov = {c.coverage for c in controls}
    return "full" if "full" in cov else "partial" if "partial" in cov else "none"


def _control_level(o: Obligation) -> str:
    own = [c for c in o.control_mapping if c.kind != "process"]
    if any(c.coverage == "full" for c in own):
        return "full"
    if any(c.coverage == "partial" for c in own):
        return "partial"
    return "none"


def _snapshot(source: str, args: argparse.Namespace) -> dict[str, Any]:
    path = Path(source)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("version", "instruments", "obligations"):
                data[key]
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise RegKBError(f"{source} is not a RegKB export: {exc}") from None
        return data  # type: ignore[no-any-return]
    if path.is_dir():
        return load_kb(path).snapshot()
    raise RegKBError(f"{source} is neither a regulations directory nor an export file")


def _changed(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def cmd_diff(args: argparse.Namespace) -> int:
    snaps = (_snapshot(args.a, args), _snapshot(args.b, args))
    out(f"a: {args.a} version {_hash12(snaps[0]['version'])}")
    out(f"b: {args.b} version {_hash12(snaps[1]['version'])}")
    changes = 0
    for label, key in (("instrument", "instruments"), ("obligation", "obligations")):
        a, b = snaps[0][key], snaps[1][key]
        for ident in sorted(set(b) - set(a)):
            out(f"added {label}: {ident}")
        for ident in sorted(set(a) - set(b)):
            out(f"removed {label}: {ident}")
        for ident in sorted(set(a) & set(b)):
            fields = _changed(a[ident], b[ident])
            if fields:
                out(f"changed {label}: {ident}: {', '.join(fields)}")
                changes += 1
        changes += len(set(a) ^ set(b))
    if not changes:
        out("no changes")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    kb = _kb(args)
    data = {"format": "regkb-export-1", "disclaimer": DISCLAIMER, **kb.snapshot()}
    target = Path(os.path.abspath(args.out))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), "utf-8")
    out(f"[OK] wrote {target} ({len(kb.obligations)} obligations, version {_hash12(kb)})")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Dev host / laptop: ask vbpl.vn about the stored instruments (WP-W1). The App never does."""
    from supervisor.regkb import watch

    settings = load_settings()
    out_dir = Path(os.path.abspath(args.out or Path(settings.data_dir) / "regwatch"))
    try:
        fetcher = watch.ToolFetcher()
    except RuntimeError as exc:
        raise RegKBError(str(exc)) from None
    sources = Path(os.path.abspath(args.sources_root)) if args.sources_root else None

    def progress(line: str) -> None:
        out(f"[..] {line}")

    if args.dry_run:
        result = watch.run_watch(
            fetcher, only=args.instrument, prev=watch.latest_report(out_dir), progress=progress
        )
        report, written = result.report, "nothing written (dry run)"
    else:
        from supervisor.evidence.signer import build_signer

        done = watch.run_and_package(
            fetcher,
            out_dir,
            build_signer(settings),
            sources_root=sources,
            only=args.instrument,
            progress=progress,
        )
        report = done["report"]
        written = f"report {done['report_json']} package {done['package']}"
    s = report["summary"]
    out(
        f"[OK] watch {report['run_id']}: {s['instruments_checked']} instruments, "
        f"{s['changes_found']} changes, {s['new_candidates']} new candidates, "
        f"{s['errors']} errors; {written}"
    )
    for row in report["instruments"]:
        for c in row["changes"]:
            out(f"  {row['instrument_id']}: {c['kind']}: {c['detail']}")
    for e in report["errors"][:10]:
        out(f"[SKIP] {e}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m supervisor.regkb", description=DISCLAIMER)
    p.add_argument("--root", type=Path, default=None, help="regulations root (default: repo)")
    p.add_argument("--internal-dir", default=None, help="internal rules dir (default: settings)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    ls = sub.add_parser("list")
    ls.add_argument("--jurisdiction")
    ls.add_argument("--instrument")
    ls.set_defaults(func=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)
    cov = sub.add_parser("coverage")
    cov.add_argument("--levels", action="store_true", help="add full/partial/none per instrument")
    cov.set_defaults(func=cmd_coverage)
    diff = sub.add_parser("diff")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.set_defaults(func=cmd_diff)
    wat = sub.add_parser("watch", help="query vbpl.vn for changes (dev host / laptop, WP-W1)")
    wat.add_argument(
        "--out", default=None, help="report and package folder (default DATA_DIR/regwatch)"
    )
    wat.add_argument("--instrument", default=None, help="check one instrument id only")
    wat.add_argument("--dry-run", action="store_true", help="query and print; write nothing")
    wat.add_argument(
        "--sources-root",
        default=None,
        help="where incoming/ texts go (default regulations/sources)",
    )
    wat.set_defaults(func=cmd_watch)
    exp = sub.add_parser("export")
    exp.add_argument("out")
    exp.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    out(DISCLAIMER)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        return int(args.func(args))
    except RegKBError as exc:
        for line in exc.errors:
            out(f"[FAIL] {line}")
        return 1
    except (SupervisorError, OSError) as exc:
        out(f"[FAIL] {exc}")
        return 1
