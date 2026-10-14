"""WP8: vendored htmx, no external assets in templates or static files (offline runtime)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[2] / "src" / "supervisor" / "console"
HTMX_SHA256 = "449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452"
URL = re.compile(r"https?://", re.IGNORECASE)


def test_htmx_is_vendored_and_pinned() -> None:
    data = (CONSOLE / "static" / "htmx.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == HTMX_SHA256
    assert b'version:"1.9.12"' in data
    licence = (CONSOLE / "static" / "htmx.LICENSE.txt").read_text(encoding="utf-8")
    assert licence.startswith("Zero-Clause BSD")
    licences = (CONSOLE.parents[2] / "docs" / "LICENSES.md").read_text(encoding="utf-8")
    assert "1.9.12" in licences and HTMX_SHA256 in licences


def test_no_external_urls_in_templates_or_static() -> None:
    files = [p for p in (CONSOLE / "templates").rglob("*") if p.is_file()]
    files += [p for p in (CONSOLE / "static").rglob("*") if p.suffix in (".css", ".js", ".html")]
    assert files
    offenders = [str(p) for p in files if URL.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders


def test_no_external_fonts() -> None:
    css = (CONSOLE / "static" / "console.css").read_text(encoding="utf-8")
    assert "@import" not in css and "@font-face" not in css and "url(" not in css
