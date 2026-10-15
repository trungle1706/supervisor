from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.testclient import TestClient

from supervisor.config import load_settings
from supervisor.ops import middleware as M
from supervisor.ops.logging_setup import log_ctx, set_principal_id


def make_app(tmp_path, **kw) -> TestClient:
    s = load_settings(data_dir=tmp_path, **kw)
    app = FastAPI()

    @app.get("/api/x")
    def get_x(request: Request):
        set_principal_id("bob")
        return {"rid": request.state.request_id, "ctx": dict(log_ctx.get() or {})}

    @app.post("/api/x")
    async def post_x(request: Request):
        return {"n": len(await request.body())}

    @app.post("/gate/check")
    def gate():
        return {"ok": True}

    @app.get("/console/page", response_class=HTMLResponse)
    def page():
        return "<html></html>"

    @app.post("/console/act", response_class=HTMLResponse)
    async def act(request: Request):
        return str(len(await request.body()))

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"a", b"b"]), media_type="text/plain")

    M.install(app, s)
    return TestClient(app)


def test_request_id_generated_echoed_and_validated(tmp_path):
    c = make_app(tmp_path)
    r = c.get("/api/x")
    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", rid) and r.json()["rid"] == rid
    assert r.json()["ctx"] == {"request_id": rid, "principal_id": "bob"}
    ok = c.get("/api/x", headers={"X-Request-ID": "abc-12345.x"})
    assert ok.headers["x-request-id"] == "abc-12345.x"
    bad = c.get("/api/x", headers={"X-Request-ID": "bad id!"})
    assert bad.headers["x-request-id"] != "bad id!"
    short = c.get("/api/x", headers={"X-Request-ID": "abc"})
    assert short.headers["x-request-id"] != "abc"


def test_security_headers_on_api_and_console(tmp_path):
    c = make_app(tmp_path)
    for url in ("/api/x", "/console/page"):
        h = c.get(url).headers
        assert "script-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY"
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in h
    assert c.get("/console/page").headers["cache-control"] == "no-store"
    assert "cache-control" not in c.get("/api/x").headers
    assert c.get("/stream").text == "ab"


def test_hsts_and_headers_off(tmp_path):
    hsts = make_app(tmp_path, hsts_enabled=True).get("/api/x")
    assert "strict-transport-security" in hsts.headers
    off = make_app(tmp_path, security_headers_enabled=False).get("/api/x")
    assert "content-security-policy" not in off.headers and "x-request-id" in off.headers


def test_body_limit_413_by_length_and_stream(tmp_path):
    c = make_app(tmp_path, max_request_bytes=1000)
    assert c.post("/api/x", content=b"a" * 500).json() == {"n": 500}
    r = c.post("/api/x", content=b"a" * 2000)
    assert r.status_code == 413 and "too large" in r.json()["error"]
    assert "content-security-policy" in r.headers
    r2 = c.post("/console/act", content=b"a" * 2000)
    assert r2.status_code == 413 and "too large" in r2.text and "<" in r2.text

    def chunks():
        yield b"a" * 600
        yield b"a" * 600

    r3 = c.post("/api/x", content=chunks())  # chunked: no Content-Length
    assert r3.status_code == 413


def test_body_limit_off(tmp_path):
    c = make_app(tmp_path, max_request_bytes=0)
    assert c.post("/api/x", content=b"a" * 50_000).json() == {"n": 50_000}


def test_rate_limit_429_and_exemptions(tmp_path):
    c = make_app(tmp_path, rate_limit_enabled=True, rate_limit_per_minute=1, rate_limit_burst=2)
    h = {"X-Dev-User": "alice"}
    assert c.post("/api/x", headers=h).status_code == 200
    assert c.post("/api/x", headers=h).status_code == 200
    r = c.post("/api/x", headers=h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert "too many" in r.json()["error"]
    assert c.post("/console/act", headers=h).status_code == 429
    assert c.get("/api/x", headers=h).status_code == 200  # GET is never limited
    assert c.post("/api/x", headers={"X-Dev-User": "carol"}).status_code == 200  # own bucket
    for _ in range(10):
        assert c.post("/gate/check", headers=h).status_code == 200  # agent ingress exempt


def test_rate_limit_off_by_default(tmp_path):
    c = make_app(tmp_path)
    assert all(c.post("/api/x").status_code == 200 for _ in range(200))


def test_token_bucket_refill_and_bounded():
    now = [0.0]
    b = M.TokenBuckets(60, 1, max_keys=3, clock=lambda: now[0])
    assert b.take("a") == 0.0 and b.take("a") > 0
    now[0] = 1.0
    assert b.take("a") == 0.0
    for k in "bcdef":
        b.take(k)
    assert len(b) == 3


def test_templates_have_no_inline_script_or_handlers():
    root = Path(M.__file__).resolve().parents[1] / "console" / "templates"
    for f in root.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", text, re.I), f
        assert not re.search(r"\son[a-z]+\s*=", text, re.I), f
        assert "hx-on" not in text and "js:" not in text, f
        assert not re.search(r'hx-trigger="[^"]*\[', text), f  # trigger filters use eval
