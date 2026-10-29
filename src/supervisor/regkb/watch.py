"""Regulation watcher (WP-W1, phase 11). Dev host or laptop only: the Databricks App never calls it.

``python -m supervisor.regkb watch [--out DIR] [--instrument ID] [--dry-run]``

For every stored Vietnamese instrument (a ``regulations/vn/*.yaml`` file with a folder under
``regulations/sources/<id>/``) the watcher asks vbpl.vn by document number and detects:

* ``amendment`` / ``replacement`` / ``repeal``: another document whose title names the number
  with "sua doi" / "thay the" / "bai bo" (a number named in the instrument file is "known");
* ``effect_status_change``: the vbpl effect status differs from the last report (or, in the first
  run, is not compatible with the status in the instrument file);
* ``updated_date_newer``: ``updatedDate`` is later than the last report or ``last_checked``;
* ``text_changed``: a primary vbpl source now has a text whose sha256 differs from the stored one
  and whose word sequence differs too (page numbers, part headings and line breaks are dropped;
  layout-only changes are counted as ``layout_only``, not reported).

New texts go to ``<sources root>/<id>/incoming/<YYYY-MM-DD>/`` with sha256 and a ``.meta.json``
sidecar. The stored text of record is never touched. A watch report (JSON and Markdown) and a
signed update package are written to ``--out`` (see ``supervisor.regkb.package``).

Everything downloaded is data. It is parsed with the standard library, written as bytes and
never imported or executed. Network access goes through the functions of ``tools/regkb_fetch.py``
(loaded by path, only when the default fetcher is built); tests inject a fake fetcher.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import secrets
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from supervisor.config import REPO_ROOT

REPORT_FORMAT = "regwatch-report-1"
TOOL = "supervisor.regkb.watch/1"
REVIEW_NOTE = "pending review (WP-W2)"
KINDS = (
    "amendment",
    "replacement",
    "repeal",
    "effect_status_change",
    "updated_date_newer",
    "text_changed",
)
MAX_AMENDMENT_TEXTS = 5
MAX_HITS = 30
NEW_KEYWORDS = ("trí tuệ nhân tạo", "AI")
NEW_AGENCIES: dict[str, str] = {  # folded agency-name fragment -> label
    "ngan hang nha nuoc": "SBV",
    "chinh phu": "Government",
    "khoa hoc va cong nghe": "MST",
    "cong an": "MPS",
}
INTERIM_QUERIES = ("cổng thông tin một cửa trí tuệ nhân tạo", "cơ chế tạm thời")
INTERIM_AGENCIES = ("chinh phu", "khoa hoc va cong nghe")
INTERIM_NOTE = (
    "Decree 142/2026 Art. 46 interim channel (single-window AI portal, temporary mechanism): "
    "candidate documents of the Government and the MST found by keyword; counsel to read them"
)
# The open items of regulations/REGULATOR_MAP.md (M-01 .. M-10): numbers are searched exactly;
# a keyword query lists candidates from the four agencies.
OPEN_ITEMS: dict[str, dict[str, Any]] = {
    "M-01": {"numbers": ["96/2025/QH15", "142/2025/QH15", "43/2024/QH15"]},
    "M-02": {"numbers": ["26/2023/QH15", "70/2024/NĐ-CP", "17/2024/TT-BCA"]},
    "M-03": {"numbers": ["169/2026/TT-BCA", "170/2026/TT-BCA"]},
    "M-04": {"numbers": ["85/2016/NĐ-CP", "12/2022/TT-BTTTT"]},
    "M-05": {"numbers": ["40/2024/TT-NHNN", "41/2025/TT-NHNN", "22/2026/TT-NHNN"]},
    "M-06": {"numbers": ["45/2025/TT-NHNN"]},
    "M-07": {"keywords": ["hướng dẫn Luật Phòng, chống rửa tiền"]},
    "M-08": {"keywords": ["thuê ngoài công nghệ thông tin ngân hàng"]},
    "M-09": {"keywords": ["định danh khách hàng điện tử mở tài khoản"]},
    "M-10": {"keywords": ["xử phạt vi phạm hành chính trong lĩnh vực ngân hàng"]},
}
# vbpl effect status code -> statuses of the instrument file it is compatible with
STATUS_COMPAT: dict[str, tuple[str, ...]] = {
    "CHL": ("in_force", "issued", "superseded"),
    "HHLMP": ("in_force", "superseded"),
    "CCHL": ("issued",),
    "HHL": ("superseded", "repealed", "expired"),
}
_KIND_WORDS = (("bai bo", "repeal"), ("thay the", "replacement"), ("sua doi", "amendment"))
_ID_RE = re.compile(r"^(VN|INTL|INT)-[A-Z0-9]+(-[A-Z0-9]+){0,3}$")
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


# ---------------------------------------------------------------------------- small helpers


def fold(text: str) -> str:
    """Lower case, no diacritics, d-stroke mapped, single spaces: for matching titles."""
    text = text.replace("đ", "d").replace("Đ", "D")
    norm = unicodedata.normalize("NFD", text)
    plain = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return " ".join(plain.lower().split())


def fold_ws(text: str) -> str:
    return " ".join(text.split())


# WP-B1: layout noise of a fetched text. A page number is a line of its own ("12", "- 12 -",
# "Trang 12", "Page 12", "12/40"). A part heading is a line that starts with Chuong / Muc / Phan /
# Tieu muc and a number (the all-capitals title line after it goes too). Article headings
# ("Dieu 3. Title") stay: an added or renamed article is a real change.
_PAGE_LINE = re.compile(
    r"^\W*(?:(?:trang|page|tr\.)\s*)?\d{1,4}(?:\s*(?:/|of|trên)\s*\d{1,4})?\W*$", re.IGNORECASE
)
_PART_HEADING = re.compile(
    r"^(?:chương|mục|phần|tiểu\s+mục)\s+(?:[ivxlc]+|\d+)\b", re.IGNORECASE | re.UNICODE
)


def _is_title_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def words_of(text: str) -> list[str]:
    """The word sequence of a text without page numbers, part headings and line breaks. Two texts
    with the same sequence differ in layout only."""
    out: list[str] = []
    skip_title = False
    for raw in unicodedata.normalize("NFC", text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if _PAGE_LINE.match(line):
            continue
        if _PART_HEADING.match(line):
            skip_title = True
            continue
        if skip_title and _is_title_line(line):
            skip_title = False
            continue
        skip_title = False
        out.extend(line.split())
    return out


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug_of(*parts: str) -> str:
    raw = "-".join(fold(p).replace("/", "-") for p in parts if p)
    return _SLUG_RE.sub("-", raw).strip("-._")[:80] or "source"


def number_in_title(number: str, title: str) -> bool:
    """True when the folded title names the full document number (not a longer number)."""
    num = fold(number)
    if not num:
        return False
    return re.search(r"(?<![0-9a-z/])" + re.escape(num) + r"(?![0-9a-z])", fold(title)) is not None


def change_kind(title: str) -> str | None:
    """amendment | replacement | repeal from the words in a title (the first match wins)."""
    low = fold(title)
    for words, kind in _KIND_WORDS:
        if words in low:
            return kind
    return None


def status_code_of(item: Mapping[str, Any]) -> str:
    st = item.get("effStatus")
    return str(st.get("code") or "") if isinstance(st, Mapping) else ""


def status_name_of(item: Mapping[str, Any]) -> str:
    st = item.get("effStatus")
    return str(st.get("name") or "") if isinstance(st, Mapping) else str(st or "")


def day_of(value: Any) -> str:
    return str(value or "")[:10]


def vbpl_url(vbpl_id: str) -> str:
    return f"https://vbpl.vn/van-ban/chi-tiet/{vbpl_id}"


# ---------------------------------------------------------------------------- the fetcher


class Fetcher(Protocol):
    """The three network calls of the watcher. Tests give a fake; the default uses the tool."""

    def search(
        self, keyword: str, *, since: str | None = None, page_size: int = 30
    ) -> list[dict[str, Any]]: ...

    def doc(self, vbpl_id: str) -> dict[str, Any] | None: ...

    def doc_text(self, data: Mapping[str, Any]) -> str: ...


def load_fetch_tool(path: Path | None = None) -> Any:
    """Load tools/regkb_fetch.py by path (it is a dev tool, not a package of the App)."""
    path = path or (REPO_ROOT / "tools" / "regkb_fetch.py")
    if not path.is_file():
        raise RuntimeError(f"tools/regkb_fetch.py not found at {path}")
    spec = importlib.util.spec_from_file_location("regkb_fetch_tool", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tools/regkb_fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolFetcher:
    """Default fetcher: the functions of ``tools/regkb_fetch.py`` (vbpl search and doc API)."""

    def __init__(self, tool: Any = None) -> None:
        self.tool = tool or load_fetch_tool()

    def search(
        self, keyword: str, *, since: str | None = None, page_size: int = 30
    ) -> list[dict[str, Any]]:
        data, _ = self.tool.vbpl_search(keyword, None, [], since, page_size)
        return [dict(i) for i in data.get("items") or [] if isinstance(i, dict)]

    def doc(self, vbpl_id: str) -> dict[str, Any] | None:
        resp = self.tool.http("GET", f"{self.tool.API_BASE}/qtdc/public/doc/{vbpl_id}")
        if resp.status_code != 200:
            return None
        data = resp.json().get("data")
        return dict(data) if isinstance(data, dict) else None

    def doc_text(self, data: Mapping[str, Any]) -> str:
        content = (data.get("documentContent") or {}).get("content")
        if not content:
            return ""
        text, _ = self.tool._run_extract(content, ())
        return str(text or "")


# ---------------------------------------------------------------------------- instruments


@dataclass
class Instrument:
    id: str
    number: str
    title: str
    status: str
    last_checked: str
    sources: list[dict[str, Any]]
    raw_text: str
    path: Path
    stored_dir: Path


def load_instruments(
    regulations: Path | None = None,
    sources_root: Path | None = None,
    only: str | None = None,
) -> list[Instrument]:
    """Vietnamese instruments with ``stored: yes`` (a file under vn/ and a sources folder)."""
    regulations = regulations or (REPO_ROOT / "regulations")
    sources_root = sources_root or (regulations / "sources")
    out: list[Instrument] = []
    for path in sorted((regulations / "vn").glob("*.yaml")):
        raw = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(raw)
        inst = doc.get("instrument") if isinstance(doc, dict) else None
        if not isinstance(inst, dict) or not _ID_RE.match(str(inst.get("id", ""))):
            continue
        iid = str(inst["id"])
        if only and iid != only:
            continue
        folder = sources_root / iid
        if not folder.is_dir() or not any(folder.iterdir()):
            continue  # stored: no
        out.append(
            Instrument(
                id=iid,
                number=str(inst.get("number") or ""),
                title=str(inst.get("title_vi") or inst.get("title_en") or ""),
                status=str(inst.get("status") or ""),
                last_checked=str(inst.get("last_checked") or ""),
                sources=[s for s in inst.get("sources") or [] if isinstance(s, dict)],
                raw_text=raw,
                path=path,
                stored_dir=folder,
            )
        )
    return out


def vbpl_ids_of(inst: Instrument) -> list[str]:
    """Ids of the primary vbpl sources (uuid or digits) with their stored sha."""
    ids: list[str] = []
    for src in inst.sources:
        url = str(src.get("url") or "")
        if src.get("kind") != "primary" or not src.get("sha256"):
            continue
        if "vbpl.vn" not in url and "vbpl-bientap-gateway" not in url:
            continue
        m = re.search(r"/minio/buckets/vbpl/([A-Za-z0-9-]{3,64})/", url) or re.search(
            r"/(?:chi-tiet|public/doc)/(?!minio/)([A-Za-z0-9-]{3,64})(?:$|[/?#])", url
        )
        if m:
            ids.append(m.group(1))
    return list(dict.fromkeys(ids))


def stored_sha_for(inst: Instrument, vbpl_id: str) -> str:
    for src in inst.sources:
        if vbpl_id in str(src.get("url") or "") and src.get("sha256"):
            return str(src["sha256"])
    return ""


def stored_text_for(inst: Instrument, sha: str) -> str | None:
    """The stored text file whose sidecar has this sha (read only), or None."""
    for meta_path in sorted(inst.stored_dir.glob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("sha256") != sha:
            continue
        stem = meta_path.name[: -len(".meta.json")]
        for ext in ("txt",):
            cand = inst.stored_dir / f"{stem}.{ext}"
            if cand.is_file():
                return cand.read_text(encoding="utf-8")
    return None


# ---------------------------------------------------------------------------- baseline


def latest_report(out_dir: Path | None, before: str | None = None) -> dict[str, Any] | None:
    """The newest ``watch-*.json`` in ``out_dir`` (the baseline of the next run), or None."""
    if out_dir is None or not out_dir.is_dir():
        return None
    for path in sorted(out_dir.glob("watch-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("format") == REPORT_FORMAT:
            return data
    return None


def _baseline(prev: Mapping[str, Any] | None, iid: str) -> dict[str, Any]:
    for row in (prev or {}).get("instruments") or []:
        if isinstance(row, dict) and row.get("instrument_id") == iid:
            obs = row.get("observed")
            return dict(obs) if isinstance(obs, dict) else {}
    return {}


# ---------------------------------------------------------------------------- one instrument


@dataclass
class Incoming:
    """A file to store under incoming/: relative name, bytes and the sidecar fields."""

    instrument_id: str
    name: str
    data: bytes
    meta: dict[str, Any] = field(default_factory=dict)


def _change(
    kind: str,
    inst: Instrument,
    detail: str,
    *,
    date: str = "",
    url: str = "",
    sha: str = "",
    doc_number: str = "",
    files: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "kind": kind,
        "instrument_id": inst.id,
        "number": inst.number,
        "detail": detail[:300],
        "date": date,
        "url": url,
        "sha256": sha,
        "doc_number": doc_number,
        "incoming": list(files),
        "review_status": "pending",
    }


def _record_view(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "vbpl_id": str(item.get("id") or ""),
        "doc_num": str(item.get("docNum") or ""),
        "title": " ".join(str(item.get("title") or "").split())[:300],
        "eff_status_code": status_code_of(item),
        "eff_status_name": status_name_of(item),
        "issue_date": day_of(item.get("issueDate")),
        "eff_from": day_of(item.get("effFrom")),
        "eff_to": day_of(item.get("effTo")),
        "updated_date": str(item.get("updatedDate") or "")[:19],
        "url": vbpl_url(str(item.get("id") or "")) if item.get("id") else "",
    }


def _incoming_item(
    inst: Instrument,
    today: str,
    now: datetime,
    vbpl_id: str,
    item: Mapping[str, Any],
    text: str,
) -> Incoming:
    data = text.encode("utf-8")
    slug = slug_of(str(item.get("docNum") or inst.number), vbpl_id[:8])
    return Incoming(
        inst.id,
        f"{today}/{slug}.txt",
        data,
        {
            "url": vbpl_url(vbpl_id),
            "title": " ".join(str(item.get("title") or "").split())[:300],
            "fetched_at": utc_stamp(now),
            "sha256": sha256_hex(data),
            "content_type": "text/plain; charset=utf-8",
            "tool": TOOL,
            "vbpl": {
                "id": vbpl_id,
                "doc_num": str(item.get("docNum") or ""),
                "eff_status": status_name_of(item),
                "issue_date": day_of(item.get("issueDate")),
                "eff_from": day_of(item.get("effFrom")),
                "updated_date": str(item.get("updatedDate") or "")[:19],
            },
        },
    )


def check_instrument(
    inst: Instrument,
    fetcher: Fetcher,
    prev: Mapping[str, Any] | None,
    now: datetime,
    incoming: list[Incoming],
) -> dict[str, Any]:
    """Check one instrument. Appends new texts to ``incoming``; returns the report row."""
    today = now.date().isoformat()
    base = _baseline(prev, inst.id)
    row: dict[str, Any] = {
        "instrument_id": inst.id,
        "number": inst.number,
        "status_kb": inst.status,
        "last_checked": inst.last_checked,
        "record": {},
        "observed": {},
        "changes": [],
        "known_related": [],
        "layout_only": [],
        "unverifiable": [],
        "errors": [],
    }
    changes: list[dict[str, Any]] = row["changes"]
    seen_related: list[str] = list(base.get("related_numbers") or [])
    try:
        items = fetcher.search(inst.number, page_size=30)
    except Exception as exc:  # noqa: BLE001 - one instrument must not stop the run
        row["errors"].append(f"search: {type(exc).__name__}: {exc}"[:200])
        return row
    own = [i for i in items if fold(str(i.get("docNum") or "")) == fold(inst.number)]
    record = own[0] if own else None
    related: list[str] = []
    if record is None:
        row["record"] = {"found": False}
    else:
        row["record"] = {"found": True, **_record_view(record)}
        code = status_code_of(record)
        prev_code = str(base.get("eff_status_code") or "")
        if prev_code:
            if code != prev_code:
                changes.append(
                    _change(
                        "effect_status_change",
                        inst,
                        f"{prev_code} -> {code} ({status_name_of(record)})",
                        date=day_of(record.get("effFrom")),
                        url=vbpl_url(str(record.get("id"))),
                    )
                )
        elif code and inst.status not in STATUS_COMPAT.get(code, (inst.status,)):
            changes.append(
                _change(
                    "effect_status_change",
                    inst,
                    f"vbpl shows {code} ({status_name_of(record)}); the file says {inst.status}",
                    date=day_of(record.get("effFrom")),
                    url=vbpl_url(str(record.get("id"))),
                )
            )
    # amendments, replacements, repeals: other documents that name this number in the title
    taken = 0
    for it in items:
        num = str(it.get("docNum") or "")
        if fold(num) == fold(inst.number) or not number_in_title(inst.number, str(it.get("title"))):
            continue
        kind = change_kind(str(it.get("title") or ""))
        if kind is None:
            continue
        related.append(num)
        if num in seen_related or num in inst.raw_text:
            row["known_related"].append(num)
            continue
        files: list[str] = []
        sha = ""
        vid = str(it.get("id") or "")
        if vid and taken < MAX_AMENDMENT_TEXTS:
            taken += 1
            try:
                data = fetcher.doc(vid)
                text = fetcher.doc_text(data) if data else ""
            except Exception as exc:  # noqa: BLE001
                row["errors"].append(f"doc {vid[:8]}: {type(exc).__name__}: {exc}"[:200])
                text = ""
            if text:
                inc = _incoming_item(inst, today, now, vid, it, text)
                incoming.append(inc)
                files.append(f"{inst.id}/{inc.name}")
                sha = str(inc.meta["sha256"])
        changes.append(
            _change(
                kind,
                inst,
                f"{num}: {' '.join(str(it.get('title') or '').split())[:200]}",
                date=day_of(it.get("issueDate")),
                url=vbpl_url(vid) if vid else "",
                sha=sha,
                doc_number=num,
                files=files,
            )
        )
    # updatedDate and the text of the primary vbpl sources
    updated = str((record or {}).get("updatedDate") or "")
    text_shas: dict[str, str] = dict(base.get("text_sha256") or {})
    for vid in vbpl_ids_of(inst):
        try:
            data = fetcher.doc(vid)
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"doc {vid[:8]}: {type(exc).__name__}: {exc}"[:200])
            continue
        if not data:
            row["errors"].append(f"doc {vid[:8]}: no data")
            continue
        updated = max(updated, str(data.get("updatedDate") or ""))
        try:
            text = fetcher.doc_text(data)
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"text {vid[:8]}: {type(exc).__name__}: {exc}"[:200])
            continue
        if not text:
            continue
        sha = sha256_hex(text.encode("utf-8"))
        text_shas[vid] = sha
        stored_sha = stored_sha_for(inst, vid)
        if not stored_sha or sha == stored_sha:
            continue
        old = stored_text_for(inst, stored_sha)
        if old is None:  # the stored sha is of a file we cannot compare: say so, no change
            row["unverifiable"].append(vid)
            continue
        if fold_ws(old) == fold_ws(text) or words_of(old) == words_of(text):
            row["layout_only"].append(vid)
            continue
        inc = _incoming_item(inst, today, now, vid, data, text)
        incoming.append(inc)
        changes.append(
            _change(
                "text_changed",
                inst,
                f"sha256 {sha[:12]} differs from the stored {stored_sha[:12]}",
                date=day_of(data.get("updatedDate")),
                url=vbpl_url(vid),
                sha=sha,
                doc_number=str(data.get("docNum") or ""),
                files=[f"{inst.id}/{inc.name}"],
            )
        )
    ref = str(base.get("updated_date") or "") or inst.last_checked
    if updated and updated[: len(ref)] > ref and updated != str(base.get("updated_date") or ""):
        changes.append(
            _change(
                "updated_date_newer",
                inst,
                f"updatedDate {updated} is later than {ref}",
                date=day_of(updated),
                url=vbpl_url(str((record or {}).get("id") or "")) if record else "",
            )
        )
    row["observed"] = {
        "eff_status_code": status_code_of(record) if record else "",
        "updated_date": updated,
        "related_numbers": sorted(set(seen_related) | set(related)),
        "text_sha256": text_shas,
    }
    return row


# ---------------------------------------------------------------------------- scans


def _agency_ok(item: Mapping[str, Any], fragments: Sequence[str]) -> bool:
    name = fold(str(item.get("agencyName") or ""))
    return any(f in name for f in fragments)


def _hit(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "doc_num": str(item.get("docNum") or ""),
        "title": " ".join(str(item.get("title") or "").split())[:200],
        "agency": str(item.get("agencyName") or ""),
        "issue_date": day_of(item.get("issueDate")),
        "eff_status": status_name_of(item),
        "url": vbpl_url(str(item.get("id"))) if item.get("id") else "",
    }


def scan_new(
    fetcher: Fetcher, known_numbers: set[str], since: str, prev: Mapping[str, Any] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """New-instrument candidates: keywords "tri tue nhan tao" and "AI" for SBV, Government, MST,
    MPS, issued since ``since``, not stored and not listed in the last report."""
    errors: list[str] = []
    seen = {fold(n) for n in known_numbers}
    for c in (prev or {}).get("new_candidates") or []:
        if isinstance(c, dict):
            seen.add(fold(str(c.get("doc_num") or "")))
    found: dict[str, dict[str, Any]] = {}
    for kw in NEW_KEYWORDS:
        try:
            items = fetcher.search(kw, since=since, page_size=50)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"new-instrument search {kw!r}: {type(exc).__name__}: {exc}"[:200])
            continue
        for it in items:
            num = str(it.get("docNum") or "")
            if not num or fold(num) in seen or not _agency_ok(it, tuple(NEW_AGENCIES)):
                continue
            if day_of(it.get("issueDate")) < since:
                continue
            hit = _hit(it)
            hit["keyword"] = kw
            found.setdefault(fold(num), hit)
    return list(found.values())[:MAX_HITS], errors


def scan_interim(fetcher: Fetcher, since: str) -> dict[str, Any]:
    hits: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for kw in INTERIM_QUERIES:
        try:
            items = fetcher.search(kw, since=since, page_size=50)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{kw!r}: {type(exc).__name__}: {exc}"[:200])
            continue
        for it in items:
            if _agency_ok(it, INTERIM_AGENCIES) and day_of(it.get("issueDate")) >= since:
                hit = _hit(it)
                hit["keyword"] = kw
                hits.setdefault(fold(str(it.get("docNum") or "")), hit)
    return {"note": INTERIM_NOTE, "hits": list(hits.values())[:MAX_HITS], "errors": errors}


def requery_open_items(fetcher: Fetcher, since: str) -> list[dict[str, Any]]:
    """Re-query M-01 .. M-10. Numbers: exact match on docNum. Keywords: candidates since date."""
    out: list[dict[str, Any]] = []
    for ref, spec in OPEN_ITEMS.items():
        entry: dict[str, Any] = {"id": ref, "found": [], "missing": [], "candidates": []}
        errors: list[str] = []
        for number in spec.get("numbers") or []:
            try:
                items = fetcher.search(number, page_size=20)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{number}: {type(exc).__name__}: {exc}"[:200])
                continue
            hit = next((i for i in items if fold(str(i.get("docNum") or "")) == fold(number)), None)
            if hit is None:
                entry["missing"].append(number)
            else:
                entry["found"].append({"number": number, **_hit(hit)})
        for kw in spec.get("keywords") or []:
            try:
                items = fetcher.search(kw, since=since, page_size=30)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{kw!r}: {type(exc).__name__}: {exc}"[:200])
                continue
            for it in items:
                if _agency_ok(it, tuple(NEW_AGENCIES)) and len(entry["candidates"]) < 10:
                    entry["candidates"].append(_hit(it))
        entry["errors"] = errors
        entry["result"] = (
            "error"
            if errors and not (entry["found"] or entry["candidates"])
            else "found"
            if entry["found"] or entry["candidates"]
            else "not_found"
        )
        out.append(entry)
    return out


# ---------------------------------------------------------------------------- the run


@dataclass
class WatchResult:
    report: dict[str, Any]
    incoming: list[Incoming]

    @property
    def changes_found(self) -> int:
        return int(self.report["summary"]["changes_found"])


def new_run_id(now: datetime) -> str:
    return "rw_" + now.strftime("%Y%m%d") + "_" + secrets.token_hex(3)


def run_watch(
    fetcher: Fetcher,
    *,
    instruments: Sequence[Instrument] | None = None,
    only: str | None = None,
    prev: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> WatchResult:
    """Query, detect, collect. Writes nothing: ``write_incoming`` and the package builder do."""
    now = now or datetime.now(UTC)
    started = utc_stamp(now)
    insts = list(instruments) if instruments is not None else load_instruments(only=only)
    if only and not insts:
        raise ValueError(f"no stored Vietnamese instrument with id {only}")
    since = min((i.last_checked for i in insts if i.last_checked), default=now.date().isoformat())
    rows: list[dict[str, Any]] = []
    incoming: list[Incoming] = []
    for inst in insts:
        if progress:
            progress(f"checking {inst.id}")
        rows.append(check_instrument(inst, fetcher, prev, now, incoming))
    errors: list[str] = [f"{r['instrument_id']}: {e}" for r in rows for e in r["errors"]]
    candidates: list[dict[str, Any]] = []
    interim: dict[str, Any] = {"note": INTERIM_NOTE, "hits": [], "errors": []}
    open_items: list[dict[str, Any]] = []
    if only is None:
        if progress:
            progress("scanning for new instruments and the interim channel")
        candidates, scan_errors = scan_new(fetcher, {i.number for i in insts}, since, prev)
        interim = scan_interim(fetcher, since)
        open_items = requery_open_items(fetcher, since)
        errors += scan_errors + interim["errors"]
        errors += [f"{o['id']}: {e}" for o in open_items for e in o["errors"]]
    changes = sum(len(r["changes"]) for r in rows)
    finished = utc_stamp(datetime.now(UTC))
    report = {
        "format": REPORT_FORMAT,
        "run_id": run_id or new_run_id(now),
        "date": now.date().isoformat(),
        "started_at": started,
        "finished_at": finished,
        "tool": TOOL,
        "since": since,
        "review_note": REVIEW_NOTE,
        "status": "ok" if not errors else "partial",
        "summary": {
            "instruments_checked": len(rows),
            "changes_found": changes,
            "new_candidates": len(candidates),
            "interim_hits": len(interim["hits"]),
            "open_items_found": sum(1 for o in open_items if o["result"] == "found"),
            "incoming_files": len(incoming),
            "errors": len(errors),
        },
        "instruments": rows,
        "new_candidates": candidates,
        "interim_channel": interim,
        "open_items": open_items,
        "errors": errors[:100],
    }
    return WatchResult(report, incoming)


def write_incoming(sources_root: Path, incoming: Sequence[Incoming]) -> list[Path]:
    """Write new texts and sidecars under ``<sources_root>/<id>/incoming/<date>/``. Never writes
    outside that folder; never touches a stored file."""
    written: list[Path] = []
    for item in incoming:
        if not _ID_RE.match(item.instrument_id):
            raise ValueError(f"bad instrument id {item.instrument_id}")
        base = (sources_root / item.instrument_id / "incoming").resolve()
        target = (base / item.name).resolve()
        if base not in target.parents:
            raise ValueError(f"path outside incoming/: {item.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)
        sidecar = target.with_name(target.stem + ".meta.json")
        sidecar.write_text(
            json.dumps(item.meta, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written += [target, sidecar]
    return written


# ---------------------------------------------------------------------------- report files


def report_markdown(report: Mapping[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Regulation watch report {report['date']}",
        "",
        "Not legal advice. Bank counsel must confirm. Nothing here is applied: every change is "
        f"{REVIEW_NOTE}.",
        "",
        f"Run `{report['run_id']}`, {report['started_at']} to {report['finished_at']}, "
        f"status {report['status']}, window since {report['since']}.",
        "",
        "| Instruments | Changes | New candidates | Interim hits | Incoming files | Errors |",
        "|---|---|---|---|---|---|",
        f"| {s['instruments_checked']} | {s['changes_found']} | {s['new_candidates']} | "
        f"{s['interim_hits']} | {s['incoming_files']} | {s['errors']} |",
        "",
        "## Changes",
        "",
    ]
    rows = [c for r in report["instruments"] for c in r["changes"]]
    if rows:
        lines += [
            "| Instrument | Kind | Detail | Date | sha256 | URL |",
            "|---|---|---|---|---|---|",
        ]
        for c in rows:
            detail = str(c["detail"]).replace("|", "/")
            lines.append(
                f"| {c['instrument_id']} | {c['kind']} | {detail} | {c['date']} | "
                f"{str(c['sha256'])[:12]} | {c['url']} |"
            )
    else:
        lines.append("No change found.")
    lines += ["", "## New instrument candidates", ""]
    if report["new_candidates"]:
        lines += ["| Number | Agency | Issued | Status | Title |", "|---|---|---|---|---|"]
        for c in report["new_candidates"]:
            lines.append(
                f"| {c['doc_num']} | {c['agency']} | {c['issue_date']} | {c['eff_status']} | "
                f"{str(c['title']).replace('|', '/')} |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Decree 142 Art. 46 interim channel",
        "",
        str(report["interim_channel"]["note"]),
    ]
    hits = report["interim_channel"]["hits"]
    lines += [""] + (
        [f"- {h['doc_num']} ({h['agency']}, {h['issue_date']}): {h['title']}" for h in hits]
        or ["No hit."]
    )
    lines += [
        "",
        "## Open items M-01 to M-10",
        "",
        "| Item | Result | Found | Missing | Candidates |",
        "|---|---|---|---|---|",
    ]
    for o in report["open_items"]:
        found = ", ".join(f"{f['number']} ({f['eff_status']})" for f in o["found"]) or "-"
        missing = ", ".join(o["missing"]) or "-"
        lines.append(
            f"| {o['id']} | {o['result']} | {found} | {missing} | {len(o['candidates'])} |"
        )
    if report["errors"]:
        lines += ["", "## Errors", ""] + [f"- {e}" for e in report["errors"]]
    return "\n".join(lines) + "\n"


def write_report(out_dir: Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"watch-{report['date']}.json"
    mp = out_dir / f"watch-{report['date']}.md"
    jp.write_text(
        json.dumps(report, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    mp.write_text(report_markdown(report), encoding="utf-8")
    return jp, mp


def run_and_package(
    fetcher: Fetcher,
    out_dir: Path,
    signer: Any,
    *,
    sources_root: Path | None = None,
    only: str | None = None,
    now: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The whole run: watch, write incoming texts, the report and the signed package."""
    from supervisor.regkb import package

    now = now or datetime.now(UTC)
    sources_root = sources_root or (REPO_ROOT / "regulations" / "sources")
    prev = latest_report(out_dir)
    result = run_watch(fetcher, only=only, prev=prev, now=now, progress=progress)
    write_incoming(sources_root, result.incoming)
    jp, mp = write_report(out_dir, result.report)
    pkg_path, pkg_sha = package.build_package(
        out_dir / f"update-package-{result.report['date']}.zip",
        report_json=jp,
        report_md=mp,
        incoming=result.incoming,
        signer=signer,
        run_id=str(result.report["run_id"]),
        created_at=utc_stamp(now),
    )
    return {
        "report": result.report,
        "report_json": jp,
        "report_md": mp,
        "report_sha256": sha256_hex(jp.read_bytes()),
        "package": pkg_path,
        "package_sha256": pkg_sha,
    }
