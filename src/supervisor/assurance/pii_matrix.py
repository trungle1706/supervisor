"""Canary matrix for the ``pii_canary`` pack (WP24b): every entity type, in every surface form,
on every surface where PII can sit.

* Entity types: PERSON, CCCD, CMND, PHONE, EMAIL, TAX_CODE, BANK_ACCOUNT, CARD_NUMBER, ADDRESS.
* Forms: plain, upper-case, no diacritics, upper-case no diacritics, lower-case no diacritics,
  telex-typed names, grouped / dotted / spaced / international numbers, glued to a label.
* Surfaces: ``prompt`` (a sentence), ``context`` (a retrieved passage), ``tool_args`` (a JSON
  tool-call argument object) and ``tool_result`` (a JSON tool result row).

All values are synthetic and seeded. ``leaks`` decides whether a planted value survives in a
text after masking: diacritics, case, digit separators and whitespace are ignored, so a half
masked value ("<PERSON:ab12> Thử") still counts as a leak.

The matrix covers the contexts the masker claims to support. A name written in a bare lower-case
sentence with an out-of-lexicon surname is a documented gap (BACKLOG), so it is not planted
here: the pack must be able to pass.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from supervisor.data import wordlists as W
from supervisor.pii_eval.generate import Gen, fold, telex_word

__all__ = ["Canary", "build_matrix", "leaks", "SURFACES"]

SURFACES = ("prompt", "context", "tool_args", "tool_result")
SEED = 20261021
_TOKEN = re.compile(r"<[A-Z_]{2,20}:[0-9a-f]{4,64}>")


@dataclass(frozen=True)
class Canary:
    id: str
    entity: str
    form: str
    surface: str
    text: str
    secrets: tuple[str, ...]
    keep: tuple[str, ...] = field(default=())


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", fold(text).lower())


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def leaks(masked: str, secret: str) -> bool:
    """True if ``secret`` still appears in ``masked`` (mask tokens removed first)."""
    rest = _TOKEN.sub(" ", masked)
    if "@" in secret:
        return secret.lower() in rest.lower()
    if re.fullmatch(r"[\d \-.+]+", secret):
        d = _digits(secret)
        return len(d) >= 6 and d in _digits(rest)
    return _norm(secret) in _norm(rest)


def _wrap(surface: str, entity: str, value: str) -> str:
    """Embed ``value`` in a realistic carrier for the surface."""
    label = {
        "PERSON": "Khách hàng",
        "CCCD": "CCCD",
        "CMND": "CMND",
        "PHONE": "SĐT",
        "EMAIL": "Email",
        "TAX_CODE": "MST",
        "BANK_ACCOUNT": "STK",
        "CARD_NUMBER": "Thẻ",
        "ADDRESS": "Địa chỉ",
    }[entity]
    key = {
        "PERSON": "full_name",
        "CCCD": "cccd",
        "CMND": "cmnd",
        "PHONE": "phone",
        "EMAIL": "email",
        "TAX_CODE": "tax_code",
        "BANK_ACCOUNT": "to_account",
        "CARD_NUMBER": "card",
        "ADDRESS": "address",
    }[entity]
    if entity == "PERSON" and surface == "context":
        return f"Hợp đồng được ký bởi {value} vào ngày hôm qua tại quầy."  # no title, no label
    if entity == "PERSON" and surface == "tool_result":
        return f"| 1 | {value} | 1.500.000.000 VND |"  # a bare table cell
    if surface == "prompt":
        return f"Xin hãy cập nhật hồ sơ. {label}: {value}. Cảm ơn."
    if surface == "context":
        return f"Hồ sơ khách (nội bộ): {label} {value}; trạng thái hoạt động."
    if surface == "tool_args":
        return json.dumps(
            {"customer_id": "C-1", key: value, "note": "cap nhat"}, ensure_ascii=False
        )
    return json.dumps(
        {"rows": [{"id": 1, key: value, "limit": "1.500.000.000 VND"}]}, ensure_ascii=False
    )


def _values(entity: str, g: Gen) -> list[tuple[str, str, tuple[str, ...]]]:
    """[(form, surface text, secrets)] for one entity."""
    out: list[tuple[str, str, tuple[str, ...]]] = []
    r = g.rng
    if entity == "PERSON":
        parts = g.name_parts()
        # use dev pools only for names from the lexicon; the label makes the rest reliable
        full = " ".join(parts)
        variants = {
            "plain": full,
            "upper": full.upper(),
            "no_diacritics": fold(full),
            "upper_no_diacritics": fold(full).upper(),
            "lower_no_diacritics": fold(full).lower(),
            "telex": " ".join(telex_word(p).capitalize() for p in parts),
        }
        for form, v in variants.items():
            out.append((form, v, (v, fold(parts[-1]))))
    elif entity == "ADDRESS":
        no = r.randrange(1, 300)
        street = r.choice(W.STREETS)
        full = f"Số {no} {street}, Phường Bến Nghé, Quận 1, TP.HCM"
        short = f"{no} {street}, P.7, Q.3, TPHCM"
        for form, v in {
            "plain": full,
            "upper": full.upper(),
            "no_diacritics": fold(full),
            "upper_no_diacritics": fold(full).upper(),
            "abbreviated": short,
        }.items():
            out.append((form, v, (v.split(",")[0].split(" ", 1)[1],)))
    elif entity == "CCCD":
        c = g.cccd()
        for form, v in {
            "plain": c,
            "spaced": " ".join(c[i : i + 3] for i in range(0, 12, 3)),
            "dashed": "-".join(c[i : i + 4] for i in range(0, 12, 4)),
            "dotted": ".".join(c[i : i + 3] for i in range(0, 12, 3)),
        }.items():
            out.append((form, v, (v,)))
    elif entity == "CMND":
        c = f"{r.choice('0123')}{g.digits(8)}"
        out.append(("plain", c, (c,)))
        out.append(("spaced", f"{c[:3]} {c[3:6]} {c[6:]}", (c,)))
    elif entity == "PHONE":
        pre = r.choice(W.MOBILE_PREFIXES)
        rest = g.digits(7)
        for form, v in {
            "plain": f"{pre}{rest}",
            "dotted": f"{pre}.{rest[:3]}.{rest[3:]}",
            "spaced": f"{pre} {rest[:3]} {rest[3:]}",
            "intl": f"+84 {pre[1:]} {rest[:3]} {rest[3:]}",
            "intl_plain": f"+84{pre[1:]}{rest}",
            "country_digits": f"84{pre[1:]}{rest}",
        }.items():
            out.append((form, v, (f"{pre}{rest}",)))
    elif entity == "EMAIL":
        parts = g.name_parts()
        local = "".join(fold(p).lower() for p in parts)
        e = f"{local}@example.invalid"
        out.append(("plain", e, (e,)))
        out.append(("upper", e.upper(), (e,)))
        local2 = f"{fold(parts[-1]).lower()}.{fold(parts[0]).lower()}{r.randrange(10, 99)}"
        e2 = f"{local2}@mail.example.invalid"
        out.append(("dotted_name", e2, (e2,)))
    elif entity == "TAX_CODE":
        t = g.tax().split("-")[0]
        out.append(("plain", t, (t,)))
        out.append(("branch", f"{g.tax().split('-')[0]}-{g.digits(3)}", ()))
        out[-1] = ("branch", out[-1][1], (out[-1][1].split("-")[0],))
    elif entity == "BANK_ACCOUNT":
        a = str(r.randrange(1, 10)) + g.digits(12)
        out.append(("plain", a, (a,)))
        out.append(("grouped", " ".join(a[i : i + 4] for i in range(0, 12, 4)) + a[12:], (a,)))
    else:  # CARD_NUMBER
        c = g.card().replace(" ", "")
        out.append(("plain", c, (c,)))
        out.append(("grouped", " ".join(c[i : i + 4] for i in range(0, 16, 4)), (c,)))
    return out


ENTITIES = (
    "PERSON",
    "CCCD",
    "CMND",
    "PHONE",
    "EMAIL",
    "TAX_CODE",
    "BANK_ACCOUNT",
    "CARD_NUMBER",
    "ADDRESS",
)


def build_matrix(seed: int = SEED, rounds: int = 2) -> list[Canary]:
    """The canary list: ``rounds`` independent draws of every entity x form x surface."""
    items: list[Canary] = []
    for rd in range(rounds):
        g = Gen(seed + rd, held=False)
        for entity in ENTITIES:
            for form, value, secrets in _values(entity, g):
                for surface in SURFACES:
                    text = _wrap(surface, entity, value)
                    items.append(
                        Canary(
                            id=f"M{rd}-{entity}-{form}-{surface}",
                            entity=entity,
                            form=form,
                            surface=surface,
                            text=text,
                            secrets=secrets,
                            keep=("1.500.000.000 VND",) if surface == "tool_result" else (),
                        )
                    )
    return items


def run_masker(
    mask: Callable[[str], str], items: list[Canary]
) -> tuple[int, int, dict[str, int], list[str]]:
    """(leaked values, changed keep strings, leaks by ``entity/form/surface``, leaked ids)."""
    leaked = 0
    false_mask = 0
    by: dict[str, int] = {}
    ids: list[str] = []
    for c in items:
        out = mask(c.text)
        n = sum(1 for s in c.secrets if leaks(out, s))
        if n:
            leaked += n
            by[f"{c.entity}/{c.form}/{c.surface}"] = (
                by.get(f"{c.entity}/{c.form}/{c.surface}", 0) + n
            )
            ids.append(c.id)
        false_mask += sum(1 for k in c.keep if k not in out)
    return leaked, false_mask, dict(sorted(by.items())), ids
