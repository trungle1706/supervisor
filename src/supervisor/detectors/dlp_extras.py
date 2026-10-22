"""``dlp_vn`` extras (WP-D2): the secrets group, custom rules and per-entity mask tokens.

Everything here runs only when a setting asks for it (``secrets.enabled``, a non-empty
``custom_rules`` or ``mask_tokens``). With none of them ``dlp_vn`` does not call this module, so
its output is byte for byte what it was (golden test ``test_dlp_off_path_d2``).

How a text goes through (``Extras.scan`` then the masker then ``Extras.resolve``):

1. ``scan`` replaces each secret and each custom match with a private-use sentinel and notes a
   ``Hit`` (kind, the replacement text, a short SHA-256 of the value). The value is held in this
   call only; it is never put in a ``Hit``.
2. The caller runs the Vietnamese masker on the sentinel text (the masker never sees a secret).
3. ``resolve`` turns each sentinel into its replacement and returns the final text with the
   position of each replacement, so a finding can point at the right span of the masked text.

A secret value never appears in a finding, a fragment, an entity or a log line: only the kind and
the first 12 hex characters of its SHA-256 (R2).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import re._parser as sre_parse  # the stdlib regex parser: used to refuse risky patterns
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from supervisor.core.secret_patterns import KINDS, is_placeholder, redact, refine_kind

# ---------------------------------------------------------------------------- limits

SECRET_ACTIONS = ("report", "block")
RULE_KINDS = ("keyword", "regex")
MAX_RULES = 32
MAX_PATTERN_CHARS = 200
MAX_TOKEN_CHARS = 40
MAX_MASK_TOKENS = 16
MAX_REPEAT_FINITE = 1000  # a finite {n,m} above this is refused
MAX_GROUP_DEPTH = 4
RULE_BUDGET_NS = 1_000_000  # 1 ms per rule and leaf
MAX_B64_RUNS = 32
MAX_B64_CHARS = 8192
MAX_HITS_PER_LEAF = 200  # also the most sentinels a text can carry (one character each)

RULE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ENTITY_KEY = re.compile(r"^pii\.([a-z_]{2,20})$")
_RULE_KEYS = frozenset({"id", "kind", "pattern", "mask_token", "preserve_length"})
# A mask token shaped like a masker pseudonym would be counted as a personal data finding.
_PSEUDONYM_SHAPE = re.compile(r"<[A-Z_]{2,20}:[0-9a-f]{4,64}>")
_SENT_OPEN, _SENT_CLOSE = "\ue000", "\ue001"
_SENT_BASE = 0xE100  # the hit number is one private-use character, so no regex class sees a digit
_SENTINEL = re.compile("\ue000([\ue100-\ue1ff])\ue001")
_B64 = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/=_-])")
_PW_NAMES = (
    "password",
    "passwd",
    "pwd",
    "passphrase",
    "secret",
    "apikey",
    "accesstoken",
    "authtoken",
    "privatekey",
)
_NOT_A_VALUE = frozenset({"true", "false", "null", "none", "nil", "undefined", "redacted"})

SECRET_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [k for k in KINDS if k != "llm_api_key"]
        + ["anthropic_api_key", "openai_api_key", "password_field"]
    )
)


def digest12(value: str) -> str:
    """Short SHA-256 of a value: what a finding keeps instead of the value."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


# ---------------------------------------------------------------------------- pattern safety


def _walk(sub: Any, depth: int, in_var_repeat: bool, problems: list[str]) -> None:
    """Refuse nested variable repeats, a branch under an unbounded repeat, back references and
    deep nesting. ``in_var_repeat``: an enclosing repeat can run more than once."""
    for op, av in sub:
        name = str(op)
        if name in ("GROUPREF", "GROUPREF_EXISTS"):
            problems.append("a back reference is not allowed")
        elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            lo, hi, body = av
            unbounded = hi == sre_parse.MAXREPEAT
            if not unbounded and hi > MAX_REPEAT_FINITE:
                problems.append(f"a repeat above {MAX_REPEAT_FINITE}")
            variable = hi > 1
            if variable and in_var_repeat:
                problems.append("nested repeats (a quantifier inside a quantifier)")
            if unbounded and any(str(o) == "BRANCH" for o, _ in _flatten(body)):
                problems.append("an alternation under an unbounded repeat")
            _walk(body, depth, in_var_repeat or variable, problems)
        elif name == "SUBPATTERN":
            if depth + 1 > MAX_GROUP_DEPTH:
                problems.append(f"groups nested deeper than {MAX_GROUP_DEPTH}")
            else:
                _walk(av[-1], depth + 1, in_var_repeat, problems)
        elif name == "BRANCH":
            for alt in av[1]:
                _walk(alt, depth, in_var_repeat, problems)
        elif name in ("ASSERT", "ASSERT_NOT"):
            _walk(av[1], depth, in_var_repeat, problems)
        elif name == "ATOMIC_GROUP":
            _walk(av, depth, in_var_repeat, problems)


def _flatten(sub: Any) -> list[tuple[Any, Any]]:
    out: list[tuple[Any, Any]] = []
    for op, av in sub:
        out.append((op, av))
        name = str(op)
        if name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            out += _flatten(av[2])
        elif name == "SUBPATTERN":
            out += _flatten(av[-1])
        elif name == "BRANCH":
            for alt in av[1]:
                out += _flatten(alt)
    return out


def regex_problems(pattern: str) -> list[str]:
    """Why a custom regex is refused (empty = accepted): too long, does not compile, matches
    the empty text, or has a shape that can run for a very long time (nested quantifiers,
    alternation under an unbounded repeat, a back reference, deep nesting)."""
    if not pattern:
        return ["is empty"]
    if len(pattern) > MAX_PATTERN_CHARS:
        return [f"is longer than {MAX_PATTERN_CHARS} characters"]
    try:
        parsed = sre_parse.parse(pattern)
        compiled = re.compile(pattern)
    except (re.error, RecursionError, OverflowError) as exc:
        return [f"is not a valid regular expression ({type(exc).__name__})"]
    problems: list[str] = []
    _walk(parsed, 0, False, problems)
    if compiled.search(""):
        problems.append("matches the empty text")
    return sorted(set(problems))


@lru_cache(maxsize=256)
def compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


# ---------------------------------------------------------------------------- settings checks


def extras_problems(settings: Mapping[str, Any]) -> list[str]:
    """Problems in ``secrets``, ``custom_rules`` and ``mask_tokens`` (empty = fine). Run at
    config load, so a bad regex stops the start-up (``ConfigError``), not a call."""
    problems: list[str] = []
    sec = settings.get("secrets")
    if sec not in (None, {}):
        if not isinstance(sec, Mapping):
            problems.append("secrets: expected an object {enabled, action}")
        else:
            for k in sec:
                if k not in ("enabled", "action"):
                    problems.append(f"secrets.{k}: unknown setting")
            if not isinstance(sec.get("enabled", False), bool):
                problems.append("secrets.enabled: expected a boolean")
            if sec.get("action", "report") not in SECRET_ACTIONS:
                problems.append(f"secrets.action: must be one of {', '.join(SECRET_ACTIONS)}")
    rules = settings.get("custom_rules")
    if rules not in (None, []):
        if not isinstance(rules, list):
            problems.append("custom_rules: expected a list")
        else:
            if len(rules) > MAX_RULES:
                problems.append(f"custom_rules: more than {MAX_RULES} rules")
            seen: set[str] = set()
            for i, r in enumerate(rules[:MAX_RULES]):
                problems += _rule_problems(i, r, seen)
    problems += _mask_token_problems(settings.get("mask_tokens"))
    return problems


def _token_problem(where: str, tok: Any) -> str | None:
    if not isinstance(tok, str) or not 1 <= len(tok) <= MAX_TOKEN_CHARS:
        return f"{where}: a text of 1..{MAX_TOKEN_CHARS} characters"
    if any(ord(c) < 32 or c in (_SENT_OPEN, _SENT_CLOSE) for c in tok):
        return f"{where}: no control characters"
    if _PSEUDONYM_SHAPE.search(tok):
        return f"{where}: must not look like a pseudonym <TYPE:hex>"
    return None


def _rule_problems(i: int, r: Any, seen: set[str]) -> list[str]:
    where = f"custom_rules[{i}]"
    if not isinstance(r, Mapping):
        return [f"{where}: expected an object"]
    out = [f"{where}.{k}: unknown setting" for k in r if k not in _RULE_KEYS]
    rid = r.get("id")
    if not isinstance(rid, str) or not RULE_ID.match(rid):
        out.append(f"{where}.id: lower case letters, digits and _ (start with a letter, max 32)")
    elif rid in seen:
        out.append(f"{where}.id: {rid!r} is used twice")
    else:
        seen.add(rid)
    kind = r.get("kind")
    if kind not in RULE_KINDS:
        out.append(f"{where}.kind: must be one of {', '.join(RULE_KINDS)}")
    pat = r.get("pattern")
    if not isinstance(pat, str) or not pat:
        out.append(f"{where}.pattern: a non-empty text")
    elif len(pat) > MAX_PATTERN_CHARS:
        out.append(f"{where}.pattern: longer than {MAX_PATTERN_CHARS} characters")
    elif kind == "regex":
        out += [f"{where}.pattern: {p}" for p in regex_problems(pat)]
    if "mask_token" in r and r["mask_token"] is not None:
        p = _token_problem(f"{where}.mask_token", r["mask_token"])
        if p:
            out.append(p)
    if not isinstance(r.get("preserve_length", False), bool):
        out.append(f"{where}.preserve_length: expected a boolean")
    return out


def _mask_token_problems(value: Any) -> list[str]:
    if value in (None, {}):
        return []
    if not isinstance(value, Mapping):
        return ["mask_tokens: expected an object {pii.<type>: token}"]
    out = []
    if len(value) > MAX_MASK_TOKENS:
        out.append(f"mask_tokens: more than {MAX_MASK_TOKENS} entries")
    for k, tok in value.items():
        if not isinstance(k, str) or not ENTITY_KEY.match(k):
            out.append("mask_tokens: a key looks like pii.phone (lower case)")
            continue
        p = _token_problem(f"mask_tokens.{k}", tok)
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------- runtime


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    pattern: str
    mask_token: str | None
    preserve_length: bool

    def replacement(self, value: str) -> str:
        if self.preserve_length:
            return "*" * len(value)
        return self.mask_token or f"<CUSTOM:{self.id}>"


@dataclass(frozen=True)
class Hit:
    """One replaced span. ``code`` is the finding code, ``replacement`` the text that goes in
    the masked output, ``digest`` the short hash of the value. No field holds the value."""

    code: str
    replacement: str
    digest: str


@dataclass
class Scanned:
    text: str  # the text with sentinels, for the masker
    hits: list[Hit] = field(default_factory=list)
    plain: bool = False  # the text held a sentinel character: replacements are put in directly


def _password_key(key: str | None) -> bool:
    if not key:
        return False
    norm = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(n in norm for n in _PW_NAMES)


def _plausible_value(text: str) -> bool:
    if not 6 <= len(text) <= 256 or any(c.isspace() for c in text):
        return False
    low = text.lower()
    if low in _NOT_A_VALUE or is_placeholder(text):
        return False
    if low.startswith(("http://", "https://", "${", "{{", "<", "$(", "env:", "os.")):
        return False
    return True


class Extras:
    """The extras of one ``evaluate`` call (built per call: it holds the rule timing)."""

    def __init__(
        self,
        settings: Mapping[str, Any],
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        sec = settings.get("secrets") or {}
        self.secrets_on = bool(sec.get("enabled"))
        self.secrets_action = str(sec.get("action") or "report")
        self.rules = tuple(
            Rule(
                str(r["id"]),
                str(r["kind"]),
                str(r["pattern"]),
                r.get("mask_token"),
                bool(r.get("preserve_length")),
            )
            for r in settings.get("custom_rules") or ()
        )
        tokens = settings.get("mask_tokens") or {}
        self.entity_tokens = {
            m.group(1).upper(): str(tok)
            for k, tok in tokens.items()
            if (m := ENTITY_KEY.match(str(k)))
        }
        self.clock = clock
        self.over_budget: set[str] = set()  # custom rule ids that ran out of time in this call
        self._memo: dict[tuple[str | None, str], Scanned] = {}

    @property
    def scans(self) -> bool:
        """True when ``scan`` can change a text (secrets on or at least one rule)."""
        return self.secrets_on or bool(self.rules)

    # -- scan -----------------------------------------------------------------
    def scan(self, text: str, key: str | None = None) -> Scanned:
        memo_key = (key if self.secrets_on and _password_key(key) else None, text)
        got = self._memo.get(memo_key)
        if got is None:
            got = self._memo[memo_key] = self._scan(text, memo_key[0])
        return got

    def _scan(self, text: str, key: str | None) -> Scanned:
        res = Scanned(text, plain=_SENT_OPEN in text or _SENT_CLOSE in text)
        if not self.scans or not text:
            return res
        if self.secrets_on:
            self._scan_secrets(res, text, key)
        for rule in self.rules:
            if len(res.hits) >= MAX_HITS_PER_LEAF:
                break
            self._scan_rule(res, rule)
        return res

    def _put(self, res: Scanned, hit: Hit) -> str:
        res.hits.append(hit)
        if res.plain:
            return hit.replacement
        return f"{_SENT_OPEN}{chr(_SENT_BASE + len(res.hits) - 1)}{_SENT_CLOSE}"

    def _scan_secrets(self, res: Scanned, text: str, key: str | None) -> None:
        def marker(kind: str, value: str) -> str:
            k = refine_kind(kind, value)
            return self._put(res, Hit(f"secret.{k}", f"<SECRET:{k}>", digest12(value)))

        out = redact(text, marker)
        if out == text and key is not None and _plausible_value(text):
            out = self._put(
                res, Hit("secret.password_field", "<SECRET:password_field>", digest12(text))
            )
        elif out == text:
            out = self._scan_base64(res, text)
        res.text = out

    def _scan_base64(self, res: Scanned, text: str) -> str:
        """A secret hidden in base64 (a run of 24 or more characters that decodes to text with a
        secret in it) is masked as a whole."""
        pieces: list[str] = []
        last = 0
        for n, m in enumerate(_B64.finditer(text)):
            if n >= MAX_B64_RUNS:
                break
            run = m.group(0)
            if len(run) > MAX_B64_CHARS:
                continue
            decoded = _b64_text(run)
            if decoded is None:
                continue
            found = _secret_hits(decoded)
            if not found:
                continue
            kind, value = found[0]
            k = refine_kind(kind, value)
            pieces += [
                text[last : m.start()],
                self._put(res, Hit(f"secret.{k}", f"<SECRET:{k}>", digest12(run))),
            ]
            last = m.end()
        if not pieces:
            return text
        return "".join(pieces) + text[last:]

    def _scan_rule(self, res: Scanned, rule: Rule) -> None:
        t0 = self.clock()
        text = res.text
        pieces: list[str] = []
        last = 0
        if rule.kind == "keyword":
            spans = _keyword_spans(text, rule.pattern)
        else:
            spans = []
            for m in compiled(rule.pattern).finditer(text):
                if m.end() > m.start():
                    spans.append((m.start(), m.end()))
                if self.clock() - t0 > RULE_BUDGET_NS:
                    break
        if self.clock() - t0 > RULE_BUDGET_NS:
            self.over_budget.add(rule.id)
            return  # a rule that ran out of time masks nothing: the call reports it
        for s, e in spans[: MAX_HITS_PER_LEAF - len(res.hits)]:
            value = text[s:e]
            pieces += [
                text[last:s],
                self._put(res, Hit(f"custom.{rule.id}", rule.replacement(value), digest12(value))),
            ]
            last = e
        if pieces:
            res.text = "".join(pieces) + text[last:]

    # -- resolve --------------------------------------------------------------
    def resolve(self, scanned: Scanned, masked: str) -> tuple[str, list[tuple[int, int, Hit]]]:
        """Put the replacements in the masked text. Returns (final text, [(start, end, hit)])
        with offsets in the final text. A sentinel the masker removed is skipped."""
        if not scanned.hits or scanned.plain:
            return masked, []
        out: list[str] = []
        spans: list[tuple[int, int, Hit]] = []
        pos = 0
        last = 0
        for m in _SENTINEL.finditer(masked):
            i = ord(m.group(1)) - _SENT_BASE
            out.append(masked[last : m.start()])
            pos += m.start() - last
            if i < len(scanned.hits):
                hit = scanned.hits[i]
                out.append(hit.replacement)
                spans.append((pos, pos + len(hit.replacement), hit))
                pos += len(hit.replacement)
            last = m.end()
        out.append(masked[last:])
        return "".join(out), spans

    def finish(self, text: str, token_re: re.Pattern[str]) -> str:
        """Per-entity mask tokens: ``<PHONE:ab12>`` becomes the configured text."""
        if not self.entity_tokens:
            return text
        return token_re.sub(lambda m: self.entity_tokens.get(m.group(1), m.group(0)), text)


def _secret_hits(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    redact(text, lambda k, v: "", lambda k, v: found.append((k, v)))
    return found


def _keyword_spans(text: str, word: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = text.find(word)
    while i >= 0 and len(spans) < MAX_HITS_PER_LEAF:
        spans.append((i, i + len(word)))
        i = text.find(word, i + len(word))
    return spans


def _b64_text(run: str) -> str | None:
    pad = run + "=" * (-len(run) % 4)
    try:
        raw = (
            base64.urlsafe_b64decode(pad)
            if ("-" in run or "_" in run)
            else base64.b64decode(pad, validate=True)
        )
        return raw.decode("utf-8")
    except (binascii.Error, ValueError):
        return None
