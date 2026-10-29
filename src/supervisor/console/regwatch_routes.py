"""Regulation watcher: import of the signed update package and the watch page (WP-W1,
REGWATCH_ENABLED, docs/regulations.md "Watcher and update package (WP-W1)").

The routers are always mounted; with the flag off every route answers HTTP 400 ``regwatch_off``
and nothing is read or written.

JSON API (admin):

* ``POST /v1/regkb/import``        multipart ``file`` = the package zip (50 MB at most); 201 when
  the package is new, 200 when the same package is already stored. Checks the signature with the
  trusted public key and every member sha against the manifest; stores under
  ``DATA_DIR/regkb/incoming/<package sha>/``. **Nothing is applied.** Refusals are HTTP 400 with a
  code: nothing_to_import, too_large, bad_zip, path_traversal, unknown_member, bad_manifest,
  bad_signature, untrusted_key, sha_mismatch.
* ``GET  /v1/regkb/watch/runs``     the ``regwatch_run`` rows and the reports of the job
* ``GET  /v1/regkb/watch/packages`` the imported packages with their changes

Console: ``GET /console/regkb/watch`` lists runs, reports and imported packages; every change
shows "pending review (WP-W2)". Not legal advice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from supervisor.adapters.auth import AuthPrincipal, current_principal
from supervisor.adapters.auth.authz import needs
from supervisor.cases.service import PermissionDenied
from supervisor.console.context import ConsoleContext, get_context
from supervisor.console.intake_routes import _same_site, parse_multipart
from supervisor.console.routes import _call, audited, render
from supervisor.core.canonical import format_ts
from supervisor.regkb import change, package, watch

router = APIRouter(prefix="/console", tags=["console"])
api_router = APIRouter(prefix="/v1", tags=["console"])
_CTX = Depends(get_context)
_ME = Depends(current_principal)
FORM_SLACK = 256 * 1024
OFF_MESSAGE = "the regulation watcher is off (REGWATCH_ENABLED=1 turns it on)"
MAX_ROWS = 50


def require_on(settings: Any) -> None:
    if not getattr(settings, "regwatch_enabled", False):
        raise package.PackageError("regwatch_off", OFF_MESSAGE)


def _actor(me: AuthPrincipal) -> str:
    if me.kind != "user":
        raise PermissionDenied("this step needs a signed-in person")
    return str(me.user_id)


def trusted_key(ctx: ConsoleContext) -> Any:
    """REGKB_IMPORT_PUBKEY when set, else the public key of this install's evidence signer."""
    path = getattr(ctx.settings, "regkb_import_pubkey", None)
    if path:
        try:
            return package.load_public_key(Path(path).read_bytes())
        except OSError as exc:
            raise package.PackageError(
                "untrusted_key", "REGKB_IMPORT_PUBKEY cannot be read"
            ) from exc
    signer = getattr(getattr(ctx.runtime, "chain", None), "signer", None)
    if signer is None:
        raise package.PackageError("untrusted_key", "no trusted public key is configured")
    return signer.public_key


async def _read_body(request: Request) -> bytes:
    limit = package.MAX_PACKAGE_BYTES + FORM_SLACK
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise package.PackageError("too_large", "the upload is larger than 50 MB")
    body = await request.body()
    if len(body) > limit:
        raise package.PackageError("too_large", "the upload is larger than 50 MB")
    return body


def _import(ctx: ConsoleContext, files: list[tuple[str, bytes]], actor: str) -> tuple[dict, bool]:
    if not files:
        raise package.PackageError("nothing_to_import", "send the package zip in the field 'file'")
    pkg = package.verify_package(files[0][1], trusted_key(ctx))
    summary, is_new = package.store_package(
        Path(ctx.settings.data_dir),
        pkg,
        actor=actor,
        imported_at=format_ts(ctx.clock.now()),
    )
    if is_new:
        s = pkg.report["summary"]
        chain = getattr(ctx.runtime, "chain", None)
        if chain is not None:
            try:
                chain.record(
                    "regkb_import",
                    pkg.sha256[:32],
                    {
                        "package_sha256": pkg.sha256,
                        "run_id": str(pkg.manifest.get("run_id", "")),
                        "key_id": str(pkg.signature.get("key_id", "")),
                        "members": len(pkg.members) + 2,
                        "size": int(pkg.size),
                        "changes_found": int(s.get("changes_found", 0)),
                        "applied": 0,
                    },
                )
            except Exception:  # noqa: BLE001 - the package is stored; the log has the cause
                import logging

                logging.getLogger(__name__).exception("regkb_import chain record failed")
    return summary, is_new


def _run_row(row: Any) -> dict[str, Any]:
    out = dict(row)
    for k in ("started_at", "finished_at"):
        v = out.get(k)
        out[k] = format_ts(v) if isinstance(v, datetime) else (str(v) if v else None)
    return {k: v for k, v in out.items() if k not in ("row_version",)}


def runs_data(ctx: ConsoleContext) -> dict[str, Any]:
    rows = ctx.state.query("regwatch_run", order_by=("started_at",))
    rows = [_run_row(r) for r in rows][::-1][:MAX_ROWS]
    reports = package.list_reports(Path(ctx.settings.data_dir) / "regwatch")[:MAX_ROWS]
    return {"runs": rows, "reports": reports, "review_note": watch.REVIEW_NOTE}


def packages_data(ctx: ConsoleContext) -> dict[str, Any]:
    pk = package.list_packages(Path(ctx.settings.data_dir))[:MAX_ROWS]
    return {"packages": pk, "review_note": watch.REVIEW_NOTE}


# ------------------------------------------------------------------------------- JSON API


@api_router.post("/regkb/import", dependencies=[Depends(needs("regkb.import"))])
@audited("regkb.import")
async def post_import(request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME) -> Any:
    require_on(ctx.settings)
    actor = _actor(me)
    _same_site(request)
    files, _ = parse_multipart(request.headers.get("content-type", ""), await _read_body(request))
    summary, is_new = await _call(_import, ctx, files, actor)
    request.state.audit_detail = f"regkb import {summary['package_sha256'][:16]} new={is_new}"
    brief = {k: v for k, v in summary.items() if k not in ("report", "changes")}
    return JSONResponse(
        status_code=201 if is_new else 200,
        content={**brief, "changes": len(summary["changes"]), "already_imported": not is_new},
    )


@api_router.get("/regkb/watch/runs", dependencies=[Depends(needs("regkb.watch"))])
async def list_runs(ctx: ConsoleContext = _CTX) -> Any:
    require_on(ctx.settings)
    data = await _call(runs_data, ctx)
    return {
        "runs": data["runs"],
        "reports": [
            {
                "file": r["file"],
                "sha256": r["sha256"],
                "summary": r["report"]["summary"],
                "date": r["report"].get("date"),
                "changes": r["changes"],
            }
            for r in data["reports"]
        ],
        "review": data["review_note"],
    }


@api_router.get("/regkb/watch/packages", dependencies=[Depends(needs("regkb.watch"))])
async def list_packages(ctx: ConsoleContext = _CTX) -> Any:
    require_on(ctx.settings)
    data = await _call(packages_data, ctx)
    return {
        "packages": [
            {**{k: v for k, v in p.items() if k != "report"}, "summary": p["report"].get("summary")}
            for p in data["packages"]
        ],
        "review": data["review_note"],
    }


# ------------------------------------------------------------------------------- console


@router.get(
    "/regkb/watch", response_class=HTMLResponse, dependencies=[Depends(needs("regkb.watch"))]
)
async def watch_page(
    request: Request, ctx: ConsoleContext = _CTX, me: AuthPrincipal = _ME
) -> Response:
    require_on(ctx.settings)
    runs = await _call(runs_data, ctx)
    pk = await _call(packages_data, ctx)
    return render(
        request,
        ctx,
        me,
        "regkb_watch.html",
        section="regkb_watch",
        rw={
            **runs,
            **pk,
            "now": format_ts(datetime.now(UTC)),
            "change_loop": change.enabled(ctx.settings),  # WP-W2: the diff buttons
        },
    )
