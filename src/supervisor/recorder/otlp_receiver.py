"""OTLP/HTTP trace receiver: ``POST /v1/traces`` with JSON bodies.

* ``Content-Type: application/json`` only. Protobuf (``application/x-protobuf``) and any
  other type get HTTP 415 with a message (send JSON: ``OTEL_EXPORTER_OTLP_PROTOCOL=http/json``).
* ``Content-Encoding: gzip`` is accepted. The body limit (``OTLP_MAX_BODY_BYTES``) applies
  to the raw and to the decompressed size; the span limit is ``OTLP_MAX_SPANS``.
* Malformed JSON or OTLP shape, too many spans, too large a body: HTTP 400 with a message.
* Success: HTTP 200 with an OTLP ``ExportTraceServiceResponse`` body (``{}``); counts are in
  ``X-Supervisor-*`` headers. Spans that are not agent events are ignored, not rejected.
* Auth (WP20): ``authorize`` checks the per-agent credential when ``INGRESS_AUTH_ENABLED=1``
  (401/403, ``gateway/ingress_auth.py``). A batch may only carry spans of the authenticated
  agent id(s); otherwise HTTP 403, nothing is written, ``X-Supervisor-Rejected`` = foreign spans.
  With the flag off, ``authorize`` only reads the SSO header and accepts every caller.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from supervisor.config import get_settings
from supervisor.gateway.ingress_auth import INGRESS_ATTR, check_span_agents, ingress_traces
from supervisor.recorder.normalise import OtlpFormatError, spans_from_otlp_json
from supervisor.recorder.service import Recorder, get_recorder

router = APIRouter(tags=["traces"])
JSON_TYPES = ("application/json",)
PROTOBUF_TYPES = ("application/x-protobuf", "application/protobuf")


class BodyTooLarge(Exception):
    pass


def recorder_dep() -> Recorder:
    return get_recorder()


async def authorize(request: Request) -> str | None:
    """Auth hook (WP20). Returns the caller principal id or None.

    Ingress auth on: the credential is verified (``IngressRejected`` = 401/403 otherwise) and
    the identity is kept on ``request.state.ingress`` for the span check. Off: the SSO header
    is read and every caller is accepted, as before."""
    ident = await ingress_traces(request)
    if ident is not None:
        return ident.principal
    return request.headers.get("x-forwarded-user") or None


setattr(authorize, INGRESS_ATTR, True)  # noqa: B010 - the ingress contract test looks for it


_REC: Recorder = Depends(recorder_dep)
_WHO: str | None = Depends(authorize)


def _limits() -> tuple[int, int]:
    s = get_settings()
    return s.otlp_max_body_bytes, s.otlp_max_spans


def _bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise BodyTooLarge
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise BodyTooLarge
    return bytes(buf)


def _gunzip(data: bytes, limit: int) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(data, limit + 1)
    if len(out) > limit or d.unconsumed_tail:
        raise BodyTooLarge
    return out


@router.post("/v1/traces")
async def receive_traces(request: Request, rec: Recorder = _REC, who: str | None = _WHO) -> Any:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype in PROTOBUF_TYPES:
        return _bad(
            "OTLP protobuf is not supported. Send OTLP/HTTP JSON "
            "(Content-Type: application/json; OTEL_EXPORTER_OTLP_PROTOCOL=http/json).",
            415,
        )
    if ctype not in JSON_TYPES:
        return _bad(f"unsupported content type {ctype or '(none)'!r}; use application/json", 415)
    max_bytes, max_spans = _limits()
    try:
        body = await _read_body(request, max_bytes)
        encoding = request.headers.get("content-encoding", "").strip().lower()
        if encoding == "gzip":
            body = _gunzip(body, max_bytes)
        elif encoding not in ("", "identity"):
            return _bad(f"unsupported content encoding {encoding!r}; use gzip or none", 415)
    except BodyTooLarge:
        return _bad(
            f"body larger than {max_bytes} bytes (OTLP_MAX_BODY_BYTES); send smaller batches"
        )
    except zlib.error:
        return _bad("body is not valid gzip")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _bad("body is not valid UTF-8 JSON")
    try:
        spans = spans_from_otlp_json(payload)
    except OtlpFormatError as exc:
        return _bad(f"invalid OTLP JSON: {exc}")
    if len(spans) > max_spans:
        return _bad(f"{len(spans)} spans in one request; the limit is {max_spans} (OTLP_MAX_SPANS)")
    agent_of = getattr(getattr(rec, "normaliser", None), "agent_id_of", None)
    if agent_of is not None:  # WP20: spans of another agent than the credential's: batch 403
        check_span_agents(request, [agent_of(sp) for sp in spans])
    result = await run_in_threadpool(rec.ingest_spans, spans, "otlp")
    headers = {
        "X-Supervisor-Accepted": str(result.written),
        "X-Supervisor-Duplicates": str(result.duplicates),
        "X-Supervisor-Ignored": str(result.ignored),
        "X-Supervisor-Spooled": str(result.spooled),
    }
    return JSONResponse(status_code=200, content={}, headers=headers)
