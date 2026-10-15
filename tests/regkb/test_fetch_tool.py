"""Offline tests for tools/regkb_fetch.py (no network)."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "regkb_fetch.py"

_spec = importlib.util.spec_from_file_location("regkb_fetch", TOOL_PATH)
assert _spec is not None and _spec.loader is not None
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

SAMPLE = """<html><head><title>Thong tu 09</title><style>.x{}</style></head>
<body><nav>MENU</nav><script>var a=1;</script>
<div class="sidebar">Quang cao</div>
<div class="content1"><p>Dieu 1. Pham vi</p><p>Noi dung &amp; hon nua</p></div>
<footer>FOOT</footer></body></html>"""


def test_extract_thuvienphapluat() -> None:
    text, title = tool.extract_html_text(SAMPLE, "thuvienphapluat.vn")
    assert title == "Thong tu 09"
    assert text == "Dieu 1. Pham vi\n\nNoi dung & hon nua"
    assert "MENU" not in text and "Quang cao" not in text


def test_extract_fallback_whole_body() -> None:
    text, _ = tool.extract_html_text(SAMPLE, "example.gov.vn")
    assert "Quang cao" in text and "Dieu 1" in text
    assert "MENU" not in text and "var a" not in text and "FOOT" not in text


def test_sidecar_format_and_sha(tmp_path: Path) -> None:
    data = "Điều 1".encode()
    p = tool.write_source(
        tmp_path,
        "VN-TT-09-2020",
        "main",
        "txt",
        data,
        url="https://vbpl.vn/x",
        title="T",
        content_type="text/plain",
    )
    assert p == tmp_path / "VN-TT-09-2020" / "main.txt"
    side = tmp_path / "VN-TT-09-2020" / "main.meta.json"
    meta = json.loads(side.read_text(encoding="utf-8"))
    assert set(meta) == {"url", "title", "fetched_at", "sha256", "content_type", "tool"}
    assert meta["sha256"] == hashlib.sha256(data).hexdigest()
    assert meta["tool"] == "regkb_fetch/1"
    assert meta["fetched_at"].endswith("Z") and len(meta["fetched_at"]) == 20
    keys = list(json.loads(side.read_text(encoding="utf-8")))
    assert keys == sorted(keys)


def test_bad_ids_refused(tmp_path: Path) -> None:
    with pytest.raises(tool.FetchError):
        tool.write_source(
            tmp_path, "bad id", "a", "txt", b"x", url="u", title="t", content_type="c"
        )
    with pytest.raises(tool.FetchError):
        tool.write_source(
            tmp_path, "VN-TT", "Bad Slug", "txt", b"x", url="u", title="t", content_type="c"
        )


def test_host_allow_list(tmp_path: Path) -> None:
    assert tool.host_allowed("https://vbpl.vn/a")
    assert tool.host_allowed("https://www.thuvienphapluat.vn/a")
    assert tool.host_allowed("https://vbpl-bientap-gateway.moj.gov.vn/api")
    assert not tool.host_allowed("https://evil.example.com/a")
    assert not tool.host_allowed("https://notvbpl.vn/a")
    assert tool.host_allowed("https://evil.example.com/a", ("evil.example.com",))
    with pytest.raises(tool.FetchError, match="host not allowed"):
        tool.fetch_url("https://evil.example.com/a", "VN-TT-1", tmp_path)
    assert (
        tool.main(
            [
                "--root",
                str(tmp_path),
                "url",
                "https://evil.example.com/a",
                "--instrument",
                "VN-TT-1",
            ]
        )
        == 1
    )


def test_parse_rsc() -> None:
    text = '0:["$@1",null]\n1:{"total":2,"items":[{"id":"a","docNum":"09/2020"}]}\n'
    data = tool.parse_rsc(text)
    assert data["total"] == 2
    assert tool.search_rows(data)[0][:2] == ["a", "09/2020"]
    with pytest.raises(tool.FetchError):
        tool.parse_rsc('1:E{"digest":"123"}')
    with pytest.raises(tool.FetchError):
        tool.parse_rsc("0:nothing")


def test_search_body() -> None:
    body = json.loads(tool.build_search_body("ai", 62, ["TT"], "2025-01-01", 20))[0]
    assert body["agencyIds"] == [62]
    assert body["docType"] == [tool.DOC_TYPES["TT"]]
    assert body["issueDateFrom"] == "2025-01-01T00:00:00"


def test_action_id_regex() -> None:
    chunk = 'x=(0,n.$)("' + "ab" * 20 + '");y=(0,n.$)("short")'
    assert tool.ACTION_RE.findall(chunk) == ["ab" * 20]


def test_strip_diacritics() -> None:
    assert tool.strip_diacritics("Ngân hàng Nhà nước Đ") == "Ngan hang Nha nuoc D"


def test_verify_detects_tamper(tmp_path: Path) -> None:
    p = tool.write_source(
        tmp_path, "VN-TT-1", "a", "txt", b"hello", url="u", title="t", content_type="c"
    )
    assert tool.verify(tmp_path) == 0
    p.write_bytes(b"hellO")
    assert tool.verify(tmp_path) == 1
    p.write_bytes(b"hello")
    (tmp_path / "VN-TT-1" / "a.meta.json").unlink()
    assert tool.verify(tmp_path) == 1


def test_src_does_not_import_tool() -> None:
    bad = []
    for f in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "tools" or "regkb_fetch" in n for n in names):
                bad.append(str(f))
    assert not bad
