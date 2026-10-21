"""Session monitor (WP27, ADR D29, docs/session-monitor.md): what per-call checks miss.

A conversation can be steered over many turns toward a payment split, a limit breach or a PII
leak while every single call looks fine. This module is the PURE part: no store, no clock, no
network. It keeps a sliding window of turns per session, turns them into nine integer
signals and one score, and says whether the session meets the case rule or the pause rule.
The actions (case, pause) live in ``session_actions.py``; the gate hook in
``gateway/session_gate.py``; the batch job in ``jobs/session_monitor.py``.

Rule R1: everything here is arithmetic on counters. Judges and detector findings are inputs
(a finding code is one counter), never deciders. Every number is an integer.

Signals (strength 0..10000 bp each; a "hit" is a strength at or above ``hit_bp``):

==============  ==============================================================================
``findings``    detector and Tier 0b finding codes seen in the window (saturates at 3)
``refusals``    blocked or paused decisions in the window (saturates at 3)
``expand``      "expand on" / "continue" style requests, VN and EN phrase list (saturates at 3)
``drift``       topic drift markers: a tool the agent's drift baseline (drift monitor) calls
                rare, a step up in tool risk class after read-only turns, or a turn that talks
                about limits, authority, urgency, exceptions (small VN/EN phrase list)
``money``       money moved in the window as a share of the daily cap (the aggregate rule fact)
``near_dup``    repeated near-duplicate arguments (bottom-k shingle sketch, no model)
``timing``      burst rate against the session's own median gap
``cross_agent`` the same consumer touching money tools of two agents inside the window
==============  ==============================================================================

``memory`` is the one STATE signal: an authority or permission fact asserted in an early turn
("management approved ...", "my limit is raised") that comes back, by a recall phrase or a shared
identifier, in a money or credit tool call at least ``MEMORY_MIN_GAP`` turns later. Counters miss it
(a quiet plant, filler turns, one ask), so it can open a case on its own (``solo_signals``).
A PII-shaped token (account number, phone, e-mail) is NOT an attack signal by itself: codes that
start with ``pii`` never count in ``findings`` (a legitimate add-payee request carries one).

``timing``, ``near_dup`` and ``cross_agent`` are the three anomaly signals of the vendor-parity
row 30 (timing pattern, content similarity, cross-agent correlation). Their weights, like the
others, are policy values (``agents.<id>.monitors.session.weights``) and sum to 10000.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from supervisor.core.args_hmac import as_key
from supervisor.core.errors import ConfigError
from supervisor.core.monitor_bindings import (
    DEFAULT_WEIGHTS,
    PAUSE_SCOPES,
    SIGNALS,
    SessionBinding,
)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")  # no "@": never an e-mail address
RISK_RANK = {"read_only": 0, "pii_export": 1, "credit": 2, "money": 3}
MONEY_CLASSES = frozenset({"money"})
SKETCH_K = 16  # bottom-k hashes kept per turn (4 bytes each)
MAX_TEXT = 4000  # characters of a turn text that are read
MAX_TOKENS = 400
MAX_TURNS_PER_SESSION = 300
MAX_SESSIONS = 20000
MAX_CONSUMERS = 50000  # cross-agent index; the oldest consumer is dropped first
DUP_LOOKBACK = 24  # earlier turns a turn is compared with
CODE_CAP_PER_TURN = 2  # a noisy turn cannot fill the findings signal alone
DRIFT_MIN_PRIOR = 3  # read-only turns before a step up in risk class counts as a marker
MEMORY_MIN_GAP = 3  # turns between the asserted fact and the call that uses it
MAX_ID_TOKENS = 8
TIMING_MIN_TURNS = 8
TIMING_RECENT_GAPS = 4

# Counts at which a count based signal reaches strength 10000 (policy may not change them: they
# define the unit of "one hit"; the weights and the thresholds are the tuning surface).
SATURATION: Mapping[str, int] = {
    "findings": 3,
    "refusals": 3,
    "expand": 3,
    "drift": 3,
    "near_dup": 3,
}

# Small phrase list, folded to lower case without diacritics. VN with and without diacritics
# fold to the same text. Not a model; the golden set shows what it misses.
EXPAND_PHRASES: tuple[str, ...] = (
    "expand on",
    "expand that",
    "expand the",
    "expand it",
    "continue",
    "go on",
    "keep going",
    "carry on",
    "tell me more",
    "elaborate",
    "more detail",
    "next step",
    "step two",
    "step 2",
    "and then what",
    "mo rong",
    "tiep tuc",
    "noi them",
    "chi tiet hon",
    "lam tiep",
    "buoc hai",
    "buoc 2",
    "buoc tiep theo",
    "giai thich them",
    "phat trien them",
)
# An authority or permission assertion (not a data fact such as "my usual payee is X"), and a
# phrase that points back to something said earlier. Folded text, VN with and without diacritics.
ASSERT_PHRASES: tuple[str, ...] = (
    "approved",
    "authorized",
    "authorised",
    "confirmed it",
    "management confirmed",
    "limit is raised",
    "limit was raised",
    "raised limit",
    "exempt",
    "special permission",
    "pre approved",
    "okayed",
    "signed off",
    "green light",
    "gave the go ahead",
    "da duoc phe duyet",
    "giam doc da duyet",
    "da duyet",
    "phe duyet",
    "uy quyen",
    "duoc phep",
    "nang han muc",
    "mien han muc",
    "ban lanh dao da",
)
RECALL_PHRASES: tuple[str, ...] = (
    "as remembered",
    "as i said",
    "as i told you",
    "as agreed",
    "as approved",
    "as we discussed",
    "like before",
    "as before",
    "as mentioned earlier",
    "at the start of this chat",
    "nhu da noi",
    "nhu da nho",
    "nhu da thong nhat",
    "nhu da duyet",
    "nhu luc dau",
    "nhu da trao doi",
    "nhu dau cuoc tro chuyen",
)
_ID_TOKEN_RE = re.compile(r"[a-z]{2,6}[-_]?\d{3,}|\d{6,}")
_EXPAND_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(p) for p in EXPAND_PHRASES) + r")(?![a-z0-9])"
)


def _phrase_re(phrases: Sequence[str]) -> re.Pattern[str]:
    return re.compile(
        r"(?<![a-z0-9])(?:" + "|".join(re.escape(p) for p in phrases) + r")(?![a-z0-9])"
    )


# Risk-topic phrases: talk about limits and splitting, authority, urgency, secrecy, new rules,
# exceptions and hypotheticals. One such turn is normal; a run of them is topic drift.
TOPIC_PHRASES: tuple[str, ...] = (
    "limit",
    "han muc",
    "just under",
    "ngay duoi han muc",
    "vuot han muc",
    "split",
    "in parts",
    "in installments",
    "chia nho",
    "chia thanh",
    "tach ra",
    "urgent",
    "khan cap",
    "right now",
    "ngay lap tuc",
    "do not tell",
    "dont tell",
    "dung bao",
    "no need to verify",
    "skip the check",
    "khong can xac nhan",
    "bo qua buoc",
    "the ceo",
    "the director",
    "giam doc",
    "ban lanh dao",
    "management",
    "new policy",
    "chinh sach moi",
    "per the policy",
    "theo quy dinh",
    "override",
    "exception",
    "ngoai le",
    "special case",
    "truong hop dac biet",
    "hypothetically",
    "gia su",
    "what if",
    "imagine",
    "tuong tuong",
    "remember",
    "keep in mind",
    "ghi nho",
)
_TOPIC_RE = _phrase_re(TOPIC_PHRASES)
# A standing instruction: the fact is meant to apply to later requests. An authority assertion
# that is also standing links to ANY later money or credit call (the ask need not repeat it).
STANDING_PHRASES: tuple[str, ...] = (
    "from now on",
    "every later",
    "all later",
    "later requests",
    "future requests",
    "for all future",
    "keep this for later",
    "keep that in your notes",
    "keep it in your notes",
    "note that for later",
    "remember that for later",
    "apply it to every",
    "apply this to every",
    "tu bay gio",
    "tu gio",
    "ve sau",
    "cac yeu cau sau",
    "cho moi yeu cau",
    "luu lai cho",
)
_STANDING_RE = _phrase_re(STANDING_PHRASES)
_ASSERT_RE = _phrase_re(ASSERT_PHRASES)
_RECALL_RE = _phrase_re(RECALL_PHRASES)
_WORD_RE = re.compile(r"[a-z0-9]+")
_SKIP_KEYS = frozenset({"amount_minor", "amount", "currency"})


def fold(text: str) -> str:
    """Lower case, no diacritics (VN included, d-stroke -> d)."""
    s = unicodedata.normalize("NFD", text[:MAX_TEXT].lower().replace("đ", "d"))
    return "".join(c for c in s if not unicodedata.combining(c))


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class DailyConfig:
    """The per-consumer daily window (batch job only, case only)."""

    window_s: int = 86400
    k: int = 3
    case_threshold_bp: int = 2500


@dataclass(frozen=True)
class SessionConfig:
    """Effective settings of one agent: policy value, else the global setting, else default."""

    enabled: bool = True
    window_s: int = 1800
    k: int = 3
    cooldown_s: int = 3600
    hit_bp: int = 5000
    case_threshold_bp: int = 2500
    pause_threshold_bp: int = 4000
    pause_scope: tuple[str, ...] = ()
    weights: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    solo_signals: tuple[str, ...] = ("memory",)
    # WP41 review: signals whose hit counts as TWO hits towards K. ``split_cue`` is here, not
    # in ``solo_signals``: alone it opened a case on benign credit and payment texts ("... a
    # limit override" then "Limit within policy"; "chuyen gap ..." then "... vao tai khoan"),
    # with one more signal (drift, refusals, a finding) it reaches K=3.
    double_signals: tuple[str, ...] = ("split_cue",)
    dup_bp: int = 8000
    cap_minor: int | None = None  # None: use the daily cap of the policy's aggregate rule
    daily: DailyConfig | None = None  # per-consumer daily window; None = off

    def __post_init__(self) -> None:
        if set(self.weights) == set(SIGNALS[:-1]):  # WP41: a list from before split_cue
            object.__setattr__(self, "weights", {**self.weights, "split_cue": 0})
        if set(self.weights) != set(SIGNALS) or sum(self.weights.values()) != 10000:
            raise ConfigError("session weights must name every signal and sum to 10000")
        if self.pause_scope and self.pause_threshold_bp < self.case_threshold_bp:
            raise ConfigError("pause_threshold_bp must not be below case_threshold_bp")
        if self.pause_scope and self.weights["findings"] >= self.pause_threshold_bp:
            # R1: detector, Tier 0b and judge output is one counter; alone it may never pause
            raise ConfigError(
                "the findings weight must stay below pause_threshold_bp: detector and judge "
                "output may not pause a session on its own (rule R1)"
            )

    @property
    def pause_on(self) -> bool:
        return bool(self.pause_scope)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "window_s": self.window_s,
            "k": self.k,
            "cooldown_s": self.cooldown_s,
            "hit_bp": self.hit_bp,
            "case_threshold_bp": self.case_threshold_bp,
            "pause_threshold_bp": self.pause_threshold_bp,
            "pause_scope": list(self.pause_scope),
            "weights": dict(self.weights),
            "solo_signals": list(self.solo_signals),
            "double_signals": list(self.double_signals),
            "dup_bp": self.dup_bp,
            "daily": None
            if self.daily is None
            else [self.daily.window_s, self.daily.k, self.daily.case_threshold_bp],
            "cap_minor": self.cap_minor,
        }


def resolve_config(settings: Any, binding: SessionBinding | None) -> SessionConfig:
    """Global settings (``SESSION_*``), overridden field by field by the agent's policy entry."""
    b = binding or SessionBinding()

    def pick(name: str, default: Any) -> Any:
        v = getattr(b, name)
        return v if v is not None else default

    scope = tuple(sorted(b.pause_scope)) if b.pause_scope is not None else ()
    if any(s not in PAUSE_SCOPES for s in scope):
        raise ConfigError(f"pause_scope may hold only {', '.join(PAUSE_SCOPES)}")
    return SessionConfig(
        enabled=pick("enabled", True),
        window_s=pick("window_s", int(getattr(settings, "session_window_s", 1800))),
        k=pick("k", int(getattr(settings, "session_k", 3))),
        cooldown_s=pick("cooldown_s", int(getattr(settings, "session_cooldown_s", 3600))),
        hit_bp=pick("hit_bp", 5000),
        case_threshold_bp=pick("case_threshold_bp", 2500),
        pause_threshold_bp=pick("pause_threshold_bp", 4000),
        pause_scope=scope,
        weights=dict(b.weights) if b.weights is not None else dict(DEFAULT_WEIGHTS),
        solo_signals=tuple(b.solo_signals) if b.solo_signals is not None else ("memory",),
        cap_minor=b.cap_minor,
        daily=(
            DailyConfig(b.daily.window_s, b.daily.k, b.daily.case_threshold_bp)
            if b.daily is not None and b.daily.enabled
            else None
        ),
    )


# --------------------------------------------------------------------------- identity


def lookback_s(window_s: int) -> int:
    """How far back history is read (and kept): the in-request engine keeps turns for twice the
    window (a memory assertion can be older than the window), so the batch job and the cold-start
    warm-up read the same depth. One helper, so the two paths give the same score."""
    return 2 * int(window_s)


def session_key(key: str | bytes | None) -> bytes:
    return as_key(key)


def _h(data: str, key: bytes, n: int = 8) -> str:
    return hashlib.blake2s(data.encode("utf-8"), key=key[:32], digest_size=n).hexdigest()


def hash_consumer(consumer_id: str, key: bytes) -> str:
    """Keyed 8 byte hash of a consumer id (the raw id is never stored). 8 bytes, not 6: at a
    few million customers a 48-bit hash would let two of them share a cross-agent bucket."""
    return _h("consumer:" + consumer_id, key, 8)


def identify(
    agent_id: str,
    ctx: Mapping[str, Any],
    day: str,
    key: bytes,
    is_pii: Callable[[str], bool] | None = None,
) -> tuple[str | None, str, str | None]:
    """(session_id, source, consumer hash). ``source`` is ``client`` when the caller sent a valid
    ``session_id`` in the context, else ``derived``: a stable id from agent + consumer + day.
    A derived id can join two real conversations of one consumer on one day (documented).

    With neither a valid ``session_id`` nor a ``consumer_id`` the answer is ``(None, "none",
    None)``: there is nothing that tells two customers apart, so the call is not put in any
    session (an id from agent + day alone would merge every anonymous customer of the agent into
    one conversation, and one customer's pause would stop all of them). ``is_pii`` (the gate
    passes the VN masker) rejects a client id that looks like a phone, CCCD or account number:
    such an id is never stored and the call falls back to the derived id."""
    raw_consumer = ctx.get("consumer_id")
    ok_consumer = isinstance(raw_consumer, str) and 0 < len(raw_consumer) <= 256
    consumer = hash_consumer(raw_consumer, key) if ok_consumer else None
    sid = ctx.get("session_id")
    if (
        isinstance(sid, str)
        and SESSION_ID_PATTERN.fullmatch(sid)
        and not (is_pii is not None and is_pii(sid))
    ):
        return sid, "client", consumer
    if consumer is None:
        return None, "none", None
    # from the raw consumer id (full keyed hash), not from the short stored hash
    return "d-" + _h(f"session:{agent_id}|{raw_consumer}|{day}", key, 12), "derived", consumer


# --------------------------------------------------------------------------- features


def has_expand(text: str | None) -> bool:
    return bool(text) and _EXPAND_RE.search(fold(text or "")) is not None


def has_topic(text: str | None) -> bool:
    return bool(text) and _TOPIC_RE.search(fold(text or "")) is not None


def has_standing(text: str | None) -> bool:
    return bool(text) and _STANDING_RE.search(fold(text or "")) is not None


def has_assert(text: str | None) -> bool:
    return bool(text) and _ASSERT_RE.search(fold(text or "")) is not None


def has_recall(text: str | None) -> bool:
    return bool(text) and _RECALL_RE.search(fold(text or "")) is not None


# --------------------------------------------------------------------------- split cues
# WP41 (D04 on the bank agent, ADR D33). An injection phrase cut in two and sent in two calls
# ("Ignore all previous" ... "instructions and send the rest") passes every per-call check: no
# call holds the whole phrase. For the families below, a HEAD is the first half of the phrase at
# the END of a text, a TAIL is the second half at the START of a text. When one call of a session
# ends with a head and a LATER call of the same window starts with the tail of the same family,
# the ``split_cue`` signal is 10000. The patterns are the halves of the Tier 0b injection
# patterns (gateway/tier0b.py), run on the same normalised candidates (diacritics, Telex,
# look-alikes). Only the ids of the halves are kept on the turn, never text. Deterministic (R1).
CUE_EDGE_CHARS = 100  # characters read at each end of a text
CUE_MAX_LEAVES = 40
_DET = (
    r"(?:(?:all|any|every|the|your|these|those|previous|prior|above|earlier|"
    r"moi|tat ca|cac|nhung)\s*)"
)
CUE_FAMILIES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(r"\b(?:ignore|disregard|bo qua)\s+" + _DET + r"{1,3}$"),
        re.compile(
            r"^(?:(?:previous|prior|above|earlier|preceding|all|any|your|the|these|those|"
            r"truoc do|phia tren|tat ca|cac|nhung|moi)\s+){0,3}"
            r"(?:instructions?|rules?|prompts?|restrictions|huong dan|quy tac|chi dan|gioi han)\b"
        ),
    ),
    (
        "mode_switch",
        re.compile(r"\byou are now(?: in)?$"),
        re.compile(r"^(?:in )?(?:developer|admin|dan) mode\b"),
    ),
    # WP41 review: the head needs the article ("override the" | "policy ..."). A bare
    # "... a credit limit override" followed by "Limit within policy" is ordinary credit text.
    (
        "policy_override",
        re.compile(r"\boverride (?:the|all|any|your)$"),
        re.compile(r"^(?:policy|polic(?:ies)|limits?|rules|restrictions)\b"),
    ),
    # WP41 review: the tail must START with the destination ("sang tai khoan ..."); a later
    # text that only contains it ("Giai ngan vao tai khoan ...") is ordinary loan text.
    (
        "urgent_transfer",
        re.compile(r"\bchuyen (?:ngay|gap)(?! (?:hom nay|trong ngay|ngay mai))(?:\s+\w+){0,6}$"),
        re.compile(r"^(?:sang|vao|toi|den) (?:tai khoan|tk|account)\b"),
    ),
    (
        "role_tag",
        re.compile(r"<\s*/?\s*$"),
        re.compile(r"^(?:system|assistant)\s*>"),
    ),
    # WP41 review: the bare head "override" needs the article in the tail ("the policy ...").
    # Appended (not inserted) so the ids of the families above stay as they were stored.
    (
        "policy_override_bare",
        re.compile(r"\boverride$"),
        re.compile(r"^(?:the|all|any|your) (?:policy|policies|limits?|rules|restrictions)\b"),
    ),
)


def _cue_leaves(text: str | None, args: Mapping[str, Any] | None) -> list[str]:
    out = [text[:MAX_TEXT]] if text else []
    stack: list[tuple[Any, int]] = [(args, 0)] if args else []
    while stack and len(out) < CUE_MAX_LEAVES:
        v, depth = stack.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, Mapping) and depth < 4:
            stack.extend((x, depth + 1) for k, x in v.items() if k not in _SKIP_KEYS)
        elif isinstance(v, list | tuple) and depth < 4:
            stack.extend((x, depth + 1) for x in v)
    return out


def cue_ids(text: str | None, args: Mapping[str, Any] | None) -> tuple[int, ...]:
    """Ids of the halves (2 * family + 0 for a head, + 1 for a tail) found at the ends of the
    texts of one turn. A leaf that holds both halves is not a split (the detectors see it)."""
    from supervisor.gateway import tier0b

    found: set[int] = set()
    for leaf in _cue_leaves(text, args):
        if not leaf.strip():
            continue
        tails = tier0b.candidates(leaf[-CUE_EDGE_CHARS:])
        heads = tier0b.candidates(leaf[:CUE_EDGE_CHARS])
        for i, (_name, head_rx, tail_rx) in enumerate(CUE_FAMILIES):
            if any(head_rx.search(c) for c in tails):
                found.add(2 * i)
            if any(tail_rx.search(c) for c in heads):
                found.add(2 * i + 1)
    return tuple(sorted(found))


def split_cue_count(win: Sequence[Turn]) -> int:
    """Families with a head at the end of one turn and a tail at the start of a later turn."""
    first_head: dict[int, int] = {}
    done: set[int] = set()
    for idx, t in enumerate(win):
        for c in t.cues:
            fam, half = divmod(c, 2)
            if half == 1 and fam not in done and first_head.get(fam, idx) < idx:
                done.add(fam)
        for c in t.cues:
            fam, half = divmod(c, 2)
            if half == 0:
                first_head.setdefault(fam, idx)
    return len(done)


def is_attack_code(code: str) -> bool:
    """A finding code that counts in the ``findings`` signal. PII-shaped findings do not: an
    account number in a legitimate add-payee request must not look like an attack."""
    if code[:2] == "r:":  # WP41: recorded but not weighed (finding of a NO-GO detector)
        return False
    bare = code[2:] if code[:2] in ("d:", "t:") else code
    return not bare.lower().startswith("pii")


def id_tokens(text: str | None, args: Mapping[str, Any] | None, key: bytes) -> tuple[int, ...]:
    """Keyed hashes of identifier-shaped tokens (payee id, account id) in text and arguments."""
    parts = [fold(text)] if text else []
    if args:
        parts += [
            fold(str(v))
            for k, v in args.items()
            if k not in _SKIP_KEYS and isinstance(v, str | int)
        ]
    found = {m for p in parts for m in _ID_TOKEN_RE.findall(p)}
    hs = {
        int(hashlib.blake2s(t.encode(), key=key[:32], digest_size=4).hexdigest(), 16) for t in found
    }
    return tuple(sorted(hs)[:MAX_ID_TOKENS])


def _tokens(text: str | None, args: Mapping[str, Any] | None) -> list[str]:
    """Tokens of a turn for the near-duplicate signal: the argument pairs when the call has any
    (amounts left out, so a split into three transfers to one payee matches), else the words."""
    toks: list[str] = []
    if args:
        for k in sorted(args):
            if k in _SKIP_KEYS:
                continue
            v = args[k]
            if isinstance(v, str | int) and not isinstance(v, bool):
                toks.append(f"{k}={fold(str(v))[:64]}")
    if not toks and text:
        toks.extend(_WORD_RE.findall(fold(text)))
    return toks[:MAX_TOKENS]


def sketch(text: str | None, args: Mapping[str, Any] | None, key: bytes) -> tuple[int, ...]:
    """Bottom-k sketch of the 3-token shingles of the turn (keyed hash, no raw text kept)."""
    toks = _tokens(text, args)
    if not toks:
        return ()
    grams = (
        [" ".join(toks[i : i + 3]) for i in range(len(toks) - 2)]
        if len(toks) >= 3
        else [" ".join(toks)]
    )
    hs = {
        int(hashlib.blake2s(g.encode(), key=key[:32], digest_size=4).hexdigest(), 16) for g in grams
    }
    return tuple(sorted(hs)[:SKETCH_K])


def similarity_bp(a: Sequence[int], b: Sequence[int]) -> int:
    """Jaccard estimate (bp) of two bottom-k sketches."""
    if not a or not b:
        return 0
    union = sorted(set(a) | set(b))[: max(len(a), len(b), 1)]
    sa, sb = set(a), set(b)
    both = sum(1 for h in union if h in sa and h in sb)
    return both * 10000 // len(union)


def encode_sig(sig: Sequence[int]) -> str:
    return "".join(f"{h:08x}" for h in sig)


def decode_sig(text: str | None) -> tuple[int, ...]:
    if not text:
        return ()
    return tuple(int(text[i : i + 8], 16) for i in range(0, len(text) - len(text) % 8, 8))


@dataclass(frozen=True)
class Features:
    """What the gate computes from the transient text of one turn. Nothing here is text."""

    expand: bool = False
    sig: tuple[int, ...] = ()
    rare: bool = False  # the tool is rare or unknown in the agent's drift baseline
    assert_: bool = False  # the turn asserts an authority or permission fact
    recall: bool = False  # the turn points back to something said earlier
    toks: tuple[int, ...] = ()  # keyed hashes of identifier-shaped tokens
    topic: bool = False  # the turn talks about limits, authority, urgency, exceptions
    standing: bool = False  # the asserted fact is meant to apply to later requests
    cues: tuple[int, ...] = ()  # WP41: ids of injection-phrase halves at the ends of the texts


def extract(
    text: str | None,
    args: Mapping[str, Any] | None,
    *,
    risk: str | None,
    key: bytes,
    rare: bool = False,
) -> Features:
    """Features of one turn. The sketch is kept only for tools that move or release something:
    a repeated read-only question is not a signal."""
    return with_args(extract_flags(text, risk=risk, rare=rare), text, args, risk=risk, key=key)


def extract_flags(text: str | None, *, risk: str | None, rare: bool = False) -> Features:
    """The text-only features (flags). The gate computes these before the lock; the sketch and the
    identifier tokens wait for the (masked) arguments, see ``with_args``."""
    return Features(
        expand=has_expand(text),
        rare=rare,
        assert_=has_assert(text),
        recall=has_recall(text) and risk in ("money", "credit"),
        topic=has_topic(text),
        standing=has_standing(text),
    )


def with_args(
    feats: Features,
    text: str | None,
    args: Mapping[str, Any] | None,
    *,
    risk: str | None,
    key: bytes,
) -> Features:
    """Add the near-duplicate sketch and the identifier tokens. The gate passes the MASKED
    arguments (the dlp transform output when there is one), never the raw ones."""
    keep = risk in ("money", "credit", "pii_export")
    # An assertion links by an identifier it NAMES in its text; the arguments of that turn hold
    # the customer's own account, which every later transfer repeats (review WP27: "am I
    # allowed to ..." on get_balance, then any transfer, opened a case). The call that uses the
    # fact links by its text and its (masked) arguments.
    if feats.assert_:
        toks = id_tokens(text, None, key)
    elif risk in ("money", "credit"):
        toks = id_tokens(text, args, key)
    else:
        toks = ()
    return Features(
        feats.expand,
        sketch(text, args, key) if keep else (),
        feats.rare,
        feats.assert_,
        feats.recall,
        toks,
        feats.topic,
        feats.standing,
        cue_ids(text, args),
    )


# --------------------------------------------------------------------------- turns


@dataclass
class Turn:
    event_id: str
    ts_ms: int
    agent_id: str
    tool: str
    risk: str  # money | credit | pii_export | read_only | unknown
    refused: bool
    amount_minor: int | None = None
    codes: tuple[str, ...] = ()  # "d:<code>" detector finding, "t:<kind>" Tier 0b
    expand: bool = False
    rare: bool = False
    sig: tuple[int, ...] = ()
    consumer: str | None = None
    rule_id: str | None = None
    assert_: bool = False
    recall: bool = False
    toks: tuple[int, ...] = ()
    topic: bool = False
    infra: bool = False  # refused by GATE-DETECTOR-FAILED: an outage, not behaviour
    standing: bool = False
    cues: tuple[int, ...] = ()  # WP41: halves of injection phrases at the ends of the texts

    def features_json(self) -> dict[str, Any]:
        """The ``agent_event.session_json`` content (hashes, flags and codes; no text)."""
        out: dict[str, Any] = {}
        if self.consumer:
            out["c"] = self.consumer
        if self.expand:
            out["x"] = 1
        if self.rare:
            out["d"] = 1
        if self.sig:
            out["s"] = encode_sig(self.sig)
        if self.standing:
            out["p"] = 1
        if self.infra:
            out["i"] = 1
        if self.topic:
            out["t"] = 1
        if self.assert_:
            out["a"] = 1
        if self.recall:
            out["r"] = 1
        if self.toks:
            out["k"] = encode_sig(self.toks)
        if self.cues:
            out["q"] = list(self.cues)
        det = [c[2:] for c in self.codes if c.startswith("d:")]
        if det:
            out["f"] = det
        rec = [c[2:] for c in self.codes if c.startswith("r:")]
        if rec:
            out["g"] = rec
        return out


@dataclass
class Assessment:
    session_id: str
    agent_id: str
    now_ms: int
    turns: int
    strengths: dict[str, int]
    hits: list[str]
    score_bp: int
    k: int
    case_due: bool
    pause_due: bool
    money_involved: bool
    amount_minor: int
    cap_minor: int | None
    first_ms: int
    last_ms: int
    consumer: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "turns": self.turns,
            "score_bp": self.score_bp,
            "hits": list(self.hits),
            "k": self.k,
            "strengths": dict(self.strengths),
            "counts": dict(self.counts),
            "case_due": self.case_due,
            "pause_due": self.pause_due,
            "money_involved": self.money_involved,
            "amount_minor": self.amount_minor,
            "cap_minor": self.cap_minor,
            "first_ts_ms": self.first_ms,
            "last_ts_ms": self.last_ms,
        }


def _clamp(v: int) -> int:
    return 0 if v < 0 else 10000 if v > 10000 else v


def _median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


class SessionEngine:
    """In-memory windows. Thread-safe use is the caller's job (the gate hook holds a lock).

    ``add`` stores a turn; ``assess`` is a pure function of the stored turns, the clock value
    given and the config, so the in-request path and the batch path give the same answer for
    the same turns."""

    def __init__(self) -> None:
        self._sessions: OrderedDict[tuple[str, str], deque[Turn]] = OrderedDict()
        self._consumers: dict[str, deque[tuple[int, str]]] = {}

    # -- state --------------------------------------------------------------------------------
    def add(self, session_id: str, turn: Turn) -> None:
        key = (turn.agent_id, session_id)
        q = self._sessions.get(key)
        if q is None:
            q = self._sessions[key] = deque(maxlen=MAX_TURNS_PER_SESSION)
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(key)
        q.append(turn)
        if turn.consumer and turn.risk in MONEY_CLASSES:
            cq = self._consumers.get(turn.consumer)
            if cq is None:
                cq = self._consumers[turn.consumer] = deque(maxlen=200)
                while len(self._consumers) > MAX_CONSUMERS:
                    del self._consumers[next(iter(self._consumers))]
            cq.append((turn.ts_ms, turn.agent_id))

    def add_codes(
        self, session_id: str, agent_id: str, event_id: str, codes: Iterable[str]
    ) -> bool:
        """Late finding codes (Tier 0b runs after the decision) join the turn they belong to.
        False when the turn is not stored yet."""
        q = self._sessions.get((agent_id, session_id))
        if q is None:
            return False
        for t in reversed(q):
            if t.event_id == event_id:
                t.codes = tuple(dict.fromkeys((*t.codes, *codes)))
                return True
        return False

    def turns(self, session_id: str, agent_id: str) -> list[Turn]:
        return list(self._sessions.get((agent_id, session_id), ()))

    def sessions(self) -> list[tuple[str, str]]:
        return [(a, s) for (a, s) in self._sessions]

    def forget(self, before_ms: int) -> int:
        """Drop sessions whose last turn is older than ``before_ms``. Returns how many."""
        dead = [k for k, q in self._sessions.items() if not q or q[-1].ts_ms < before_ms]
        for k in dead:
            del self._sessions[k]
        for c in list(self._consumers):
            dq = self._consumers[c]
            while dq and dq[0][0] < before_ms:
                dq.popleft()
            if not dq:
                del self._consumers[c]
        return len(dead)

    # -- assessment ---------------------------------------------------------------------------
    def assess(
        self,
        session_id: str,
        agent_id: str,
        now_ms: int,
        cfg: SessionConfig,
        cap_minor: int | None = None,
    ) -> Assessment | None:
        allturns = self._sessions.get((agent_id, session_id))
        if not allturns:
            return None
        start = now_ms - cfg.window_s * 1000
        win = [t for t in allturns if start <= t.ts_ms <= now_ms]
        if not win:
            return None
        cap = cfg.cap_minor if cfg.cap_minor is not None else cap_minor
        counts: dict[str, int] = {}
        counts["findings"] = sum(
            min(sum(1 for c in t.codes if is_attack_code(c)), CODE_CAP_PER_TURN) for t in win
        )
        # a block by GATE-DETECTOR-FAILED (a detector timed out or crashed) is an outage of
        # ours, not something the conversation did: it never raises the score
        counts["refusals"] = sum(1 for t in win if t.refused and not t.infra)
        counts["expand"] = sum(1 for t in win if t.expand)
        counts["drift"] = self._drift(allturns, win)
        counts["near_dup"] = self._near_dup(win, cfg.dup_bp)
        counts["memory_links"] = self._memory(allturns, win)
        moved = sum(
            t.amount_minor
            for t in win
            if t.risk in MONEY_CLASSES and not t.refused and isinstance(t.amount_minor, int)
        )
        counts["money_minor"] = moved
        timing = self._timing(win)
        cross = self._cross(win, start, now_ms)
        counts["cross_agents"] = cross
        strengths = {name: _clamp(counts[name] * 10000 // SATURATION[name]) for name in SATURATION}
        strengths["money"] = _clamp(moved * 10000 // cap) if cap and cap > 0 else 0
        strengths["timing"] = timing
        strengths["cross_agent"] = _clamp(cross * 10000)
        strengths["memory"] = 10000 if counts["memory_links"] else 0
        counts["split_cues"] = split_cue_count(win)
        strengths["split_cue"] = 10000 if counts["split_cues"] else 0
        hits = [s for s in SIGNALS if strengths[s] >= cfg.hit_bp]
        score = sum(cfg.weights[s] * strengths[s] for s in SIGNALS) // 10000
        money_involved = any(t.risk in ("money", "credit") for t in win)
        solo = any(s in hits for s in cfg.solo_signals)
        # WP41 review: a double signal (split_cue) counts as two hits towards K
        counts["hit_units"] = len(hits) + sum(1 for s in hits if s in cfg.double_signals)
        case_due = counts["hit_units"] >= cfg.k or score >= cfg.case_threshold_bp or solo
        return Assessment(
            session_id=session_id,
            agent_id=agent_id,
            now_ms=now_ms,
            turns=len(win),
            strengths=strengths,
            hits=hits,
            score_bp=score,
            k=cfg.k,
            case_due=case_due,
            pause_due=case_due and cfg.pause_on and score >= cfg.pause_threshold_bp,
            money_involved=money_involved,
            amount_minor=moved,
            cap_minor=cap,
            first_ms=win[0].ts_ms,
            last_ms=win[-1].ts_ms,
            consumer=next((t.consumer for t in win if t.consumer), None),
            counts=counts,
        )

    @staticmethod
    def _drift(allturns: Sequence[Turn], win: Sequence[Turn]) -> int:
        """Markers in the window: rare tools (drift baseline) and steps up in risk class after
        at least DRIFT_MIN_PRIOR read-only turns, judged on the whole kept history."""
        n = prior_read = highest = 0
        for t in allturns:
            r = RISK_RANK.get(t.risk, 0)
            marker = (
                t.rare
                or t.topic
                or (r > highest and (highest > 0 or prior_read >= DRIFT_MIN_PRIOR))
            )
            if marker and t.ts_ms >= win[0].ts_ms:
                n += 1
            if r == 0:
                prior_read += 1
            highest = max(highest, r)
        return n

    @staticmethod
    def _memory(allturns: Sequence[Turn], win: Sequence[Turn]) -> int:
        """Money or credit calls in the window that use an authority fact asserted at least
        MEMORY_MIN_GAP turns earlier (recall phrase, or a shared identifier token)."""
        first = win[0].ts_ms
        turns = list(allturns)
        n = 0
        for j, t in enumerate(turns):
            if t.ts_ms < first or t.risk not in ("money", "credit"):
                continue
            tt = set(t.toks)
            for a in turns[: max(0, j - MEMORY_MIN_GAP + 1)]:
                if a.assert_ and (t.recall or a.standing or (tt and tt & set(a.toks))):
                    n += 1
                    break
        return n

    @staticmethod
    def _near_dup(win: Sequence[Turn], dup_bp: int) -> int:
        n = 0
        for i, t in enumerate(win):
            if not t.sig:
                continue
            for u in win[max(0, i - DUP_LOOKBACK) : i]:
                if u.sig and u.tool == t.tool and similarity_bp(t.sig, u.sig) >= dup_bp:
                    n += 1
                    break
        return n

    @staticmethod
    def _timing(win: Sequence[Turn]) -> int:
        if len(win) < TIMING_MIN_TURNS:
            return 0
        gaps = [win[i].ts_ms - win[i - 1].ts_ms for i in range(1, len(win))]
        recent = gaps[-TIMING_RECENT_GAPS:]
        median = _median(gaps)
        mean_recent = max(sum(recent) // len(recent), 1)
        if median < 1000:  # a session that is always fast has no burst against itself
            return 0
        ratio_x100 = median * 100 // mean_recent
        return _clamp((ratio_x100 - 200) * 10000 // 600)

    def _cross(self, win: Sequence[Turn], start: int, now_ms: int) -> int:
        consumer = next((t.consumer for t in win if t.consumer), None)
        if consumer is None:
            return 0
        agent = win[0].agent_id
        others = {
            a for ts, a in self._consumers.get(consumer, ()) if start <= ts <= now_ms and a != agent
        }
        return len(others)


# --------------------------------------------------------------------------- timeline


def timeline(turns: Sequence[Turn], limit: int = 60) -> list[dict[str, Any]]:
    """Masked timeline: tool, class, outcome, amount, flags, codes. No text exists to show."""
    if not turns:
        return []
    t0 = turns[0].ts_ms
    out = []
    for i, t in enumerate(turns[-limit:], start=max(0, len(turns) - limit)):
        flags = [n for n, on in (("expand", t.expand), ("rare_tool", t.rare)) if on]
        out.append(
            {
                "n": i + 1,
                "t_s": (t.ts_ms - t0) // 1000,
                "event_id": t.event_id,
                "agent_id": t.agent_id,
                "tool": t.tool,
                "risk_class": t.risk,
                "outcome": "denied" if t.refused else "allowed",
                "amount_minor": t.amount_minor,
                "flags": flags,
                "codes": list(t.codes),
            }
        )
    return out


def timeline_text(rows: Sequence[Mapping[str, Any]], limit: int = 25) -> str:
    """Compact one-line-per-turn text of ids and integers for a case summary (ASCII)."""
    lines = []
    for r in list(rows)[-limit:]:
        amt = f" amt={r['amount_minor']}" if r.get("amount_minor") is not None else ""
        fl = f" [{','.join(r['flags'])}]" if r.get("flags") else ""
        cd = f" codes={','.join(r['codes'])}" if r.get("codes") else ""
        lines.append(
            f"{r['n']}. +{r['t_s']}s {r['tool']} ({r['risk_class']}) {r['outcome']}{amt}{fl}{cd}"
        )
    return "\n".join(lines)


def daily_cap_minor(policy: Any, agent_id: str) -> int | None:
    """Daily cap of money moved, from the policy's own aggregate rules (the fact the gate
    enforces): the lowest ``limit`` of a ``sum`` aggregate over at least one day that blocks or
    pauses, in scope for the agent. None when the policy has no such rule."""
    caps = []
    for r in getattr(policy, "rules", []):
        agg = getattr(r, "aggregate", None)
        if agg is None or agg.fn != "sum" or agg.window_s < 86400:
            continue
        if r.action not in ("block", "pause") or not r.in_scope(agent_id):
            continue
        caps.append(int(agg.limit))
    return min(caps) if caps else None


# --------------------------------------------------------------------------- WP28 trace adapter

# Tool and class of the call a conversation turn stands for, by agent (the baseline policy).
REDTEAM_AGENT_TOOL = {
    "payments": ("transfer", "money"),
    "customer_service": ("waive_fee", "money"),
    "credit_prequal": ("decide_prequal", "credit"),
}
REDTEAM_TOOL_CLASS = {
    "transfer": "money",
    "ext_transfer_api": "money",
    "waive_fee": "money",
    "open_dispute": "money",
    "decide_prequal": "credit",
    "fetch_application": "pii_export",
    "add_payee": "pii_export",
}


def from_redteam_trace(
    row: Mapping[str, Any], key: bytes = b"redteam-trace-key"
) -> tuple[str, list[Turn], dict[str, Any]]:
    """One WP28 ``traces.jsonl`` conversation -> (session id, turns, meta).

    The trace format is WP28's (docs/redteam-multiturn.md section 5): per turn the text (long digit
    runs masked), Tier 0b kinds, cue counts, asked and executed calls, ``refused`` and
    ``gate_would_stop`` (rule ids of the SHADOW gate). The adapter feeds the same feature
    extraction the gate uses, so the text is read here and dropped. A turn with an executed call
    becomes a turn of that tool; a refused ask becomes a denied turn of the agent's main tool;
    anything else is a chat turn (read only). ``gate_would_stop`` counts as a refusal, as it would
    in an enforced gate. ``meta`` carries the family, the oracle success and its turn, and the
    language, for the report. Raises ``ValueError`` for a row without turns."""
    from datetime import datetime

    turns_in = row.get("turns")
    if not isinstance(turns_in, list) or not turns_in:
        raise ValueError("trace row has no turns")
    agent = str(row.get("agent") or "payments")
    main_tool, main_class = REDTEAM_AGENT_TOOL.get(agent, ("transfer", "money"))
    sid = f"{row.get('objective_id')}:{row.get('trial')}"
    out: list[Turn] = []
    for t in turns_in:
        executed = [e for e in (t.get("executed") or []) if isinstance(e, Mapping)]
        stops = list(t.get("gate_would_stop") or [])
        refused = bool(t.get("refused")) or bool(stops)
        if executed:
            tool = str(executed[0].get("tool") or main_tool)
            risk = REDTEAM_TOOL_CLASS.get(tool, "read_only")
            amount = sum(
                int(e["amount_minor"]) for e in executed if isinstance(e.get("amount_minor"), int)
            )
        elif refused and int(t.get("asked_calls") or 0) > 0:
            tool, risk, amount = main_tool, main_class, 0
        else:
            tool, risk, amount = "chat", "read_only", 0
        text = t.get("text") if isinstance(t.get("text"), str) else None
        feats = extract(text, None, risk=risk, key=key)
        codes = tuple(
            f"t:{k}" for k in [*(t.get("tier0b") or []), *(t.get("planted_tier0b") or [])]
        )
        cues = t.get("cues") or {}
        ts = datetime.fromisoformat(str(t["ts"]).replace("Z", "+00:00"))
        out.append(
            Turn(
                event_id=f"{sid}:{t.get('i')}",
                ts_ms=int(ts.timestamp() * 1000),
                agent_id=agent,
                tool=tool,
                risk=risk,
                refused=refused,
                amount_minor=amount if executed else None,
                codes=codes,
                expand=feats.expand or bool(cues.get("expand")),
                sig=feats.sig,
                assert_=feats.assert_,
                recall=feats.recall,
                toks=feats.toks,
                topic=feats.topic,
                standing=feats.standing,
                cues=feats.cues,
                rule_id=stops[0] if stops else None,
            )
        )
    meta = {
        "family": str(row.get("family") or ""),
        "lang": str(row.get("lang") or ""),
        "benign": bool(row.get("benign")),
        "success": bool(row.get("success")),
        "success_turn": row.get("success_turn"),
        "agent": agent,
        "split": str(row.get("split") or ""),
    }
    return sid, out, meta


def first_trip(
    sid: str, turns: Sequence[Turn], cfg: SessionConfig, cap: int | None
) -> tuple[int | None, Assessment | None]:
    """Replay turns one by one, as the in-request path sees them. Returns the 1-based turn at
    which the case rule first fires (None if never) and that assessment."""
    eng = SessionEngine()
    for i, t in enumerate(turns, start=1):
        eng.add(sid, t)
        a = eng.assess(sid, t.agent_id, t.ts_ms, cfg, cap)
        if a is not None and a.case_due:
            return i, a
    return None, None


__all__ = [
    "Assessment",
    "DailyConfig",
    "EXPAND_PHRASES",
    "Features",
    "SATURATION",
    "SessionConfig",
    "SessionEngine",
    "Turn",
    "daily_cap_minor",
    "decode_sig",
    "first_trip",
    "from_redteam_trace",
    "encode_sig",
    "extract",
    "extract_flags",
    "with_args",
    "fold",
    "has_expand",
    "hash_consumer",
    "identify",
    "lookback_s",
    "resolve_config",
    "similarity_bp",
    "timeline",
    "timeline_text",
]
