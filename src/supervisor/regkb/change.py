"""Change to re-evaluation (WP-W2, flag ``REGKB_CHANGE_LOOP``): the diff mode of the law agent and
the apply of a confirmed change.

    imported package (WP-W1)   DATA_DIR/regkb/incoming/<package sha>/incoming/<id>/<date>/<file>.txt
        |  diff    (python -m supervisor.regkb.lawagent --diff <id> --incoming <sha|path>)
        v
    DATA_DIR/regkb/changes/<package sha>/<instrument>/   diff.json  diff.md  diff.meta.json
                                                          old.txt  incoming.txt  incoming.meta.json
        |  a person with regkb.confirm accepts or drops the drafted duties, then presses Apply
        v
    DATA_DIR/regkb/overrides/<instrument>/override.yaml  + text/<sha12>.txt (the new text of record)
        |  the loader applies the override on top of regulations/vn when the flag is on
        v
    new RegKB version hash; chain record ``regkb_change``; the governance event ``regkb_changed``

What is deterministic and what is not:

* The article diff is a comparison of white-space-folded text per article (``diff_texts``): no
  model. A text that is unchanged makes no model call.
* The model drafts duties for the changed and the added articles only, through
  ``lawagent.run_agent`` (same guards: the quote must sit inside the article of the incoming
  text, the duty id must be in the vocabulary). A draft is never an obligation.
* The obligations of an article that changed are found by ``lawagent.article_numbers`` over
  ``article_ref`` (``affected_obligations`` in the report).
* The committed ``regulations/`` files are never written at run time.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import os
import re
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError
from supervisor.regkb import lawagent, package
from supervisor.regkb.drafts import DraftStore
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.loader import OVERRIDE_FILE, OVERRIDE_FORMAT, _load_yaml, load_kb
from supervisor.regkb.model import KnowledgeBase, to_plain

FORMAT_DIFF = "regkb-diff-1"
BANNER = lawagent.BANNER
OFF_MESSAGE = (
    "the change loop is off (REGKB_CHANGE_LOOP=1 turns it on; it needs LAWAGENT_ENABLED and "
    "GOVERNANCE_ENABLED)"
)
TABLE = "regkb_change"
LINK_TABLE = "regkb_change_draft"
STATUSES = ("diffed", "applied")
BANNER_DAYS = 7
MAX_TEXT = 3_000_000  # characters of one text
# The re-classification trigger list (WP-C1): articles whose change moves a system to
# re-evaluation. None = any change of the instrument (Decision 33 Appendix IV is an annex that
# the article splitter does not read, so the whole text counts).
CLASSIFICATION_TRIGGERS: dict[str, tuple[int, ...] | None] = {
    "VN-AI-2025": (7, 9, 10),
    "VN-DEC142-2026": (6, 8, 9, 11),
    "VN-QD33-2026": None,
    "VN-TT53-2026": (4,),
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^(VN|INTL|INT)-[A-Z0-9]+(-[A-Z0-9]+){0,3}$")
_COVERAGE_RANK = {"none": 0, "partial": 1, "full": 2}
_FILE_KEYS = (
    "id",
    "article_ref",
    "text_vi",
    "text_en",
    "summary_en",
    "summary_vi",
    "duties",
    "applies_to",
    "addressee",
    "control_mapping",
    "evidence_needed",
    "verification",
    "sources",
    "confidence",
    "notes",
    "confirmed_by",
)


class ChangeError(SupervisorError):
    """A refused step of the change loop. The message starts with the short code (HTTP 400)."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code


# ---------------------------------------------------------------------------- flag and paths


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "regkb_change_loop", False)
        and getattr(settings, "lawagent_enabled", False)
        and getattr(settings, "governance_enabled", False)
    )


def require_on(settings: Any) -> None:
    if not enabled(settings):
        raise ChangeError("change_loop_off", OFF_MESSAGE)


def check_ids(package_sha: str, instrument_id: str) -> None:
    if not _SHA.match(package_sha):
        raise ChangeError("bad_package", "the package sha must be 64 lower-case hex characters")
    if not _ID.match(instrument_id):
        raise ChangeError("bad_instrument", "the instrument id is not valid")


def change_id_of(package_sha: str, instrument_id: str) -> str:
    return "rc_" + hashlib.sha256(f"{package_sha}|{instrument_id}".encode()).hexdigest()[:20]


def regkb_root(data_dir: Path | str) -> Path:
    return Path(os.path.abspath(Path(data_dir) / "regkb"))


def changes_dir(data_dir: Path | str, package_sha: str, instrument_id: str) -> Path:
    return regkb_root(data_dir) / "changes" / package_sha / instrument_id


def overrides_root(data_dir: Path | str) -> Path:
    return regkb_root(data_dir) / "overrides"


def override_path(data_dir: Path | str, instrument_id: str) -> Path:
    return overrides_root(data_dir) / instrument_id / OVERRIDE_FILE


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(4)}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def kb_of(data_dir: Path | str) -> KnowledgeBase:
    """The knowledge base with the overrides under ``data_dir`` applied (explicit, so a caller
    does not depend on the process settings)."""
    return load_kb(overrides_dir=overrides_root(data_dir))


# ---------------------------------------------------------------------------- texts


def current_text(
    data_dir: Path | str, kb: KnowledgeBase, instrument_id: str
) -> tuple[str, str, str]:
    """(text, sha256, where) of the text of record: the newest override text when the instrument
    has one, else the stored primary text under ``regulations/sources``."""
    path = override_path(data_dir, instrument_id)
    if path.is_file():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        text = doc.get("text") or {}
        tpath = (Path(data_dir).resolve() / str(text.get("path", ""))).resolve()
        if Path(data_dir).resolve() in tpath.parents and tpath.is_file():
            data = tpath.read_bytes()
            return data.decode("utf-8"), sha256_hex(data), str(text.get("path"))
    from supervisor.config import REPO_ROOT

    try:
        return lawagent.stored_text(kb, instrument_id, REPO_ROOT)
    except RegKBError as exc:
        raise ChangeError("no_stored_text", str(exc)) from None


def find_incoming(
    data_dir: Path | str, package_sha: str, instrument_id: str, name: str | None = None
) -> tuple[str, bytes, dict[str, Any]]:
    """(name, bytes, sidecar) of the incoming text of one instrument in a stored package.
    Without ``name`` the package must hold exactly one ``text_changed`` file for the instrument."""
    check_ids(package_sha, instrument_id)
    pkg = package.incoming_root(Path(data_dir)) / package_sha
    if not (pkg / "import.json").is_file():
        raise ChangeError("no_package", "this package is not imported")
    summary = package.summary_of(pkg)
    listed = sorted(
        {
            f
            for c in summary["changes"]
            if c.get("instrument_id") == instrument_id and c.get("kind") == "text_changed"
            for f in c.get("incoming") or []
        }
    )
    prefix = f"{instrument_id}/"
    if name is None:
        if len(listed) != 1:
            raise ChangeError(
                "incoming_ambiguous",
                "name the incoming text (field incoming); the package lists "
                + (", ".join(listed) if listed else "no text of this instrument as changed"),
            )
        name = listed[0]
    if not name.startswith(prefix) or not name.endswith(".txt") or ".." in name.split("/"):
        raise ChangeError(
            "bad_incoming", "the incoming name must be <instrument>/<date>/<file>.txt"
        )
    base = (pkg / "incoming").resolve()
    path = (base / name).resolve()
    if base not in path.parents or not path.is_file():
        raise ChangeError("no_incoming", f"the package has no file {name}")
    meta: dict[str, Any] = {}
    side = path.with_name(path.name[: -len(".txt")] + ".meta.json")
    if side.is_file():
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except ValueError:
            meta = {}
    return name, path.read_bytes(), meta if isinstance(meta, dict) else {}


# ---------------------------------------------------------------------------- the article diff


@dataclass(frozen=True)
class ArticleDelta:
    number: int
    status: str  # unchanged | changed | added | removed
    old_heading: str | None
    new_heading: str | None
    old_sha256: str | None
    new_sha256: str | None
    changed_chars: int

    @property
    def label(self) -> str:
        return f"Điều {self.number}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "label": self.label,
            "status": self.status,
            "old_heading": self.old_heading,
            "new_heading": self.new_heading,
            "old_sha256": self.old_sha256,
            "new_sha256": self.new_sha256,
            "changed_chars": self.changed_chars,
        }


def changed_chars(old: str, new: str) -> int:
    """Characters in the words that differ (word level; the larger side of each differing run).
    A whole number: the size of the change, not a score."""
    a, b = old.split(), new.split()
    total = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            total += max(len(" ".join(a[i1:i2])), len(" ".join(b[j1:j2])))
    return total


def diff_texts(old_text: str, new_text: str) -> tuple[list[ArticleDelta], bool]:
    """Article by article, matched by number, on white-space-folded text. Returns the deltas
    (every article, unchanged ones too) and ``outside``: True when the whole texts differ although
    no article does (an annex, a signature block, a title)."""
    old = {a.number: a for a in lawagent.split_articles(old_text)}
    new = {a.number: a for a in lawagent.split_articles(new_text)}
    out: list[ArticleDelta] = []
    for n in sorted(set(old) | set(new)):
        o, w = old.get(n), new.get(n)
        if o is None and w is not None:
            out.append(ArticleDelta(n, "added", None, w.heading, None, w.body_sha256, len(w.text)))
        elif w is None and o is not None:
            out.append(
                ArticleDelta(n, "removed", o.heading, None, o.body_sha256, None, len(o.text))
            )
        elif o is not None and w is not None:
            same = o.text == w.text
            out.append(
                ArticleDelta(
                    n,
                    "unchanged" if same else "changed",
                    o.heading,
                    w.heading,
                    o.body_sha256,
                    w.body_sha256,
                    0 if same else changed_chars(o.text, w.text),
                )
            )
    touched = any(d.status != "unchanged" for d in out)
    outside = (not touched) and lawagent.normalise_ws(old_text) != lawagent.normalise_ws(new_text)
    return out, outside


def _coverage_of(o: Any) -> str:
    best = "none"
    for c in o.control_mapping:
        if _COVERAGE_RANK.get(c.coverage, 0) > _COVERAGE_RANK[best]:
            best = c.coverage
    return best


def affected_obligations(
    kb: KnowledgeBase, instrument_id: str, deltas: Sequence[ArticleDelta]
) -> list[dict[str, Any]]:
    """The obligations of the instrument whose article changed or was removed. An obligation whose
    articles are all removed is ``article_removed``; one that names a changed article (or a mix) is
    ``article_changed``. An obligation with no article number (an annex) is not listed."""
    changed = {d.number for d in deltas if d.status == "changed"}
    removed = {d.number for d in deltas if d.status == "removed"}
    out = []
    for o in sorted(kb.obligations_of(instrument_id), key=lambda x: x.id):
        nums = set(lawagent.article_numbers(o.article_ref))
        if not nums or not nums & (changed | removed):
            continue
        reason = "article_removed" if nums <= removed else "article_changed"
        out.append(
            {
                "id": o.id,
                "article_ref": o.article_ref,
                "articles": sorted(nums),
                "reason": reason,
                "coverage": _coverage_of(o),
            }
        )
    return out


def classification_hit(
    instrument_id: str, deltas: Sequence[ArticleDelta], outside: bool = False
) -> bool:
    """True when an article of the re-classification trigger list changed, was added or removed."""
    if instrument_id not in CLASSIFICATION_TRIGGERS:
        return False
    arts = CLASSIFICATION_TRIGGERS[instrument_id]
    touched = [d for d in deltas if d.status != "unchanged"]
    if arts is None:
        return bool(touched) or outside
    return any(d.number in arts for d in touched)


def classification_path_articles(settings: Any) -> dict[str, set[int]]:
    """instrument id -> article numbers the classification tree cites (``article`` and ``see`` of
    every node). An obligation on these articles with coverage full or partial is on the
    classification path of a system."""
    path = getattr(settings, "classification_config", None)
    out: dict[str, set[int]] = {}
    try:
        doc = yaml.safe_load(Path(str(path)).read_text(encoding="utf-8")) if path else None
    except (OSError, yaml.YAMLError):
        return out
    for node in (doc or {}).get("nodes") or []:
        refs = [node.get("article")] + list(node.get("see") or [])
        for ref in refs:
            if isinstance(ref, Mapping) and ref.get("instrument"):
                out.setdefault(str(ref["instrument"]), set()).update(
                    lawagent.article_numbers(str(ref.get("ref", "")))
                )
    return out


# ---------------------------------------------------------------------------- state rows


def get_row(state: Any, package_sha: str, instrument_id: str) -> dict[str, Any] | None:
    row = state.get(TABLE, {"change_id": change_id_of(package_sha, instrument_id)})
    return dict(row) if row is not None else None


def list_rows(state: Any) -> list[dict[str, Any]]:
    rows = [dict(r) for r in state.query(TABLE)]
    rows.sort(key=lambda r: (str(r["created_at"]), str(r["change_id"])), reverse=True)
    return rows


def linked_drafts(state: Any, change_id: str) -> list[dict[str, Any]]:
    """The drafts made for this change, with the link fields, in article order."""
    store_rows = []
    for link in state.query(LINK_TABLE, {"change_id": change_id}):
        row = state.get("regkb_draft", {"draft_id": link["draft_id"]})
        if row is not None:
            store_rows.append({**dict(row), "change_ref": link["change_ref"]})

    def key(r: Mapping[str, Any]) -> tuple[Any, ...]:
        try:
            return (*lawagent.parse_article_ref(r["article"]), str(r["draft_id"]))
        except ValueError:
            return (0, "", str(r["draft_id"]))

    return sorted(store_rows, key=key)


# ---------------------------------------------------------------------------- the diff run


def make_chat(settings: Any) -> Any:
    """The gateway model of the law agent. Tests replace this function."""
    chat = lawagent.make_chat(settings)
    if getattr(chat, "is_mock", False):
        raise ChangeError(
            "mock_model",
            "the configured chat model is a mock (set LLM_BASE_URL and LLM_MODEL for the "
            "real gateway)",
        )
    return chat


def _duties() -> dict[str, Any]:
    from supervisor.config import REPO_ROOT

    return (_load_yaml(REPO_ROOT / "regulations" / "schema" / "duties.yaml") or {})["duties"]


def report_markdown(report: Mapping[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Law change diff: {report['instrument_id']}",
        "",
        f"> {BANNER}",
        "",
        f"* package: `{report['package_sha256']}`",
        f"* old text sha256: `{report['old']['sha256']}`",
        f"* new text sha256: `{report['new']['sha256']}` ({report['new']['name']})",
        f"* generated: {report['generated_at']}",
        f"* articles: {s['unchanged']} unchanged, {s['changed']} changed, {s['added']} added, "
        f"{s['removed']} removed; changed characters {s['changed_chars']}",
        f"* classification article touched: {'yes' if s['classification_hit'] else 'no'}",
        f"* drafts made: {s['drafts_made']} (model {report['model'].get('id') or '-'})",
        "",
        "## Articles that are not unchanged",
        "",
        "| article | status | changed chars | old sha256 | new sha256 |",
        "|---|---|---|---|---|",
    ]
    for a in report["articles"]:
        if a["status"] != "unchanged":
            lines.append(
                f"| {a['label']} | {a['status']} | {a['changed_chars']} | "
                f"{(a['old_sha256'] or '-')[:12]} | {(a['new_sha256'] or '-')[:12]} |"
            )
    lines += ["", "## Affected obligations", ""]
    if report["affected_obligations"]:
        lines += ["| obligation | article_ref | reason | coverage |", "|---|---|---|---|"]
        for o in report["affected_obligations"]:
            lines.append(f"| {o['id']} | {o['article_ref']} | {o['reason']} | {o['coverage']} |")
    else:
        lines.append("None.")
    lines += ["", "## Drafted duties (a person confirms or drops each)", ""]
    if report["drafts"]:
        lines += ["| draft | article | duty |", "|---|---|---|"]
        for d in report["drafts"]:
            lines.append(f"| {d['draft_id']} | {d['article']} | {d['duty_id']} |")
    else:
        lines.append("None.")
    if report["outside_articles_changed"]:
        lines += [
            "",
            "The text differs outside the articles (annex, title or signature block); read it.",
        ]
    return "\n".join(lines) + "\n"


def run_diff(
    *,
    data_dir: Path | str,
    state: Any,
    clock: Any,
    settings: Any,
    instrument_id: str,
    package_sha: str | None = None,
    incoming: str | None = None,
    incoming_file: Path | None = None,
    actor: str,
    chat: Any = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Diff the text of record of ``instrument_id`` against an incoming text, draft the changed and
    added articles with the model, and write the report. ``incoming`` is a name inside the
    package ``package_sha`` (see ``find_incoming``); ``incoming_file`` is a local text file (the
    CLI), its sha256 then stands for the package sha. Returns the report."""
    require_on(settings)
    if incoming_file is None:
        if not package_sha:
            raise ChangeError("bad_package", "the package sha is required")
        check_ids(package_sha, instrument_id)
    kb = kb_of(data_dir)
    try:
        kb.instrument(instrument_id)
    except Exception:  # noqa: BLE001 - UnknownObligationError
        raise ChangeError("unknown_instrument", "unknown instrument id") from None
    if incoming_file is not None:
        data = Path(incoming_file).read_bytes()
        package_sha = package_sha or sha256_hex(data)
        name, meta = f"{instrument_id}/local/{Path(incoming_file).name}", {}
    else:
        assert package_sha is not None
        name, data, meta = find_incoming(data_dir, package_sha, instrument_id, incoming)
    check_ids(package_sha, instrument_id)
    if len(data) > MAX_TEXT:
        raise ChangeError("too_large", "the incoming text is too large")
    try:
        new_text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ChangeError("bad_incoming", "the incoming text is not UTF-8") from None
    cid = change_id_of(package_sha, instrument_id)
    prior = get_row(state, package_sha, instrument_id)
    if prior is not None and prior["status"] == "applied":
        raise ChangeError("already_applied", "this change was applied; it cannot be diffed again")
    old_text, old_sha, old_where = current_text(data_dir, kb, instrument_id)
    new_sha = sha256_hex(data)
    deltas, outside = diff_texts(old_text, new_text)
    if not deltas and not lawagent.split_articles(new_text):
        raise ChangeError("no_articles", "the incoming text has no 'Dieu N.' headings")
    affected = affected_obligations(kb, instrument_id, deltas)
    hit = classification_hit(instrument_id, deltas, outside)
    todo = [d.number for d in deltas if d.status in ("changed", "added")]
    drafts: list[dict[str, Any]] = []
    model_id = ""
    summary_run = None
    if todo:  # no model call for a text that is unchanged
        chat = chat or make_chat(settings)
        model_id = str(getattr(chat, "model_id", "unknown"))
        summary_run = lawagent.run_agent(
            instrument_id=instrument_id,
            text=new_text,
            duties=_duties(),
            chat=chat,
            store=DraftStore(state, clock),
            numbers=todo,
            progress=progress,
        )
        for row in summary_run.rows:
            ref = f"{package_sha}:{row['article']}"
            drafts.append(
                {"draft_id": row["draft_id"], "article": row["article"], "duty_id": row["duty_id"]}
            )
            try:
                state.insert(
                    LINK_TABLE,
                    {
                        "draft_id": row["draft_id"],
                        "change_id": cid,
                        "change_ref": ref,
                        "article": row["article"],
                    },
                )
            except DuplicateKeyError:  # a repeated diff links a draft only once
                continue
    counts = {s: sum(1 for d in deltas if d.status == s) for s in lawagent_statuses()}
    report: dict[str, Any] = {
        "format": FORMAT_DIFF,
        "banner": BANNER,
        "change_id": cid,
        "package_sha256": package_sha,
        "instrument_id": instrument_id,
        "generated_at": format_ts(clock.now()),
        "old": {"sha256": old_sha, "where": old_where},
        "new": {"sha256": new_sha, "name": name},
        "outside_articles_changed": outside,
        "model": {
            "id": model_id,
            "prompt_version": lawagent.PROMPT_VERSION,
            "calls": len(todo) if summary_run is not None else 0,
        },
        "summary": {
            **counts,
            "articles_old": counts["unchanged"] + counts["changed"] + counts["removed"],
            "articles_new": counts["unchanged"] + counts["changed"] + counts["added"],
            "changed_chars": sum(d.changed_chars for d in deltas),
            "classification_hit": hit,
            "drafts_made": len(drafts),
            "affected_obligations_n": len(affected),
            "dropped_by_rules": summary_run.dropped if summary_run else 0,
        },
        "articles": [d.as_dict() for d in deltas],
        "affected_obligations": affected,
        "drafts": drafts,
    }
    out = changes_dir(data_dir, package_sha, instrument_id)
    json_b = _json_bytes(report)
    md_b = report_markdown(report).encode("utf-8")
    _write(out / "diff.json", json_b)
    _write(out / "diff.md", md_b)
    _write(out / "old.txt", old_text.encode("utf-8"))
    _write(out / "incoming.txt", data)
    _write(out / "incoming.meta.json", _json_bytes(meta))
    _write(
        out / "diff.meta.json",
        _json_bytes(
            {
                "diff_json_sha256": sha256_hex(json_b),
                "diff_md_sha256": sha256_hex(md_b),
                "incoming_sha256": new_sha,
                "old_sha256": old_sha,
            }
        ),
    )
    fields = {
        "package_sha": package_sha,
        "instrument_id": instrument_id,
        "status": "diffed",
        "old_sha": old_sha,
        "new_sha": new_sha,
        "incoming_name": name,
        "articles_changed": counts["changed"],
        "articles_added": counts["added"],
        "articles_removed": counts["removed"],
        "changed_chars": report["summary"]["changed_chars"],
        "articles": [d.number for d in deltas if d.status != "unchanged"],
        "obligations_affected": [o["id"] for o in affected],
        "classification_hit": hit,
        "drafts_n": len(drafts) + (int(prior["drafts_n"]) if prior else 0),
        "model_id": model_id or None,
        "obligations_added": 0,
        "obligations_updated": 0,
        "obligations_removed": 0,
    }
    if prior is None:
        state.insert(
            TABLE,
            {
                "change_id": cid,
                **fields,
                "created_at": clock.now(),
                "created_by": actor,
            },
        )
    else:
        try:
            state.update(TABLE, {"change_id": cid}, fields, int(prior["row_version"]))
        except ConcurrencyError:
            raise ChangeError("changed", "the change was changed in another window") from None
    return report


def lawagent_statuses() -> tuple[str, ...]:
    return ("unchanged", "changed", "added", "removed")


def read_report(data_dir: Path | str, package_sha: str, instrument_id: str) -> dict[str, Any]:
    check_ids(package_sha, instrument_id)
    path = changes_dir(data_dir, package_sha, instrument_id) / "diff.json"
    if not path.is_file():
        raise ChangeError("no_diff", "no diff yet for this package and instrument; run the diff")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ChangeError("bad_diff", "the diff report cannot be read") from None
    return data if isinstance(data, dict) else {}


def side_by_side(
    data_dir: Path | str, package_sha: str, instrument_id: str, report: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """For each article that is not unchanged: the old and the new folded text, side by side."""
    out_dir = changes_dir(data_dir, package_sha, instrument_id)
    try:
        old = {
            a.number: a
            for a in lawagent.split_articles((out_dir / "old.txt").read_text(encoding="utf-8"))
        }
        new = {
            a.number: a
            for a in lawagent.split_articles((out_dir / "incoming.txt").read_text(encoding="utf-8"))
        }
    except OSError:
        return []
    rows = []
    for a in report.get("articles") or []:
        if a["status"] == "unchanged":
            continue
        rows.append(
            {
                **a,
                "old_text": old[a["number"]].text if a["number"] in old else "",
                "new_text": new[a["number"]].text if a["number"] in new else "",
            }
        )
    return rows


# ---------------------------------------------------------------------------- the apply


def _roles(subject: str) -> list[str]:
    return lawagent._roles(subject)  # noqa: SLF001 - same package


def build_obligations(
    kb: KnowledgeBase,
    instrument_id: str,
    drafts: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    change_ref: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Confirmed drafts -> obligation dicts in the file shape. A draft whose article and duty
    match an existing obligation replaces it (same id, its mapping and applies_to kept); any other
    draft is a new obligation with a free id. Returns (obligations, added, updated)."""
    existing = kb.obligations_of(instrument_id)
    taken = {o.id for o in kb.obligations.values()}
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    added = updated = 0
    for r in drafts:
        number, _clause = lawagent.parse_article_ref(r["article"])
        old = next(
            (
                o
                for o in sorted(existing, key=lambda x: x.id)
                if o.id not in used
                and number in lawagent.article_numbers(o.article_ref)
                and r["duty_id"] in o.duties
            ),
            None,
        )
        roles = _roles(str(r["subject"]))
        note = (
            f"Drafted by the law agent for {change_ref} (source {r['source']}, model "
            f"{r.get('model_id') or '-'}, run {r['run_id']}); confirmed by {r['confirmed_by']}. "
            f"Subject: {r['subject']} Trigger: {r['trigger']} Not legal advice; bank counsel "
            "must confirm."
        )
        if old is not None:
            used.add(old.id)
            ob = {k: v for k, v in to_plain(old).items() if k in _FILE_KEYS}
            ob["control_mapping"] = ob.get("control_mapping", [])
            updated += 1
        else:
            ob = {
                "id": lawagent.obligation_id(instrument_id, r["article"], taken),
                "article_ref": lawagent._article_ref(r["article"]),  # noqa: SLF001
                "duties": [r["duty_id"]],
                "applies_to": {"role": roles} if roles else {},
                "addressee": roles[0] if len(roles) == 1 else "any",
                "control_mapping": [],
                "confidence": "medium",
            }
            added += 1
        ob.update(
            {
                "text_vi": r["text_vi"],
                "summary_en": r["summary_en"],
                "evidence_needed": [r["evidence_asked"]],
                "verification": "VERIFIED_PRIMARY",
                "confirmed_by": r["confirmed_by"],
                "sources": [dict(source)],
                "notes": note,
            }
        )
        out.append(ob)
    return out, added, updated


def _override_doc(
    data_dir: Path | str,
    instrument_id: str,
    *,
    text: Mapping[str, Any],
    obligations: Sequence[Mapping[str, Any]],
    removed: Sequence[str],
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    """The override document: what an earlier apply left, with this change merged on top."""
    prev: dict[str, Any] = {}
    path = override_path(data_dir, instrument_id)
    if path.is_file():
        prev = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = {str(o["id"]): dict(o) for o in prev.get("obligations") or []}
    for o in obligations:
        merged[str(o["id"])] = dict(o)
    gone = (set(prev.get("removed") or []) | set(removed)) - set(merged)
    for oid in removed:
        merged.pop(str(oid), None)
    return {
        "schema_version": 1,
        "format": OVERRIDE_FORMAT,
        "instrument_id": instrument_id,
        "text": dict(text),
        "removed": sorted(gone),
        "obligations": [merged[k] for k in sorted(merged)],
        "applied": [*(prev.get("applied") or []), dict(entry)],
    }


def _check_override(data_dir: Path | str, instrument_id: str, doc: Mapping[str, Any]) -> None:
    """Load the base files plus this override alone, from a staging folder, with the same
    validator and quote checks. Raises ChangeError(override_invalid) and writes nothing real."""
    root = regkb_root(data_dir)
    stage = root / f".stage-{secrets.token_hex(6)}"
    try:
        (stage / instrument_id).mkdir(parents=True)
        (stage / instrument_id / OVERRIDE_FILE).write_text(
            yaml.safe_dump(dict(doc), allow_unicode=True, sort_keys=True, width=100),
            encoding="utf-8",
        )
        try:
            load_kb(overrides_dir=stage)
        except RegKBError as exc:
            errors = getattr(exc, "errors", None) or [str(exc)]
            raise ChangeError(
                "override_invalid", "; ".join(str(e) for e in errors[:3])[:600]
            ) from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def apply_change(
    *,
    data_dir: Path | str,
    state: Any,
    clock: Any,
    settings: Any,
    package_sha: str,
    instrument_id: str,
    actor: str,
    record: Callable[[str, str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Write the override of a diffed change from the confirmed drafts. The committed files are
    not touched. Nothing is written when the override fails the validator or a quote check."""
    require_on(settings)
    check_ids(package_sha, instrument_id)
    row = get_row(state, package_sha, instrument_id)
    if row is None:
        raise ChangeError("no_diff", "no diff yet for this package and instrument; run the diff")
    if row["status"] == "applied":
        raise ChangeError("already_applied", "this change was applied already")
    report = read_report(data_dir, package_sha, instrument_id)
    out_dir = changes_dir(data_dir, package_sha, instrument_id)
    incoming = (out_dir / "incoming.txt").read_bytes()
    if sha256_hex(incoming) != report["new"]["sha256"] or row["new_sha"] != report["new"]["sha256"]:
        raise ChangeError("bad_diff", "the stored incoming text differs from the diff report")
    kb = kb_of(data_dir)
    _text, cur_sha, _where = current_text(data_dir, kb, instrument_id)
    if cur_sha != report["old"]["sha256"]:
        raise ChangeError(
            "stale_diff", "the text of record changed after this diff; run the diff again"
        )
    s = report["summary"]
    if not (s["changed"] or s["added"] or s["removed"] or report["outside_articles_changed"]):
        raise ChangeError("nothing_to_apply", "the incoming text has no change to apply")
    cid = row["change_id"]
    confirmed = [r for r in linked_drafts(state, cid) if r["status"] == "confirmed"]
    meta = json.loads((out_dir / "incoming.meta.json").read_text(encoding="utf-8") or "{}")
    old_primary = next(
        (x for x in kb.instrument(instrument_id).sources if x.kind == "primary"), None
    )
    day = clock.now().date().isoformat()
    rel = f"regkb/overrides/{instrument_id}/text/{report['new']['sha256'][:12]}.txt"
    url = str(meta.get("url") or (old_primary.url if old_primary else ""))
    if not url.startswith(("http://", "https://")):
        raise ChangeError("bad_incoming", "the incoming text has no source url")
    title = str(meta.get("title") or (old_primary.title if old_primary else instrument_id))
    source = {
        "url": url,
        "title": title[:300] or instrument_id,
        "fetched_at": str(meta.get("fetched_at") or day)[:10],
        "kind": "primary",
        "sha256": report["new"]["sha256"],
        "local_path": rel,
    }
    change_ref = f"{package_sha}"
    obligations, added, updated = build_obligations(
        kb, instrument_id, confirmed, source, f"package {package_sha[:8]}"
    )
    removed = [o["id"] for o in report["affected_obligations"] if o["reason"] == "article_removed"]
    removed = [oid for oid in removed if oid in kb.obligations]
    entry = {
        "package_sha256": package_sha,
        "change_id": cid,
        "applied_at": format_ts(clock.now()),
        "applied_by": actor,
        "text_sha256": report["new"]["sha256"],
    }
    doc = _override_doc(
        data_dir,
        instrument_id,
        text={"path": rel, **{k: v for k, v in source.items() if k != "local_path"}},
        obligations=obligations,
        removed=removed,
        entry=entry,
    )
    # the text must exist for the check; it is content-addressed, so writing it is harmless
    text_path = Path(os.path.abspath(Path(data_dir) / rel))
    _write(text_path, incoming)
    _write(text_path.with_name(text_path.stem + ".meta.json"), _json_bytes(meta))
    _check_override(data_dir, instrument_id, doc)
    version_before = kb.version
    _write(
        override_path(data_dir, instrument_id),
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, width=100).encode("utf-8"),
    )
    kb_after = kb_of(data_dir)
    now = clock.now()
    try:
        state.update(
            TABLE,
            {"change_id": cid},
            {
                "status": "applied",
                "applied_at": now,
                "applied_by": actor,
                "obligations_added": added,
                "obligations_updated": updated,
                "obligations_removed": len(removed),
                "version_before": version_before,
                "version_after": kb_after.version,
            },
            int(row["row_version"]),
        )
    except ConcurrencyError:
        raise ChangeError("changed", "the change was changed in another window") from None
    result = {
        "change_id": cid,
        "package_sha256": package_sha,
        "instrument_id": instrument_id,
        "articles_changed": int(row["articles_changed"]),
        "obligations_added": added,
        "obligations_updated": updated,
        "obligations_removed": len(removed),
        "version_before": version_before,
        "version_after": kb_after.version,
        "unconfirmed_drafts": sum(1 for r in linked_drafts(state, cid) if r["status"] == "draft"),
        "change_ref": change_ref,
    }
    if record is not None:
        try:
            record(
                "regkb_change",
                cid,
                {
                    "package_sha256": package_sha,
                    "instrument_id": instrument_id,
                    "articles_changed": int(row["articles_changed"])
                    + int(row["articles_added"])
                    + int(row["articles_removed"]),
                    "obligations_added": added,
                    "obligations_updated": updated,
                    "obligations_removed": len(removed),
                    "actor_ref": sha256_hex(actor.encode("utf-8"))[:16],
                },
            )
        except Exception:  # noqa: BLE001 - the override is written; the log has the cause
            import logging

            logging.getLogger(__name__).exception("regkb_change chain record failed")
    from supervisor.regkb import internal

    internal.invalidate_caches()
    return result


# ---------------------------------------------------------------------------- lists and banner


def pending_items(data_dir: Path | str, state: Any) -> list[dict[str, Any]]:
    """One item per imported package and instrument that has watcher changes: the kinds, the
    incoming texts that can be diffed, and the state of its change row (no_diff, diffed,
    applied)."""
    rows = {(r["package_sha"], r["instrument_id"]): r for r in list_rows(state)}
    items: list[dict[str, Any]] = []
    for pkg in package.list_packages(Path(data_dir)):
        by: dict[str, list[dict[str, Any]]] = {}
        for c in pkg["changes"]:
            by.setdefault(str(c.get("instrument_id", "")), []).append(c)
        for iid, changes in sorted(by.items()):
            if not _ID.match(iid):
                continue
            texts = sorted(
                {
                    f
                    for c in changes
                    if c.get("kind") == "text_changed"
                    for f in c.get("incoming") or []
                }
            )
            row = rows.get((pkg["package_sha256"], iid))
            items.append(
                {
                    "package_sha": pkg["package_sha256"],
                    "run_id": pkg.get("run_id", ""),
                    "imported_at": pkg.get("imported_at", ""),
                    "instrument_id": iid,
                    "kinds": sorted({str(c.get("kind")) for c in changes}),
                    "texts": texts,
                    "can_diff": bool(texts),
                    "status": row["status"] if row else "no_diff",
                    "change": row,
                }
            )
    return items


def banner(state: Any, data_dir: Path | str, now: Any) -> dict[str, Any] | None:
    """The two lines of My overview: ``pending`` = packages and instruments with a text that is
    not applied yet; ``applied`` = changes applied in the last 7 days with the number of
    systems that were re-opened. None when there is nothing to show."""
    pending = sum(
        1 for i in pending_items(data_dir, state) if i["status"] != "applied" and i["can_diff"]
    )
    since = now - dt.timedelta(days=BANNER_DAYS)
    applied = []
    for r in list_rows(state):
        if r["status"] != "applied" or r.get("applied_at") is None or r["applied_at"] < since:
            continue
        ref = f"regkb_change:{r['change_id']}"
        systems = {
            str(e["system_id"])
            for e in state.query("governance_event", {"kind": "regkb_changed"})
            if e.get("system_id") and str(e["ref"]) == ref
        }
        applied.append(
            {
                "date": r["applied_at"].date().isoformat(),
                "instrument_id": r["instrument_id"],
                "systems": len(systems),
                "package_sha": r["package_sha"],
            }
        )
    if not pending and not applied:
        return None
    return {"pending": pending, "applied": applied}


__all__ = [
    "BANNER",
    "CLASSIFICATION_TRIGGERS",
    "ArticleDelta",
    "ChangeError",
    "affected_obligations",
    "apply_change",
    "banner",
    "change_id_of",
    "classification_hit",
    "diff_texts",
    "enabled",
    "pending_items",
    "require_on",
    "run_diff",
]
