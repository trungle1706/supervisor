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
import hashlib
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


# ------------------------------------------------------------------------------ gate cases (WP-F3)
# The test gate runs the real harness on a case, so a gate case carries the inputs of a run:
#
#   {case_id, inputs: {system, facts, packs, regkb, documents}, expected: {checklist_id: verdict},
#    expected_evidence_refs: [ref], rubric_notes}
#
# ``inputs`` is the subset of the run inputs of ``factory.runtime.run_agent`` (facts v1 export,
# system record fields, pack results, RegKB rows, document sections). Synthetic Vietnamese only;
# every string goes through the masker. A legacy F2 case (one text, one expected verdict) is
# converted by ``legacy_to_gate``. Labels for the calibration subset live in ``calibration.json``.

GATE_FILE = "gate_cases.json"
LABEL_FILE = "calibration.json"
INPUT_KEYS = ("system", "facts", "packs", "regkb", "documents")
MAX_INPUT_BYTES = 60_000
MAX_REFS = 20
MAX_LABELS = 2000
LABEL_SOURCES = ("golden", "simulation")


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_has_float(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_float(v) for v in value)
    return False


def _why_not_gate_case(c: Mapping[str, Any], ids: set[str]) -> str:
    if not CASE_ID_RE.match(str(c.get("case_id") or "")):
        return "case_id is missing or not a short id"
    inputs = c.get("inputs")
    if not isinstance(inputs, Mapping) or not inputs:
        return "inputs must be an object (system, facts, packs, regkb, documents)"
    extra = sorted(set(inputs) - set(INPUT_KEYS))
    if extra:
        return f"inputs has unknown key(s): {', '.join(extra)}"
    if len(json.dumps(inputs, ensure_ascii=False)) > MAX_INPUT_BYTES:
        return f"inputs is larger than {MAX_INPUT_BYTES // 1000} KB"
    if _has_float(c):
        return "a number with a decimal point is not allowed (integers only)"
    expected = c.get("expected")
    if not isinstance(expected, Mapping) or not expected:
        return "expected must map checklist ids to verdicts"
    for cid, verdict in expected.items():
        if cid not in ids:
            return f"expected names {str(cid)[:40]}, which is not an item of this agent"
        if verdict not in caps.VERDICTS:
            return f"expected verdict for {cid} must be one of {', '.join(caps.VERDICTS)}"
    refs = c.get("expected_evidence_refs", [])
    if (
        not isinstance(refs, list)
        or len(refs) > MAX_REFS
        or not all(isinstance(r, str) and 0 < len(r) <= caps.REF_MAX for r in refs)
    ):
        return f"expected_evidence_refs must be a list of at most {MAX_REFS} refs"
    if len(str(c.get("rubric_notes") or "")) > MAX_NOTE:
        return f"rubric_notes is longer than {MAX_NOTE} characters"
    if any(trips_masker(s) for s in _strings(c)):
        return "the case holds personal data (masker); use synthetic data only"
    return ""


def check_gate_cases(
    cases: Iterable[Mapping[str, Any]], checklist_ids: Iterable[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Split gate cases into ``(accepted, rejected)``; a rejection is ``{case_id, reason}``."""
    ids = set(checklist_ids)
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in cases:
        cid = str(c.get("case_id") or "")
        why = "case_id appears twice in the file" if cid in seen else _why_not_gate_case(c, ids)
        seen.add(cid)
        if why:
            bad.append({"case_id": cid[:64] or "?", "reason": why})
            continue
        ok.append(
            {
                "case_id": cid,
                "inputs": json.loads(json.dumps(c["inputs"])),
                "expected": {str(k): str(v) for k, v in dict(c["expected"]).items()},
                "expected_evidence_refs": list(c.get("expected_evidence_refs") or []),
                "rubric_notes": str(c.get("rubric_notes") or ""),
            }
        )
    return ok, bad


def is_gate_upload(rows: Iterable[Mapping[str, Any]]) -> bool:
    return any("inputs" in r or "expected" in r for r in rows)


def parse_json_rows(filename: str, raw: bytes, key: str = "cases") -> list[dict[str, Any]]:
    """Rows of a JSON upload (a list, or an object with ``key``): gate cases and labels."""
    if len(raw) > MAX_BYTES:
        raise GoldenError(f"the file is larger than {MAX_BYTES // 1000} KB")
    if not (filename or "").lower().endswith(".json"):
        raise GoldenError("the file must end in .json")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise GoldenError("the file is not valid UTF-8 JSON") from None
    rows = doc.get(key) if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list) or not rows:
        raise GoldenError(f"the JSON must be a non-empty list or an object with a {key} list")
    if not all(isinstance(r, Mapping) for r in rows):
        raise GoldenError("every row must be an object")
    return [dict(r) for r in rows]


def _write_list(d: Path, name: str, rows: list[dict[str, Any]]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    tmp.replace(d / name)


def _read_list(path: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [c for c in doc if isinstance(c, dict)] if isinstance(doc, list) else []


def load_gate_cases(data_dir: Path, agent_id: str) -> list[dict[str, Any]]:
    return _read_list(golden_dir(data_dir, agent_id) / GATE_FILE)


def store_gate_cases(
    data_dir: Path, agent_id: str, accepted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = {c["case_id"]: c for c in load_gate_cases(data_dir, agent_id)}
    merged.update({c["case_id"]: c for c in accepted})
    if len(merged) > caps.GOLDEN_MAX_CASES:
        raise GoldenError("the golden set is full")
    cases = [merged[k] for k in sorted(merged)]
    _write_list(golden_dir(data_dir, agent_id), GATE_FILE, cases)
    return cases


def legacy_to_gate(case: Mapping[str, Any]) -> dict[str, Any]:
    """A WP-F2 case (one text, one expected verdict) as a gate case: the text is a document
    section the run can load and cite."""
    cid = str(case["case_id"])
    ref = f"{cid}#1"
    return {
        "case_id": cid,
        "inputs": {
            "documents": [{"doc_id": cid, "sections": [{"ref": ref, "text": case["input"]}]}]
        },
        "expected": {str(case["checklist_id"]): str(case["expected_verdict"])},
        "expected_evidence_refs": [],
        "rubric_notes": str(case.get("note") or ""),
    }


def all_gate_cases(data_dir: Path, agent_id: str) -> list[dict[str, Any]]:
    """The gate cases of an agent: the stored gate cases plus the converted legacy cases whose
    id is not already a gate case. Ordered by case_id."""
    cases = {c["case_id"]: c for c in load_gate_cases(data_dir, agent_id)}
    for c in load_cases(data_dir, agent_id):
        cases.setdefault(c["case_id"], legacy_to_gate(c))
    return [cases[k] for k in sorted(cases)]


def gate_stratification(
    cases: Iterable[Mapping[str, Any]], checklist_ids: Iterable[str]
) -> dict[str, Any]:
    """Integer counts and the readiness problems of the set for a full gate: at least
    ``GOLDEN_MIN_CASES`` cases and every checklist item covered by at least one case."""
    cases = list(cases)
    ids = list(checklist_ids)
    per_item = Counter(cid for c in cases for cid in (c.get("expected") or {}))
    per_verdict = Counter(v for c in cases for v in (c.get("expected") or {}).values())
    uncovered = [i for i in ids if per_item.get(i, 0) == 0]
    problems = []
    if len(cases) < caps.GOLDEN_MIN_CASES:
        problems.append(f"too_few_cases: {len(cases)} of {caps.GOLDEN_MIN_CASES}")
    if uncovered:
        problems.append("items_without_case: " + ", ".join(uncovered))
    return {
        "total": len(cases),
        "min_cases": caps.GOLDEN_MIN_CASES,
        "per_item": {i: per_item.get(i, 0) for i in ids},
        "per_verdict": {v: per_verdict.get(v, 0) for v in caps.VERDICTS},
        "uncovered": uncovered,
        "problems": problems,
        "ready": not problems,
    }


def golden_sha256(data_dir: Path, agent_id: str) -> str:
    raw = json.dumps(all_gate_cases(data_dir, agent_id), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------ calibration labels
# {case_id, finding_id, human_verdict, label_by, labelled_at}; a finding id is ``f-<checklist_id>``
# (the id the runtime gives). ``source`` is ``golden`` (a case of the set) or ``simulation``
# (a mark of the simulation review; ``ref`` names the run and the system).


def checklist_of_finding(finding_id: str) -> str:
    return finding_id[2:] if finding_id.startswith("f-") else finding_id


def check_labels(
    rows: Iterable[Mapping[str, Any]], case_ids: Iterable[str], checklist_ids: Iterable[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    known, ids = set(case_ids), set(checklist_ids)
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, str]] = []
    for r in rows:
        cid, fid = str(r.get("case_id") or ""), str(r.get("finding_id") or "")
        why = ""
        if cid not in known:
            why = "case_id is not a case of the golden set"
        elif checklist_of_finding(fid) not in ids:
            why = "finding_id must be f-<checklist id>"
        elif r.get("human_verdict") not in caps.VERDICTS:
            why = f"human_verdict must be one of {', '.join(caps.VERDICTS)}"
        elif not str(r.get("label_by") or "").strip() or len(str(r.get("label_by"))) > 120:
            why = "label_by is the person who labelled (at most 120 characters)"
        elif not caps.TIMESTAMP_RE.match(str(r.get("labelled_at") or "")):
            why = "labelled_at must be an RFC 3339 UTC timestamp"
        if why:
            bad.append({"case_id": cid[:64] or "?", "reason": why})
        else:
            ok.append(
                {
                    "case_id": cid,
                    "finding_id": fid,
                    "human_verdict": str(r["human_verdict"]),
                    "label_by": str(r["label_by"]).strip(),
                    "labelled_at": str(r["labelled_at"]),
                    "source": "golden",
                    "ref": "",
                }
            )
    return ok, bad


def load_labels(data_dir: Path, agent_id: str) -> list[dict[str, Any]]:
    return _read_list(golden_dir(data_dir, agent_id) / LABEL_FILE)


def store_labels(
    data_dir: Path, agent_id: str, labels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge by (case_id, finding_id): a later label of the same finding replaces the earlier."""
    merged = {(r["case_id"], r["finding_id"]): r for r in load_labels(data_dir, agent_id)}
    merged.update({(r["case_id"], r["finding_id"]): r for r in labels})
    if len(merged) > MAX_LABELS:
        raise GoldenError("too many calibration labels")
    rows = [merged[k] for k in sorted(merged)]
    _write_list(golden_dir(data_dir, agent_id), LABEL_FILE, rows)
    return rows
