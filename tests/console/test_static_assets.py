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


FONTS = {
    "plus-jakarta-sans-latin.woff2": "153fc85b70298beeb1d61a5f723331649e7f23bb77302a66e61cb3e2fbdb5e79",
    "plus-jakarta-sans-latin-ext.woff2": (
        "38e3b8fd8045048eb311d90170a4429ed2c8f405852dc3d91b5af8452758703f"
    ),
    "plus-jakarta-sans-vietnamese.woff2": (
        "b275d1258601dda240fc6a1d4a6cad56e691d898f5cdf1b0e4fd6ca0022d8e40"
    ),
    "jetbrains-mono-latin.woff2": "83c005d49d8a6a50474c73a5a36ac0468076e9c4a29da7bdb14995d80560a5be",
    "jetbrains-mono-latin-ext.woff2": "db5ff4db83e580426280e9337a58dc57d3a83784a1b03ad80914651594441d52",
    "jetbrains-mono-vietnamese.woff2": (
        "c89b9cc0bc6262bd4f8d8494b6961601f3aefa829d08c2e3635f4d501d3a47c2"
    ),
}


def test_fonts_are_vendored_woff2_with_licence() -> None:
    """WP12: Plus Jakarta Sans + JetBrains Mono (OFL-1.1) as local woff2; no font CDN."""
    fonts = CONSOLE / "static" / "fonts"
    licences = (CONSOLE.parents[2] / "docs" / "LICENSES.md").read_text(encoding="utf-8")
    for name, sha in FONTS.items():
        data = (fonts / name).read_bytes()
        assert data[:4] == b"wOF2", name
        assert hashlib.sha256(data).hexdigest() == sha, name
        assert sha in licences, name
    for name in ("OFL-PlusJakartaSans.txt", "OFL-JetBrainsMono.txt"):
        assert "SIL Open Font License" in (fonts / name).read_text(encoding="utf-8")
    assert "OFL-1.1" in licences


def test_font_faces_point_at_local_files_only() -> None:
    css = (CONSOLE / "static" / "console.css").read_text(encoding="utf-8")
    assert "@import" not in css
    urls = re.findall(r"url\(([^)]*)\)", css)
    assert len(urls) == 6, "the stylesheet declares the six vendored font files"
    for u in urls:
        assert u.startswith("/console/static/fonts/"), u
        assert (CONSOLE / "static" / "fonts" / u.rsplit("/", 1)[1]).is_file(), u
    assert css.count("--brand:") == 1  # one brand token the owner can swap


def test_templates_load_no_external_assets() -> None:
    html = "".join(p.read_text(encoding="utf-8") for p in (CONSOLE / "templates").glob("*.html"))
    refs = re.findall(r'(?:src|href)="([^"{]+)"', html)
    assert refs
    for ref in refs:
        assert not URL.match(ref) and not ref.startswith("//"), ref
