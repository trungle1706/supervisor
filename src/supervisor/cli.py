"""Command line entry point: python -m supervisor.cli <command>.

ASCII output only. Never use console-script stubs (AppLocker blocks them).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from supervisor.config import REPO_ROOT  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402

EXPORT_REQS_ARGV = [
    "uv",
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "databricks",
    "--no-hashes",
    "--no-emit-project",
    "--no-header",
]
NEXUS_PH = "FILL-ME-nexus-host"
# Commented Nexus switch (docs/BANK_DEPLOY_GUIDE.md section 5.2). `export-reqs --nexus HOST`
# turns the two lines on in the user's LOCAL copy only; the committed file keeps them off.
REQS_HEADER = f"""\
# Exported from uv.lock. Do not edit. Regenerate: uv run python -m supervisor.cli export-reqs
# (= uv export --frozen --no-dev --extra databricks --no-hashes --no-emit-project --no-header)
# The Databricks App installs this file at BUILD; the runtime has no package index.
# If BUILD cannot reach PyPI, switch to the bank Nexus GROUP index in your LOCAL copy only:
#   uv run python -m supervisor.cli export-reqs --nexus <nexus host>
# That turns on the two lines below. Never commit the result.
# --index-url https://{NEXUS_PH}/repository/pypi-common-group/simple/
# --trusted-host {NEXUS_PH}
"""
_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def render_requirements(exported: str, nexus_host: str | None = None) -> str:
    """requirements.txt text: the header (Nexus lines commented, or on) + uv export output."""
    header = REQS_HEADER
    if nexus_host is not None:
        if nexus_host.startswith("FILL-ME") or not _HOSTNAME.match(nexus_host):
            raise SupervisorError(f"--nexus needs a plain host name, got {nexus_host!r}")
        header = header.replace(
            f"# --index-url https://{NEXUS_PH}/", f"--index-url https://{nexus_host}/"
        ).replace(f"# --trusted-host {NEXUS_PH}", f"--trusted-host {nexus_host}")
    return header + exported


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from supervisor.config import load_settings

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"[OK] serving on http://{host}:{port} (mode={settings.supervisor_mode})")
    uvicorn.run("supervisor.app:app", host=host, port=port, log_level="info")
    return 0


def cmd_preflight(_: argparse.Namespace) -> int:
    from supervisor.preflight import main

    return main()


def cmd_demo(args: argparse.Namespace) -> int:
    """WP11 demo harness: seed, 4 incidents, tamper test, reset (supervisor.demo.runbook)."""
    from supervisor.demo import runbook

    return runbook.main(list(getattr(args, "demo_args", None) or []))


def cmd_verify(args: argparse.Namespace) -> int:
    from supervisor.evidence import verify

    argv = [args.export_dir]
    if args.pubkey:
        argv += ["--pubkey", args.pubkey]
    if args.anchors:
        argv += ["--anchors", args.anchors]
    if args.strict:
        argv.append("--strict")
    if args.partial:
        argv.append("--partial")
    return int(verify.main(argv))


def cmd_export_reqs(args: argparse.Namespace) -> int:
    from supervisor import sandbox

    out = Path(args.output).resolve() if args.output else REPO_ROOT / "requirements.txt"
    nexus = getattr(args, "nexus", None)
    text = render_requirements("", nexus)  # validate --nexus before running uv
    result = sandbox.run(EXPORT_REQS_ARGV, cwd=REPO_ROOT, timeout_s=300)
    if not result.ok:
        print("[FAIL] uv export failed:")
        print(result.stderr.encode("ascii", "backslashreplace").decode("ascii"))
        return 1
    text = render_requirements(result.stdout, nexus)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] wrote {out}".encode("ascii", "backslashreplace").decode("ascii"))
    if nexus:
        print(f"[OK] Nexus index lines are ON ({nexus}). Local copy only: do not commit this file.")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """WP11 hand-off zip: archive of HEAD + requirements + uv.toml + HANDOFF + leak sweep."""
    from supervisor import release

    return release.main(list(getattr(args, "release_args", None) or []))


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def cmd_support_bundle(args: argparse.Namespace) -> int:
    """WP18: settings (redacted), preflight, schema, chain heads, masked logs, env -> zip."""
    from supervisor.config import load_settings
    from supervisor.ops.support import build_support_bundle

    settings = load_settings()
    zpath, hashes = build_support_bundle(
        settings,
        Path(args.out),
        log_lines=args.log_lines,
        force=args.force,
        network=args.network,
    )
    for name in sorted(hashes):
        print(_ascii(f"[OK] {name} sha256={hashes[name][:16]}"))
    print(_ascii(f"[OK] wrote {zpath}"))
    if not args.network:
        print("[SKIP] network checks not run (add --network to include them)")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """WP18: SQLite online backup (+ anchors, + signing key with --include-key)."""
    from supervisor.config import load_settings
    from supervisor.ops import backup

    settings = load_settings()
    if settings.effective_sql_backend != "sqlite":
        print("[FAIL] backup is for SQLite mode; use export-delta")
        return 1
    m = backup.backup(settings, Path(args.out), include_key=args.include_key)
    out = Path(args.out).resolve()
    print(_ascii(f"[OK] database copy {out / backup.DB_NAME} ({m['db_size']} bytes)"))
    print(_ascii(f"[OK] tables {len(m['table_counts'])}, rows {sum(m['table_counts'].values())}"))
    print(_ascii(f"[OK] chain lanes {len(m['chain_lane_heads'])}, anchors {m['anchor_files']}"))
    if m["signing_key_included"]:
        print("[OK] signing key included")
        print("[WARN] the backup folder holds the signing key: store it as a secret")
    else:
        print("[SKIP] signing key not included (use --include-key, or back up SIGNER_KEY_PATH)")
    print(_ascii(f"[OK] manifest {out / backup.MANIFEST}"))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """WP18: restore a backup, then verify the evidence chain."""
    from supervisor.config import load_settings
    from supervisor.ops import backup

    settings = load_settings()
    r = backup.restore(
        settings,
        Path(args.src),
        force=args.force,
        pubkey=Path(args.pubkey) if args.pubkey else None,
        allow_key_change=args.allow_key_change,
    )
    if r["moved_aside"]:
        print(_ascii(f"[OK] existing store moved aside: {r['moved_aside']}"))
    print(_ascii(f"[OK] restored {r['target']}"))
    if r["key_restored"]:
        print("[OK] signing key restored")
    if r["anchors_restored"]:
        print(f"[OK] anchors restored: {r['anchors_restored']}")
    for w in r["warnings"]:
        print(_ascii(f"[WARN] {w}"))
    if r["verify_ok"]:  # always true here: a failed verify raises before the swap
        print("[OK] evidence chain verifies")
        return 0
    print("[FAIL] evidence chain does not verify")
    for line in r["verify_lines"][-10:]:
        print(_ascii("  " + line))
    return 1


def cmd_export_delta(args: argparse.Namespace) -> int:
    """WP18: read every table (one SELECT each) into DIR/<table>.jsonl."""
    from supervisor.config import load_settings
    from supervisor.ops import backup

    settings = load_settings()
    tables = [t.strip() for t in args.tables.split(",") if t.strip()] if args.tables else None
    m = backup.export_delta(settings, Path(args.out), tables=tables, include_raw=args.include_raw)
    for name, info in m["tables"].items():
        print(_ascii(f"[OK] {name}: {info['rows']} rows"))
    for name in m.get("skipped_restricted", []):
        print(_ascii(f"[SKIP] {name}: restricted raw capture (add --include-raw)"))
    print(_ascii(f"[OK] manifest {Path(args.out).resolve() / backup.MANIFEST}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m supervisor.cli", description="Supervisor CLI")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=cmd_serve)
    sub.add_parser("preflight", help="check config and environment").set_defaults(
        func=cmd_preflight
    )
    # demo and release parse their own options (main() hands them the rest of argv).
    sub.add_parser(
        "demo", help="demo harness: seed, inject 1-4, tamper, reset, serve (WP11)"
    ).set_defaults(func=cmd_demo)
    v = sub.add_parser("verify", help="verify an evidence export offline (WP6)")
    v.add_argument("export_dir", nargs="?", default=".")
    v.add_argument("--pubkey", default=None, help="pinned notary public key (PEM)")
    v.add_argument("--anchors", default=None, help="directory of anchor documents")
    v.add_argument("--strict", action="store_true", help="fail on entries not yet sealed")
    v.add_argument("--partial", action="store_true", help="accept a lane (partial) export")
    v.set_defaults(func=cmd_verify)
    r = sub.add_parser("export-reqs", help="write requirements.txt from uv.lock")
    r.add_argument("-o", "--output", default=None, help="output file (default: requirements.txt)")
    r.add_argument(
        "--nexus",
        default=None,
        metavar="HOST",
        help="turn on the Nexus --index-url/--trusted-host lines (local copy only)",
    )
    r.set_defaults(func=cmd_export_reqs)
    sb = sub.add_parser("support-bundle", help="redacted diagnostics zip for support (WP18)")
    sb.add_argument("--out", required=True, help="output directory (created)")
    sb.add_argument("--log-lines", type=int, default=500, help="log lines to include")
    sb.add_argument("--force", action="store_true", help="allow a non-empty output directory")
    sb.add_argument("--network", action="store_true", help="also run network preflight checks")
    sb.set_defaults(func=cmd_support_bundle)
    bk = sub.add_parser("backup", help="SQLite online backup (WP18)")
    bk.add_argument("--out", required=True, help="backup directory (empty or new)")
    bk.add_argument("--include-key", action="store_true", help="also copy the signing key")
    bk.set_defaults(func=cmd_backup)
    rs = sub.add_parser("restore", help="restore a backup and verify the chain (WP18)")
    rs.add_argument("--from", dest="src", required=True, help="backup directory")
    rs.add_argument("--force", action="store_true", help="move an existing store aside")
    rs.add_argument(
        "--pubkey",
        default=None,
        help="PEM public key to pin for the chain check (default: the current signer's key)",
    )
    rs.add_argument(
        "--allow-key-change",
        action="store_true",
        help="accept a backup signed by a different key (prints a WARNING with both fingerprints)",
    )
    rs.set_defaults(func=cmd_restore)
    ed = sub.add_parser("export-delta", help="export every table to JSONL (WP18)")
    ed.add_argument("--out", required=True, help="export directory (empty or new)")
    ed.add_argument("--tables", default=None, help="comma list of tables (default: all)")
    ed.add_argument(
        "--include-raw",
        action="store_true",
        help="also export agent_event_raw (unmasked capture; store as restricted data)",
    )
    ed.set_defaults(func=cmd_export_delta)
    sub.add_parser("release", help="build the hand-off zip (WP11)").set_defaults(func=cmd_release)
    return p


PASSTHROUGH = {"demo": "demo_args", "release": "release_args"}  # own argparse inside


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH:
        # demo and release parse their own options (any order), so hand them the rest.
        args = argparse.Namespace(command=argv[0], **{PASSTHROUGH[argv[0]]: argv[1:]})
        args.func = cmd_demo if argv[0] == "demo" else cmd_release
    else:
        args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
