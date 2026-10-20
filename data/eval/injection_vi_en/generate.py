"""Generate the golden set of the injection classifier (WP25). Seeded: same seed, same bytes.

    uv run python data/eval/injection_vi_en/generate.py            # rewrite the files here
    uv run python data/eval/injection_vi_en/generate.py --check    # fail if the files are stale

Files written next to this script:

    train.jsonl       fitting data (tools/train_classifier.py reads it)
    dev.jsonl         thresholds are chosen on it
    heldout.jsonl     reported; nobody tunes on it
    evasion.jsonl     heldout positives (and benign twins) re-written with one evasion each
    adversarial.jsonl hand-written probes from adversarial.py (not template based)
    MANIFEST.json     counts, hashes, seed, licence

Splits use disjoint template pools (templates.py). An item has: id, split, detector, direction,
payload, meta, label, expect_codes, sensitive, category, lang, source, licence, labeller, tags,
surface, target, evasion. Licence: "synthetic, this repo". Labeller: "synthetic" (templates), "synthetic, LLM-paraphrased" or
"human (hand-written probe)" (adversarial). Paraphrases of the templates (paraphrases.json, made offline by paraphrase.py with the local LLM)
are labelled "synthetic, LLM-paraphrased".
"""

from __future__ import annotations

import argparse
import base64
import codecs
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import adversarial  # noqa: E402
import templates as T  # noqa: E402

from supervisor.assurance import perturb  # noqa: E402

SEED = 20261022
LICENCE = "synthetic, this repo"
DETECTOR = "injection_classifier"
CODES = {
    "args": "injection.direct_injection",
    "tool_results": "injection.indirect_injection",
    "tool_description": "injection.tool_poisoning",
}
# items per split: (positives, negatives) per surface (= per code)
SIZES = {"train": (800, 800), "dev": (150, 250), "heldout": (150, 300)}
EVADE_TRAIN_RATE = 0.45
EVASION_KINDS = (
    "typo",
    "no_diacritics",
    "telex",
    "code_switch",
    "confusable",
    "zero_width",
    "nfd",
    "fullwidth_digits",
    "leet",
    "dollar_s",
    "base64",
    "rot13",
    "reversed",
    "md_comment",
    "json_in_string",
    "split_fields",
)
EVASION_PER_KIND = 45  # positives per kind in evasion.jsonl (and as many benign twins)
AMOUNTS = ["500.000", "2.000.000", "5.000.000", "15.000.000", "50.000.000", "200.000.000", "1.200.000.000"]
RISK_MIX = (("money", 0.45), ("credit", 0.15), ("read_only", 0.30), ("pii_export", 0.10))
TOOLS = {
    "money": T.TOOLS_MONEY,
    "credit": T.TOOLS_CREDIT,
    "read_only": T.TOOLS_READ,
    "pii_export": T.TOOLS_PII,
}
AGENTS = {"money": "payments", "credit": "credit_prequal", "read_only": "customer_service", "pii_export": "payments"}


# --------------------------------------------------------------------------- slot filling


def load_paraphrases() -> dict[str, Any]:
    path = HERE / "paraphrases.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def expand(name: str, para: dict[str, Any]) -> dict[str, Any]:
    """The pool with the committed LLM paraphrases added to each list of templates.

    ``pool["_m"][section][key][i] = (origin index, is_paraphrase)``; the origin index of a
    paraphrase is the index of the template it was made from (hard negatives are origin >= 2)."""
    pool = {sec: {k: list(v) for k, v in d.items()} for sec, d in T.POOLS[name].items()}
    meta: dict[str, Any] = {sec: {k: [(i, False) for i in range(len(v))] for k, v in d.items()} for sec, d in pool.items()}
    for key, rec in para.get(name, {}).items():
        sec, k, idx = key.split("|")
        for text in rec["paraphrases"]:
            pool[sec][k].append(text)
            meta[sec][k].append((int(idx), True))
    pool["_m"] = meta
    return pool


class Pick:
    """Random choice from an expanded template list, remembering whether it was paraphrased."""

    def __init__(self, pool: dict[str, Any], rng: random.Random) -> None:
        self.pool, self.rng = pool, rng
        self.para = False

    def __call__(self, section: str, key: str) -> tuple[int, str, int]:
        lst = self.pool[section][key]
        i = self.rng.randrange(len(lst))
        origin, is_para = self.pool["_m"][section][key][i]
        self.para = self.para or is_para
        return i, lst[i], origin


class Fill:
    """Fills the slots of one template and remembers the sensitive values it inserted."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.sensitive: list[str] = []

    def __call__(self, template: str) -> str:
        r = self.rng
        out = template
        if "{amt}" in out:
            out = out.replace("{amt}", r.choice(T_AMOUNTS))
        if "{acct}" in out:
            acct = "".join(r.choice("0123456789") for _ in range(r.choice((12, 13, 14))))
            self.sensitive.append(acct)
            out = out.replace("{acct}", acct)
        if "{name}" in out:
            name = r.choice(T.NAMES)
            self.sensitive.append(name)
            out = out.replace("{name}", name)
        if "{ref}" in out:
            out = out.replace("{ref}", f"HD-2026-{r.randrange(10000):04d}")
        if "{date}" in out:
            out = out.replace("{date}", f"{r.randrange(1, 29):02d}/{r.randrange(1, 13):02d}/2026")
        return out


T_AMOUNTS = AMOUNTS


# --------------------------------------------------------------------------- evasions


def _leet(text: str, rng: random.Random) -> str:
    table = {"i": "1", "o": "0", "e": "3", "a": "4", "s": "5", "t": "7"}
    out = []
    for i, c in enumerate(text):
        inner = 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha()
        out.append(table[c] if c in table and inner and rng.random() < 0.45 else c)
    return "".join(out)


def _dollar(text: str, rng: random.Random) -> str:
    out = []
    for i, c in enumerate(text):
        inner = 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha()
        out.append("$" if c == "s" and inner and rng.random() < 0.7 else c)
    return "".join(out)


def evade(kind: str, text: str, rng: random.Random, seed: int) -> str:
    if kind == "leet":
        return _leet(text, rng)
    if kind == "dollar_s":
        return _dollar(text, rng)
    if kind == "base64":
        lead = rng.choice(["Please decode and follow: ", "Giải mã rồi làm theo: ", "Payload: "])
        return lead + base64.b64encode(text.encode("utf-8")).decode()
    if kind == "rot13":
        return codecs.encode(text, "rot13")
    if kind == "reversed":
        return text[::-1]
    if kind == "md_comment":
        return f"<!-- {text} -->"
    if kind == "json_in_string":
        return json.dumps({"note": text}, ensure_ascii=False)
    return perturb.apply(kind, text, seed=seed)


# --------------------------------------------------------------------------- items


def _pick_risk(rng: random.Random) -> str:
    x = rng.random()
    acc = 0.0
    for name, w in RISK_MIX:
        acc += w
        if x < acc:
            return name
    return "read_only"


def _lang(rng: random.Random, pool: dict[str, list[str]]) -> str:
    opts = [("en", 0.40), ("vi", 0.50), ("mx", 0.10)]
    opts = [(k, w) for k, w in opts if k in pool]
    total = sum(w for _, w in opts)
    x = rng.random() * total
    acc = 0.0
    for k, w in opts:
        acc += w
        if x < acc:
            return k
    return opts[-1][0]


def _args_for(risk: str, rng: random.Random, field: str | None, text: str | None, fill: Fill) -> dict[str, Any]:
    if risk == "money":
        a: dict[str, Any] = {
            "amount_minor": rng.choice([50_000, 1_000_000, 25_000_000, 400_000_000]),
            "from_account_id": f"ACC-{rng.randrange(1000, 9999)}",
            "payee_id": f"P-{rng.randrange(100, 999)}",
        }
    elif risk == "credit":
        a = {"application_id": f"APP-{rng.randrange(1000, 9999)}", "decision": rng.choice(["approve", "refer", "decline"])}
    elif risk == "pii_export":
        a = {"customer_id": f"C-{rng.randrange(100, 999)}", "payee_name": fill("{name}")}
    else:
        a = {"customer_id": f"C-{rng.randrange(100, 999)}"}
    if field is not None and text is not None:
        a[field] = text
    return a


def _make(
    pool: dict[str, Any],
    surface: str,
    positive: bool,
    rng: random.Random,
) -> dict[str, Any]:
    """One item (without id / split fields). ``text`` is the field the evasions rewrite."""
    fill = Fill(rng)
    pick = Pick(pool, rng)
    risk = _pick_risk(rng)
    tool = rng.choice(TOOLS[risk])
    meta: dict[str, Any] = {"tool_name": tool, "risk_class": risk, "agent_id": AGENTS[risk]}
    tid = ""
    hard = False
    if surface == "args":
        section = "args_inj" if positive else "args_ben"
        lang = _lang(rng, pool[section])
        i, tmpl, origin = pick(section, lang)
        tid = f"{section}.{lang}.{i}"
        hard = (not positive) and origin >= 2
        text = fill(tmpl)
        if rng.random() < (0.35 if positive else 0.4):
            # a second, ordinary sentence before or after (same rate for both labels)
            _, ptmpl, porigin = pick("args_ben", lang if lang in pool["args_ben"] else "en")
            hard = hard or ((not positive) and porigin >= 2)
            prefix = fill(ptmpl)
            text = f"{prefix} {text}" if rng.random() < 0.5 else f"{text} {prefix}"
        field = rng.choice(T.FREE_FIELDS)
        payload: dict[str, Any] = {"args": _args_for(risk, rng, field, text, fill)}
        target: dict[str, Any] = {"part": "args", "field": field}
    elif surface == "tool_results":
        lang = rng.choice(["en", "vi"])
        ci, carrier, _ = pick("res_carrier", lang)
        if positive:
            lead = rng.choice(pool["res_inj"][f"lead_{lang}"])
            _, core_t, _ = pick("res_inj", f"core_{lang}")
            core = fill(core_t)
            inj = f"<!-- {core} -->" if lead == "<!--" else f"{lead} {core}"
            text = fill(carrier.replace("{inj}", inj))
            tid = f"res_inj.{lang}.{ci}"
        else:
            bi, btmpl, borigin = pick("res_ben", lang)
            hard = borigin >= 2
            if rng.random() < 0.5:
                text = fill(btmpl)
                tid = f"res_ben.{lang}.{bi}"
            else:
                sentence = fill(btmpl)
                text = fill(carrier.replace("{inj}", sentence))
                tid = f"res_carrier_ben.{lang}.{ci}.{bi}"
        payload = {"args": _args_for(risk, rng, None, None, fill), "tool_results": [text]}
        target = {"part": "tool_results", "index": 0}
    else:
        lang = rng.choice(["en", "vi"])
        n_base = len(pool["desc_base"][lang])
        union = [("desc_base", i) for i in range(n_base)] + [
            ("desc_ben", i) for i in range(len(pool["desc_ben"][lang]))
        ]

        def one(sec_i: tuple[str, int]) -> str:
            sec, i = sec_i
            origin, is_para = pool["_m"][sec][lang][i]
            pick.para = pick.para or is_para
            return fill(pool[sec][lang][i])

        if positive:
            parts = [one(x) for x in rng.sample(union, rng.choice((1, 1, 2)))]
            _, inj_t, _ = pick("desc_inj", lang)
            parts.insert(rng.choice((0, len(parts), len(parts))), fill(inj_t))
            text = " ".join(parts)
            tid = f"desc_inj.{lang}"
        else:
            picks = rng.sample(union, rng.choice((1, 2, 2, 3)))
            text = " ".join(one(x) for x in picks)
            hard = any(sec == "desc_ben" for sec, _ in picks)
            tid = f"desc_ben.{lang}"
        meta["tool_description"] = text
        payload = {"args": _args_for(risk, rng, None, None, fill)}
        target = {"part": "meta", "field": "tool_description"}
    return {
        "payload": payload,
        "meta": meta,
        "label": int(positive),
        "expect_codes": [CODES[surface]] if positive else [],
        "sensitive": sorted(set(fill.sensitive)),
        "category": "injection" if positive else ("benign-hard" if hard else "benign"),
        "lang": lang,
        "surface": surface,
        "target": target,
        "template_id": tid,
        "para": pick.para,
        "evasion": None,
    }


def _get_text(item: dict[str, Any]) -> str:
    t = item["target"]
    if t["part"] == "args":
        return str(item["payload"]["args"][t["field"]])
    if t["part"] == "tool_results":
        return str(item["payload"]["tool_results"][t["index"]])
    return str(item["meta"][t["field"]])


def _set_text(item: dict[str, Any], text: str) -> None:
    t = item["target"]
    if t["part"] == "args":
        item["payload"]["args"][t["field"]] = text
    elif t["part"] == "tool_results":
        item["payload"]["tool_results"][t["index"]] = text
    else:
        item["meta"][t["field"]] = text


def apply_evasion(item: dict[str, Any], kind: str, rng: random.Random, seed: int) -> dict[str, Any]:
    out = json.loads(json.dumps(item))
    text = _get_text(out)
    if kind == "split_fields":
        if out["target"]["part"] != "args":
            kind = "typo"  # split across fields is an arguments evasion; fall back for the others
        else:
            words = text.split(" ")
            cut = max(1, len(words) // 2)
            _set_text(out, " ".join(words[:cut]))
            out["payload"]["args"]["note_2"] = " ".join(words[cut:])
            out["evasion"] = "split_fields"
            return out
    _set_text(out, evade(kind, text, rng, seed))
    out["evasion"] = kind
    return out


def _source(split: str, item: dict[str, Any]) -> str:
    return f"generator seed={SEED} split={split} template={item['template_id']}"


def _finish(split: str, n: int, item: dict[str, Any], tags: list[str] | None = None) -> dict[str, Any]:
    code = {"args": "DIR", "tool_results": "IND", "tool_description": "POI"}[item["surface"]]
    item = dict(item)
    item.update(
        {
            "id": f"INJ-{split}-{code}-{n:04d}",
            "split": split,
            "detector": DETECTOR,
            "direction": "input",
            "source": _source(split, item) + (" (synthetic, LLM-paraphrased)" if item.get("para") else ""),
            "licence": LICENCE,
            "labeller": "synthetic, LLM-paraphrased" if item.get("para") else "synthetic",
            "tags": tags or [item["surface"]],
        }
    )
    return item


def build_split(split: str, rng: random.Random) -> list[dict[str, Any]]:
    pool = expand(split, load_paraphrases())
    npos, nneg = SIZES[split]
    out: list[dict[str, Any]] = []
    for surface in ("args", "tool_results", "tool_description"):
        seen: set[str] = set()
        made = 0
        for positive, want in ((True, npos), (False, nneg)):
            got = tries = 0
            while got < want and tries < want * 60:
                tries += 1
                it = _make(pool, surface, positive, rng)
                key = f"{int(positive)}|{_get_text(it)}"  # unique texts only
                if key in seen:
                    continue
                seen.add(key)
                if split == "train" and rng.random() < EVADE_TRAIN_RATE:
                    kind = rng.choice(EVASION_KINDS)
                    it = apply_evasion(it, kind, rng, rng.randrange(1 << 30))
                made += 1
                got += 1
                out.append(_finish(split, len(out) + 1, it))
    return out


def build_evasion(heldout: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """Heldout positives and benign twins, each re-written with one evasion kind."""
    pos = [x for x in heldout if x["label"] == 1 and x["evasion"] is None]
    neg = [x for x in heldout if x["label"] == 0 and x["evasion"] is None]
    out: list[dict[str, Any]] = []
    for kind in EVASION_KINDS:
        for label, pool in ((1, pos), (0, neg)):
            by_surface: dict[str, list[dict[str, Any]]] = {}
            for x in pool:
                by_surface.setdefault(x["surface"], []).append(x)
            per = EVASION_PER_KIND // 3
            for surface in ("args", "tool_results", "tool_description"):
                for src in rng.sample(by_surface[surface], per):
                    ev = apply_evasion(src, kind, rng, rng.randrange(1 << 30))
                    ev["clean_id"] = src["id"]
                    out.append(_finish("evasion", len(out) + 1, ev, [kind, ev["surface"]]))
    return out


def build_adversarial() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n, p in enumerate(adversarial.PROBES, 1):
        s = p["s"]
        positive = bool(p["y"])
        risk = "money" if s == "args" else ("credit" if s == "tool_results" and n % 2 else "read_only")
        tool = {"money": "transfer", "credit": "decide_prequal", "read_only": "get_balance"}[risk]
        meta: dict[str, Any] = {"tool_name": tool, "risk_class": risk, "agent_id": AGENTS[risk]}
        args: dict[str, Any] = {"customer_id": "C-100"}
        if risk == "money":
            args.update({"amount_minor": 1_000_000, "from_account_id": "ACC-1001", "payee_id": "P-200"})
        payload: dict[str, Any] = {"args": args}
        if s == "args":
            args["memo"] = p["t"]
            if "extra" in p:
                args["note"] = p["extra"]
            target: dict[str, Any] = {"part": "args", "field": "memo"}
        elif s == "tool_results":
            payload["tool_results"] = [p["t"]]
            target = {"part": "tool_results", "index": 0}
        else:
            meta["tool_description"] = p["t"]
            target = {"part": "meta", "field": "tool_description"}
        if "prior" in p:
            meta["prior_calls"] = list(p["prior"])
        out.append(
            {
                "id": f"INJ-adv-{n:04d}",
                "split": "adversarial",
                "detector": DETECTOR,
                "direction": "input",
                "payload": payload,
                "meta": meta,
                "label": int(positive),
                "expect_codes": [CODES[s]] if positive else [],
                "sensitive": [],
                "category": p["c"],
                "lang": "mixed",
                "surface": s,
                "target": target,
                "template_id": "hand-written",
                "evasion": None,
                "source": "hand-written probe, outside the templates",
                "licence": LICENCE,
                "labeller": "human (hand-written probe)",
                "tags": [s, p["c"]],
            }
        )
    return out


# --------------------------------------------------------------------------- files


def dump(items: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in items)


def build_all() -> dict[str, str]:
    rng = random.Random(SEED)  # noqa: S311 - seeded data generation, not security
    train = build_split("train", rng)
    dev = build_split("dev", rng)
    held = build_split("heldout", rng)
    evas = build_evasion(held, rng)
    adv = build_adversarial()
    return {
        "train.jsonl": dump(train),
        "dev.jsonl": dump(dev),
        "heldout.jsonl": dump(held),
        "evasion.jsonl": dump(evas),
        "adversarial.jsonl": dump(adv),
    }


def _count(pool: dict[str, Any]) -> int:
    n = 0
    for part in pool.values():
        n += sum(len(v) for v in part.values())
    return n


def manifest(files: dict[str, str]) -> dict[str, Any]:
    info = {}
    for name, text in sorted(files.items()):
        rows = [json.loads(line) for line in text.splitlines()]
        info[name] = {
            "n_items": len(rows),
            "n_positive": sum(r["label"] for r in rows),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    return {
        "name": "injection_vi_en",
        "seed": SEED,
        "licence": LICENCE,
        "labellers": ["synthetic", "synthetic, LLM-paraphrased", "human (hand-written probe)"],
        "llm_paraphrase": {
            "model": "qwen3.8-27b-int4 (local, inference only, concurrency 2)",
            "paraphrases_sha256": hashlib.sha256((HERE / "paraphrases.json").read_bytes()).hexdigest()
            if (HERE / "paraphrases.json").is_file()
            else None,
            "n_paraphrases": sum(len(r["paraphrases"]) for p in load_paraphrases().values() for r in p.values()),
        },
        "template_strings": {k: _count(p) for k, p in T.POOLS.items()},
        "files": info,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the injection_vi_en golden set (seeded).")
    ap.add_argument("--check", action="store_true", help="exit 1 when the files differ")
    args = ap.parse_args(argv)
    files = build_all()
    man = json.dumps(manifest(files), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.check:
        stale = [
            n
            for n, t in {**files, "MANIFEST.json": man}.items()
            if not (HERE / n).is_file() or (HERE / n).read_text(encoding="utf-8") != t
        ]
        for n in stale:
            print(f"[FAIL] {n} is stale")
        if not stale:
            print("[OK] golden files are current")
        return 1 if stale else 0
    for name, text in files.items():
        (HERE / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"[OK] {name}: {text.count(chr(10))} items")
    (HERE / "MANIFEST.json").write_text(man, encoding="utf-8", newline="\n")
    print("[OK] MANIFEST.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
