# ruff: noqa: S311, E501  (a seeded generator for test data, not for security; data lines are long)
"""Golden set of the ``dlp_vn`` secrets group and custom rules (WP-D2).

Unlike the other golden sets this one is NOT a committed file: every planted secret is built at
run time from seeded random characters and split literals, so no file in the repository holds
anything that looks like a credential (``tests/test_no_secrets.py`` stays green and a scanner
that reads the repository finds nothing). The build is deterministic: the same seed gives the
same items, so the harness numbers and the baseline are stable.

Suites (the harness slug is ``dlp_vn_secrets``; every item runs against the ``dlp_vn`` detector
with the item's own ``settings``):

* ``dev`` and ``heldout``: one positive per secret kind with different wrappers (a flat argument,
  a nested list, a tool result, the output side), custom keyword and regex rules, and benign
  look-alikes. The two splits use different wrappers, values and rules.
* ``adversarial``: written by hand outside the templates: base64 (the detector decodes it), the
  secret split over two fields, spaced, with a zero-width character, reversed, percent encoded,
  and case changes of a keyword. Most of the evasions are expected misses; the row reports how
  many (no tuning on it).

Item shape is the one of ``golden.py`` plus ``settings`` (the dlp_vn settings of the item).
"""

from __future__ import annotations

import base64
import random
import string
from collections.abc import Callable
from typing import Any

from supervisor.detectors.dlp_extras import SECRET_KINDS

SEED = 20261022
SUITE = "dlp_vn_secrets"
LICENCE = "own (synthetic, MIT)"
META_EXPORT = {"tool_name": "add_payee", "risk_class": "pii_export", "agent_id": "payments"}
META_READ = {"tool_name": "get_balance", "risk_class": "read_only", "agent_id": "payments"}
ALNUM = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
LOWER_DIGITS = string.ascii_lowercase + string.digits
URLSAFE = ALNUM + "_-"
B64 = ALNUM + "+/"

SECRETS_ON = {"enabled": True, "action": "report"}


def _pick(r: random.Random, alphabet: str, n: int) -> str:
    return "".join(r.choice(alphabet) for _ in range(n))


def _pw(r: random.Random) -> str:
    """A password with a digit (the unquoted pattern needs one) and no quote or space."""
    return _pick(r, string.ascii_letters, 6) + _pick(r, string.digits, 3) + _pick(r, "-_!", 1)


# kind -> builder(r) -> (text containing the secret, the secret value that must never leak)
Builder = Callable[[random.Random], tuple[str, str]]


def _plain(make: Callable[[random.Random], str]) -> Builder:
    def build(r: random.Random) -> tuple[str, str]:
        v = make(r)
        return v, v

    return build


def _wrapped(prefix: str, make: Callable[[random.Random], str], suffix: str = "") -> Builder:
    def build(r: random.Random) -> tuple[str, str]:
        v = make(r)
        return f"{prefix}{v}{suffix}", v

    return build


def _pem(r: random.Random) -> tuple[str, str]:
    head, tail = (
        "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
        "-----END " + "RSA PRIVATE" + " KEY-----",
    )
    body = "\n".join(_pick(r, B64, 64) for _ in range(3))
    return f"{head}\n{body}\n{tail}", body.split("\n")[0]


def _jwt(r: random.Random) -> str:
    return (
        "ey"
        + "J"
        + _pick(r, URLSAFE, 16)
        + ".ey"
        + "J"
        + _pick(r, URLSAFE, 20)
        + "."
        + _pick(r, URLSAFE, 24)
    )


def _basic(r: random.Random) -> tuple[str, str]:
    v = base64.b64encode(f"svc{_pick(r, LOWER_DIGITS, 4)}:{_pw(r)}".encode()).decode()
    return f"Authorization: Basic {v}", v


def _env(r: random.Random) -> tuple[str, str]:
    v = _pw(r) + _pick(r, ALNUM, 4)
    return f"export DB_PASSWORD={v}", v


def _url(r: random.Random) -> tuple[str, str]:
    v = _pw(r)
    return f"postgresql://admin:{v}@db.example.invalid:5432/app", v


def _quoted(r: random.Random) -> tuple[str, str]:
    v = _pw(r) + _pick(r, ALNUM, 3)
    return f"password = '{v}'", v


def _unquoted(r: random.Random) -> tuple[str, str]:
    v = _pw(r)
    return f"db:\n  password: {v}", v


def _private_key_id(r: random.Random) -> tuple[str, str]:
    v = _pick(r, "0123456789abcdef", 40)
    return f'"private_key_id": "{v}"', v


BUILDERS: dict[str, Builder] = {
    "pem_private_key": _pem,
    "databricks_token": _wrapped("", lambda r: "da" + "pi" + _pick(r, "0123456789abcdef", 32)),
    "databricks_oauth_secret": _wrapped(
        "", lambda r: "do" + "se" + _pick(r, "0123456789abcdef", 32)
    ),
    "aws_access_key": _plain(lambda r: "AK" + "IA" + _pick(r, UPPER_DIGITS, 16)),
    "aws_secret_key": _wrapped("aws_secret_access_key = ", lambda r: _pick(r, ALNUM + "/+", 40)),
    "azure_storage_key": _wrapped(
        "DefaultEndpointsProtocol=https;AccountKey=", lambda r: _pick(r, B64, 86) + "=="
    ),
    "azure_sas_signature": _wrapped(
        "https://acct.blob.example.invalid/c?sig=", lambda r: _pick(r, ALNUM, 43) + "%3D"
    ),
    "azure_client_secret": _plain(lambda r: _pick(r, ALNUM, 3) + "8Q" + "~" + _pick(r, ALNUM, 32)),
    "gcp_api_key": _plain(lambda r: "AI" + "za" + _pick(r, URLSAFE, 35)),
    "gcp_private_key_id": _private_key_id,
    "github_token": _plain(lambda r: "gh" + "p_" + _pick(r, ALNUM, 36)),
    "gitlab_token": _plain(lambda r: "gl" + "pat-" + _pick(r, URLSAFE, 22)),
    "huggingface_token": _plain(lambda r: "h" + "f_" + _pick(r, ALNUM, 34)),
    "stripe_key": _plain(lambda r: "s" + "k_live_" + _pick(r, ALNUM, 24)),
    "sendgrid_key": _plain(
        lambda r: "S" + "G." + _pick(r, URLSAFE, 22) + "." + _pick(r, URLSAFE, 43)
    ),
    "npm_token": _plain(lambda r: "np" + "m_" + _pick(r, ALNUM, 36)),
    "vault_token": _plain(lambda r: "h" + "vs." + _pick(r, URLSAFE, 26)),
    "slack_token": _plain(
        lambda r: "xo" + "xb-" + _pick(r, string.digits, 11) + "-" + _pick(r, ALNUM, 24)
    ),
    "anthropic_api_key": _plain(lambda r: "s" + "k-ant-" + "api03-" + _pick(r, URLSAFE, 40)),
    "openai_api_key": _plain(lambda r: "s" + "k-proj-" + _pick(r, URLSAFE, 40)),
    "jwt": _plain(_jwt),
    "gcp_oauth_token": _plain(lambda r: "ya" + "29." + _pick(r, URLSAFE, 30)),
    "bearer_token": _wrapped("Authorization: Bearer ", lambda r: _pick(r, ALNUM, 32)),
    "basic_auth": _basic,
    "url_password": _url,
    "assigned_secret": _quoted,
    "assigned_secret_env": _env,
    "assigned_secret_unquoted": _unquoted,
}

# Expected finding code per kind (the LLM key pattern reports as one of two vendors).
EXPECT = {k: f"secret.{k}" for k in BUILDERS}
# A bare letters-and-digits value after an env or JSON name is caught by the password field too.
assert set(BUILDERS) | {"password_field"} == set(SECRET_KINDS), "every secret kind has a builder"


def _shape(split: str, i: int, text: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """(payload, meta, direction) of the i-th item. Dev: arguments and a tool result; held-out:
    a nested list, the output side and a read-only tool."""
    if split == "dev":
        if i % 3 == 0:
            return {"args": {"note": f"please use this:\n{text}"}}, META_EXPORT, "input"
        if i % 3 == 1:
            return {"args": {"id": "C-1"}, "tool_results": [{"body": text}]}, META_EXPORT, "input"
        return {"args": {"config": {"text": text}}}, META_READ, "input"
    if i % 3 == 0:
        return {"args": {"items": ["ok", f"fyi: {text}"]}}, META_READ, "input"
    if i % 3 == 1:
        return {"output": f"Here is the value you asked for: {text}"}, META_EXPORT, "output"
    return {"args": {"payload": {"deep": [{"v": text}]}}}, META_EXPORT, "input"


def _item(
    n: int,
    split: str,
    payload: dict[str, Any],
    meta: dict[str, Any],
    direction: str,
    label: int,
    *,
    expect: list[str],
    sensitive: list[str],
    category: str,
    settings: dict[str, Any],
    lang: str = "en",
    tags: list[str] | None = None,
    labeller: str = "synthetic",
) -> dict[str, Any]:
    return {
        "id": f"D-{SUITE}-{split[:3].upper()}{n:04d}",
        "split": split,
        "detector": "dlp_vn",
        "suite": SUITE,
        "direction": direction,
        "payload": payload,
        "meta": dict(meta),
        "label": label,
        "expect_codes": sorted(expect),
        "sensitive": sensitive,
        "category": category,
        "lang": lang,
        "source": f"built at run time, seed {SEED}",
        "licence": LICENCE,
        "labeller": labeller,
        "tags": tags or [],
        "settings": settings,
    }


# ---------------------------------------------------------------------------- dev and heldout

NEG_DEV = [
    ("benign-prefix", "The AK" + "IA prefix is described in the runbook, no key here"),
    ("benign-short-key", "set the flag sk-short and retry"),
    ("benign-password-word", "Please reset your password using the link we sent"),
    ("benign-code", "api_key = settings.llm_api_key  # read from the environment"),
    ("benign-type", "token: str"),
    ("benign-uuid", "request 3f2b8c1e-9a47-4d1e-8c55-0b7a1d2e3f44 was queued"),
    ("benign-placeholder", "api_key: FILL-ME-llm-key"),
    ("benign-mask", "password = '********'"),
    ("benign-vi", "Khách quên mật khẩu và cần được hướng dẫn đặt lại"),
    ("benign-short-bearer", "Authorization: Bearer abc"),
    ("benign-two-part-jwt", "eyJhbGciOiJI.eyJzdWIiOiJ4"),
    (
        "benign-long-word",
        "the identifier InternationalizationConfigurationManagerFactory is public",
    ),
]
NEG_HELD = [
    ("benign-prefix", "Tokens that start with gh" + "p_ are GitHub tokens, per the docs"),
    ("benign-short-key", "the s" + "k- prefix marks provider keys"),
    ("benign-password-word", "Mật khẩu phải có ít nhất tám ký tự"),
    ("benign-code", "client_secret = os.environ['CLIENT_SECRET']"),
    ("benign-type", "password: Optional[str] = None"),
    ("benign-sha", "commit 9fceb02d0ae598e95dc970b74767f19372d61af8 fixed the typo"),
    ("benign-placeholder", "DB_PASSWORD=FILL-ME-password"),
    ("benign-x", "secret = 'xxxxxxxx'"),
    ("benign-doc", "Store the key in a vault and never paste a bearer token in chat"),
    ("benign-hex", "color #ff8800 and size 14px"),
    ("benign-path", "https://example.invalid/reset/password"),
    (
        "benign-b64-text",
        base64.b64encode(b"Dear customer, your statement is ready for download.").decode(),
    ),
]

VI_KEYS_DEV = ["mat_khau", "matkhau"]
VI_KEYS_HELD = ["m\u1eadt_kh\u1ea9u", "MatKhau", "pw", "mk"]
META_KEYS_DEV = [
    ("passwordPolicy", "Hunter2Pass9x"),
    ("password_changed_at", "2026-10-22T10:00:00Z"),
    ("apiKeyName", "production-key-01"),
    ("privateKeyType", "rsa2048x"),
]
META_KEYS_HELD = [
    ("secrets_manager", "vault-prod-01"),
    ("client_secret_id", "b3f1c2d4e5f6"),
    ("pwd_reset_url", "https://example.invalid/reset/abc"),
    ("passphrase_required", "yes please"),
]

RULES_DEV: list[dict[str, Any]] = [
    {"id": "proj", "kind": "regex", "pattern": "PRJ-[0-9]{4}-[A-Z]{2}"},
    {"id": "conf", "kind": "keyword", "pattern": "CONFIDENTIAL"},
]
RULES_HELD: list[dict[str, Any]] = [
    {"id": "acct", "kind": "regex", "pattern": "INT-ACC-[0-9]{8}"},
    {"id": "tag", "kind": "keyword", "pattern": "project-nightjar", "mask_token": "[REDACTED]"},
    {"id": "emp", "kind": "regex", "pattern": "EMP[0-9]{5}", "preserve_length": True},
]


def _custom_cases(split: str, r: random.Random) -> list[tuple[str, str, list[str], list[str]]]:
    """(category, text, expected codes, values that must not leak); label 1 when codes given."""
    if split == "dev":
        a, b = f"PRJ-{r.randint(1000, 9999)}-QA", f"PRJ-{r.randint(1000, 9999)}-ZX"
        return [
            ("custom-regex", f"see ticket {a} for details", ["custom.proj"], [a]),
            ("custom-regex", f"{a} and {b} are both open", ["custom.proj"], [a, b]),
            (
                "custom-keyword",
                "this memo is CONFIDENTIAL until Friday",
                ["custom.conf"],
                ["CONFIDENTIAL"],
            ),
            (
                "custom-both",
                f"CONFIDENTIAL: {a}",
                ["custom.conf", "custom.proj"],
                [a, "CONFIDENTIAL"],
            ),
            ("custom-near-miss", "ticket PRJ-12-QA is short", [], []),
            ("custom-near-miss", "a confidential note (lower case)", [], []),
            ("custom-near-miss", "PRJ-1234-q is not a project code", [], []),
            ("custom-benign", "nothing special in this note", [], []),
        ]
    a, k, e = (
        f"INT-ACC-{r.randint(10**7, 10**8 - 1)}",
        "project-nightjar",
        f"EMP{r.randint(10000, 99999)}",
    )
    return [
        ("custom-regex", f"credit {a} today", ["custom.acct"], [a]),
        ("custom-keyword-token", f"codename {k} is on hold", ["custom.tag"], [k]),
        ("custom-preserve-length", f"employee {e} asked", ["custom.emp"], [e]),
        ("custom-both", f"{k} touches {a}", ["custom.tag", "custom.acct"], [k, a]),
        ("custom-near-miss", "INT-ACC-1234 is too short", [], []),
        ("custom-near-miss", "project nightjar (two words)", [], []),
        ("custom-near-miss", "EMP12 is not an employee id", [], []),
        ("custom-benign", "nothing special in this note either", [], []),
    ]


def _split(split: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    n = 0
    settings = {"secrets": dict(SECRETS_ON)}
    for i, kind in enumerate(BUILDERS):
        r = random.Random(f"{SEED}:{split}:{kind}")
        text, value = BUILDERS[kind](r)
        payload, meta, direction = _shape(split, i, text)
        n += 1
        items.append(
            _item(
                n,
                split,
                payload,
                meta,
                direction,
                1,
                expect=[EXPECT[kind]],
                sensitive=[value],
                category=kind,
                settings=settings,
            )
        )
    # a password under a JSON key (the password field)
    r = random.Random(f"{SEED}:{split}:password_field")
    pw = _pw(r) + _pick(r, ALNUM, 3)
    n += 1
    key = "password" if split == "dev" else "client_secret"
    items.append(
        _item(
            n,
            split,
            {"args": {"user": "svc", key: pw}},
            META_EXPORT,
            "input",
            1,
            expect=["secret.password_field"],
            sensitive=[pw],
            category="password_field",
            settings=settings,
        )
    )
    # Vietnamese and short names of a password field (positives)
    for j, vkey in enumerate(VI_KEYS_DEV if split == "dev" else VI_KEYS_HELD):
        r = random.Random(f"{SEED}:{split}:vi:{j}")
        vpw = _pw(r) + _pick(r, ALNUM, 3)
        n += 1
        items.append(
            _item(
                n,
                split,
                {"args": {"user": "svc", vkey: vpw}},
                META_EXPORT,
                "input",
                1,
                expect=["secret.password_field"],
                sensitive=[vpw],
                category="password_field_vi",
                settings=settings,
                lang="vi",
            )
        )
    # metadata names that merely contain a password word (benign)
    for mkey, mval in META_KEYS_DEV if split == "dev" else META_KEYS_HELD:
        n += 1
        items.append(
            _item(
                n,
                split,
                {"args": {mkey: mval}},
                META_EXPORT,
                "input",
                0,
                expect=[],
                sensitive=[],
                category="benign-metadata-name",
                settings=settings,
            )
        )
    for cat, text in NEG_DEV if split == "dev" else NEG_HELD:
        payload, meta, direction = _shape(split, n, text)
        n += 1
        items.append(
            _item(
                n,
                split,
                payload,
                meta,
                direction,
                0,
                expect=[],
                sensitive=[],
                category=cat,
                settings=settings,
            )
        )
    rules = RULES_DEV if split == "dev" else RULES_HELD
    csettings = {"custom_rules": rules}
    r = random.Random(f"{SEED}:{split}:custom")
    for cat, text, codes, sens in _custom_cases(split, r):
        payload, meta, direction = _shape(split, n, text)
        n += 1
        items.append(
            _item(
                n,
                split,
                payload,
                meta,
                direction,
                1 if codes else 0,
                expect=codes,
                sensitive=sens,
                category=cat,
                settings=csettings,
            )
        )
    return items


# ---------------------------------------------------------------------------- adversarial


def _adversarial() -> list[dict[str, Any]]:
    r = random.Random(f"{SEED}:adversarial")
    out: list[dict[str, Any]] = []
    n = 0
    settings = {"secrets": dict(SECRETS_ON)}

    def add(
        payload: dict[str, Any],
        label: int,
        category: str,
        *,
        expect: list[str] | None = None,
        sensitive: list[str] | None = None,
        settings_: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        nonlocal n
        n += 1
        out.append(
            _item(
                n,
                "adversarial",
                payload,
                meta or META_EXPORT,
                "output" if "output" in payload else "input",
                label,
                expect=expect or [],
                sensitive=sensitive or [],
                category=category,
                settings=settings_ or settings,
                tags=["probe"],
                labeller="expert rubric",
            )
        )

    aws = "AK" + "IA" + _pick(r, UPPER_DIGITS, 16)
    gh = "gh" + "p_" + _pick(r, ALNUM, 36)
    stripe = "s" + "k_live_" + _pick(r, ALNUM, 24)
    hf = "h" + "f_" + _pick(r, ALNUM, 34)
    jwt = _jwt(r)
    oa = "s" + "k-proj-" + _pick(r, URLSAFE, 40)
    # base64: the detector decodes a run of 24 or more characters and looks inside
    for kind, tok in (
        ("aws_access_key", aws),
        ("github_token", gh),
        ("stripe_key", stripe),
        ("huggingface_token", hf),
        ("jwt", jwt),
        ("openai_api_key", oa),
    ):
        enc = base64.b64encode(f"token={tok}".encode()).decode()
        add({"args": {"blob": enc}}, 1, "base64", expect=[f"secret.{kind}"], sensitive=[tok, enc])
    enc = base64.urlsafe_b64encode(f"x:{aws}:y".encode()).decode()
    add(
        {"args": {"blob": f"data={enc}"}},
        1,
        "base64-urlsafe",
        expect=["secret.aws_access_key"],
        sensitive=[aws],
    )
    # split over two fields (not detectable by a per-field scan)
    add({"args": {"a": aws[:10], "b": aws[10:]}}, 1, "split-across-fields", sensitive=[aws])
    add({"args": {"a": gh[:20], "b": gh[20:]}}, 1, "split-across-fields", sensitive=[gh])
    add(
        {"args": {"parts": [stripe[:12], stripe[12:]]}},
        1,
        "split-across-fields",
        sensitive=[stripe],
    )
    # spacing, zero width, reversed, percent encoded
    add({"args": {"n": " ".join(aws)}}, 1, "spaced-letters", sensitive=[aws])
    add({"args": {"n": aws[:8] + "\u200b" + aws[8:]}}, 1, "zero-width", sensitive=[aws])
    add({"args": {"n": gh[::-1]}}, 1, "reversed-text", sensitive=[gh])
    add(
        {"args": {"n": "".join(f"%{ord(c):02X}" for c in hf)}}, 1, "percent-encoded", sensitive=[hf]
    )
    add({"args": {"n": hf[:6] + "-" + hf[6:]}}, 1, "hyphen-inserted", sensitive=[hf])
    # a secret in a field whose name is not a password name, wrapped in prose (should still hit)
    add(
        {"args": {"n": f"the key is {aws}, thanks"}},
        1,
        "in-prose",
        expect=["secret.aws_access_key"],
        sensitive=[aws],
    )
    add(
        {"args": {"n": f'{{"auth": "Bearer {_pick(r, ALNUM, 40)}"}}'}},
        1,
        "json-in-string",
        expect=["secret.bearer_token"],
    )
    add(
        {"output": f"use {gh} now"},
        1,
        "output-side",
        expect=["secret.github_token"],
        sensitive=[gh],
        meta=META_EXPORT,
    )
    # benign look-alikes
    add(
        {
            "args": {
                "n": base64.b64encode(b"Hello, this is a perfectly ordinary sentence.").decode()
            }
        },
        0,
        "benign-base64",
    )
    add({"args": {"n": "0123456789abcdef0123456789abcdef0123456789abcdef"}}, 0, "benign-hex-run")
    add({"args": {"n": "see the s" + "k-" + " prefix in the vendor guide"}}, 0, "benign-prefix")
    add({"args": {"n": "AK" + "IA is the prefix of AWS ids"}}, 0, "benign-prefix")
    add({"args": {"password": "true"}}, 0, "benign-flag")
    add(
        {"args": {"password_policy": "at least eight characters and one digit"}}, 0, "benign-policy"
    )
    add({"args": {"password": "${DB_PASSWORD}"}}, 0, "benign-template")
    # custom rules
    cs = {
        "custom_rules": [
            {"id": "conf", "kind": "keyword", "pattern": "CONFIDENTIAL"},
            {"id": "proj", "kind": "regex", "pattern": "PRJ-[0-9]{4}-[A-Z]{2}"},
        ]
    }
    add(
        {"args": {"n": "this is CONFIDENTIAL"}},
        1,
        "custom-exact",
        expect=["custom.conf"],
        sensitive=["CONFIDENTIAL"],
        settings_=cs,
    )
    add(
        {"args": {"n": "this is confidential"}},
        1,
        "custom-case-change",
        sensitive=["confidential"],
        settings_=cs,
    )
    add(
        {"args": {"n": "this is CONFI\u200bDENTIAL"}},
        1,
        "custom-zero-width",
        sensitive=["CONFI\u200bDENTIAL"],
        settings_=cs,
    )
    add(
        {"args": {"n": "PRJ-1234-" + "QA"}},
        1,
        "custom-exact",
        expect=["custom.proj"],
        sensitive=["PRJ-1234-QA"],
        settings_=cs,
    )
    add(
        {"args": {"a": "PRJ-12", "b": "34-QA"}},
        1,
        "custom-split-across-fields",
        sensitive=["PRJ-12", "34-QA"],
        settings_=cs,
    )
    add(
        {"args": {"n": base64.b64encode(b"CONFIDENTIAL").decode()}},
        1,
        "custom-base64",
        sensitive=["CONFIDENTIAL"],
        settings_=cs,
    )
    add({"args": {"n": "PRJ-12 34-QA is not one code"}}, 0, "custom-benign-lookalike", settings_=cs)
    return out


def load(split: str | None = None) -> list[dict[str, Any]]:
    """Items of the suite (built now; deterministic). ``split``: dev | heldout | adversarial."""
    out: list[dict[str, Any]] = []
    for sp in ("dev", "heldout"):
        if split in (None, sp):
            out += _split(sp)
    if split in (None, "adversarial"):
        out += _adversarial()
    return out
