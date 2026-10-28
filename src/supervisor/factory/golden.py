"""Golden-set store of an agent (WP-F2): ``<DATA_DIR>/factory/<agent_id>/golden/cases.json``.

The eval_pack store of a definition. A person uploads a JSON or CSV file of cases; the editor shows
the count and the stratification (cases per checklist item and per expected verdict). The gate that
uses the set is WP-F3. Synthetic Vietnamese cases only: every case text goes through the masker
and a case that trips it is refused (and listed), never stored.

Case fields: ``case_id`` (slug), ``checklist_id`` (an item of the definition), ``input`` (text, at
most 2,000 characters), ``expected_verdict`` (``pass`` / ``fail`` / ``not_applicable`` /
``question``), ``note`` (optional, at most 300 characters). CSV has the same names as header.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.factory import caps

MAX_BYTES = 1_000_000
MAX_CASES = 500
MAX_INPUT = 2000
MAX_NOTE = 300
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
FIELDS = ("case_id", "checklist_id", "input", "expected_verdict", "note")
_PII_KEY = b"factory-golden-span-finder"


class GoldenError(SupervisorError):
    """A golden-set upload is refused (shown as HTTP 400)."""


def trips_masker(text: str) -> bool:
    """True when the Vietnamese regex masker finds personal data (name, phone, account, id,
    email, address) in ``text``. The masker is only used to find spans; nothing is stored."""
    from supervisor.adapters.masking.vn_regex import VnRegexMasker

    return bool(VnRegexMasker(_PII_KEY).find(text or ""))


def golden_dir(data_dir: Path, agent_id: str) -> Path:
    if not caps.ID_RE.match(agent_id):
        raise GoldenError("invalid agent id")
    return Path(data_dir) / "factory" / agent_id / "golden"


def parse_upload(filename: str, raw: bytes) -> list[dict[str, Any]]:
    """The cases of an uploaded file as plain dicts (not yet checked case by case)."""
    if len(raw) > MAX_BYTES:
        raise GoldenError(f"the file is larger than {MAX_BYTES // 1000} KB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise GoldenError("the file must be UTF-8") from None
    name = (filename or "").lower()
    rows: list[Any]
    if name.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        missing = [f for f in FIELDS[:4] if f not in (reader.fieldnames or [])]
        if missing:
            raise GoldenError(f"the CSV header lacks: {', '.join(missing)}")
        rows = list(reader)
    elif name.endswith(".json"):
        try:
            doc = json.loads(text)
        except ValueError:
            raise GoldenError("the file is not valid JSON") from None
        rows = doc.get("cases") if isinstance(doc, Mapping) else doc
        if not isinstance(rows, list):
            raise GoldenError("the JSON must be a list of cases or an object with a cases list")
    else:
        raise GoldenError("the file must end in .json or .csv")
    if not rows:
        raise GoldenError("the file holds no case")
    if len(rows) > MAX_CASES:
        raise GoldenError(f"more than {MAX_CASES} cases in one file")
    out = []
    for r in rows:
        if not isinstance(r, Mapping):
            raise GoldenError("every case must be an object")
        out.append({k: r.get(k) for k in FIELDS if r.get(k) not in (None, "")})
    return out


def check_cases(
    cases: Iterable[Mapping[str, Any]], checklist_ids: Iterable[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Split into ``(accepted, rejected)``; a rejection is ``{case_id, reason}``."""
    ids = set(checklist_ids)
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in cases:
        cid = str(c.get("case_id") or "")
        why = ""
        text = str(c.get("input") or "")
        if not CASE_ID_RE.match(cid):
            why = "case_id is missing or not a short id"
        elif cid in seen:
            why = "case_id appears twice in the file"
        elif c.get("checklist_id") not in ids:
            why = "checklist_id is not an item of this agent"
        elif c.get("expected_verdict") not in caps.VERDICTS:
            why = f"expected_verdict must be one of {', '.join(caps.VERDICTS)}"
        elif not text.strip() or len(text) > MAX_INPUT:
            why = f"input must be text of 1 to {MAX_INPUT} characters"
        elif len(str(c.get("note") or "")) > MAX_NOTE:
            why = f"note is longer than {MAX_NOTE} characters"
        elif trips_masker(text) or trips_masker(str(c.get("note") or "")):
            why = "the text holds personal data (masker); use synthetic data only"
        seen.add(cid)
        if why:
            bad.append({"case_id": cid[:64] or "?", "reason": why})
        else:
            ok.append(
                {
                    "case_id": cid,
                    "checklist_id": str(c["checklist_id"]),
                    "input": text.strip(),
                    "expected_verdict": str(c["expected_verdict"]),
                    "note": str(c.get("note") or ""),
                }
            )
    return ok, bad


def load_cases(data_dir: Path, agent_id: str) -> list[dict[str, Any]]:
    path = golden_dir(data_dir, agent_id) / "cases.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [c for c in doc if isinstance(c, dict)] if isinstance(doc, list) else []


def store_cases(
    data_dir: Path, agent_id: str, accepted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge by ``case_id`` (a new case replaces the old one with the same id) and write."""
    merged = {c["case_id"]: c for c in load_cases(data_dir, agent_id)}
    merged.update({c["case_id"]: c for c in accepted})
    if len(merged) > MAX_CASES * 4:
        raise GoldenError("the golden set is full")
    cases = [merged[k] for k in sorted(merged)]
    d = golden_dir(data_dir, agent_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "cases.json.tmp"
    tmp.write_text(json.dumps(cases, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    tmp.replace(d / "cases.json")
    return cases


def stratification(
    cases: Iterable[Mapping[str, Any]], checklist_ids: Iterable[str]
) -> dict[str, Any]:
    """Counts only (integers): per checklist item, per verdict, and the items with no case."""
    cases = list(cases)
    per_item = Counter(str(c.get("checklist_id")) for c in cases)
    per_verdict = Counter(str(c.get("expected_verdict")) for c in cases)
    ids = list(checklist_ids)
    return {
        "total": len(cases),
        "per_item": {i: per_item.get(i, 0) for i in ids},
        "per_verdict": {v: per_verdict.get(v, 0) for v in caps.VERDICTS},
        "uncovered": [i for i in ids if per_item.get(i, 0) == 0],
    }
