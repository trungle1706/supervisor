# ruff: noqa: E501, S311
"""WP-F5: generate the golden sets of the six starter agents (dev tool, no model, deterministic).

Run:  python -m tools.factory_golden_gen            # write config/factory_agents/golden/<agent>/
      python -m tools.factory_golden_gen --check    # fail when the committed files differ

For every starter agent in ``config/factory_agents/<agent>.yaml`` it writes

* ``cases.json``        gate cases (``inputs``, ``expected``, ``expected_evidence_refs``): at least 50
                        per agent, every checklist item with at least 3 cases, spread over the verdicts
                        pass, fail, question and (where the item has an applicability clause)
                        not_applicable;
* ``calibration.json``  24 synthetic human-style labels (``label_by: synthetic.labeller``); three of
                        them differ from the expected verdict, like a careful human would.

The scenarios are in ``tools/factory_golden_specs.py``. All text is synthetic Vietnamese: no real
person, bank, account or document. Same seed, same bytes. The two templates (supply chain,
reputation) get an empty golden set.

An evidence ref of a case always points at a source of that case's own inputs. Refs carry the case
token so that two cases never share a ref.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.factory import golden
from tools.factory_golden_specs import SPECS

SEED = 20261028
TODAY = dt.date(2026, 10, 28)
AGENT_DIR = REPO_ROOT / "config" / "factory_agents"
SHORT = {
    "model-risk-assessor": "mr",
    "data-governance-assessor": "dg",
    "cyber-assessor": "cy",
    "legal-compliance-assessor": "lc",
    "third-party-assessor": "tp",
    "ethics-assessor": "et",
}
TEMPLATES = ("supply-chain-assessor", "reputation-assessor")
MIN_CASES = 60
MIN_PER_ITEM = 5
LABELS = 24
FLIPS = 3
LABELLER = "synthetic.labeller"
LABELLED_AT = "2026-10-20T08:00:00Z"
PLAN = ("p", "f", "q", "n", "p", "f", "q")

DEV = ["Phòng Phát triển ứng dụng", "Khối Công nghệ thông tin", "Phòng Kỹ thuật dữ liệu"]
IND = [
    "Phòng Kiểm định mô hình độc lập",
    "Phòng Quản lý rủi ro mô hình",
    "Phòng Đánh giá rủi ro tuyến hai",
]
DATA_UNIT = ["Ban Quản trị dữ liệu", "Phòng Quản lý dữ liệu", "Phòng Kho dữ liệu"]
SEC = ["Phòng An ninh thông tin", "Trung tâm Giám sát an toàn"]
VENDOR = [
    "Công ty Alpha Cloud",
    "Nhà cung cấp Beta AI",
    "Công ty Gamma Nền tảng",
    "Đối tác Delta Tech",
]
DS = ["bo_giao_dich_mau_a", "bo_ho_so_tin_dung_mau_b", "bo_hoi_thoai_mau_c", "bo_khieu_nai_mau_d"]
USECASE = [
    "xếp hạng hồ sơ tín dụng",
    "tư vấn sản phẩm tiền gửi",
    "phân loại yêu cầu của khách hàng",
    "gợi ý hạn mức thẻ",
    "tóm tắt hồ sơ vay",
]
SYSNAME = [
    "Trợ lý hồ sơ tín dụng",
    "Trợ lý tư vấn tiền gửi",
    "Bộ phân loại yêu cầu",
    "Công cụ gợi ý hạn mức",
]
MODELS = ["xep-hang", "de-xuat", "tra-cuu", "phan-loai", "tom-tat"]
FACTORS = [
    "thu nhập ổn định",
    "lịch sử trả nợ",
    "kỳ hạn vay",
    "số dư trung bình",
    "loại sản phẩm",
    "thời gian gắn bó",
]
NOTES = {
    "pass": "Kỳ vọng pass: nguồn đã trích cho thấy quy tắc đạt; phải trích đúng tham chiếu của nguồn.",
    "fail": "Kỳ vọng fail: nguồn cho thấy quy tắc bị vi phạm; thiếu sót được ghi rõ trong nguồn.",
    "question": "Kỳ vọng question: các nguồn đã nạp không quyết định được mục này; không được đoán.",
    "not_applicable": "Kỳ vọng not_applicable: nguồn cho thấy mục không áp dụng cho hệ thống này.",
}
PACK_TEXT = {
    "pass": "{pack}: passed at version {pv} (current version {pv}); {n} of {n} probes ok",
    "fail": "{pack}: failed at version {pv} (current version {pv}); {k} of {n} probes failed",
    "stale": "{pack}: passed at version {pv0}; current version is {pv}; no run at the current version",
}
NEUTRAL_DOCS = [
    "Hướng dẫn chung của phòng: lịch họp tuần, đầu mối liên hệ và mẫu biên bản; không có nội dung về mục đang xét.",
    "Ghi chú vận hành: lịch bảo trì định kỳ vào cuối tuần, thông báo trước cho các bên liên quan.",
]
NEUTRAL_FACTS = [
    (
        "tool",
        "tra_cuu_danh_muc",
        "công cụ tra cứu danh mục sản phẩm, chỉ đọc",
        "agent/tools.py",
        9,
        "def tra_cuu_danh_muc():",
    ),
    (
        "model",
        "mo_hinh_ngon_ngu",
        "mô hình ngôn ngữ dùng cho tóm tắt",
        "agent/model.py",
        5,
        "MODEL_NAME = 'mo_hinh_ngon_ngu'",
    ),
]
KIND_OF_SNIPPET = {"r": "system_record", "d": "document", "f": "fact", "k": "pack", "g": "regkb"}
NEUTRAL_PACKS = ["atlas_coverage", "judge_golden_set"]


def agent_files() -> dict[str, dict[str, Any]]:
    out = {}
    for agent_id in SHORT:
        path = AGENT_DIR / f"{agent_id}.yaml"
        out[agent_id] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return out


def iso(d: dt.date) -> str:
    return d.isoformat()


def context(rng: random.Random, token: str) -> dict[str, Any]:
    pv = rng.randint(2, 7)
    return {
        "model": f"mo-hinh-{rng.choice(MODELS)}-{rng.randint(1, 9)}",
        "ver": f"v{rng.randint(1, 4)}.{rng.randint(0, 9)}",
        "n": rng.randint(3, 40),
        "k": rng.randint(1, 4),
        "pv": pv,
        "pv0": pv - 1,
        "date": iso(TODAY - dt.timedelta(days=rng.randint(15, 150))),
        "old": iso(TODAY - dt.timedelta(days=rng.randint(420, 800))),
        "future": iso(TODAY + dt.timedelta(days=rng.randint(100, 400))),
        "dev": rng.choice(DEV),
        "ind": rng.choice(IND),
        "data_unit": rng.choice(DATA_UNIT),
        "sec": rng.choice(SEC),
        "vendor": rng.choice(VENDOR),
        "ds": rng.choice(DS),
        "ds2": rng.choice(DS) + "_kt",
        "usecase": rng.choice(USECASE),
        "sysname": rng.choice(SYSNAME),
        "level": rng.choice(["high", "medium"]),
        "factor1": FACTORS[0],
        "factor2": rng.choice(FACTORS[1:3]),
        "factor3": rng.choice(FACTORS[3:]),
        "token": token,
    }


class Builder:
    """The inputs of one case: record fields, facts, packs, RegKB rows, document sections."""

    def __init__(self, sid: str, token: str, ctx: dict[str, Any]) -> None:
        self.sid, self.token, self.ctx = sid, token, ctx
        self.system: dict[str, Any] = {
            "system_id": sid,
            "name": ctx["sysname"],
            "owner_team": ctx["dev"],
            "system_type": "assistant",
            "lifecycle_stage": "operation",
        }
        self.facts: list[dict[str, Any]] = []
        self.packs: list[dict[str, Any]] = []
        self.regkb: list[dict[str, Any]] = []
        self.docs: list[dict[str, Any]] = []
        self.refs: list[str] = []

    def fill(self, text: str) -> str:
        out = text.format(**self.ctx)
        return out

    def add(self, snip: tuple[Any, ...]) -> None:
        kind = snip[0]
        ev = bool(snip[-1])
        ref = ""
        if kind == "r":
            key, val = snip[1], self.fill(snip[2])
            self.system[key] = val
            ref = f"{self.sid}.{key}"
        elif kind == "d":
            k = len(self.docs) + 1
            ref = f"internal-{self.token}-{k}#1"
            self.docs.append(
                {
                    "doc_id": f"internal-{self.token}-{k}",
                    "sections": [{"ref": ref, "label": f"Phần {k}", "text": self.fill(snip[1])}],
                }
            )
        elif kind == "f":
            _, fk, name, detail, file, line, quote, _ = snip
            ref = f"fct-{self.token}-{len(self.facts) + 1}"
            self.facts.append(
                {
                    "fact_id": ref,
                    "kind": fk,
                    "name": self.fill(name),
                    "detail": self.fill(detail),
                    "file": file,
                    "line": line,
                    "quote": self.fill(quote),
                }
            )
        elif kind == "k":
            _, pack, state, _ = snip
            ref = f"pack:{pack}:{self.token}"
            self.packs.append(
                {
                    "ref": ref,
                    "label": f"pack {pack}",
                    "text": PACK_TEXT[state].format(
                        pack=pack, **{k: v for k, v in self.ctx.items() if k != "pack"}
                    ),
                }
            )
        elif kind == "g":
            _, inst, art, text, _ = snip
            ref = f"{inst}#{art}-{self.token}"
            self.regkb.append({"ref": ref, "label": f"{inst} {art}", "text": self.fill(text)})
        else:  # pragma: no cover - a spec error
            raise ValueError(f"unknown snippet {kind}")
        if ev:
            self.refs.append(ref)

    def neutral(self, rng: random.Random, kinds: list[str], docs_ok: bool) -> None:
        if "fact" in kinds:
            nf = rng.choice(NEUTRAL_FACTS)
            self.add(("f", nf[0], nf[1], nf[2], nf[3], nf[4], nf[5], False))
        if docs_ok and "document" in kinds:
            self.add(("d", rng.choice(NEUTRAL_DOCS), False))
        if "pack" in kinds:
            self.add(("k", rng.choice(NEUTRAL_PACKS), "pass", False))

    def inputs(self) -> dict[str, Any]:
        out: dict[str, Any] = {"system": dict(sorted(self.system.items()))}
        if self.facts:
            out["facts"] = {"version": 1, "node_id": self.sid, "facts": self.facts}
        if self.packs:
            out["packs"] = self.packs
        if self.regkb:
            out["regkb"] = self.regkb
        if self.docs:
            out["documents"] = self.docs
        return out


def plan_for(n_per: int, has_na: bool) -> list[str]:
    plan = list(PLAN)
    plan[3] = "n" if has_na else "f"
    return plan[:n_per]


def make_cases(defn: dict[str, Any]) -> list[dict[str, Any]]:
    agent_id = defn["id"]
    short = SHORT[agent_id]
    items = defn["checklist"]
    docs_ok = any(t["tool_id"] == "search_documents" for t in defn["tools"])
    inst = defn["policy_refs"][0]["doc_id"]
    n_per = max(MIN_PER_ITEM, math.ceil(MIN_CASES / len(items)))
    cases: list[dict[str, Any]] = []
    for item in items:
        spec = SPECS.get(item["id"])
        if spec is None:
            raise SystemExit(f"no scenario spec for {item['id']}")
        used = {"p": 0, "f": 0, "n": 0}
        for k, kind in enumerate(plan_for(n_per, "n" in spec), start=1):
            case_id = f"{short}-{item['id'].lower()}-{k:02d}"
            rng = random.Random(f"{SEED}/{case_id}")
            token = f"{short}{item['id'][-2:]}{k:02d}"
            sid = "case-" + re.sub(r"[^A-Za-z0-9_.-]", "_", case_id)  # what the gate gives the run
            b = Builder(sid, token, context(rng, token))
            if kind == "q":
                verdict = "question"
            else:
                variants = spec[kind]
                variant = variants[used[kind] % len(variants)]
                used[kind] += 1
                verdict = {"p": "pass", "f": "fail", "n": "not_applicable"}[kind]
                for snip in variant:
                    if snip[-1] and KIND_OF_SNIPPET[snip[0]] not in item["evidence"]:
                        raise SystemExit(
                            f"{item['id']}: an evidence snippet of kind {KIND_OF_SNIPPET[snip[0]]} "
                            f"is not one of the item's evidence kinds {item['evidence']}"
                        )
                    b.add(snip)
            b.neutral(rng, list(item["evidence"]), docs_ok)
            b.add(
                (
                    "g",
                    inst,
                    "Art.14(3)",
                    "Điều 14(3): ngân hàng quản lý tối thiểu tám loại rủi ro đối với việc sử dụng trí tuệ nhân tạo.",
                    False,
                )
            )
            refs = [] if verdict == "question" else list(dict.fromkeys(b.refs))
            cases.append(
                {
                    "case_id": case_id,
                    "inputs": b.inputs(),
                    "expected": {item["id"]: verdict},
                    "expected_evidence_refs": refs,
                    "rubric_notes": NOTES[verdict],
                }
            )
    return cases


def make_labels(defn: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_item: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        by_item.setdefault(next(iter(c["expected"])), []).append(c)
    order = [i["id"] for i in defn["checklist"]]
    picked: list[dict[str, Any]] = []
    rnd = 0
    while len(picked) < LABELS:
        for iid in order:
            lst = by_item[iid]
            if rnd < len(lst) and len(picked) < LABELS:
                picked.append(lst[rnd])
        rnd += 1
    rng = random.Random(f"{SEED}/labels/{defn['id']}")
    decided = [
        i for i, c in enumerate(picked) if next(iter(c["expected"].values())) in ("pass", "fail")
    ]
    flip = set(rng.sample(decided, FLIPS))
    rows = []
    for i, c in enumerate(picked):
        iid, verdict = next(iter(c["expected"].items()))
        rows.append(
            {
                "case_id": c["case_id"],
                "finding_id": f"f-{iid}",
                "human_verdict": "question" if i in flip else verdict,
                "label_by": LABELLER,
                "labelled_at": LABELLED_AT,
            }
        )
    return rows


def dump(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def build() -> dict[Path, str]:
    """Every output file (path -> text)."""
    out: dict[Path, str] = {}
    for agent_id, defn in agent_files().items():
        ids = [c["id"] for c in defn["checklist"]]
        cases = make_cases(defn)
        ok, bad = golden.check_gate_cases(cases, ids)
        if bad:
            raise SystemExit(f"{agent_id}: {len(bad)} case(s) refused, first: {bad[0]}")
        strat = golden.gate_stratification(ok, ids)
        low = [i for i, n in strat["per_item"].items() if n < 3]
        if not strat["ready"] or low:
            raise SystemExit(f"{agent_id}: stratification problems {strat['problems']} {low}")
        labels = make_labels(defn, cases)
        good, bad2 = golden.check_labels(labels, [c["case_id"] for c in cases], ids)
        if bad2 or len(good) < 20:
            raise SystemExit(f"{agent_id}: label problems {bad2[:1]} ({len(good)})")
        leftovers = [
            c["case_id"]
            for c in cases
            if re.search(r"\{[a-z0-9]+\}", json.dumps(c, ensure_ascii=False))
        ]
        if leftovers:
            raise SystemExit(f"{agent_id}: unfilled placeholder in {leftovers[:3]}")
        base = AGENT_DIR / "golden" / agent_id
        out[base / "cases.json"] = dump(cases)
        out[base / "calibration.json"] = dump(labels)
    for agent_id in TEMPLATES:
        out[AGENT_DIR / "golden" / agent_id / "cases.json"] = "[]\n"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.factory_golden_gen")
    parser.add_argument("--check", action="store_true", help="fail when the committed files differ")
    args = parser.parse_args(argv)
    files = build()
    if args.check:
        stale = [
            p for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t
        ]
        for p in stale:
            sys.stdout.write(
                f"[FAIL] {p.relative_to(REPO_ROOT)} differs from the generator output\n"
            )
        if not stale:
            sys.stdout.write(f"[OK] {len(files)} file(s) are current\n")
        return 1 if stale else 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sys.stdout.write(f"[OK] wrote {len(files)} file(s) under config/factory_agents/golden\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
