"""``dlp_vn``: Vietnamese personal data (WP37). Wraps the ``vn_regex`` masker as a detector.

The only detector that may *transform*. For each entity type found it returns one finding with
the pseudonym tokens (never the value), the located tokens in the MASKED text, and the number of
values masked. With ``mode=transform`` and a risk class (or tool) that is in scope, the findings
carry the payload after masking; the gate puts it in ``transformed_payload``.

Scores are rule based (illustrative): a value that passes a check digit or has a label is
stronger than a name that matched the lexicon.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    DOCUMENT_PART,
    FRAGMENT_TEXT_MAX,
    MAX_DEPTH,
    SCORE_MAX,
    Entity,
    Finding,
    Fragment,
    Leaf,
    SettingField,
    SettingsSchema,
    clip,
    detector_id,
    map_leaves,
    parts_for,
    threshold_for,
    walk_leaves,
)
from supervisor.core.detectors import _key as _safe_key
from supervisor.core.ports import Masker
from supervisor.detectors.dlp_extras import (
    RULE_LEAF_CHARS,
    Extras,
    Hit,
    Scanned,
    make_digest,
)

_TOKEN = re.compile(r"<([A-Z_]{2,20}):([0-9a-f]{4,64})>")

# Illustrative confidence per entity type (basis points).
SCORE_BY_TYPE: dict[str, int] = {
    "EMAIL": 10_000,
    "CARD_NUMBER": 9_800,
    "PHONE": 9_500,
    "CCCD": 9_500,
    "CMND": 9_000,
    "TAX_CODE": 9_000,
    "BANK_ACCOUNT": 9_000,
    "PERSON": 8_000,
    "ADDRESS": 8_000,
    "AMOUNT": 5_000,
}
DEFAULT_SCORE = 8_000
RISK_CLASSES = ("money", "credit", "pii_export", "read_only")

# Frozen with the version string: change a number, change the version.
PRESETS: dict[str, int] = {"strict": 5_000, "balanced": 8_000, "lenient": 9_500}


# WP41 (D29): typed pseudonyms. With pseudonym_mode "typed" a text value that sits directly under
# an argument whose NAME says what it is gets that class, not the one the masker guesses from
# the digits (a bare 10 digit tax code looks like a bank account). The label goes in front of
# the value for the masker and is cut off again.
_KEY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|_)(tax|mst|ma_so_thue)(_|$)", re.I), "mã số thuế "),
    (re.compile(r"(^|_)(account|acct|stk|tai_khoan)(_|$)", re.I), "tài khoản "),
)
PSEUDONYM_MODES = ("generic", "typed")
KEEP_ARG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def keep_args_problems(value: Any) -> list[str]:
    """Problems in a ``keep_args`` setting: ``{tool: [argument names]}`` (empty = fine)."""
    if value in (None, {}):
        return []
    if not isinstance(value, Mapping):
        return ["keep_args: expected a mapping of tool name to a list of argument names"]
    problems: list[str] = []
    if len(value) > 64:
        problems.append("keep_args: more than 64 tools")
    for tool, names in value.items():
        if not isinstance(tool, str) or not KEEP_ARG_RE.match(tool):
            problems.append("keep_args: a tool name is not a plain identifier")
        elif (
            not isinstance(names, list)
            or not 0 < len(names) <= 8
            or any(not isinstance(n, str) or not KEEP_ARG_RE.match(n) for n in names)
        ):
            problems.append(f"keep_args.{tool}: 1..8 argument names (letters, digits, _ . -)")
    return problems


def _hint_label(key: str | None) -> str | None:
    if not key:
        return None
    for rx, label in _KEY_HINTS:
        if rx.search(key):
            return label
    return None


def _typed_mask(mask: Any, key: str | None, text: str) -> str:
    label = _hint_label(key)
    if label is None:
        return mask(text)
    out = mask(label + text)
    return out[len(label) :] if out.startswith(label) else mask(text)


def _mask_tree(value: Any, mask: Any, depth: int = 0, typed: bool = False) -> Any:
    """``map_leaves`` that also masks string dict keys: a transformed payload goes on to a
    pii_export tool, and a name used as a key must not reach it in clear (R2)."""
    if isinstance(value, Mapping) and depth <= MAX_DEPTH:
        return {
            (mask(k) if isinstance(k, str) else k): (
                _typed_mask(mask, k, v)
                if typed and isinstance(k, str) and isinstance(v, str)
                else _mask_tree(v, mask, depth + 1, typed)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple) and depth <= MAX_DEPTH:
        return [_mask_tree(v, mask, depth + 1, typed) for v in value]
    return map_leaves(value, mask, depth)


def _masked_documents(docs: Any, mask: Any) -> list[dict[str, Any]]:
    """The documents whose text changed, as ``{index, text}`` (the masked text). ``index`` is the
    position of the document in the request. The name is not returned: it is not changed text,
    and a name can be personal data."""
    out = []
    for pos, doc in enumerate(docs if isinstance(docs, list) else []):
        text = doc.get("text") if isinstance(doc, Mapping) else None
        if isinstance(text, str):
            masked = mask(text)
            if masked != text:
                idx = doc.get("index")
                out.append({"index": idx if isinstance(idx, int) else pos, "text": masked})
    return out


def _mask_tree_x(value: Any, leaf: Any, depth: int = 0) -> Any:
    """WP-D2: like ``_mask_tree`` for a payload with extras on. ``leaf(key, text)`` masks one
    string; ``key`` is the dict key above it (None for a list item or the root), also used to
    mask a string key."""
    if isinstance(value, Mapping) and depth <= MAX_DEPTH:
        return {
            (leaf(None, k) if isinstance(k, str) else k): (
                leaf(k, v)
                if isinstance(k, str) and isinstance(v, str)
                else _mask_tree_x(v, leaf, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple) and depth <= MAX_DEPTH:
        return [_mask_tree_x(v, leaf, depth + 1) for v in value]
    return map_leaves(value, lambda t: leaf(None, t), depth)


def _keyed_leaves(
    part: str, value: Any, path: str = "$", key: str | None = None, depth: int = 0
) -> Any:
    """``walk_leaves`` that also gives the REAL dict key above a string (the path shows
    ``*`` for a key that is not a plain identifier, e.g. a Vietnamese name)."""
    if depth > MAX_DEPTH:
        return
    if isinstance(value, str):
        yield Leaf(part, path, value), key
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _keyed_leaves(
                part, v, f"{path}.{_safe_key(k)}", k if isinstance(k, str) else None, depth + 1
            )
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            yield from _keyed_leaves(part, v, f"{path}[{i}]", None, depth + 1)


def _leaves(part: str, value: Any, keyed: bool) -> Any:
    if keyed:  # WP-D2 path: the real key is needed
        yield from _keyed_leaves(part, value)
        return
    for leaf in walk_leaves(part, value):  # the old path, unchanged
        yield leaf, (None if leaf.path.endswith("]") else leaf.path.rsplit(".", 1)[-1])


def _str_keys(value: Any, path: str = "$", depth: int = 0) -> Any:
    """(path of the dict, key) for every string key of 8 or more characters."""
    if depth > MAX_DEPTH:
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str) and len(k) >= 8:
                yield path, k
            yield from _str_keys(v, f"{path}.{_safe_key(k)}", depth + 1)
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            yield from _str_keys(v, f"{path}[{i}]", depth + 1)


def _notes(slug: str, did: str, preset: str, x: Extras) -> list[Finding]:
    """Coverage notes of the custom rules: a regex read only the first characters of a text,
    or ran out of its time. A note is not a failure and not a finding (core registry)."""
    out = []
    for rid in sorted(x.leaf_cut):
        out.append(
            _note(slug, did, preset, f"custom rule {rid}: first {RULE_LEAF_CHARS} characters")
        )
    for rid in sorted(x.over_budget):
        out.append(_note(slug, did, preset, f"custom rule {rid}: time budget"))
    return out


def _note(slug: str, did: str, preset: str, detail: str) -> Finding:
    return Finding(
        detector_slug=slug,
        detector_id=did,
        code="coverage_note.cut",
        threshold_bp=SCORE_MAX,
        detail=detail,
        preset=preset,
    )


def extras_active(settings: Mapping[str, Any]) -> bool:
    """WP-D2: True when a setting asks for the secrets group, a custom rule or a mask token."""
    return bool(
        (settings.get("secrets") or {}).get("enabled")
        or settings.get("custom_rules")
        or settings.get("mask_tokens")
    )


class DlpVnDetector:
    slug = "dlp_vn"
    name = "Vietnamese personal data (DLP)"
    category = "data_protection"
    deterministic = True  # rules and a masker, no model: its findings count in the session monitor
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
    # WP-D1: the document text is scanned too; it is masked in the transformed payload only for a
    # pii_export tool (the same rule as the arguments)
    parts = ("args", "tool_results", "output", DOCUMENT_PART)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "mode",
                "Mode",
                "enum",
                default="transform",
                enum=("report", "transform"),
                description="transform: mask payloads of tools in scope; report: findings only.",
            ),
            SettingField(
                "transform_risk_classes",
                "Transform for risk classes",
                "array",
                default=["pii_export"],
                items="string",
                item_enum=RISK_CLASSES,
                max_length=4,
            ),
            SettingField(
                "transform_tools",
                "Transform for these tools",
                "array",
                default=[],
                items="string",
                max_length=64,
            ),
            SettingField(
                "keep_args",
                "Arguments passed unmasked, per tool",
                "object",
                default={},
                description=(
                    "{tool: [argument names]}. A named top-level argument reaches the tool as "
                    "sent (a lookup key); it is still masked in every record, chain entry, "
                    "finding and SIEM event. The decision lists it as kept_args. Loading one "
                    "writes an audit line."
                ),
            ),
            SettingField(
                "pseudonym_mode",
                "Pseudonym typing",
                "enum",
                default="generic",
                enum=PSEUDONYM_MODES,
                description=(
                    "generic: the masker guesses the class from the value. typed: the argument "
                    "name decides for tax and account values, so a tax code stays TAX_CODE."
                ),
            ),
            # WP-D2. Absent or default = the detector behaves exactly as before.
            SettingField(
                "secrets",
                "Secrets group",
                "object",
                default={"enabled": False, "action": "report"},
                fields=(
                    SettingField("enabled", "Detect secrets", "boolean", default=False),
                    SettingField(
                        "action",
                        "Action on a secret in tool arguments",
                        "enum",
                        default="report",
                        enum=("report", "block"),
                        description=(
                            "report: a secret.<kind> finding (masked in the transformed "
                            "payload where dlp_vn transforms). block: a secret in a tool "
                            "argument blocks the call, GATE-SECRET-IN-ARGS, for every tool class."
                        ),
                    ),
                ),
                description=(
                    "Credentials (cloud keys, API tokens, JWT, PEM, DSN, password fields) are "
                    "reported as secret.<kind>, never as personal data. The value is never "
                    "stored; a finding keeps a short hash."
                ),
            ),
            SettingField(
                "custom_rules",
                "Custom rules",
                "array",
                default=[],
                items="object",
                max_length=32,
                description=(
                    "[{id, kind: keyword | regex, pattern, mask_token?, preserve_length?}]. "
                    "A keyword is an exact substring. A regex has a 1 ms budget per rule and "
                    "leaf; nested quantifiers are refused at load. Mask token default "
                    "<CUSTOM:id>; preserve_length repeats *."
                ),
            ),
            SettingField(
                "mask_tokens",
                "Mask token per entity",
                "object",
                default={},
                description=(
                    "{pii.phone: '<PHONE>'}: the text that replaces a built-in entity in the "
                    "transformed payload. Findings keep the pseudonym."
                ),
            ),
        )
    )

    def __init__(self, masker: Masker) -> None:
        self.masker = masker

    # -- helpers --------------------------------------------------------------
    def _in_scope(self, settings: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
        if settings.get("mode") != "transform":
            return False
        return meta.get("risk_class") in (settings.get("transform_risk_classes") or ()) or (
            meta.get("tool_name") in (settings.get("transform_tools") or ())
        )

    def transforms_here(self, settings: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
        """WP41 review: the registry asks before a cut scan; a transform of text read only in
        part is never handed out (core.detectors.APPLIED_PARTS)."""
        return self._in_scope(settings, meta)

    def _leaf_fn(self, x: Extras | None, typed: bool, mask: Any) -> Any:
        """``full(key, text) -> (final text, spans, scanned)``: one string through the secrets
        and custom rules (WP-D2, when ``x`` is set), the masker and the pseudonym typing. With
        ``x`` None this is exactly the masker call the detector always made."""

        def inner(key: str | None, text: str) -> str:
            return _typed_mask(mask, key, text) if typed and key else mask(text)

        def full(key: str | None, text: str) -> tuple[str, list[tuple[int, int, Hit]], Scanned]:
            if x is None:
                return inner(key, text), [], Scanned(text)
            sc = x.scan(text, key)
            final, spans = x.resolve(sc, inner(key, sc.text))
            if sc.plain:  # the text held a sentinel character: replacements went in directly
                final = inner(key, sc.text)
            return final, spans, sc

        return full

    # WP-D2: over max_payload_chars the registry skips every detector, except one that asks to
    # read the head of the arguments (see head_scan_here). Only a secret block counts there.
    scan_head_when_oversize = True

    def head_scan_here(self, settings: Mapping[str, Any]) -> bool:
        sec = settings.get("secrets") or {}
        return bool(sec.get("enabled")) and sec.get("action") == "block"

    def _extras(self, settings: Mapping[str, Any]) -> Extras | None:
        """The WP-D2 extras of this call, or None (the old code path) when none is on."""
        if not extras_active(settings):
            return None
        return Extras(settings, digest=make_digest(self.masker))

    def masked_leaf(self, text: str, settings: Mapping[str, Any], key: str | None = None) -> str:
        """The masked text of one string as ``evaluate`` shows it in a fragment (harness)."""
        x = self._extras(settings)
        typed = settings.get("pseudonym_mode") == "typed"
        return self._leaf_fn(x, typed, self.masker.mask)(key, text)[0]

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        meta = payload.get("meta") or {}
        typed = settings.get("pseudonym_mode") == "typed"
        memo: dict[str, str] = {}

        def mask(text: str) -> str:  # the scan and the transform mask the same text twice
            out = memo.get(text)
            if out is None:
                out = memo[text] = self.masker.mask(text)
            return out

        x = self._extras(settings)
        full = self._leaf_fn(x, typed, mask)
        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        counts: Counter[str] = Counter()
        tokens: dict[str, Counter[str]] = {}
        frags: dict[str, list[Fragment]] = {}
        seen_in: dict[str, set[str]] = {}  # entity type -> parts it was found in
        parts = parts_for(payload, direction, self)
        xhits: dict[str, list[Hit]] = {}  # WP-D2: secret.<kind> and custom.<id>
        xfrags: dict[str, list[Fragment]] = {}
        for part in parts:
            if payload.get(part) is None:
                continue
            for leaf, key in _leaves(part, payload[part], x is not None):
                masked, spans, sc = full(key, leaf.text)
                if masked == leaf.text:
                    continue
                if x is not None:
                    for h in sc.hits:
                        xhits.setdefault(h.code, []).append(h)
                    if spans:
                        for s0, e0, h in spans:
                            xfrags.setdefault(h.code, []).append(
                                Fragment(part, leaf.path, s0, e0, clip(masked, s0, e0))
                            )
                    else:  # no exact span (the text held a sentinel character): the whole leaf
                        for h in sc.hits:
                            xfrags.setdefault(h.code, []).append(
                                Fragment(
                                    part,
                                    leaf.path,
                                    0,
                                    min(len(masked), FRAGMENT_TEXT_MAX),
                                    clip(masked, 0, FRAGMENT_TEXT_MAX),
                                    "leaf",
                                )
                            )
                before = Counter(m.group(0) for m in _TOKEN.finditer(leaf.text))
                for m in _TOKEN.finditer(masked):
                    if before.get(m.group(0), 0) > 0:  # already a token in the input
                        before[m.group(0)] -= 1
                        continue
                    typ = m.group(1)
                    counts[typ] += 1
                    tokens.setdefault(typ, Counter())[m.group(0)] += 1
                    seen_in.setdefault(typ, set()).add(part)
                    frags.setdefault(typ, []).append(
                        Fragment(
                            part, leaf.path, m.start(), m.end(), clip(masked, m.start(), m.end())
                        )
                    )
            if x is not None and x.scans:  # L1: a secret used as a key is found too
                for kpath, kname in _str_keys(payload[part]):
                    masked, _, sc = full(None, kname)
                    for h in sc.hits:
                        xhits.setdefault(h.code, []).append(h)
                        xfrags.setdefault(h.code, []).append(
                            Fragment(
                                part,
                                kpath,
                                0,
                                min(len(masked), FRAGMENT_TEXT_MAX),
                                clip(masked, 0, FRAGMENT_TEXT_MAX),
                                "leaf",
                            )
                        )
        late = _notes(self.slug, did, preset, x) if x is not None else []
        if not counts and not xhits:
            return late
        transform = self._in_scope(settings, meta)
        # WP-D2: a secret in the arguments with action block. The gate blocks the call; the
        # masked arguments ride along so observe mode (which lifts the block) still sends
        # the masked copy to the tool, not the raw one.
        blocking = {
            code
            for code in xhits
            if x is not None
            and code.startswith("secret.")
            and x.secrets_action == "block"
            and any(f.part == "args" for f in xfrags.get(code, ()))
        }
        doc_transform = transform and meta.get("risk_class") == "pii_export"
        out_payload: dict[str, Any] | None = None
        block_payload: dict[str, Any] | None = None
        if transform or blocking:
            if x is None:
                tree = {
                    part: _mask_tree(payload[part], mask, typed=typed)
                    for part in parts
                    if payload.get(part) is not None and part != DOCUMENT_PART
                }
            else:

                def final_leaf(key: str | None, text: str) -> str:
                    return x.finish(full(key, text)[0], _TOKEN)

                tree = {
                    part: _mask_tree_x(payload[part], final_leaf)
                    for part in parts
                    if payload.get(part) is not None and part != DOCUMENT_PART
                }
            if doc_transform and payload.get(DOCUMENT_PART) is not None:
                changed = _masked_documents(
                    payload[DOCUMENT_PART],
                    mask if x is None else (lambda t: x.finish(full(None, t)[0], _TOKEN)),
                )
                if changed:
                    tree[DOCUMENT_PART] = changed
            block_payload = tree
            out_payload = tree if transform else None
        findings = []
        for typ in sorted(counts):
            # an entity found only in a document, on a tool that is not pii_export, is reported
            hint = (
                "transform"
                if transform and (seen_in[typ] != {DOCUMENT_PART} or doc_transform)
                else "report"
            )
            findings.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=f"pii.{typ.lower()}",
                    score_bp=min(SCORE_MAX, SCORE_BY_TYPE.get(typ, DEFAULT_SCORE)),
                    threshold_bp=threshold,
                    entities=tuple(
                        Entity(typ, tok, n) for tok, n in sorted(tokens[typ].items())[:20]
                    ),
                    fragments=tuple(frags[typ]),
                    masked_count=counts[typ],
                    action_hint=hint,
                    preset=preset,
                    transformed_payload=out_payload if hint == "transform" else None,
                )
            )
        for code in sorted(xhits):
            hits = xhits[code]
            kind = code.split(".", 1)[1]
            etype = "SECRET" if code.startswith("secret.") else "CUSTOM"
            per: Counter[str] = Counter(f"<{etype}:{kind}:{h.digest}>" for h in hits)
            fr = tuple(xfrags.get(code, ()))
            hint = "transform" if transform else "report"
            payload_out = out_payload
            if code in blocking:
                hint = "block"  # the gate turns it into GATE-SECRET-IN-ARGS (detector_gate.py)
                payload_out = block_payload
            findings.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=code,
                    score_bp=SCORE_MAX,
                    threshold_bp=threshold,
                    entities=tuple(Entity(etype, tok, n) for tok, n in sorted(per.items())[:20]),
                    fragments=fr,
                    masked_count=len(hits),
                    action_hint=hint,
                    preset=preset,
                    transformed_payload=payload_out,
                )
            )
        return [*findings, *late]
