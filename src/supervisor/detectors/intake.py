"""Document and URL intake (WP-D1, docs/detectors.md "Documents and URLs").

The gate receives ``context.documents``: a list of ``{name, media_type, text?, bytes_b64?, url?}``.
This module turns them into text a detector can read, before the detectors run:

* TXT, CSV, Markdown, JSON (string values and keys, so a ``\\u`` escape cannot hide a phrase) and
  HTML (all text, comments and the text attributes) are read as text;
* PDF through ``pypdf`` (optional extra ``documents``; imported on first use);
* DOCX by unzipping ``word/document.xml`` (and the header, footer, comment and note parts) with
  the standard library and reading the ``w:t`` runs;
* images, scans, encrypted or damaged files, and any other format are *uninspectable*, with a
  fixed reason. There is no OCR (it needs a binary, which the bank guide forbids).

The type is decided by the first bytes (``%PDF``, ``PK``, an image header) before the declared
media type or the file name, so a PDF sent as ``text/plain`` is still read as a PDF.

Limits (the finding ``document.limit_exceeded`` says a limit was hit; the surplus is not read):
10 documents, 2 MB each after decoding, 10 unique URLs, 2 s per document, 6 s in all.

Privacy (R2): raw document bytes are never stored. ``IntakeResult.meta`` keeps, per document, the
sha256, the size, the media type, the source and the status; no name, no text, no URL.
Pure standard library apart from the lazily imported ``pypdf`` and the injected fetcher.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
import io
import json
import logging
import re
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from supervisor.adapters.fetch.client import Fetcher, FetchFailed
from supervisor.adapters.fetch.guard import UrlRefused
from supervisor.core.bounded import BoundedSlots, NoSlot

MAX_DOCUMENTS = 10
MAX_DOC_BYTES = 2 * 1024 * 1024
MAX_URLS = 10
EXTRACT_TIMEOUT_S = 2.0
TOTAL_BUDGET_S = 6.0
MAX_LIST = 1000  # a longer list is refused with HTTP 400 (the limit above is a finding)
MAX_NAME = 255
MAX_URL = 2048
MAX_PAGES = 500
MAX_ZIP_MEMBER = 16 * 1024 * 1024
MAX_XML_PARTS = 40
ALLOWED_KEYS = frozenset({"name", "media_type", "text", "bytes_b64", "url"})

CODE_UNINSPECTABLE = "document.uninspectable"
CODE_LIMIT = "document.limit_exceeded"
CODE_SSRF = "url.ssrf_refused"
CODE_DOMAIN = "url.domain_blocked"

_SLOTS = BoundedSlots(8)
_MEDIA = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,60}/[a-z0-9][a-z0-9!#$&^_.+-]{0,60}$")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/csv",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
}
_TEXT_EXT = (
    ".txt",
    ".csv",
    ".md",
    ".markdown",
    ".json",
    ".ndjson",
    ".log",
    ".yaml",
    ".yml",
    ".tsv",
)
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic")
_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
)


class _TooLarge(Exception):
    """A document is over MAX_DOC_BYTES (``size`` is the decoded size, or an estimate)."""

    def __init__(self, size: int) -> None:
        super().__init__("too_large")
        self.size = size


class Uninspectable(Exception):
    """The document cannot be read. ``reason`` is a fixed short phrase."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------- the request field


def check_documents(value: Any) -> str | None:
    """None when ``context.documents`` has a valid shape, else the HTTP 400 message. Sizes are not
    checked here: a document over the limit is a finding, not an error."""
    if not isinstance(value, list):
        return "context.documents must be a list"
    if len(value) > MAX_LIST:
        return f"context.documents has more than {MAX_LIST} items"
    for i, doc in enumerate(value):
        where = f"context.documents[{i}]"
        if not isinstance(doc, Mapping):
            return f"{where} must be an object"
        extra = sorted(str(k) for k in doc if k not in ALLOWED_KEYS)
        if extra:
            return f"{where}: unknown field {extra[0][:40]!r}"
        for key, cap in (("name", MAX_NAME), ("media_type", 100), ("url", MAX_URL)):
            v = doc.get(key)
            if v is not None and (not isinstance(v, str) or len(v) > cap):
                return f"{where}.{key} must be a string of at most {cap} characters"
        for key in ("text", "bytes_b64"):
            if doc.get(key) is not None and not isinstance(doc[key], str):
                return f"{where}.{key} must be a string"
        given = [k for k in ("text", "bytes_b64", "url") if doc.get(k) is not None]
        if len(given) != 1:
            return f"{where} needs exactly one of text, bytes_b64 or url"
    return None


def documents_problem(value: Any, intake_on: bool) -> str | None:
    """The HTTP 400 message for ``context.documents`` on a gate request or a playground run, or
    None. With the intake off (the default) any value is refused."""
    if value is None:
        return None
    if not intake_on:
        return "context.documents needs DOCUMENT_INTAKE_ENABLED=1 and DETECTORS_ENABLED=1"
    return check_documents(value)


# ---------------------------------------------------------------------------- result


@dataclass
class IntakeResult:
    documents: list[dict[str, str]] = field(default_factory=list)  # [{name, text}], readable only
    meta: list[dict[str, Any]] = field(default_factory=list)  # per document, no text, no name
    events: list[dict[str, Any]] = field(default_factory=list)  # {code, reason, index}
    unread: int = 0  # documents (and surplus) whose text was not read
    closing: int = 0  # the part of ``unread`` that fails closed on a risky tool

    def detector_meta(self) -> dict[str, Any]:
        """What the ``document_intake`` detector reads (payload ``meta.intake``)."""
        return {
            "events": [dict(e) for e in self.events],
            "unread": self.unread,
            "closing": self.closing,
        }


# ---------------------------------------------------------------------------- type decision


def normalise_media_type(value: Any) -> str:
    """A declared media type, lower case, without parameters; ``""`` if it is not well formed."""
    if not isinstance(value, str):
        return ""
    base = value.split(";", 1)[0].strip().lower()
    return base if _MEDIA.match(base) else ""


def sniff(data: bytes) -> str | None:
    """``pdf``, ``zip``, ``image`` from the first bytes, else None."""
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[:12].startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image"
    if data[4:12] == b"ftypheic" or any(data.startswith(m) for m in _IMAGE_MAGIC):
        return "image"
    return None


def _kind(data: bytes, media_type: str, name: str) -> str:
    """text, html, json, pdf, docx, image or other. The bytes decide before the label does."""
    found = sniff(data)
    if found == "pdf":
        return "pdf"
    if found == "image":
        return "image"
    low = name.lower()
    if found == "zip":
        return (
            "docx" if media_type == _DOCX or low.endswith(".docx") or _has_docx(data) else "other"
        )
    if media_type.startswith("image/") or low.endswith(_IMAGE_EXT):
        return "image"
    if media_type == "application/pdf" or low.endswith(".pdf"):
        return "pdf"  # a label without a PDF header: let the reader say it is damaged
    if media_type == _DOCX or low.endswith(".docx"):
        return "docx"
    if media_type in ("text/html", "application/xhtml+xml") or low.endswith((".html", ".htm")):
        return "html"
    if media_type in ("application/json", "text/json") or low.endswith(".json"):
        return "json"
    if media_type.startswith("text/") or media_type in _TEXT_TYPES or low.endswith(_TEXT_EXT):
        return "text"
    return "other"


def _has_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------- readers


def decode_text(data: bytes) -> str:
    """Text of a byte string: UTF-8 (with or without a BOM) or UTF-16 with a BOM. A binary or
    mostly undecodable file raises ``Uninspectable``."""
    if data.startswith(codecs.BOM_UTF8):
        text = data[3:].decode("utf-8", "replace")
    elif data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8", "replace")
    if "\x00" in text[:4096]:
        raise Uninspectable("binary_content")
    if text and text.count("�") * 10 > len(text):
        raise Uninspectable("undecodable_text")
    return text


def _json_strings(value: Any, out: list[str], depth: int = 0) -> None:
    if depth > 64:
        raise Uninspectable("json_too_deep")
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            out.append(str(k))
            _json_strings(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _json_strings(v, out, depth + 1)


def read_json(data: bytes) -> str:
    """The strings of a JSON document (keys and values, in order), one per line. The escapes are
    decoded, so ``\\u0069gnore`` reads as ``ignore``. Text that is not JSON is read as text."""
    raw = decode_text(data)
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return raw
    out: list[str] = []
    _json_strings(value, out)
    return "\n".join(out)


class _HtmlText(HTMLParser):
    """All the text of a page, the comments and the attributes a person or a model may read."""

    ATTRS = ("alt", "title", "aria-label", "placeholder", "content", "value")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_comment(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for k, v in attrs:
            if k in self.ATTRS and v and v.strip():
                self.parts.append(v.strip())


def read_html(data: bytes) -> str:
    parser = _HtmlText()
    try:
        parser.feed(decode_text(data))
        parser.close()
    except Uninspectable:
        raise
    except Exception:  # noqa: BLE001 - the parser is lenient; anything else is a damaged page
        raise Uninspectable("parse_failed") from None
    return "\n".join(parser.parts)


_DTD = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCX_PARTS = re.compile(
    r"^word/(document|comments|footnotes|endnotes|header\d*|footer\d*)\.xml$", re.IGNORECASE
)


def _docx_xml_text(xml: bytes) -> str:
    if _DTD.search(xml):
        raise Uninspectable("unsafe_xml")  # no entity expansion: refuse the part
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - DOCTYPE and ENTITY refused above
    except ElementTree.ParseError:
        raise Uninspectable("parse_failed") from None
    lines: list[str] = []
    for para in root.iter(f"{_W}p"):
        buf: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                buf.append(node.text)
            elif node.tag == f"{_W}tab":
                buf.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                buf.append("\n")
        line = "".join(buf)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def read_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = [i for i in z.infolist() if _DOCX_PARTS.match(i.filename)]
            if not any(i.filename.lower() == "word/document.xml" for i in infos):
                raise Uninspectable("not_a_docx")
            infos = infos[:MAX_XML_PARTS]
            if sum(i.file_size for i in infos) > 2 * MAX_ZIP_MEMBER:
                raise Uninspectable("zip_too_large")
            texts = []
            for info in infos:
                if info.file_size > MAX_ZIP_MEMBER:
                    raise Uninspectable("zip_too_large")
                with z.open(info) as fh:
                    xml = fh.read(MAX_ZIP_MEMBER + 1)
                if len(xml) > MAX_ZIP_MEMBER:
                    raise Uninspectable("zip_too_large")
                texts.append(_docx_xml_text(xml))
            return "\n".join(t for t in texts if t)
    except Uninspectable:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
        raise Uninspectable("parse_failed") from None


def read_pdf(data: bytes, deadline: float) -> str:
    """Text of a PDF with ``pypdf`` (extra ``documents``). White text on a white page is text
    like any other and is returned; so are the title, subject and keywords."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Uninspectable("pdf_reader_missing") from None
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # a damaged file is a reason, not a log line
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except Exception:  # noqa: BLE001
                opened = 0
            if not opened:
                raise Uninspectable("encrypted")
        parts: list[str] = []
        meta = reader.metadata
        if meta:
            for key in ("/Title", "/Subject", "/Keywords", "/Author"):
                v = meta.get(key)
                if isinstance(v, str) and v.strip():
                    parts.append(v.strip())
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES:
                raise Uninspectable("too_many_pages")
            if time.monotonic() > deadline:
                raise Uninspectable("timeout")
            parts.append(page.extract_text() or "")
        return "\n".join(p for p in parts if p)
    except Uninspectable:
        raise
    except Exception:  # noqa: BLE001 - pypdf raises many types on a damaged file
        raise Uninspectable("parse_failed") from None


def extract_text(
    data: bytes,
    media_type: str = "",
    name: str = "",
    *,
    deadline: float | None = None,
) -> str:
    """Text of one document. Raises ``Uninspectable`` (fixed reason) when it cannot be read.
    An empty document gives ``""``: a document with no text is allowed."""
    if deadline is None:
        deadline = time.monotonic() + EXTRACT_TIMEOUT_S
    if not data:
        return ""
    kind = _kind(data, media_type, name)
    if kind == "image":
        raise Uninspectable("image_no_ocr")
    if kind == "pdf":
        return read_pdf(data, deadline)
    if kind == "docx":
        return read_docx(data)
    if kind == "html":
        return read_html(data)
    if kind == "json":
        return read_json(data)
    if kind == "text":
        return decode_text(data)
    try:  # unknown label: plain text is fine, anything binary is not
        return decode_text(data)
    except Uninspectable:
        raise Uninspectable("unsupported_type") from None


# ---------------------------------------------------------------------------- the service


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IntakeService:
    """Reads the documents of one gate call. Thread safe; holds no per-call state."""

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        *,
        extract_timeout_s: float = EXTRACT_TIMEOUT_S,
        total_budget_s: float = TOTAL_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fetcher = fetcher
        self.extract_timeout_s = extract_timeout_s
        self.total_budget_s = total_budget_s
        self.clock = clock

    # -- one document ------------------------------------------------------------------
    def _bytes_of(self, doc: Mapping[str, Any]) -> tuple[bytes, str, str]:
        """(bytes, media type, source). Raises ``Uninspectable``, ``UrlRefused`` or
        ``FetchFailed`` (the last two only for a URL)."""
        declared = normalise_media_type(doc.get("media_type"))
        if isinstance(doc.get("text"), str):
            if len(doc["text"]) > MAX_DOC_BYTES:  # at least one byte per character
                raise _TooLarge(len(doc["text"]))
            return doc["text"].encode("utf-8", "replace"), declared or "text/plain", "inline"
        if isinstance(doc.get("bytes_b64"), str):
            b64 = doc["bytes_b64"]
            if len(b64) > (MAX_DOC_BYTES * 4) // 3 + 8:
                raise _TooLarge(len(b64) * 3 // 4)  # not decoded: it would cost the memory
            try:
                return base64.b64decode(b64, validate=True), declared, "inline"
            except (binascii.Error, ValueError):
                raise Uninspectable("bad_base64") from None
        if self.fetcher is None or not self.fetcher.enabled:
            raise Uninspectable("url_fetch_disabled")
        fetched = self.fetcher.fetch(str(doc["url"]))
        return fetched.data, declared or normalise_media_type(fetched.media_type), "url"

    def _extract(self, data: bytes, media_type: str, name: str) -> str:
        deadline = self.clock() + self.extract_timeout_s
        try:
            return str(
                _SLOTS.call(
                    lambda: extract_text(data, media_type, name, deadline=deadline),
                    self.extract_timeout_s,
                    "intake",
                )
            )
        except TimeoutError:
            raise Uninspectable("timeout") from None
        except NoSlot:
            raise Uninspectable("busy") from None

    # -- the call -------------------------------------------------------------------------
    def run(self, raw: Any) -> IntakeResult:
        """Read ``context.documents``. Never raises: a document that cannot be read is
        reported, not thrown."""
        out = IntakeResult()
        docs = [d for d in raw if isinstance(d, Mapping)] if isinstance(raw, list) else []
        start = self.clock()
        seen_urls: set[str] = set()
        read_count = 0
        limit_hit = False
        for doc in docs:
            url = doc.get("url") if isinstance(doc.get("url"), str) else None
            if url is not None and url in seen_urls:
                continue  # the same link twice counts once
            if read_count >= MAX_DOCUMENTS or (url is not None and len(seen_urls) >= MAX_URLS):
                limit_hit = True  # the surplus is not read
                out.unread += 1
                out.closing += 1
                continue
            if url is not None:
                seen_urls.add(url)
            read_count += 1
            index = len(out.meta)
            name = doc.get("name") if isinstance(doc.get("name"), str) and doc["name"] else ""
            entry: dict[str, Any] = {
                "index": index,
                "source": "url" if url is not None else "inline",
                "media_type": normalise_media_type(doc.get("media_type")) or "unknown",
                "sha256": None,
                "size": 0,
                "status": "read",
            }
            if url is not None:
                entry["url_sha256"] = hashlib.sha256(url.encode("utf-8", "replace")).hexdigest()
            try:
                if self.clock() - start > self.total_budget_s:
                    raise Uninspectable("time_budget")
                data, media_type, _src = self._bytes_of(doc)
                entry["sha256"], entry["size"] = _sha(data), len(data)
                if media_type:
                    entry["media_type"] = media_type
                if len(data) > MAX_DOC_BYTES:
                    raise _TooLarge(len(data))
                label = name or (f"document-{index + 1}")
                text = self._extract(data, media_type, name)
                out.documents.append({"name": label[:MAX_NAME], "text": text})
                entry["chars"] = len(text)
            except _TooLarge as exc:
                entry["size"] = exc.size
                entry["status"], entry["reason"] = "unread", "too_large"
                out.unread += 1
                out.closing += 1
                out.events.append(
                    {"code": CODE_LIMIT, "reason": "document_too_large", "index": index}
                )
            except Uninspectable as exc:
                entry["status"], entry["reason"] = "unread", exc.reason
                out.unread += 1
                out.closing += 1
                out.events.append(
                    {"code": CODE_UNINSPECTABLE, "reason": exc.reason, "index": index}
                )
            except UrlRefused as exc:
                entry["status"], entry["reason"] = "refused", exc.detail
                out.unread += 1  # not read, but its own finding: it does not close a risky tool
                out.events.append({"code": exc.code, "reason": exc.detail, "index": index})
            except FetchFailed as exc:
                entry["status"], entry["reason"] = "unread", exc.reason
                out.unread += 1
                out.closing += 1
                out.events.append(
                    {"code": CODE_UNINSPECTABLE, "reason": exc.reason, "index": index}
                )
            out.meta.append(entry)
        if limit_hit:
            out.events.append({"code": CODE_LIMIT, "reason": "too_many_documents", "index": None})
        return out


def public_meta(result: IntakeResult) -> list[dict[str, Any]]:
    """The per-document facts that go in the gate answer and the evidence chain."""
    return [dict(m) for m in result.meta]


def reasons(events: Sequence[Mapping[str, Any]], code: str, limit: int = 3) -> str:
    """A short list of the distinct reasons of one event code (for a ``detail`` field)."""
    seen = list(dict.fromkeys(str(e.get("reason")) for e in events if e.get("code") == code))
    return ",".join(seen[:limit])[:80]
