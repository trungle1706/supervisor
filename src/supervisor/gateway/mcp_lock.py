"""MCP tool locking, pure part (WP26, ADR D24): tool hashes, list hash, diff, poisoning scan.

No I/O, no web, no SQL. The store, the chain and the review cases live in
``mcp_lock_service``; the HTTP proxy (``mcp_http``) uses both.

Hash of one tool (SHA-256 over canonical JSON: sorted keys, ASCII escapes, no spaces)::

    {name, description, inputSchema, annotations}  + title and outputSchema when present

The hash is byte exact. A change of one space, one homoglyph or one annotation changes it
(a whitespace-only edit is drift on purpose: a trailing run of blanks is how text is hidden).
The list hash is the SHA-256 of the sorted ``[name, tool_hash]`` pairs, so the order of
``tools/list`` does not matter.

The poisoning scan is deterministic and REPORT ONLY (R1): it marks a tool ``suspicious``
for the review case. The lock, not the scan, blocks. Findings hold a kind, a field and a
count; never the matched text. ``register_description_scorer`` is the hook for the WP25
classifier: its integer score (basis points) is stored as ``score_bp`` and never changes
``suspicious`` or the lock.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from typing import Any

SCAN_VERSION = "mcp_scan_v1"
HASH_FIELDS = ("name", "description", "inputSchema", "annotations")
OPTIONAL_HASH_FIELDS = ("title", "outputSchema")
MAX_STORED_DEF = 64_000
MAX_TOOLS = 1000
_NAME_OK = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}\Z")


# ------------------------------------------------------------------------------ hashing
def canonical_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    """The fields that identify a tool. A missing field gets its empty value so that
    "no annotations" and "empty annotations" are the same tool."""
    out: dict[str, Any] = {
        "name": tool.get("name"),
        "description": tool.get("description") if tool.get("description") is not None else "",
        "inputSchema": tool.get("inputSchema") if tool.get("inputSchema") is not None else {},
        "annotations": tool.get("annotations") if tool.get("annotations") is not None else {},
    }
    for key in OPTIONAL_HASH_FIELDS:
        if tool.get(key) is not None:
            out[key] = tool[key]
    return out


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def tool_hash(tool: Mapping[str, Any]) -> str:
    return hashlib.sha256(_dump(canonical_tool(tool)).encode("ascii")).hexdigest()


def list_hash(hashes: Mapping[str, str]) -> str:
    """Hash of a whole tool list from ``{name: tool_hash}`` (order free)."""
    return hashlib.sha256(_dump(sorted([n, h] for n, h in hashes.items())).encode()).hexdigest()


def stored_definition(tool: Mapping[str, Any]) -> str:
    """JSON text kept in the manifest row for the diff view (capped; the hash covers it all)."""
    text = _dump(canonical_tool(tool))
    if len(text) <= MAX_STORED_DEF:
        return text
    return _dump({"truncated": True, "sha256": tool_hash(tool), "name": tool.get("name")})


class ToolListError(ValueError):
    """The upstream ``tools/list`` result is not a list of tool objects."""


def parse_tools(result: Any) -> list[dict[str, Any]]:
    """The ``tools`` array of a ``tools/list`` result. Each entry needs a string ``name``."""
    tools = result.get("tools") if isinstance(result, Mapping) else None
    if not isinstance(tools, list):
        raise ToolListError("tools/list result has no tools array")
    if len(tools) > MAX_TOOLS:
        raise ToolListError(f"tools/list has more than {MAX_TOOLS} tools")
    out: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, Mapping) or not isinstance(t.get("name"), str) or not t["name"]:
            raise ToolListError("a tool in tools/list has no name")
        out.append(dict(t))
    return out


def group_tools(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tools by name. Two tools with one name are one entry whose definition is the list of
    both, so it never equals a locked single definition (a duplicate name is a shadowing
    attack). The entry is marked ``_duplicate``."""
    by: dict[str, list[dict[str, Any]]] = {}
    for t in tools:
        by.setdefault(t["name"], []).append(t)
    out: dict[str, dict[str, Any]] = {}
    for name, items in by.items():
        if len(items) == 1:
            out[name] = items[0]
        else:
            out[name] = {"name": name, "description": "", "inputSchema": {}, "_duplicate": items}
    return out


def hash_group(tool: Mapping[str, Any]) -> str:
    if "_duplicate" in tool:
        return hashlib.sha256(
            _dump([canonical_tool(t) for t in tool["_duplicate"]]).encode("ascii")
        ).hexdigest()
    return tool_hash(tool)


# ------------------------------------------------------------------------------ diff
def _schema_notes(old: Any, new: Any) -> list[str]:
    """Plain notes on how an input schema moved (a widening is the risky direction)."""
    notes: list[str] = []
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        return ["input schema type changed"] if old != new else []
    op = old.get("properties") if isinstance(old.get("properties"), Mapping) else {}
    np_ = new.get("properties") if isinstance(new.get("properties"), Mapping) else {}
    for name in sorted(set(np_) - set(op)):
        notes.append(f"parameter added: {_ascii(name)}")
    for name in sorted(set(op) - set(np_)):
        notes.append(f"parameter removed: {_ascii(name)}")
    for name in sorted(set(op) & set(np_)):
        if op[name] != np_[name]:
            notes.append(f"parameter changed: {_ascii(name)}")
    o_req, n_req = old.get("required") or [], new.get("required") or []
    if isinstance(o_req, list) and isinstance(n_req, list):
        for name in sorted(set(map(str, o_req)) - set(map(str, n_req))):
            notes.append(f"parameter no longer required: {_ascii(name)}")
    if old.get("additionalProperties") is not True and new.get("additionalProperties") is True:
        notes.append("additionalProperties opened")
    return notes


def _ascii(text: Any) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")[:80]


def diff_tools(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None) -> dict[str, Any]:
    """Which hashed fields differ between a locked and an observed definition."""
    if old is None or new is None:
        return {"changed": [], "notes": ["no locked definition" if old is None else "removed"]}
    a, b = canonical_tool(old), canonical_tool(new)
    changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    notes: list[str] = []
    if "inputSchema" in changed:
        notes += _schema_notes(a.get("inputSchema"), b.get("inputSchema"))
    if "description" in changed:
        da, db = str(a.get("description")), str(b.get("description"))
        if " ".join(da.split()) == " ".join(db.split()):
            notes.append("description differs only in whitespace")
        else:
            notes.append(f"description length {len(da)} -> {len(db)}")
    if "name" in changed:
        notes.append("name differs")
    return {"changed": changed, "notes": notes}


# ------------------------------------------------------------------------------ scan
# Phrases run over the diacritics-stripped, case-folded, confusable-folded candidates of the
# Tier 0b normaliser, so "bỏ qua", "bo qua", telex and Cyrillic look-alikes all meet one form.
_PHRASES: dict[str, list[str]] = {
    "instruction_phrase_en": [
        r"\bignore (?:all |any )?(?:the |your )?(?:previous|prior|above|earlier|preceding)\b",
        r"\bdisregard (?:all |any )?(?:the |your )?(?:previous|prior|above|earlier)\b",
        r"\b(?:do not|don't|dont|never) (?:tell|inform|mention|reveal|show|notify|alert)\b"
        r"[^.\n]{0,30}\buser\b",
        r"\bwithout (?:telling|informing|notifying|alerting)\b[^.\n]{0,20}\buser\b",
        r"\bbefore (?:using|calling|invoking|running) this tool\b[^.\n]{0,80}"
        r"\b(?:read|send|include|pass|append|first)\b",
        r"\b(?:send|forward|post|upload|leak|exfiltrate|email)\b[^.\n]{0,40}"
        r"\b(?:to|towards)\b[^.\n]{0,20}\b(?:https?://|an? external|remote server|attacker)",
        r"(?:~/\.ssh|\bid_rsa\b|/etc/passwd|\.aws/credentials)",
        r"\byou (?:must|should) (?:always )?(?:first )?(?:call|use|run) this tool\b",
    ],
    "instruction_phrase_vi": [
        r"\bbo qua\b[^.\n]{0,25}\b(?:truoc do|phia tren|o tren|moi|cac|tat ca|huong dan|chi dan|"
        r"quy tac|gioi han)\b",
        r"\b(?:dung|khong duoc|dung bao gio|khong)\b[^.\n]{0,12}\b(?:noi|cho biet|bao|tiet lo)\b"
        r"[^.\n]{0,30}\bnguoi dung\b",
        r"\btruoc khi (?:dung|goi|su dung|chay) cong cu nay\b",
        r"\bgui (?:toi|den|cho)\b[^.\n]{0,40}(?:http|@|email|mail|tai khoan|ben ngoai|may chu)",
        r"\bban (?:phai|hay) (?:luon )?(?:goi|doc|gui|bo qua)\b",
    ],
    "prompt_markup": [
        r"<\s*/?\s*(?:important|system|assistant|instructions?|secret|admin|override)\s*>",
        r"<!--",
        r"^\s*#{1,6}\s*(?:system|instructions?|important|override)\b",
        r"```\s*(?:system|prompt|instructions?)\b",
        r"\[\s*(?:system|inst|/inst)\s*\]",
        r"<\|[a-z_]{2,20}\|>",
    ],
}
_COMPILED = {k: [re.compile(p, re.M) for p in v] for k, v in _PHRASES.items()}


def _invisible(ch: str) -> bool:
    from supervisor.gateway.tier0b import _DROP

    if ord(ch) in _DROP:
        return True
    cat = unicodedata.category(ch)
    return cat in ("Cf", "Co", "Cs") or (cat == "Cc" and ch not in "\n\r\t")


def _walk(value: Any, depth: int = 0) -> Iterator[str]:
    """Every string in a JSON value: values, and the keys of mappings."""
    if depth > 8:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k)
            yield from _walk(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v, depth + 1)


Scorer = Callable[[str], int]
_scorer: Scorer | None = None


def register_description_scorer(fn: Scorer | None) -> None:
    """WP25 hook: ``fn(text) -> int`` in basis points (0-10000), run once per tool over the
    description and schema text. The score is stored as ``scan.score_bp``. It is advice: it
    never sets ``suspicious`` and never blocks (R1)."""
    global _scorer
    _scorer = fn


def _fields(tool: Mapping[str, Any]) -> dict[str, list[str]]:
    c = canonical_tool(tool)
    return {
        "description": list(_walk(c.get("description"))),
        "inputSchema": list(_walk(c.get("inputSchema"))),
        "annotations": list(_walk(c.get("annotations"))),
        "title": list(_walk(c.get("title"))),
        "outputSchema": list(_walk(c.get("outputSchema"))),
        # fields the hash does not cover are still read by the scan
        "other": list(_walk({k: v for k, v in tool.items() if k not in c and k != "_duplicate"})),
    }


def scan_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic poisoning scan. Returns ``{suspicious, findings, score_bp, scan_version}``;
    ``findings`` is a sorted list of ``{kind, field, count}`` (no matched text)."""
    from supervisor.gateway.tier0b import MAX_SCAN_CHARS, RegexClassifier, candidates

    findings: dict[tuple[str, str], int] = {}

    def add(kind: str, field: str, n: int = 1) -> None:
        if n:
            findings[(kind, field)] = findings.get((kind, field), 0) + n

    if "_duplicate" in tool:
        add("duplicate_name", "name")
        pool = [t for t in tool["_duplicate"]]
    else:
        pool = [tool]
    classifier = RegexClassifier()
    joined_parts: list[str] = []
    for t in pool:
        nm = t.get("name")
        if not isinstance(nm, str) or not _NAME_OK.match(nm):
            add("name_nonstandard", "name")
        for field, texts in _fields(t).items():
            blob = "\n".join(texts)[:MAX_SCAN_CHARS]
            if not blob:
                continue
            joined_parts.append(blob)
            if sum(_invisible(ch) for ch in blob):
                add("hidden_unicode", field)
            if any(f.kind == "injection" for f in classifier.classify("tool", {"d": blob})):
                add("injection_phrase", field)
            for kind, patterns in _COMPILED.items():
                hits = max(
                    (sum(len(p.findall(c)) for p in patterns) for c in candidates(blob)),
                    default=0,
                )
                add(kind, field, hits)
        if len(str(t.get("description") or "")) > 4000:
            add("oversized_description", "description")
    # A phrase split across fields ("ignore" in the description, "previous instructions" in an
    # annotation) is only seen where the end of one field meets the start of another.
    seen = {k for k, _f in findings}
    seams = {
        a[-300:] + " " + b[:300]
        for i, a in enumerate(joined_parts)
        for j, b in enumerate(joined_parts)
        if i != j
    }
    for seam in sorted(seams):
        if "injection_phrase" not in seen and any(
            f.kind == "injection" for f in classifier.classify("tool", {"d": seam})
        ):
            add("injection_phrase", "split_fields")
            seen.add("injection_phrase")
        for kind, patterns in _COMPILED.items():
            if kind not in seen and any(p.search(c) for p in patterns for c in candidates(seam)):
                add(kind, "split_fields")
                seen.add(kind)
    score: int | None = None
    if _scorer is not None:
        try:
            score = max(0, min(10000, int(_scorer("\n".join(joined_parts)[:MAX_SCAN_CHARS]))))
        except Exception:  # noqa: BLE001 - a broken scorer never affects the lock
            score = None
    rows = [{"kind": k, "field": f, "count": n} for (k, f), n in sorted(findings.items())]
    return {
        "suspicious": bool(rows),
        "findings": rows,
        "score_bp": score,
        "scan_version": SCAN_VERSION,
    }


def finding_kinds(scan: Mapping[str, Any]) -> list[str]:
    return sorted({f["kind"] for f in scan.get("findings", [])})
