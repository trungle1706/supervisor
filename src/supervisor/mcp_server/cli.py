"""Command line of the MCP server (WP-G6). ASCII output.

  python -m supervisor.mcp_server [serve] [--host H] [--port P]   serve POST /mcp alone
  python -m supervisor.mcp_server tools                           the registered tools
  python -m supervisor.mcp_server app issue NAME --scopes S --by USER [--roles R] [--out-key-file F]
  python -m supervisor.mcp_server app rotate APP_ID --by USER [--out-key-file F]
  python -m supervisor.mcp_server app list
  python -m supervisor.mcp_server app approve APP_ID --by USER
  python -m supervisor.mcp_server app block APP_ID --by USER

Needs MCP_SERVER_ENABLED=1; with the flag off every command prints [SKIP] and does nothing.
``serve`` is for a host without the main app. When the main app runs, it already serves /mcp
(two processes must not write the same evidence chain). A new app is ``pending`` until it is
approved; the secret is shown once (or written to --out-key-file, mode 600).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from supervisor.core.errors import SupervisorError

SKIP = "[SKIP] the MCP server is off (MCP_SERVER_ENABLED=1 turns it on)"


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def make_app() -> Any:
    """A small FastAPI app with only ``POST /mcp``: it builds the runtime at startup."""
    import logging

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    from supervisor import __version__
    from supervisor.config import get_settings
    from supervisor.console import context as console_context
    from supervisor.gateway import wiring as gate_wiring
    from supervisor.mcp_server.routes import mcp_router

    log = logging.getLogger("supervisor.mcp_server")

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        try:
            await run_in_threadpool(gate_wiring.install_runtime, get_settings())
        except Exception:  # noqa: BLE001 - the route retries the build on first use
            log.exception("runtime build failed at startup")
        try:
            yield
        finally:
            console_context.set_context(None)
            gate_wiring.shutdown_runtime()

    app = FastAPI(
        title="Supervisor MCP",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(mcp_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(SupervisorError)
    async def _bad(request: Request, exc: SupervisorError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error class=%s", type(exc).__name__, exc_info=exc)
        return JSONResponse(
            status_code=400, content={"error": f"unexpected error: {type(exc).__name__}"}
        )

    return app


def _serve(args: argparse.Namespace, settings: Any) -> int:
    import uvicorn

    host = args.host or settings.mcp_server_host
    port = args.port or settings.mcp_server_port
    if host not in ("127.0.0.1", "localhost", "::1"):
        _say(f"[WARN] listening on {host}: the traffic is signed, not encrypted; put TLS in front")
    _say(f"[OK] serving POST /mcp on http://{host}:{port}/mcp (one process, one worker)")
    uvicorn.run(make_app(), host=host, port=int(port), workers=1, log_level="warning")
    return 0


def _write_secret_file(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if os.name == "posix":
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret + "\n")


def _audit(adapters: Any, by: str, detail: str, app_id: str | None) -> None:
    from supervisor.adapters.auth.audit import write_action

    write_action(
        adapters.tables,
        adapters.clock,
        request_id=None,
        actor=None,
        actor_fallback=(by, "operator", "cli"),
        permission="mcp.apps",
        method="CLI",
        path="supervisor.mcp_server app",
        outcome="ok",
        target_kind="mcp_app",
        target_id=app_id,
        detail=detail,
    )


def _store_secret(
    settings: Any, app_id: str, secret: str, rotate: bool, out_file: Path | None
) -> None:
    """Put the new secret where the verifier reads it, and give it to the operator once."""
    from supervisor.adapters.auth.agent_creds import (
        FileKeyStore,
        KeyStoreError,
        env_name,
        rotate_keys,
    )

    kind = settings.effective_ingress_key_store
    if kind == "file":
        store = FileKeyStore(settings.ingress_keys_file)
        try:
            data = store.read_all()
        except KeyStoreError as exc:
            raise SupervisorError(str(exc)) from None
        if not rotate and data.get(app_id):
            raise SupervisorError(f"{app_id} already has a key in the key file; use app rotate")
        overlap = timedelta(hours=settings.ingress_key_overlap_hours)
        data[app_id] = rotate_keys(data.get(app_id, []), secret, datetime.now(UTC), overlap)
        store.write_all(data)
        _say(f"[OK] key stored in {Path(settings.ingress_keys_file).name} for {app_id}")
    else:
        _say(f"[OK] new key for {app_id} (store kind is {kind}; this command cannot write it)")
        if kind == "env":
            _say(f"     set {env_name(app_id)}=<secret>")
        else:
            scope = settings.ingress_secret_scope
            _say(f"     put it in secret agent-{app_id}-current of scope {scope}")
    if out_file is not None:
        _write_secret_file(out_file, secret)
        _say(f"     secret written to {out_file.name} (chmod 600); give it to the app")
    else:
        _say(f"     secret (shown once): {secret}")


def _app_cmd(args: argparse.Namespace, settings: Any) -> int:
    from supervisor.adapters.factory import build_adapters
    from supervisor.gateway.ingress_sign import new_secret
    from supervisor.jobs import bootstrap_schema
    from supervisor.mcp_server.apps import McpAppService

    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        svc = McpAppService(adapters.state, adapters.clock)
        if args.app_cmd == "list":
            rows = svc.list_apps()
            _say(f"{'APP':32} {'STATUS':9} {'ROLES':16} SCOPES")
            for r in rows:
                _say(
                    f"{r['app_id']:32} {r['status']:9} {','.join(r['roles']):16} "
                    f"{','.join(r['scopes'])}"
                )
            _say(f"[OK] {len(rows)} app(s)")
            return 0
        if args.app_cmd == "issue":
            secret = new_secret()
            scopes = [x for x in args.scopes.split(",") if x]
            roles = [x for x in (args.roles or "").split(",") if x]
            row = svc.create(args.name, scopes, roles, args.by, secret)
            _store_secret(settings, row["app_id"], secret, False, args.out_key_file)
            _audit(adapters, args.by, "issue", row["app_id"])
            _say(f"[OK] app {row['app_id']} is pending; an admin approves it before tools work")
        elif args.app_cmd == "rotate":
            secret = new_secret()
            svc.get(args.app_id)
            svc.set_key(args.app_id, secret)
            _store_secret(settings, args.app_id, secret, True, args.out_key_file)
            _audit(adapters, args.by, "rotate", args.app_id)
        elif args.app_cmd == "approve":
            svc.approve(args.app_id, args.by)
            _audit(adapters, args.by, "approve", args.app_id)
            _say(f"[OK] {args.app_id} is approved")
        else:
            svc.block(args.app_id, args.by)
            _audit(adapters, args.by, "block", args.app_id)
            _say(f"[OK] {args.app_id} is blocked")
        return 0
    finally:
        adapters.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.mcp_server", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="")
    p.add_argument("--port", type=int, default=0)
    sub.add_parser("tools")
    app = sub.add_parser("app")
    asub = app.add_subparsers(dest="app_cmd", required=True)
    p = asub.add_parser("issue")
    p.add_argument("name")
    p.add_argument("--scopes", required=True, help="comma list of governance.read, ...")
    p.add_argument("--roles", default="", help="console roles of the app (default viewer)")
    p.add_argument("--by", required=True)
    p.add_argument("--out-key-file", type=Path)
    p = asub.add_parser("rotate")
    p.add_argument("app_id")
    p.add_argument("--by", required=True)
    p.add_argument("--out-key-file", type=Path)
    asub.add_parser("list")
    for name in ("approve", "block"):
        p = asub.add_parser(name)
        p.add_argument("app_id")
        p.add_argument("--by", required=True)
    args = ap.parse_args(argv)
    cmd = args.cmd or "serve"
    if cmd == "serve" and not hasattr(args, "host"):
        args.host, args.port = "", 0

    from supervisor.config import load_settings

    try:
        settings = load_settings()
        if not settings.mcp_server_enabled:
            _say(SKIP)
            return 0
        if cmd == "tools":
            from supervisor.mcp_server.server import build_registry

            for t in build_registry():
                _say(f"{t.name:24} {t.scope:18} {'write' if t.write else 'read'}")
            return 0
        if cmd == "app":
            return _app_cmd(args, settings)
        return _serve(args, settings)
    except (SupervisorError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
