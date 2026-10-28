"""Internal documents in RegKB (WP-W3, flag REGKB_INTERNAL, needs LAWAGENT_ENABLED).

What happens, in order:

1. ``InternalDocs.upload`` takes a .txt, .md or .pdf (text layer) file, reads its text, masks the
   personal data (``Masker``), and stores under ``DATA_DIR/regkb/internal/<doc_id>/``:
   ``text.txt`` (the raw text, for the person), ``text.masked.txt`` (the only text a model sees)
   and ``.meta.json`` (title, owner group, version label, who, when, sha256 of ``text.txt``).
   One row goes to ``regkb_internal_doc`` and one ``regkb_internal`` record to the chain.
2. ``InternalDocs.draft`` (law agent "internal" mode) splits the masked text into sections
   (``internal_text.split_sections``), asks the gateway model for at most one duty row per section,
   checks each reply with ``check_internal_draft`` (duty ids known, quote inside the section) and
   writes what passes to ``regkb_draft`` with ``instrument_id = VN-INT-<doc_id>``.
3. A person with ``regkb.confirm`` confirms rows on the drafts page. ``InternalDocs.after_decision``
   then rebuilds ``instrument.yaml`` of the document from ALL confirmed rows, checks it with the
   RegKB validator, and drops the RegKB caches. The loader reads the file at startup next to
   ``regulations/vn`` while the flag is on.

The model only drafts. The raw text never goes to the model. Nothing leaves the gateway.
Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.ports import ChatModel
from supervisor.regkb.drafts import MAX_QUOTE, DraftStore, quote_key
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.internal_text import Section, split_sections
from supervisor.regkb.lawagent import BANNER, MIN_QUOTE, TIMEOUT_S, duty_lines, normalise_ws
from supervisor.regkb.loader import (
    INTERNAL_BINDING,
    INTERNAL_DOC_FILE,
    INTERNAL_DOC_PREFIX,
    INTERNAL_ONLY_VERIFICATION,
    REPO_ROOT,
    _load_yaml,
    _Loader,
    internal_docs_dir,
)

log = logging.getLogger("supervisor.regkb.internal")

TABLE = "regkb_internal_doc"
STATUSES = ("uploaded", "drafted", "confirmed", "retired")
SUFFIXES = (".txt", ".md", ".pdf")
PROMPT_VERSION = "lawagent-int-1"
DOC_ID_RE = re.compile(r"^[0-9A-F]{12}$")
MAX_FIELD = 200
MAX_DRAFT_SECTIONS = 300
MIN_TEXT_CHARS = 40
FILE_RAW = "text.txt"
FILE_MASKED = "text.masked.txt"
FILE_META = ".meta.json"
FILE_DRAFTS = "drafts.json"
SOURCE_URL = "https://regkb.internal.invalid/{instrument}"
OFF_MESSAGE = (
    "internal documents in RegKB are off (REGKB_INTERNAL=1 and LAWAGENT_ENABLED=1 turn them on)"
)


class InternalError(SupervisorError):
    """A refused step. The message starts with the short code (HTTP 400 at the route)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


# ---------------------------------------------------------------------------- flag and ids


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "regkb_internal", False) and getattr(settings, "lawagent_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise InternalError("regkb_internal_off", OFF_MESSAGE)


def instrument_id(doc_id: str) -> str:
    return INTERNAL_DOC_PREFIX + doc_id


def is_internal_instrument(iid: str) -> bool:
    return str(iid).startswith(INTERNAL_DOC_PREFIX)


def doc_id_of(iid: str) -> str:
    return str(iid)[len(INTERNAL_DOC_PREFIX) :]


def check_doc_id(doc_id: str) -> str:
    if not DOC_ID_RE.match(doc_id or ""):
        raise InternalError("bad_doc_id", "the document id is 12 characters of 0-9 A-F")
    return doc_id


def max_bytes(settings: Any) -> int:
    return int(getattr(settings, "regkb_internal_max_mb", 10)) * 1024 * 1024


# ---------------------------------------------------------------------------- reading a file


def read_upload(name: str, data: bytes, limit: int) -> str:
    """Text of an uploaded file. Raises InternalError with a code for anything not accepted."""
    low = (name or "").lower()
    if not low.endswith(SUFFIXES):
        raise InternalError("bad_type", "only .txt, .md and .pdf (with a text layer) are taken")
    if not data:
        raise InternalError("empty_file", "the file is empty")
    if len(data) > limit:
        raise InternalError("too_large", f"the file is larger than {limit // 1_048_576} MB")
    from supervisor.detectors import intake as di

    try:
        if low.endswith(".pdf"):
            if not data.startswith(b"%PDF-"):
                raise InternalError("bad_type", "the file is not a PDF")
            text = di.read_pdf(data, _deadline())
            if not text.strip():
                raise InternalError("pdf_no_text_layer", "the PDF has no text layer (a scan?)")
            return text
        if data.startswith((b"%PDF-", b"PK\x03\x04")):
            raise InternalError("bad_type", "the content is not plain text")
        return di.decode_text(data)
    except di.Uninspectable as exc:
        code = "pdf_reader_missing" if exc.reason == "pdf_reader_missing" else "unreadable"
        raise InternalError(code, f"the file cannot be read ({exc.reason})") from None


def _deadline() -> float:
    import time

    return time.monotonic() + 30.0


# ---------------------------------------------------------------------------- the rules


@dataclass(frozen=True)
class Checked:
    ok: bool
    reason: str
    row: dict[str, Any] | None = None
    dropped_dimensions: int = 0


def _dimension_ids() -> tuple[str, ...]:
    from supervisor.governance.risk_dimensions import DIMENSION_IDS

    return tuple(DIMENSION_IDS)


def check_internal_draft(
    raw: Mapping[str, Any], section: Section, duties: Mapping[str, Any]
) -> Checked:
    """Rules for the reply of the model for one section. The first rule that fails drops it.

    1. the model says the section imposes a duty (``imposes_duty`` true);
    2. one to three duty ids, every one in duties.yaml;
    3. subject, trigger, evidence and summary are not empty;
    4. the quote has 12..2000 characters and is a substring of the section text (white space
       folded, nothing else changed);
    5. dimension ids outside the eight are removed (counted, not a reason to drop).
    """
    if not raw.get("imposes_duty"):
        return Checked(False, "no_duty")
    ids = raw.get("duties")
    if not isinstance(ids, list):
        ids = [raw.get("duty_id")] if raw.get("duty_id") else []
    clean: list[str] = []
    for d in ids:
        d = str(d or "").strip()
        if d not in duties:
            return Checked(False, "unknown_duty")
        if d not in clean:
            clean.append(d)
    if not 1 <= len(clean) <= 3:
        return Checked(False, "bad_duty_count")
    fields = {
        k: normalise_ws(str(raw.get(k, "") or ""))
        for k in ("subject", "trigger", "evidence_asked", "summary_en")
    }
    if not all(fields.values()):
        return Checked(False, "missing_field")
    quote = normalise_ws(str(raw.get("quote", "") or ""))
    if not MIN_QUOTE <= len(quote) <= MAX_QUOTE:
        return Checked(False, "bad_quote_length")
    if quote not in section.text:
        return Checked(False, "quote_not_in_section")
    known = _dimension_ids()
    asked = raw.get("dimensions") if isinstance(raw.get("dimensions"), list) else []
    dims = [d for i, d in enumerate(asked) if d in known and d not in asked[:i]]
    return Checked(
        True,
        "",
        {
            "article": section.ref,
            "duty_id": ",".join(clean),
            "subject": fields["subject"],
            "trigger": fields["trigger"],
            "evidence_asked": fields["evidence_asked"],
            "text_vi": quote,
            "summary_en": fields["summary_en"],
            "dimensions": dims,
            "label": section.label,
        },
        dropped_dimensions=len(asked) - len(dims),
    )


def schema() -> dict[str, Any]:
    dims = list(_dimension_ids())
    return {
        "type": "object",
        "properties": {
            "imposes_duty": {"type": "boolean"},
            "duties": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "trigger": {"type": "string"},
            "evidence_asked": {"type": "string"},
            "quote": {"type": "string"},
            "summary_en": {"type": "string"},
            "dimensions": {"type": "array", "items": {"type": "string", "enum": dims}},
        },
        "required": [
            "imposes_duty",
            "duties",
            "subject",
            "trigger",
            "evidence_asked",
            "quote",
            "summary_en",
            "dimensions",
        ],
        "additionalProperties": False,
    }


_SYSTEM = (
    "You read one section of an internal policy of a bank. You say whether the section imposes a "
    "duty on the bank or on its staff or systems, and if so you describe that one duty.\n"
    "Rules:\n"
    "- imposes_duty is false when the section only gives a definition, a purpose or background. "
    "Then give empty strings and empty lists for the other fields.\n"
    "- duties: one to three ids from the duty list below. Never invent an id.\n"
    "- quote must be copied word for word from the section text (same spelling, same "
    "diacritics). Do not shorten with '...' and do not translate. One sentence or one clause, "
    "at most 600 characters.\n"
    "- subject: who must act. trigger: when the duty applies. evidence_asked: what an auditor "
    "would ask to see. summary_en: one English sentence. Write these four in English.\n"
    "- dimensions: the ids from the risk dimension list below that the duty touches (zero or "
    "more).\n"
    "- Tokens like <PHONE:ab12> stand for masked personal data. Leave them as they are.\n"
    "- Draft only what the text says. Do not give legal advice.\n"
    "Duty list (id: meaning):\n{duties}\n"
    "Risk dimension list (id: meaning):\n{dimensions}"
)


def dimension_lines() -> str:
    from supervisor.governance.risk_dimensions import load_config

    return "\n".join(f"{d.id}: {d.label_en}" for d in load_config().dimensions)


def build_messages(section: Section, duties: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _SYSTEM.format(duties=duty_lines(duties), dimensions=dimension_lines()),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"section": section.label, "section_text": section.text}, ensure_ascii=False
            ),
        },
    ]


# ---------------------------------------------------------------------------- the run summary


@dataclass
class RunSummary:
    run_id: str
    doc_id: str
    model_id: str
    mock: bool
    sections_read: int = 0
    kept: int = 0
    dropped: int = 0
    no_duty: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    skipped_existing: int = 0
    skipped_decided: int = 0
    model_errors: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "doc_id": self.doc_id,
            "model_id": self.model_id,
            "mock": self.mock,
            "prompt_version": PROMPT_VERSION,
            "sections_read": self.sections_read,
            "kept": self.kept,
            "dropped": self.dropped,
            "no_duty": self.no_duty,
            "drop_reasons": dict(self.drop_reasons),
            "skipped_existing": self.skipped_existing,
            "skipped_decided": self.skipped_decided,
            "model_errors": self.model_errors,
        }

    def lines(self) -> list[str]:
        out = []
        if self.mock:
            out.append("[WARN] MOCK MODEL: these drafts did not come from a real model.")
        out.append(
            f"[OK] run {self.run_id}: {instrument_id(self.doc_id)}, model {self.model_id}, "
            f"prompt {PROMPT_VERSION}"
        )
        out.append(
            f"[OK] sections read {self.sections_read}; no duty {self.no_duty}; kept {self.kept}; "
            f"dropped by the rules {self.dropped}"
        )
        if self.drop_reasons:
            out.append(
                "[OK] drop reasons: "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.drop_reasons.items()))
            )
        if self.skipped_existing or self.skipped_decided:
            out.append(
                f"[OK] not written again: {self.skipped_existing} already drafted or confirmed, "
                f"{self.skipped_decided} already dropped by a person"
            )
        if self.model_errors:
            out.append(f"[FAIL] model errors on {self.model_errors} section(s); run again")
        return out


# ---------------------------------------------------------------------------- the service


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _stamp(value: Any) -> str:
    return format_ts(value) if hasattr(value, "isoformat") else str(value or "")


class InternalDocs:
    """Files, the ``regkb_internal_doc`` table and the drafts of the internal documents."""

    def __init__(
        self,
        state: Any,
        clock: Any,
        settings: Any,
        *,
        masker: Any = None,
        evidence: Any = None,
    ) -> None:
        self.state = state
        self.clock = clock
        self.settings = settings
        self.masker = masker
        self.evidence = evidence
        self.drafts = DraftStore(state, clock)

    # ---- paths -------------------------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(os.path.abspath(Path(self.settings.data_dir) / "regkb" / "internal"))

    def doc_dir(self, doc_id: str) -> Path:
        return self.root / check_doc_id(doc_id)

    # ---- chain -------------------------------------------------------------------------
    def _chain(self, doc_id: str, payload: Mapping[str, Any]) -> None:
        if self.evidence is None:
            return
        try:
            self.evidence.record("regkb_internal", instrument_id(doc_id), payload)
        except Exception:  # noqa: BLE001 - the row is stored; log and go on
            log.exception("regkb_internal chain record failed")

    # ---- upload ------------------------------------------------------------------------
    def _mask(self, text: str) -> str:
        if self.masker is None:
            raise InternalError(
                "masker_off", "personal data cannot be masked here (MASKER_KIND=none); refused"
            )
        return str(self.masker.mask(text))

    def upload(
        self,
        name: str,
        data: bytes,
        *,
        title: str,
        owner_group: str,
        version_label: str,
        actor: str,
    ) -> dict[str, Any]:
        require_on(self.settings)
        if not actor:
            raise InternalError("actor_required", "a signed-in person must upload")
        text = read_upload(name, data, max_bytes(self.settings))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text.strip()) < MIN_TEXT_CHARS:
            raise InternalError("too_short", f"the text has fewer than {MIN_TEXT_CHARS} characters")
        masked = self._mask(text)
        stem = Path(name).stem
        meta_in = {
            "title": (title or stem).strip(),
            "owner_group": (owner_group or "").strip(),
            "version_label": (version_label or "v1").strip(),
        }
        if not meta_in["owner_group"]:
            raise InternalError("owner_group_required", "name the owner group of the document")
        for key, value in meta_in.items():
            if len(value) > MAX_FIELD:
                raise InternalError(
                    "field_too_long", f"{key} is longer than {MAX_FIELD} characters"
                )
            meta_in[key] = " ".join(self._mask(value).split())
        sections = split_sections(masked)
        if not sections:
            raise InternalError("no_sections", "no section could be found in the text")
        raw_bytes = text.encode("utf-8")
        masked_bytes = masked.encode("utf-8")
        for _ in range(5):
            doc_id = secrets.token_hex(6).upper()
            if not (self.root / doc_id).exists():
                break
        else:  # pragma: no cover - 5 collisions of 48 bits
            raise InternalError("id_clash", "try again")
        ddir = self.doc_dir(doc_id)
        ddir.mkdir(parents=True, exist_ok=False)
        now = self.clock.now()
        meta = {
            "doc_id": doc_id,
            **meta_in,
            "uploaded_by": actor,
            "uploaded_at": _stamp(now),
            "sha256": _sha(raw_bytes),
            "masked_sha256": _sha(masked_bytes),
            "source_name": Path(name).name[:120],
            "source_bytes": len(data),
            "mask_version": str(getattr(self.masker, "mask_version", "")),
            "sections": len(sections),
        }
        try:
            _write(ddir / FILE_RAW, raw_bytes)
            _write(ddir / FILE_MASKED, masked_bytes)
            _write(ddir / FILE_META, json.dumps(meta, ensure_ascii=False, indent=2).encode())
            row = self.state.insert(
                TABLE,
                {
                    "doc_id": doc_id,
                    "title": meta["title"],
                    "owner_group": meta["owner_group"],
                    "version_label": meta["version_label"],
                    "sha256": meta["sha256"],
                    "status": "uploaded",
                    "uploaded_by": actor,
                    "uploaded_at": now,
                },
            )
        except Exception:
            shutil.rmtree(ddir, ignore_errors=True)
            raise
        self._chain(
            doc_id,
            {
                "action": "upload",
                "doc_id": doc_id,
                "sha256": meta["sha256"],
                "masked_sha256": meta["masked_sha256"],
                "sections": len(sections),
                "bytes": len(data),
            },
        )
        return {**self._view(dict(row)), "section_count": len(sections)}

    # ---- reading -----------------------------------------------------------------------
    def _row(self, doc_id: str) -> dict[str, Any]:
        row = self.state.get(TABLE, {"doc_id": check_doc_id(doc_id)})
        if row is None:
            raise InternalError("unknown_doc", "this internal document does not exist")
        return dict(row)

    def _view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        counts = Counter(r["status"] for r in self.drafts.list(instrument_id(row["doc_id"])))
        return {
            "doc_id": row["doc_id"],
            "instrument_id": instrument_id(row["doc_id"]),
            "title": row["title"],
            "owner_group": row["owner_group"],
            "version_label": row["version_label"],
            "sha256": row["sha256"],
            "status": row["status"],
            "uploaded_by": row["uploaded_by"],
            "uploaded_at": _stamp(row["uploaded_at"]),
            "row_version": row.get("row_version"),
            "drafts": {s: counts.get(s, 0) for s in ("draft", "confirmed", "dropped")},
            "has_instrument": (self.doc_dir(row["doc_id"]) / INTERNAL_DOC_FILE).is_file(),
        }

    def list(self) -> list[dict[str, Any]]:
        rows = self.state.query(TABLE, {}, order_by=("uploaded_at", "doc_id"))
        return [self._view(dict(r)) for r in rows]

    def masked_text(self, doc_id: str) -> str:
        """The masked text, checked against the hash in the sidecar (a changed file is refused)."""
        self._row(doc_id)
        ddir = self.doc_dir(doc_id)
        try:
            meta = json.loads((ddir / FILE_META).read_text("utf-8"))
            data = (ddir / FILE_MASKED).read_bytes()
        except (OSError, ValueError):
            raise InternalError(
                "files_missing", "the stored files of this document are missing"
            ) from None
        if _sha(data) != meta.get("masked_sha256"):
            raise InternalError("files_changed", "the stored masked text changed after upload")
        return data.decode("utf-8")

    def sections(self, doc_id: str) -> list[Section]:
        return split_sections(self.masked_text(doc_id))

    def get(self, doc_id: str) -> dict[str, Any]:
        out = self._view(self._row(doc_id))
        out["sections"] = [
            {"n": s.n, "ref": s.ref, "label": s.label, "heading": s.heading, "chars": len(s.text)}
            for s in self.sections(doc_id)
        ]
        out["banner"] = BANNER
        return out

    def section(self, doc_id: str, n: int) -> dict[str, Any]:
        """The masked text of one section (for the checklist drafter of WP-F2)."""
        secs = self.sections(doc_id)
        if not 1 <= n <= len(secs):
            raise InternalError("unknown_section", f"the document has sections 1 to {len(secs)}")
        s = secs[n - 1]
        return {
            "doc_id": doc_id,
            "instrument_id": instrument_id(doc_id),
            "n": s.n,
            "ref": s.ref,
            "label": s.label,
            "heading": s.heading,
            "text": s.text,
            "masked": True,
        }

    # ---- sidecar of the drafts ---------------------------------------------------------
    def draft_meta(self, doc_id: str) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads((self.doc_dir(doc_id) / FILE_DRAFTS).read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_draft_meta(self, doc_id: str, meta: Mapping[str, Any]) -> None:
        _write(
            self.doc_dir(doc_id) / FILE_DRAFTS,
            json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True).encode(),
        )

    # ---- the law agent, internal mode --------------------------------------------------
    def draft(
        self,
        doc_id: str,
        chat: ChatModel,
        *,
        duties: Mapping[str, Any] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> RunSummary:
        require_on(self.settings)
        row = self._row(doc_id)
        if row["status"] == "retired":
            raise InternalError("retired", "this document is retired")
        secs = self.sections(doc_id)
        if len(secs) > MAX_DRAFT_SECTIONS:
            raise InternalError("too_many_sections", f"more than {MAX_DRAFT_SECTIONS} sections")
        if duties is None:
            duties = (_load_yaml(REPO_ROOT / "regulations" / "schema" / "duties.yaml") or {})[
                "duties"
            ]
        iid = instrument_id(doc_id)
        summary = RunSummary(
            run_id="lr_" + secrets.token_hex(6),
            doc_id=doc_id,
            model_id=str(getattr(chat, "model_id", "unknown")),
            mock=bool(getattr(chat, "is_mock", False)),
        )
        seen = self.drafts.existing_keys(iid)
        reasons: Counter[str] = Counter()
        say = progress or (lambda _line: None)
        sch = schema()
        for sec in secs:
            summary.sections_read += 1
            try:
                reply = chat.complete_json(build_messages(sec, duties), sch, TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - one bad section must not stop the run
                summary.model_errors += 1
                log.warning("law agent internal: section %d failed: %s", sec.n, type(exc).__name__)
                say(f"[FAIL] {sec.ref}: model error {type(exc).__name__}")
                continue
            res = check_internal_draft(reply if isinstance(reply, Mapping) else {}, sec, duties)
            if not res.ok or res.row is None:
                if res.reason == "no_duty":
                    summary.no_duty += 1
                else:
                    summary.dropped += 1
                    reasons[res.reason] += 1
                say(f"[OK] {sec.ref} {sec.label}: {res.reason}")
                continue
            key = (res.row["article"], res.row["duty_id"], quote_key(res.row["text_vi"]))
            prior = seen.get(key)
            if prior == "dropped":
                summary.skipped_decided += 1
                continue
            if prior is not None:
                summary.skipped_existing += 1
                continue
            seen[key] = "draft"
            summary.kept += 1
            summary.rows.append(
                {
                    **{k: v for k, v in res.row.items() if k not in ("dimensions", "label")},
                    "_dimensions": res.row["dimensions"],
                    "_label": res.row["label"],
                    "instrument_id": iid,
                    "source": "model",
                    "model_id": summary.model_id,
                    "prompt_version": PROMPT_VERSION,
                    "run_id": summary.run_id,
                }
            )
            say(f"[OK] {sec.ref} {sec.label}: kept")
        summary.drop_reasons = dict(reasons)
        extras = {
            r["text_vi"] + "|" + r["article"]: (r.pop("_dimensions"), r.pop("_label"))
            for r in summary.rows
        }
        stored = self.drafts.add(summary.rows)
        meta = self.draft_meta(doc_id)
        for r in stored:
            dims, label = extras[r["text_vi"] + "|" + r["article"]]
            meta[r["draft_id"]] = {"dimensions": dims, "label": label}
        if stored:
            self._save_draft_meta(doc_id, meta)
            self._set_status(doc_id, "drafted", only_from=("uploaded",))
        summary.rows = stored
        return summary

    # ---- status ------------------------------------------------------------------------
    def _set_status(
        self, doc_id: str, status: str, *, only_from: Sequence[str] | None = None
    ) -> dict[str, Any]:
        row = self._row(doc_id)
        if row["status"] == status or (only_from is not None and row["status"] not in only_from):
            return row
        try:
            return dict(
                self.state.update(
                    TABLE, {"doc_id": doc_id}, {"status": status}, int(row["row_version"])
                )
            )
        except ConcurrencyError:
            log.warning("regkb_internal_doc %s changed in another window", doc_id)
            return self._row(doc_id)

    def retire(self, doc_id: str, actor: str) -> dict[str, Any]:
        """Retire a document: its instrument file is removed and the loader no longer sees it."""
        require_on(self.settings)
        self._row(doc_id)
        path = self.doc_dir(doc_id) / INTERNAL_DOC_FILE
        if path.exists():
            path.unlink()
        invalidate_caches()
        row = self._set_status(doc_id, "retired")
        self._chain(doc_id, {"action": "retire", "doc_id": doc_id, "sha256": row["sha256"]})
        return self._view(row)

    # ---- confirmed rows become an instrument ------------------------------------------
    def after_decision(self, doc_id: str, actor: str) -> dict[str, Any]:
        """Call after a person decided a draft of this document: rebuild instrument.yaml from all
        confirmed rows, validate it, refresh the caches, set the status."""
        require_on(self.settings)
        row = self._row(doc_id)
        if row["status"] == "retired":
            return self._view(row)
        iid = instrument_id(doc_id)
        confirmed = self.drafts.list(iid, "confirmed")
        path = self.doc_dir(doc_id) / INTERNAL_DOC_FILE
        if not confirmed:
            if path.exists():
                path.unlink()
            invalidate_caches()
            return self._view(self._set_status(doc_id, "drafted", only_from=("confirmed",)))
        data = build_instrument(
            self._meta(doc_id), confirmed, self.draft_meta(doc_id), self.clock.now()
        )
        text = dump_instrument(data)
        problems = validate_instrument_text(text, doc_id, self.doc_dir(doc_id) / FILE_RAW)
        if problems:
            raise InternalError("instrument_invalid", "; ".join(problems[:3]))
        _write(path, text.encode("utf-8"))
        invalidate_caches()
        row = self._set_status(doc_id, "confirmed")
        self._chain(
            doc_id,
            {
                "action": "confirm",
                "doc_id": doc_id,
                "sha256": row["sha256"],
                "confirmed": len(confirmed),
                "dropped": len(self.drafts.list(iid, "dropped")),
                "open": len(self.drafts.list(iid, "draft")),
                "instrument_sha256": _sha(text.encode("utf-8")),
            },
        )
        return self._view(row)

    def _meta(self, doc_id: str) -> dict[str, Any]:
        try:
            return dict(json.loads((self.doc_dir(doc_id) / FILE_META).read_text("utf-8")))
        except (OSError, ValueError):
            raise InternalError(
                "files_missing", "the stored files of this document are missing"
            ) from None


# ---------------------------------------------------------------------------- the instrument


def _day(value: Any) -> str:
    return str(value or "")[:10]


def build_instrument(
    meta: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    draft_meta: Mapping[str, Mapping[str, Any]],
    now: Any,
) -> dict[str, Any]:
    """The instrument file (a dict in the shape of ``regulations/vn/*.yaml``) for one document.

    ``rows`` are the confirmed ``regkb_draft`` rows. Ids: ``VN-INT-<doc>-S<n>-NN`` (the next free
    two-digit suffix per section). Every row carries ``verification: VERIFIED_INTERNAL``.
    """
    doc_id = str(meta["doc_id"])
    iid = instrument_id(doc_id)
    today = _day(format_ts(now))
    url = SOURCE_URL.format(instrument=iid)
    source = {
        "url": url,
        "title": f"Internal document {meta['title']} ({meta['version_label']}), stored text",
        "fetched_at": _day(meta.get("uploaded_at")) or today,
        "kind": "primary",
        "sha256": meta["sha256"],
        "local_path": f"regkb/internal/{doc_id}/{FILE_RAW}",
    }
    used: Counter[str] = Counter()
    obligations = []
    for r in sorted(rows, key=lambda x: (_sec_n(x["article"]), str(x["draft_id"]))):
        ref = str(r["article"])
        used[ref] += 1
        extra = draft_meta.get(str(r["draft_id"]), {})
        dims = ", ".join(extra.get("dimensions") or []) or "none"
        n = _sec_n(ref)
        label = str(extra.get("label") or "")
        obligations.append(
            {
                "id": f"{iid}-{ref}-{used[ref]:02d}",
                "article_ref": f"Sec. {n} ({label})" if label else f"Sec. {n}",
                "text_vi": r["text_vi"],
                "summary_en": r["summary_en"],
                "duties": [d for d in str(r["duty_id"]).split(",") if d],
                "applies_to": {},
                "addressee": "bank",
                "control_mapping": [],
                "evidence_needed": [r["evidence_asked"]],
                "verification": INTERNAL_ONLY_VERIFICATION,
                "confirmed_by": r["confirmed_by"],
                "sources": [dict(source)],
                "confidence": "medium",
                "notes": (
                    f"Internal document {doc_id}, section {n}. Risk dimensions: {dims}. "
                    f"Subject: {r['subject']} Trigger: {r['trigger']} Drafted by the law agent "
                    f"(model {r.get('model_id') or '-'}, prompt {r.get('prompt_version') or '-'}, "
                    f"run {r['run_id']}); confirmed by {r['confirmed_by']} on "
                    f"{_day(_stamp(r.get('confirmed_at')))}. Not legal advice."
                ),
            }
        )
    return {
        "schema_version": 1,
        "instrument": {
            "id": iid,
            "jurisdiction": "VN",
            "kind": "internal",
            "issuer": meta["owner_group"],
            "number": meta["version_label"],
            "title_vi": meta["title"],
            "title_en": meta["title"],
            "status": "in_force",
            "binding": INTERNAL_BINDING,
            "dates": {
                "issued": {
                    "date": _day(meta.get("uploaded_at")) or today,
                    "source": url,
                    "verification": INTERNAL_ONLY_VERIFICATION,
                    "note": "date of the upload",
                }
            },
            "sources": [dict(source)],
            "verification": INTERNAL_ONLY_VERIFICATION,
            "primary_text_fetched": True,
            "last_checked": today,
            "notes": (
                "Internal document of the bank, uploaded through RegKB (WP-W3). The rows were "
                "drafted by a model from the masked text and confirmed by a person. Binding on the "
                "bank by its own rule, not by law. Not legal advice."
            ),
        },
        "obligations": obligations,
    }


def _sec_n(ref: str) -> int:
    m = re.fullmatch(r"S(\d{1,4})", str(ref))
    return int(m.group(1)) if m else 0


def dump_instrument(data: Mapping[str, Any]) -> str:
    head = (
        f"# {BANNER}\n"
        "# Written by supervisor.regkb.internal from the rows a person confirmed. Do not edit by\n"
        "# hand: the file is rebuilt after every decision on the drafts page.\n"
    )
    return head + yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False, width=100)


def validate_instrument_text(text: str, doc_id: str, raw_file: Path) -> list[str]:
    """Run the RegKB validator and the loader rules on the file in a scratch folder. Returns the
    problems (empty = valid). Nothing in the real folders changes."""
    with tempfile.TemporaryDirectory(prefix="regkb-int-") as tmp:
        docs = Path(tmp) / "regkb" / "internal"
        ddir = docs / doc_id
        ddir.mkdir(parents=True)
        shutil.copyfile(raw_file, ddir / FILE_RAW)
        target = ddir / INTERNAL_DOC_FILE
        target.write_text(text, encoding="utf-8")
        try:
            loader = _Loader(REPO_ROOT / "regulations", None, docs.resolve())
            real = target.resolve()
            loader.docs.add(loader.rel(real))
            loader.load_file(real, INTERNAL_DOC_PREFIX, True)
        except RegKBError as exc:
            return [str(exc)]
        return loader.schema_errors + loader.semantic_errors


# ---------------------------------------------------------------------------- caches


def invalidate_caches() -> None:
    """Forget the cached KnowledgeBase objects so the next read sees the new instrument file."""
    import contextlib

    with contextlib.suppress(Exception):
        from supervisor.console import regkb_view

        regkb_view._kb.cache_clear()
    with contextlib.suppress(Exception):
        from supervisor.console import compliance_view

        compliance_view._kb.cache_clear()
        compliance_view._demo_matrix.cache_clear()
    with contextlib.suppress(Exception):
        from supervisor.governance.register_v2 import duties

        duties._CACHE.clear()
    with contextlib.suppress(Exception):
        from supervisor.governance import rules_service

        rules_service._kb_obligation_ids.cache_clear()
    with contextlib.suppress(Exception):
        from supervisor.risk import refs

        refs._obligation_ids.cache_clear()


# ---------------------------------------------------------------------------- the model to use


def make_chat(settings: Any) -> ChatModel:
    """The gateway model as the law agent uses it. A mock is refused (no draft from a mock)."""
    from supervisor.regkb.lawagent import make_chat as _make

    chat = _make(settings)
    if getattr(chat, "is_mock", False):
        raise InternalError(
            "model_is_mock",
            "the configured chat model is a mock (LLM_BASE_URL empty or LLM_MOCK=1)",
        )
    return chat


def make_masker(settings: Any) -> Any:
    from supervisor.adapters.factory import make_masker as _make

    return _make(settings)


def service(ctx: Any) -> InternalDocs:
    """The service for a console context. The masker is built per call (cheap)."""
    return InternalDocs(
        ctx.state,
        ctx.clock,
        ctx.settings,
        masker=make_masker(ctx.settings),
        evidence=getattr(ctx.runtime, "chain", None),
    )


__all__ = [
    "InternalDocs",
    "InternalError",
    "build_instrument",
    "check_internal_draft",
    "enabled",
    "instrument_id",
    "internal_docs_dir",
    "invalidate_caches",
    "is_internal_instrument",
    "require_on",
    "service",
]
