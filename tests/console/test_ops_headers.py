from __future__ import annotations


def test_console_page_renders_with_security_headers(console):
    r = console.get("/console/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers
