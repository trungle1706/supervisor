"""Law agent (WP-L1): draft duties from the stored official text of one instrument.

    python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026 [--articles 1-5]
        [--out drafts.json]
    python -m supervisor.regkb.lawagent --instrument VN-DEC142-2026 --export-confirmed out.yaml
    python -m supervisor.regkb.lawagent --compare old.txt new.txt
    python -m supervisor.regkb.lawagent --internal 3F9A0C21B7D4 [--out drafts.json]
    python -m supervisor.regkb.lawagent --diff VN-DEC142-2026 --incoming <package sha | text file>
        [--incoming-name VN-DEC142-2026/2026-10-28/x.txt] [--out report.json]

What happens, in order:

1. ``split_articles`` cuts the stored text into articles at the ``Dieu N.`` headings.
2. For each article the chat model drafts 0..n duties (duty id from ``duties.yaml``, subject,
   trigger, evidence an auditor asks for, a verbatim quote, a one-line English summary).
3. ``check_draft`` is a set of deterministic rules. A draft whose quote is not in the article
   text, whose duty id is unknown, or whose article does not exist is dropped and counted.
4. What passes is written to the ``regkb_draft`` table with status ``draft``. A draft is never an
   obligation: a person confirms or drops it on ``/console/regkb/<instrument>/drafts``.
5. ``--export-confirmed`` writes the confirmed rows in the obligation YAML shape of
   ``regulations/vn/*.yaml`` for an engineer to paste into the instrument file in a pull request.

Internal mode (WP-W3, REGKB_INTERNAL=1): ``--internal <doc_id>`` reads the MASKED text of an
uploaded internal document (``regkb/internal.py``), draft one duty row per section that imposes a
duty, and writes it to ``regkb_draft`` with ``instrument_id = VN-INT-<doc_id>``.

Diff mode (WP-W2, REGKB_CHANGE_LOOP=1): ``--diff <instrument> --incoming <package sha or file>``
compares the text of record with the incoming text article by article, drafts the changed and the
added articles only (no model call when nothing changed) into ``regkb_draft`` and writes the
report under ``DATA_DIR/regkb/changes/<package sha>/<instrument>/`` (see ``regkb/change.py``). A
person confirms the change on ``/console/regkb/changes/<package sha>/<instrument>``.

The model only drafts. A mock chat model is for unit tests: a run on a mock is refused unless
``--allow-mock`` is given, and every output then says MOCK MODEL.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.ports import ChatModel
from supervisor.regkb.drafts import MAX_QUOTE, DraftStore, quote_key
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.model import Instrument, KnowledgeBase

log = logging.getLogger("supervisor.regkb.lawagent")

PROMPT_VERSION = "lawagent-1"
BANNER = "Not legal advice. Bank counsel must confirm."
MIN_QUOTE = 12  # characters; a shorter quote proves nothing
TIMEOUT_S = 180.0
PAGE_URL = "/console/regkb/{instrument}/drafts"

# ---------------------------------------------------------------------------- text helpers

_HEADING = re.compile(r"^Điều\s+(\d{1,3})\.\s*(.*)$")
# A chapter or section heading closes the article above it; the chapter title line that follows
# belongs to no article. So does the signature block and the annex list.
_CLOSER = re.compile(
    r"^(Chương\s+[IVXLC]+\s*$|Mục\s+(\d+|[IVXLC]+)\.?(\s|$)|TM\.\s|Nơi nhận:"
    r"|Phụ lục\s*$|PHỤ LỤC\s*$)"
)
_CLAUSE = re.compile(r"^\d{1,3}[a-zđ]?$")


def normalise_ws(text: str) -> str:
    """NFC and runs of white space folded to one space. Nothing else changes (case stays)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Article:
    number: int
    heading: str  # "Điều 5. Nguyên tắc ..." (first line, white space folded)
    body: str  # the lines after the heading, white space folded
    text: str  # heading and body, white space folded: what the quote is checked against
    body_sha256: str

    @property
    def label(self) -> str:
        return f"Điều {self.number}"


def split_articles(text: str) -> list[Article]:
    """Cut an instrument text at its ``Điều N.`` headings.

    A heading counts only when its number is the next one in the row (1, 2, 3, ...). That keeps
    a cross-reference that starts a wrapped line ("Điều 8. ...") and the numbering of the forms in
    an annex from opening a new article. A chapter heading, the signature block or the annex list
    closes the open article.
    """
    articles: list[Article] = []
    current: tuple[int, str, list[str]] | None = None
    last = 0

    def close() -> None:
        nonlocal current
        if current is not None:
            number, heading, lines = current
            body = normalise_ws("\n".join(lines))
            full = normalise_ws(heading + "\n" + "\n".join(lines))
            articles.append(Article(number, normalise_ws(heading), body, full, sha256_text(body)))
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HEADING.match(line)
        if m and int(m.group(1)) == last + 1:
            close()
            last = int(m.group(1))
            current = (last, line, [])
            continue
        if _CLOSER.match(line):
            close()
            continue
        if current is not None:
            current[2].append(line)
    close()
    return articles


# ---------------------------------------------------------------------------- diff mode


@dataclass(frozen=True)
class ArticleChange:
    number: int
    heading: str  # the new heading (the old one for a removed article)
    old_heading: str | None
    new_heading: str | None
    old_sha256: str | None  # sha256 of the folded article body
    new_sha256: str | None


@dataclass(frozen=True)
class ArticleDiff:
    added: tuple[ArticleChange, ...] = ()
    changed: tuple[ArticleChange, ...] = ()
    removed: tuple[ArticleChange, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": [asdict(c) for c in self.added],
            "changed": [asdict(c) for c in self.changed],
            "removed": [asdict(c) for c in self.removed],
        }


def compare(old_text: str, new_text: str) -> ArticleDiff:
    """Added, changed and removed articles between two versions of one text.

    Articles are matched by number. An article is *changed* when its heading or the hash of its
    body differs. Pure function: no file, no model. (An inserted article shifts the numbers of
    the ones below it, so they show as changed; a person reads that list.)
    """
    old = {a.number: a for a in split_articles(old_text)}
    new = {a.number: a for a in split_articles(new_text)}
    added, changed, removed = [], [], []
    for n in sorted(set(old) | set(new)):
        o, w = old.get(n), new.get(n)
        if o is None and w is not None:
            added.append(ArticleChange(n, w.heading, None, w.heading, None, w.body_sha256))
        elif w is None and o is not None:
            removed.append(ArticleChange(n, o.heading, o.heading, None, o.body_sha256, None))
        elif (
            o is not None
            and w is not None
            and (o.body_sha256 != w.body_sha256 or o.heading != w.heading)
        ):
            changed.append(
                ArticleChange(n, w.heading, o.heading, w.heading, o.body_sha256, w.body_sha256)
            )
    return ArticleDiff(tuple(added), tuple(changed), tuple(removed))


# ---------------------------------------------------------------------------- article refs


def make_article_ref(number: int, clause: str = "") -> str:
    """'Điều 12' for an article, '12.3' for clause 3 of article 12."""
    return f"{number}.{clause}" if clause else f"Điều {number}"


def parse_article_ref(ref: str) -> tuple[int, str]:
    """Inverse of ``make_article_ref``. Raises ValueError on anything else."""
    text = normalise_ws(ref)
    m = re.fullmatch(r"Điều (\d{1,3})", text)
    if m:
        return int(m.group(1)), ""
    m = re.fullmatch(r"(\d{1,3})\.(\d{1,3}[a-zđ]?)", text)
    if m:
        return int(m.group(1)), m.group(2)
    raise ValueError(f"not an article reference: {ref!r}")


def article_numbers(ref: str) -> list[int]:
    """Article numbers an ``article_ref`` of an obligation names: 'Art. 5(3)' -> [5];
    'Art. 5(1), 6(2)' -> [5, 6]; 'Decree 142/2026 Art. 5-7' -> [5, 6, 7]; 'Appendix IV' -> [].
    Clause numbers in brackets are not article numbers. Used to find the obligations of an
    article that changed (WP-W2)."""
    out: list[int] = []
    for m in re.finditer(r"(?:Art\.\s*|,\s*)(\d{1,3})(?:\s*-\s*(\d{1,3})(?!\d))?(?![\d/])", ref):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        if lo <= hi <= lo + 60:
            out += range(lo, hi + 1)
    return sorted(set(out))


def parse_range(spec: str, available: Sequence[int]) -> list[int]:
    """'1-5', '3', '1,4,7-9' -> article numbers that exist. Raises ValueError for a bad spec or
    for a number the text does not have."""
    wanted: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,3})(?:-(\d{1,3}))?", part)
        if not m:
            raise ValueError(f"bad article range {part!r} (use 1-5 or 1,3,7-9)")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if hi < lo:
            raise ValueError(f"bad article range {part!r}")
        wanted += range(lo, hi + 1)
    missing = sorted(set(wanted) - set(available))
    if missing:
        raise ValueError(f"the text has no article {missing[0]}")
    return sorted(set(wanted))


# ---------------------------------------------------------------------------- the rules


@dataclass(frozen=True)
class Checked:
    """The result of the rules for one draft the model returned."""

    ok: bool
    reason: str  # "" when ok
    row: dict[str, Any] | None = None


def check_draft(
    raw: Mapping[str, Any],
    article: Article,
    articles: Mapping[int, Article],
    duties: Mapping[str, Any],
) -> Checked:
    """Deterministic rules for one draft of one article. The first rule that fails drops it.

    1. the article exists in the stored text;
    2. the duty id is in the duty vocabulary;
    3. the clause (when given) has the form 3 or 3a;
    4. subject, trigger, evidence and summary are not empty;
    5. the quote has 12..2000 characters and is a substring of the article text (white space
       folded, nothing else changed).
    """
    if article.number not in articles:
        return Checked(False, "unknown_article")
    duty = str(raw.get("duty_id", "")).strip()
    if duty not in duties:
        return Checked(False, "unknown_duty")
    clause = str(raw.get("clause", "") or "").strip()
    if clause and not _CLAUSE.match(clause):
        return Checked(False, "bad_clause")
    fields = {
        k: normalise_ws(str(raw.get(k, "") or ""))
        for k in ("subject", "trigger", "evidence_asked", "summary_en")
    }
    if not all(fields.values()):
        return Checked(False, "missing_field")
    quote = normalise_ws(str(raw.get("quote", "") or ""))
    if not MIN_QUOTE <= len(quote) <= MAX_QUOTE:
        return Checked(False, "bad_quote_length")
    if quote not in articles[article.number].text:
        return Checked(False, "quote_not_in_article")
    return Checked(
        True,
        "",
        {
            "article": make_article_ref(article.number, clause),
            "duty_id": duty,
            "subject": fields["subject"],
            "trigger": fields["trigger"],
            "evidence_asked": fields["evidence_asked"],
            "text_vi": quote,
            "summary_en": fields["summary_en"],
        },
    )


# ---------------------------------------------------------------------------- the model call

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "duty_id": {"type": "string"},
                    "clause": {"type": "string"},
                    "subject": {"type": "string"},
                    "trigger": {"type": "string"},
                    "evidence_asked": {"type": "string"},
                    "quote": {"type": "string"},
                    "summary_en": {"type": "string"},
                },
                "required": [
                    "duty_id",
                    "clause",
                    "subject",
                    "trigger",
                    "evidence_asked",
                    "quote",
                    "summary_en",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["drafts"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You read one article of a Vietnamese legal text for a bank. You list the duties in the "
    "article that could bind a bank or an AI system deployed by a bank.\n"
    "Rules:\n"
    "- Return 0..n drafts. An article with no duty gives an empty list.\n"
    "- duty_id must be one id from the duty list below. Never invent an id.\n"
    "- quote must be copied word for word from the article text (Vietnamese, same spelling, "
    "same diacritics). Do not shorten with '...' and do not translate. Use one sentence or "
    "one clause, at most 600 characters.\n"
    "- clause is the clause number the quote sits in (for example '3' or '2a'), or an empty "
    "string when the duty is for the whole article.\n"
    "- subject: who must act. trigger: when the duty applies. evidence_asked: what an auditor "
    "would ask to see. summary_en: one English sentence. Write these four in English.\n"
    "- Draft only what the text says. Do not give legal advice.\n"
    "Duty list (id: meaning):\n{duties}"
)


def duty_lines(duties: Mapping[str, Any]) -> str:
    lines = []
    for did in sorted(duties):
        label = duties[did].get("label_en", "") if isinstance(duties[did], Mapping) else ""
        lines.append(f"{did}: {label}")
    return "\n".join(lines)


def build_messages(
    instrument_id: str, article: Article, duties: Mapping[str, Any]
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM.format(duties=duty_lines(duties))},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instrument": instrument_id,
                    "article": article.label,
                    "article_text": article.text,
                },
                ensure_ascii=False,
            ),
        },
    ]


# ---------------------------------------------------------------------------- the run


@dataclass
class RunSummary:
    run_id: str
    instrument_id: str
    model_id: str
    mock: bool
    prompt_version: str = PROMPT_VERSION
    articles_read: int = 0
    model_drafts: int = 0
    kept: int = 0
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    skipped_existing: int = 0
    skipped_decided: int = 0
    model_errors: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = []
        if self.mock:
            out.append("[WARN] MOCK MODEL: these drafts did not come from a real model.")
        out.append(
            f"[OK] run {self.run_id}: {self.instrument_id}, model {self.model_id}, "
            f"prompt {self.prompt_version}"
        )
        out.append(
            f"[OK] articles read {self.articles_read}; model drafts {self.model_drafts}; "
            f"kept {self.kept}; dropped by the rules {self.dropped}"
        )
        if self.drop_reasons:
            reasons = ", ".join(f"{k}={v}" for k, v in sorted(self.drop_reasons.items()))
            out.append(f"[OK] drop reasons: {reasons}")
        if self.skipped_existing or self.skipped_decided:
            out.append(
                f"[OK] not written again: {self.skipped_existing} already drafted or confirmed, "
                f"{self.skipped_decided} already dropped by a person"
            )
        if self.model_errors:
            out.append(
                f"[FAIL] model errors on {self.model_errors} article(s); run again for those"
            )
        return out


def run_agent(
    *,
    instrument_id: str,
    text: str,
    duties: Mapping[str, Any],
    chat: ChatModel,
    store: DraftStore,
    numbers: Sequence[int] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunSummary:
    """Read the chosen articles, check every draft with the rules, write what passes."""
    articles = {a.number: a for a in split_articles(text)}
    if not articles:
        raise RegKBError(f"no 'Dieu N.' headings found in the stored text of {instrument_id}")
    chosen = list(numbers) if numbers is not None else sorted(articles)
    unknown = [n for n in chosen if n not in articles]
    if unknown:
        raise RegKBError(f"the text has no article {unknown[0]}")
    summary = RunSummary(
        run_id="lr_" + uuid.uuid4().hex[:12],
        instrument_id=instrument_id,
        model_id=str(getattr(chat, "model_id", "unknown")),
        mock=bool(getattr(chat, "is_mock", False)),
    )
    seen = store.existing_keys(instrument_id)
    reasons: Counter[str] = Counter()
    say = progress or (lambda _line: None)
    for n in chosen:
        art = articles[n]
        summary.articles_read += 1
        try:
            reply = chat.complete_json(
                build_messages(instrument_id, art, duties), SCHEMA, TIMEOUT_S
            )
            items = list(reply.get("drafts", []))
        except Exception as exc:  # noqa: BLE001 - one bad article must not stop the run
            summary.model_errors += 1
            log.warning("law agent: article %d failed: %s", n, type(exc).__name__)
            say(f"[FAIL] {art.label}: model error {type(exc).__name__}")
            continue
        kept = dropped = 0
        for raw in items:
            summary.model_drafts += 1
            result = check_draft(raw if isinstance(raw, Mapping) else {}, art, articles, duties)
            if not result.ok or result.row is None:
                dropped += 1
                reasons[result.reason] += 1
                continue
            key = (result.row["article"], result.row["duty_id"], quote_key(result.row["text_vi"]))
            prior = seen.get(key)
            if prior == "dropped":
                summary.skipped_decided += 1
                continue
            if prior is not None:
                summary.skipped_existing += 1
                continue
            seen[key] = "draft"
            kept += 1
            summary.rows.append(
                {
                    **result.row,
                    "instrument_id": instrument_id,
                    "source": "model",
                    "model_id": summary.model_id,
                    "prompt_version": PROMPT_VERSION,
                    "run_id": summary.run_id,
                }
            )
        summary.kept += kept
        summary.dropped += dropped
        say(f"[OK] {art.label}: {kept} kept, {dropped} dropped")
    summary.drop_reasons = dict(reasons)
    summary.rows = store.add(summary.rows)
    return summary


# ---------------------------------------------------------------------------- stored text


def stored_text(kb: KnowledgeBase, instrument_id: str, repo_root: Path) -> tuple[str, str, str]:
    """(text, sha256 of the file, relative path) of the stored primary text of an instrument."""
    inst = kb.instrument(instrument_id)
    base = repo_root.resolve()
    for src in inst.sources:
        if src.kind == "primary" and src.local_path and src.local_path.endswith(".txt"):
            path = (base / src.local_path).resolve()
            if base in path.parents and path.is_file():
                data = path.read_bytes()
                return data.decode("utf-8"), hashlib.sha256(data).hexdigest(), src.local_path
    raise RegKBError(f"{instrument_id} has no stored primary .txt text under regulations/sources")


# ---------------------------------------------------------------------------- export

_ROLE_WORDS = {
    "deployer": ("deployer", "bên triển khai", "ben trien khai"),
    "provider": ("provider", "nhà cung cấp", "nha cung cap"),
}


def _roles(subject: str) -> list[str]:
    low = subject.lower()
    return [r for r, words in _ROLE_WORDS.items() if any(w in low for w in words)]


def obligation_id(instrument_id: str, article: str, taken: set[str]) -> str:
    """VN-DEC142-2026-A5.03-01 for clause 3 of article 5; the next free two-digit suffix."""
    number, clause = parse_article_ref(article)
    if clause:
        m = re.fullmatch(r"(\d+)([a-zđ]?)", clause)
        assert m is not None
        suffix = f"{int(m.group(1)):02d}{m.group(2).upper() if m.group(2).isascii() else ''}"
        part = f"A{number}.{suffix}"
    else:
        part = f"A{number}"
    for i in range(1, 100):
        oid = f"{instrument_id}-{part}-{i:02d}"
        if oid not in taken:
            taken.add(oid)
            return oid
    raise RegKBError(f"no free obligation id for {instrument_id} {article}")


def _article_ref(article: str) -> str:
    number, clause = parse_article_ref(article)
    return f"Art. {number}({clause})" if clause else f"Art. {number}"


def _source_entries(inst: Instrument) -> list[dict[str, Any]]:
    out = []
    for s in inst.sources:
        if s.kind != "primary":
            continue
        entry: dict[str, Any] = {
            "url": s.url,
            "title": s.title,
            "fetched_at": s.fetched_at,
            "kind": s.kind,
        }
        if s.sha256:
            entry["sha256"] = s.sha256
        if s.local_path:
            entry["local_path"] = s.local_path
        out.append(entry)
    return out


def export_obligations(
    rows: Sequence[Mapping[str, Any]], kb: KnowledgeBase, instrument_id: str
) -> list[dict[str, Any]]:
    """Confirmed rows -> obligation dicts in the shape of ``regulations/vn/*.yaml``.

    Each one has ``verification: VERIFIED_PRIMARY``, ``confirmed_by``, the primary source of the
    instrument with its stored sha256, and an empty ``control_mapping`` (the mapping to Supervisor
    controls is a second step by an engineer). The ids avoid every id the knowledge base has.
    """
    inst = kb.instrument(instrument_id)
    sources = _source_entries(inst)
    if not sources:
        raise RegKBError(f"{instrument_id} has no primary source to cite")
    taken = {o.id for o in kb.obligations_of(instrument_id)}
    out = []
    ordered = sorted(
        (r for r in rows if r["status"] == "confirmed"),
        key=lambda r: (parse_article_ref(r["article"]), str(r["draft_id"])),
    )
    for r in ordered:
        roles = _roles(str(r["subject"]))
        when = r.get("confirmed_at")
        day = when.date().isoformat() if hasattr(when, "date") else str(when or "")[:10]
        ob: dict[str, Any] = {
            "id": obligation_id(instrument_id, r["article"], taken),
            "article_ref": _article_ref(r["article"]),
            "text_vi": r["text_vi"],
            "summary_en": r["summary_en"],
            "duties": [r["duty_id"]],
            "applies_to": {"role": roles} if roles else {},
            "addressee": roles[0] if len(roles) == 1 else "any",
            "control_mapping": [],
            "evidence_needed": [r["evidence_asked"]],
            "verification": "VERIFIED_PRIMARY",
            "confirmed_by": r["confirmed_by"],
            "sources": [dict(s) for s in sources],
            "confidence": "medium",
            "notes": (
                f"Drafted by the law agent (source {r['source']}, "
                f"model {r.get('model_id') or '-'}, "
                f"prompt {r.get('prompt_version') or '-'}, run {r['run_id']}); confirmed by "
                f"{r['confirmed_by']} on {day}. Subject: {r['subject']} Trigger: {r['trigger']} "
                "No control mapping yet. Not legal advice; bank counsel must confirm."
            ),
        }
        out.append(ob)
    return out


def export_yaml(obligations: Sequence[Mapping[str, Any]], instrument_id: str) -> str:
    head = (
        f"# {BANNER}\n"
        f"# Law agent export for {instrument_id}. Paste the items below under `obligations:`\n"
        "# of the instrument file in regulations/vn/, add control_mapping, run\n"
        "#   python -m supervisor.regkb validate\n"
        "# and open a pull request. Every item was confirmed by the person named in confirmed_by.\n"
    )
    body = yaml.safe_dump(
        {"obligations": [dict(o) for o in obligations]},
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    return head + body


# ---------------------------------------------------------------------------- the model to use


def make_chat(settings: Any) -> ChatModel:
    """LAWAGENT_MODEL when set, else the bank chat model (LLM_MODEL), as the advisors use it."""
    from supervisor.adapters.factory import make_chat_model

    model = str(getattr(settings, "lawagent_model", "") or "")
    if model and settings.llm_base_url and not settings.llm_mock:
        settings = settings.model_copy(update={"llm_model": model})
    return make_chat_model(settings)


# ---------------------------------------------------------------------------- CLI


def _out(line: str = "") -> None:
    from supervisor.regkb.cli import ascii_text

    sys.stdout.write(ascii_text(line) + "\n")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _compare_cli(old: str, new: str) -> int:
    diff = compare(Path(old).read_text("utf-8"), Path(new).read_text("utf-8"))
    _out(BANNER)
    for name in ("added", "changed", "removed"):
        items = getattr(diff, name)
        _out(f"[OK] {name}: {len(items)}")
        for c in items:
            _out(
                f"  Dieu {c.number}  {c.heading}  "
                f"{(c.old_sha256 or '-')[:12]} -> {(c.new_sha256 or '-')[:12]}"
            )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.regkb.lawagent",
        description="Draft duties from the stored official text of one instrument. "
        "Drafts need a person to confirm them. " + BANNER,
    )
    parser.add_argument("--instrument", help="instrument id, for example VN-DEC142-2026")
    parser.add_argument("--articles", help="articles to read, for example 1-5 or 1,3,7-9")
    parser.add_argument("--out", help="also write the new drafts and the summary to this JSON file")
    parser.add_argument("--export-confirmed", metavar="FILE", help="write confirmed rows as YAML")
    parser.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"), help="list changed articles")
    parser.add_argument("--internal", metavar="DOC_ID", help="internal mode: draft an uploaded doc")
    parser.add_argument("--diff", metavar="INSTRUMENT", help="diff mode (REGKB_CHANGE_LOOP=1)")
    parser.add_argument("--incoming", help="diff mode: a package sha (64 hex) or a text file")
    parser.add_argument("--incoming-name", help="diff mode: the text inside the package")
    parser.add_argument("--allow-mock", action="store_true", help="allow a mock model (tests only)")
    args = parser.parse_args(argv)
    from supervisor.bootstrap import bootstrap

    bootstrap()
    from supervisor.core.errors import SupervisorError

    try:
        if args.compare:
            return _compare_cli(*args.compare)
        if args.diff:
            return _diff_cli(args)
        if args.internal:
            return _internal_cli(args)
        if not args.instrument:
            parser.error("--instrument or --internal is required")
        return _run_cli(args)
    except (SupervisorError, RegKBError, OSError, ValueError) as exc:  # InternalError is one
        _out(f"[FAIL] {exc}")
        _out(BANNER)
        return 2


def _run_cli(args: argparse.Namespace) -> int:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import REPO_ROOT, load_settings
    from supervisor.regkb.loader import _load_yaml, load_kb

    settings = load_settings()
    _out(BANNER)
    if not settings.lawagent_enabled:
        _out("[SKIP] the law agent is off (set LAWAGENT_ENABLED=1)")
        return 2
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            from supervisor.jobs import bootstrap_schema

            bootstrap_schema.run(settings, adapters)
        store = DraftStore(adapters.state, adapters.clock)
        kb = load_kb()
        kb.instrument(args.instrument)  # RegKBError for an unknown id
        if args.export_confirmed:
            return _export_cli(args, store, kb)
        text, sha, rel = stored_text(kb, args.instrument, REPO_ROOT)
        duties = (_load_yaml(REPO_ROOT / "regulations" / "schema" / "duties.yaml") or {})["duties"]
        chat = make_chat(settings)
        if getattr(chat, "is_mock", False) and not args.allow_mock:
            _out("[FAIL] the configured chat model is a mock (LLM_BASE_URL empty or LLM_MOCK=1).")
            _out(
                "       Set LLM_BASE_URL and LLM_MODEL for the real gateway, "
                "or --allow-mock in tests."
            )
            return 2
        numbers = None
        if args.articles:
            numbers = parse_range(args.articles, [a.number for a in split_articles(text)])
        _out(f"[OK] text {rel} sha256 {sha[:12]}")
        summary = run_agent(
            instrument_id=args.instrument,
            text=text,
            duties=duties,
            chat=chat,
            store=store,
            numbers=numbers,
            progress=_out,
        )
        for line in summary.lines():
            _out(line)
        _out("[OK] review: " + PAGE_URL.format(instrument=args.instrument))
        if args.out:
            payload = {
                "banner": BANNER,
                "summary": {k: v for k, v in asdict(summary).items() if k != "rows"},
                "drafts": summary.rows,
            }
            Path(args.out).write_text(
                json.dumps(
                    payload, ensure_ascii=False, indent=2, default=_jsonable, sort_keys=True
                ),
                encoding="utf-8",
                newline="\n",
            )
            _out(f"[OK] wrote {args.out}")
        _out(BANNER)
        return 1 if summary.model_errors and not summary.rows else 0
    finally:
        adapters.close()


def _diff_cli(args: argparse.Namespace) -> int:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.regkb import change

    settings = load_settings()
    _out(BANNER)
    if not change.enabled(settings):
        _out("[SKIP] the change loop is off (REGKB_CHANGE_LOOP=1; it needs LAWAGENT_ENABLED and")
        _out("       GOVERNANCE_ENABLED)")
        return 2
    if not args.incoming:
        _out("[FAIL] --incoming <package sha or text file> is required with --diff")
        return 2
    is_sha = re.fullmatch(r"[0-9a-f]{64}", args.incoming) is not None
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            from supervisor.jobs import bootstrap_schema

            bootstrap_schema.run(settings, adapters)
        chat = make_chat(settings) if args.allow_mock else None  # None = the gateway, no mock
        report = change.run_diff(
            data_dir=settings.data_dir,
            state=adapters.state,
            clock=adapters.clock,
            settings=settings,
            instrument_id=args.diff,
            package_sha=args.incoming if is_sha else None,
            incoming=args.incoming_name,
            incoming_file=None if is_sha else Path(args.incoming),
            actor="cli:lawagent",
            chat=chat,
            progress=_out,
        )
        s = report["summary"]
        _out(
            f"[OK] {report['instrument_id']}: {s['unchanged']} unchanged, {s['changed']} changed, "
            f"{s['added']} added, {s['removed']} removed; changed characters {s['changed_chars']}"
        )
        _out(
            f"[OK] affected obligations {s['affected_obligations_n']}; drafts {s['drafts_made']} "
            f"(model calls {report['model']['calls']}); classification article touched: "
            f"{'yes' if s['classification_hit'] else 'no'}"
        )
        _out("[OK] review: " + f"/console/regkb/changes/{report['package_sha256']}/{args.diff}")
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
            _out(f"[OK] wrote {args.out}")
        _out(BANNER)
        return 0
    finally:
        adapters.close()


def _internal_cli(args: argparse.Namespace) -> int:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.regkb import internal

    settings = load_settings()
    _out(BANNER)
    if not settings.lawagent_enabled:
        _out("[SKIP] the law agent is off (set LAWAGENT_ENABLED=1)")
        return 2
    if not settings.regkb_internal:
        _out("[SKIP] internal documents are off (set REGKB_INTERNAL=1)")
        return 2
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            from supervisor.jobs import bootstrap_schema

            bootstrap_schema.run(settings, adapters)
        svc = internal.InternalDocs(
            adapters.state, adapters.clock, settings, masker=internal.make_masker(settings)
        )
        if args.allow_mock:
            chat = make_chat(settings)
        else:
            chat = internal.make_chat(settings)
        summary = svc.draft(args.internal, chat, progress=_out)
        for line in summary.lines():
            _out(line)
        _out("[OK] review: " + PAGE_URL.format(instrument=internal.instrument_id(args.internal)))
        if args.out:
            payload = {"banner": BANNER, "summary": summary.as_dict(), "drafts": summary.rows}
            Path(args.out).write_text(
                json.dumps(
                    payload, ensure_ascii=False, indent=2, default=_jsonable, sort_keys=True
                ),
                encoding="utf-8",
                newline="\n",
            )
            _out(f"[OK] wrote {args.out}")
        _out(BANNER)
        return 1 if summary.model_errors and not summary.rows else 0
    finally:
        adapters.close()


def _export_cli(args: argparse.Namespace, store: DraftStore, kb: KnowledgeBase) -> int:
    rows = store.list(args.instrument, "confirmed")
    obligations = export_obligations(rows, kb, args.instrument)
    Path(args.export_confirmed).write_text(
        export_yaml(obligations, args.instrument), encoding="utf-8", newline="\n"
    )
    _out(f"[OK] {len(obligations)} confirmed draft(s) written to {args.export_confirmed}")
    _out(BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
