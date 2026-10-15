"""Dev-host-only fetcher for Vietnamese primary legal texts (WP13).

NOT part of the app: nothing under src/ may import this module.
Stores files as regulations/sources/<instrument_id>/<slug>.<ext> plus a .meta.json sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

TOOL = "regkb_fetch/1"
CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
API_BASE = "https://vbpl-bientap-gateway.moj.gov.vn/api"
VBPL = "https://vbpl.vn"
SEARCH_URL = f"{VBPL}/van-ban/tim-kiem"
DEFAULT_ROOT = Path("regulations/sources")
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT = 60.0
MIN_INTERVAL = 1.0
KNOWN_ACTION_ID = "c529d164f28418e5898a834422629e64c6816af1"
DOC_TYPES = {
    "TT": "178c63a9-73ff-4fd4-9d91-18d690520090",
    "QD": "0a5362e8-cdca-436e-96cd-979598df3b16",
    "VBHN": "26b8a9ff-1b59-4c57-9605-f2ad4ed7c324",
}
ALLOWED_HOSTS = (
    "vbpl.vn",
    "vbpl-bientap-gateway.moj.gov.vn",
    "thuvienphapluat.vn",
    "chinhphu.vn",
    "sbv.gov.vn",
    "quochoi.vn",
    "moj.gov.vn",
)
INSTRUMENT_RE = re.compile(r"^(VN|INTL|INT)-[A-Z0-9]+(-[A-Z0-9]+){0,3}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ACTION_RE = re.compile(r"\(0,\w+\.\$\)\(\"([0-9a-f]{40})\"\)")
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def out(msg: str) -> None:
    sys.stdout.write(msg + "\n")


def err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- helpers


def strip_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    norm = unicodedata.normalize("NFD", text)
    plain = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return plain.encode("ascii", "replace").decode("ascii")


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def host_allowed(url: str, extra: tuple[str, ...] = ()) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in (*ALLOWED_HOSTS, *extra))


def check_instrument(instrument: str) -> None:
    if not INSTRUMENT_RE.match(instrument):
        raise FetchError(f"bad instrument id: {instrument}")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", strip_diacritics(text).lower()).strip("-._")
    return s[:80] or "source"


_last_request = 0.0


def _throttle() -> None:
    global _last_request
    delta = MIN_INTERVAL - (time.monotonic() - _last_request)
    if delta > 0:
        time.sleep(delta)
    _last_request = time.monotonic()


def http(
    method: str,
    url: str,
    *,
    allow_hosts: tuple[str, ...] = (),
    headers: dict[str, str] | None = None,
    content: str | None = None,
) -> httpx.Response:
    if not host_allowed(url, allow_hosts):
        raise FetchError(f"host not allowed: {url} (use --allow-host to override)")
    hdrs = {"User-Agent": CHROME_UA, **(headers or {})}
    _throttle()
    chunks: list[bytes] = []
    size = 0
    with (
        httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=hdrs) as client,
        client.stream(method, url, content=content) as resp,
    ):
        for chunk in resp.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise FetchError(f"response larger than {MAX_BYTES} bytes: {url}")
            chunks.append(chunk)
        return httpx.Response(
            resp.status_code,
            headers={
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in ("content-encoding", "content-length")
            },
            content=b"".join(chunks),
            request=resp.request,
        )


# ---------------------------------------------------------------- HTML


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    SKIP = {"script", "style", "nav", "noscript", "header", "footer", "template"}
    VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "source", "wbr"}

    def __init__(self, selectors: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__(convert_charrefs=True)
        self.selectors = selectors  # ("class"|"id", value)
        self.parts: list[str] = []
        self.skip = 0
        self.stack: list[tuple[str, bool]] = []  # (tag, is_selector_root)
        self.in_sel = 0
        self.title = ""
        self._in_title = False

    def _matches(self, attrs: list[tuple[str, str | None]]) -> bool:
        d = dict(attrs)
        return any(val in (d.get(kind) or "").split() for kind, val in self.selectors)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self.VOID:
            if tag == "br" and not self.skip:
                self.parts.append("\n")
            return
        root = bool(self.selectors) and self._matches(attrs)
        self.stack.append((tag, root))
        if root:
            self.in_sel += 1
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self.VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, root in reversed(self.stack[i:]):
                    if t in self.SKIP:
                        self.skip -= 1
                    if root:
                        self.in_sel -= 1
                del self.stack[i:]
                break
        if tag in self.BLOCK and not self.skip:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self.skip or (self.selectors and not self.in_sel):
            return
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts).replace("\xa0", " ")
        lines = [" ".join(ln.split()) for ln in raw.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _run_extract(html: str, selectors: tuple[tuple[str, str], ...]) -> tuple[str, str]:
    p = _TextExtractor(selectors)
    p.feed(html)
    p.close()
    return p.text(), " ".join(p.title.split())


def extract_html_text(html: str, host: str = "") -> tuple[str, str]:
    """Return (main_text, page_title). Falls back to whole-body text."""
    if host.endswith("thuvienphapluat.vn"):
        sels: tuple[tuple[str, str], ...] = (("class", "content1"), ("id", "divContentDoc"))
    elif host.endswith("vbpl.vn"):
        sels = (("class", "article-content"), ("class", "document-content"), ("id", "content"))
    else:
        sels = ()
    if sels:
        text, title = _run_extract(html, sels)
        if text:
            return text, title
    return _run_extract(html, ())


# ---------------------------------------------------------------- storage


def write_source(
    root: Path,
    instrument: str,
    slug: str,
    ext: str,
    data: bytes,
    *,
    url: str,
    title: str,
    content_type: str,
) -> Path:
    check_instrument(instrument)
    if not SLUG_RE.match(slug):
        raise FetchError(f"bad slug: {slug}")
    folder = root / instrument
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.{ext}"
    path.write_bytes(data)
    meta = {
        "url": url,
        "title": title,
        "fetched_at": now_utc(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": content_type,
        "tool": TOOL,
    }
    (folder / f"{slug}.meta.json").write_text(
        json.dumps(meta, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------- url


def fetch_url(
    url: str,
    instrument: str,
    root: Path,
    *,
    slug: str | None = None,
    title: str | None = None,
    raw: bool = False,
    allow_hosts: tuple[str, ...] = (),
) -> list[Path]:
    check_instrument(instrument)
    resp = http("GET", url, allow_hosts=allow_hosts)
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code} for {url}")
    ctype = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    parsed = urllib.parse.urlparse(url)
    base = slug or slugify(Path(parsed.path).stem or parsed.hostname or "source")
    low = parsed.path.lower()
    kw = {"url": url, "title": title or base}
    if "pdf" in ctype or low.endswith(".pdf"):
        return [write_source(root, instrument, base, "pdf", resp.content, content_type=ctype, **kw)]
    if "wordprocessingml" in ctype or low.endswith(".docx"):
        return [
            write_source(root, instrument, base, "docx", resp.content, content_type=ctype, **kw)
        ]
    html = resp.content.decode(resp.encoding or "utf-8", errors="replace")
    text, page_title = extract_html_text(html, (parsed.hostname or "").lower())
    if not text:
        raise FetchError(f"no text extracted from {url}")
    kw["title"] = title or page_title or base
    paths = [
        write_source(
            root,
            instrument,
            base,
            "txt",
            text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            **kw,
        )
    ]
    if raw:
        paths.append(
            write_source(
                root,
                instrument,
                base + ".raw",
                "html",
                resp.content,
                content_type=ctype or "text/html",
                **kw,
            )
        )
    return paths


# ---------------------------------------------------------------- vbpl search


def discover_action_ids(allow_hosts: tuple[str, ...] = ()) -> list[str]:
    """Scan the search page and its JS chunks for 40-hex server action ids (in order)."""
    html = http("GET", SEARCH_URL, allow_hosts=allow_hosts).text
    found = list(ACTION_RE.findall(html))
    srcs = re.findall(r"/_next/static/chunks/[^\"' ]+\.js", html)
    srcs.sort(key=lambda x: ("7325-" not in x, x))
    for src in dict.fromkeys(srcs):
        found += ACTION_RE.findall(http("GET", VBPL + src, allow_hosts=allow_hosts).text)
        if found and "7325-" in src:
            break
    return list(dict.fromkeys(found))


def discover_action_id(allow_hosts: tuple[str, ...] = ()) -> str | None:
    ids = discover_action_ids(allow_hosts)
    return ids[0] if ids else None


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "regkb_fetch" / "vbpl_action_id.txt"


def parse_rsc(text: str) -> dict:
    """Return the JSON object from the RSC line that starts with '1:'."""
    for line in text.splitlines():
        if line.startswith("1:"):
            body = line[2:]
            if body.startswith("E"):
                raise FetchError(f"server action error: {body[:200]}")
            return json.loads(body)
    raise FetchError("no '1:' line in RSC response")


def build_search_body(
    keyword: str,
    agency: int | None,
    doc_types: list[str],
    date_from: str | None,
    page_size: int,
) -> str:
    payload: dict = {
        "pageNumber": 1,
        "pageSize": page_size,
        "sortBy": "issueDate",
        "sortDirection": "desc",
        "groupVbpl": True,
        "optionDoc": "all",
        "matchMode": "all_words",
        "keyword": keyword,
    }
    if agency is not None:
        payload["agencyIds"] = [agency]
    if doc_types:
        payload["docType"] = [DOC_TYPES.get(d.upper(), d) for d in doc_types]
    if date_from:
        payload["issueDateFrom"] = f"{date_from}T00:00:00"
    return json.dumps([payload])


def looks_like_search(data: dict) -> bool:
    items = data.get("items")
    if not isinstance(items, list) or "total" not in data:
        return False
    return all(isinstance(i, dict) and "docNum" in i and "effStatus" in i for i in items)


def _post_search(action_id: str, body: str, allow_hosts: tuple[str, ...]) -> dict:
    resp = http(
        "POST",
        SEARCH_URL,
        allow_hosts=allow_hosts,
        content=body,
        headers={
            "Next-Action": action_id,
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
        },
    )
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code}: {resp.text[:120]}")
    data = parse_rsc(resp.text)
    if not isinstance(data, dict) or not looks_like_search(data):
        raise FetchError("response is not a vbpl search result")
    return data


def vbpl_search(
    keyword: str,
    agency: int | None,
    doc_types: list[str],
    date_from: str | None,
    page_size: int,
    action_id: str | None = None,
    allow_hosts: tuple[str, ...] = (),
) -> tuple[dict, str]:
    body = build_search_body(keyword, agency, doc_types, date_from, page_size)
    cp = cache_path()
    candidates: list[str] = []
    if action_id:
        candidates.append(action_id)
    else:
        try:
            if cp.exists():
                candidates.append(cp.read_text(encoding="utf-8").strip())
        except OSError:
            pass
        candidates.append(KNOWN_ACTION_ID)
    last: Exception | None = None
    for aid in dict.fromkeys(candidates):
        try:
            return _post_search(aid, body, allow_hosts), aid
        except (FetchError, httpx.HTTPError, ValueError) as exc:
            last = exc
            err(f"[SKIP] action id {aid[:8]} failed: {exc}")
    if not action_id:
        for found in discover_action_ids(allow_hosts):
            if found in candidates:
                continue
            try:
                data = _post_search(found, body, allow_hosts)
            except (FetchError, httpx.HTTPError, ValueError):
                continue
            try:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_text(found + "\n", encoding="utf-8")
            except OSError:
                pass
            return data, found
    raise FetchError(f"vbpl search failed: {last}")


def format_table(rows: list[list[str]], headers: list[str]) -> str:
    cells = [[strip_diacritics(str(c)) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, r, strict=True)]
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), "-+-".join("-" * w for w in widths)]
    lines += [fmt.format(*r) for r in cells]
    return "\n".join(lines)


def search_rows(data: dict) -> list[list[str]]:
    rows = []
    for it in data.get("items") or []:
        st = it.get("effStatus") or {}
        dt = it.get("docType")
        rows.append(
            [
                str(it.get("id", "")),
                str(it.get("docNum", "")),
                (dt.get("name", "") if isinstance(dt, dict) else str(dt or "")),
                str(it.get("issueDate") or "")[:10],
                str(it.get("effFrom") or "")[:10],
                str(st.get("name", "") if isinstance(st, dict) else st),
                " ".join(str(it.get("title", "")).split())[:70],
            ]
        )
    return rows


SEARCH_HEADERS = ["id", "number", "type", "issued", "eff_from", "status", "title"]


def vbpl_sitemap(keyword: str, allow_hosts: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    kw = strip_diacritics(keyword).lower().replace(" ", "-")
    hits: list[tuple[str, str]] = []
    for n in range(1, 37):
        try:
            resp = http("GET", f"{VBPL}/sitemap/{n}.xml", allow_hosts=allow_hosts)
        except (FetchError, httpx.HTTPError) as exc:
            err(f"[SKIP] sitemap {n}: {exc}")
            continue
        if resp.status_code != 200:
            continue
        for m in re.finditer(
            r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]*)</lastmod>)?", resp.text
        ):
            if kw in strip_diacritics(urllib.parse.unquote(m.group(1))).lower():
                hits.append((m.group(1), m.group(2) or ""))
    return hits


# ---------------------------------------------------------------- vbpl-doc


def vbpl_id_from(arg: str) -> str:
    m = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", arg
    ) or re.search(r"\d{3,}", arg)
    if not m:
        raise FetchError(f"cannot find a vbpl id in {arg}")
    return m.group(0)


def _download(bucket: str, name: str) -> bytes:
    base = f"{API_BASE}/qtdc/public/doc/minio/buckets/vbpl/{bucket}/"
    errs = []
    for fn in (name, urllib.parse.quote(name, safe="")):
        r = http("GET", f"{base}{fn}/download")
        if r.status_code == 200 and r.content:
            return r.content
        errs.append(f"HTTP {r.status_code}")
    raise FetchError(f"download {name}: {'; '.join(errs)}")


def fetch_vbpl_doc(arg: str, instrument: str, root: Path, slug: str | None = None) -> list[Path]:
    check_instrument(instrument)
    vid = vbpl_id_from(arg)
    api_url = f"{API_BASE}/qtdc/public/doc/{vid}"
    r = http("GET", api_url)
    if r.status_code != 200:
        raise FetchError(f"API HTTP {r.status_code} for {vid}")
    data = r.json().get("data")
    if not data:
        raise FetchError(f"empty data for {vid}")
    title = " ".join((data.get("title") or vid).split())
    base = slug or slugify(str(data.get("docNum") or vid))
    paths: list[Path] = []
    content = (data.get("documentContent") or {}).get("content")
    if content:
        text, _ = _run_extract(content, ())
        if text:
            paths.append(
                write_source(
                    root,
                    instrument,
                    base,
                    "txt",
                    text.encode("utf-8"),
                    url=api_url,
                    title=title,
                    content_type="text/plain; charset=utf-8",
                )
            )
    for key, ext, ctype in (
        ("documentContentFileName", "pdf", "application/pdf"),
        ("documentContentFileDocName", "docx", DOCX_TYPE),
    ):
        fname = data.get(key)
        if not fname:
            continue
        try:
            blob = _download(vid, fname)
        except (FetchError, httpx.HTTPError) as exc:
            err(f"[SKIP] {ext} attachment: {exc}")
            continue
        file_url = f"{API_BASE}/qtdc/public/doc/minio/buckets/vbpl/{vid}/{fname}/download"
        paths.append(
            write_source(
                root,
                instrument,
                f"{base}-{ext}",
                ext,
                blob,
                url=file_url,
                title=title,
                content_type=ctype,
            )
        )
    if not paths:
        raise FetchError(f"no content or attachments for {vid}")
    return paths


# ---------------------------------------------------------------- verify / list


def iter_sources(root: Path) -> Iterator[tuple[str, Path, Path]]:
    if not root.is_dir():
        return
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(folder.iterdir()):
            if f.is_file() and not f.name.endswith(".meta.json"):
                yield folder.name, f, f.with_name(f.stem + ".meta.json")


def verify(root: Path) -> int:
    bad = 0
    for inst, f, side in iter_sources(root):
        label = f"{inst}/{f.name}"
        if not side.exists():
            out(f"[FAIL] {label}: missing sidecar")
            bad += 1
            continue
        try:
            want = json.loads(side.read_text(encoding="utf-8")).get("sha256")
        except (OSError, ValueError) as exc:
            out(f"[FAIL] {label}: bad sidecar ({exc})")
            bad += 1
            continue
        if hashlib.sha256(f.read_bytes()).hexdigest() == want:
            out(f"[OK] {label}")
        else:
            out(f"[FAIL] {label}: sha256 mismatch")
            bad += 1
    return 1 if bad else 0


def list_sources(root: Path) -> None:
    rows = []
    for inst, f, side in iter_sources(root):
        m: dict = {}
        if side.exists():
            try:
                m = json.loads(side.read_text(encoding="utf-8"))
            except ValueError:
                m = {}
        rows.append(
            [
                inst,
                f.name,
                m.get("fetched_at", "-"),
                (m.get("sha256") or "-")[:12],
                m.get("url", "-"),
            ]
        )
    out(format_table(rows, ["instrument", "file", "fetched_at", "sha256", "url"]))


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="regkb_fetch", description=__doc__)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="sources root")
    ap.add_argument("--allow-host", action="append", default=[], help="extra allowed host")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("url", help="fetch one URL")
    u.add_argument("url")
    u.add_argument("--instrument", required=True)
    u.add_argument("--slug")
    u.add_argument("--title")
    u.add_argument("--raw", action="store_true", help="also keep raw HTML")
    s = sub.add_parser("vbpl-search", help="search vbpl.vn")
    s.add_argument("--keyword", required=True)
    s.add_argument("--agency", type=int, default=None)
    s.add_argument("--doc-type", nargs="*", default=[], help="TT QD VBHN or uuid")
    s.add_argument("--from", dest="date_from")
    s.add_argument("--page-size", type=int, default=20)
    s.add_argument("--action-id")
    sm = sub.add_parser("vbpl-sitemap", help="fallback: scan vbpl.vn sitemaps")
    sm.add_argument("--keyword", required=True)
    d = sub.add_parser("vbpl-doc", help="fetch a vbpl document by id or URL")
    d.add_argument("doc")
    d.add_argument("--instrument", required=True)
    d.add_argument("--slug")
    sub.add_parser("verify", help="check sha256 of stored files")
    sub.add_parser("list", help="list stored sources")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allow = tuple(args.allow_host)
    try:
        if args.cmd == "verify":
            return verify(args.root)
        if args.cmd == "list":
            list_sources(args.root)
            return 0
        if args.cmd == "url":
            for p in fetch_url(
                args.url,
                args.instrument,
                args.root,
                slug=args.slug,
                title=args.title,
                raw=args.raw,
                allow_hosts=allow,
            ):
                out(f"[OK] {p}")
            return 0
        if args.cmd == "vbpl-search":
            data, aid = vbpl_search(
                args.keyword,
                args.agency,
                args.doc_type,
                args.date_from,
                args.page_size,
                args.action_id,
                allow,
            )
            out(f"[OK] total={data.get('total')} action_id={aid}")
            out(format_table(search_rows(data), SEARCH_HEADERS))
            return 0
        if args.cmd == "vbpl-sitemap":
            hits = vbpl_sitemap(args.keyword, allow)
            for loc, mod in hits:
                out(f"{mod or '-'}  {loc}")
            out(f"[OK] {len(hits)} hits")
            return 0
        if args.cmd == "vbpl-doc":
            for p in fetch_vbpl_doc(args.doc, args.instrument, args.root, args.slug):
                out(f"[OK] {p}")
            return 0
    except (FetchError, httpx.HTTPError) as exc:
        out(f"[FAIL] {exc}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
