"""Scoring of a masker against the labelled Vietnamese PII golden set (WP24b).

Per entity type: recall (primary), precision, Wilson 95% interval, all in integer basis points.
Two recall figures:

* ``leak_recall``: every alphanumeric character of the gold span is covered by SOME detected
  span. This is what a data protection officer cares about: nothing of the value survives.
* ``typed_recall``: covered by detected spans of the SAME type (the pseudonym is typed right).

Over-masking: a ``keep`` string (amount, date, reference) touched by any detected span. An
over-masked amount is a hard fail, because the credit rules need the amount.

Failure taxonomy: every miss and every false hit gets one label (``missed-uppercase-person``,
``missed-address``, ``over-mask-amount``, ...). Counts only; no item values in the report
(values are synthetic here, but the report format is also used on bank-supplied sets).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from supervisor.pii_eval.generate import DATA_DIR, ENTITY_TYPES

__all__ = ["evaluate", "load_items", "wilson_bp", "main"]

HARD_KEEP_KINDS = ("AMOUNT",)


class _SpanLike(Protocol):
    start: int
    end: int
    type: str


class _Masker(Protocol):
    def find(self, text: str) -> Sequence[_SpanLike]: ...

    @staticmethod
    def canonical(text: str) -> str: ...


def wilson_bp(k: int, n: int, z: float = 1.96) -> tuple[int, int] | None:
    """Wilson score interval for k successes in n trials, in basis points (low, high)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0, math.floor((centre - half) * 10000)), min(10000, math.ceil((centre + half) * 10000))


def _bp(k: int, n: int) -> int | None:
    return None if n == 0 else (k * 10000) // n


def load_items(split: str | None = None, data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in ("dev", "heldout"):
        if split not in (None, "all", name):
            continue
        p = data_dir / f"{name}.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _alnum_positions(text: str, start: int, end: int) -> list[int]:
    return [i for i in range(start, end) if text[i].isalnum()]


def _form_tag(item: dict[str, Any], span: dict[str, Any]) -> str:
    s = span["text"]
    letters = [c for c in s if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        form = "uppercase"
    elif letters and all(c.islower() for c in letters):
        form = "lowercase"
    else:
        form = "mixed"
    if "telex" in item.get("tags", ()):
        form = "telex"
    elif letters and all(ord(c) < 128 for c in letters) and span["type"] in ("PERSON", "ADDRESS"):
        form += "-nodiac"
    return form


def _miss_label(item: dict[str, Any], span: dict[str, Any], partial: bool) -> str:
    t = span["type"]
    base = "partial" if partial else "missed"
    if t in ("PERSON", "ADDRESS"):
        return f"{base}-{t.lower()}-{_form_tag(item, span)}"
    extra = [x for x in ("grouped", "intl", "glued") if x in item.get("tags", ())]
    return f"{base}-{t.lower()}" + (f"-{extra[0]}" if extra else "")


def evaluate(
    masker: _Masker,
    items: Iterable[dict[str, Any]],
    *,
    amounts_masked: bool = False,
) -> dict[str, Any]:
    """Score ``masker`` on ``items``. Returns a JSON-able report (integers only)."""
    gold_n: Counter[str] = Counter()
    leak_hit: Counter[str] = Counter()
    typed_hit: Counter[str] = Counter()
    pred_n: Counter[str] = Counter()
    pred_ok: Counter[str] = Counter()
    keep_n: Counter[str] = Counter()
    keep_touched: Counter[str] = Counter()
    taxonomy: Counter[str] = Counter()
    fail_ids: dict[str, list[str]] = defaultdict(list)
    n_items = 0
    t_ns: list[int] = []
    for item in items:
        n_items += 1
        text = item["text"]
        canon = masker.canonical(text)
        if canon != text:  # offsets are into the canonical text; golden items are canonical
            raise ValueError(f"item {item['id']} is not canonical text")
        t0 = time.perf_counter_ns()
        preds = list(masker.find(text))
        t_ns.append(time.perf_counter_ns() - t0)
        spans = item["spans"] + (
            [
                {"type": "AMOUNT", "start": k["start"], "end": k["end"], "text": k["text"]}
                for k in item["keep"]
                if k["kind"] == "AMOUNT"
            ]
            if amounts_masked
            else []
        )
        covered_any: set[int] = set()
        for p in preds:
            if p.type == "AMOUNT" and not amounts_masked:
                continue
            covered_any.update(range(p.start, p.end))
        for g in spans:
            gold_n[g["type"]] += 1
            pos = _alnum_positions(text, g["start"], g["end"])
            same = set()
            for p in preds:
                if p.type == g["type"]:
                    same.update(range(p.start, p.end))
            any_cov = [i for i in pos if i in covered_any]
            leak_ok = len(any_cov) == len(pos)
            typed_ok = all(i in same for i in pos)
            leak_hit[g["type"]] += leak_ok
            typed_hit[g["type"]] += typed_ok
            if not leak_ok:
                lab = _miss_label(item, g, partial=bool(any_cov))
                taxonomy[lab] += 1
                fail_ids[lab].append(item["id"])
            elif not typed_ok:
                lab = f"wrong-type-{g['type'].lower()}"
                taxonomy[lab] += 1
                fail_ids[lab].append(item["id"])
        for p in preds:
            if p.type == "AMOUNT" and not amounts_masked:
                continue
            pred_n[p.type] += 1
            if any(g["type"] == p.type and g["start"] < p.end and p.start < g["end"] for g in spans):
                pred_ok[p.type] += 1
                continue
            touched_keep = next(
                (
                    k
                    for k in item["keep"]
                    if k["start"] < p.end and p.start < k["end"] and not (amounts_masked and k["kind"] == "AMOUNT")
                ),
                None,
            )
            if touched_keep is not None:
                lab = f"over-mask-{touched_keep['kind'].lower()}"
            elif any(g["start"] < p.end and p.start < g["end"] for g in spans):
                lab = f"wrong-type-{p.type.lower()}"
            else:
                lab = f"false-{p.type.lower()}"
            taxonomy[lab] += 1
            fail_ids[lab].append(item["id"])
        for k in item["keep"]:
            if amounts_masked and k["kind"] == "AMOUNT":
                continue
            keep_n[k["kind"]] += 1
            if any(
                p.start < k["end"] and k["start"] < p.end and not (p.type == "AMOUNT" and not amounts_masked)
                for p in preds
            ):
                keep_touched[k["kind"]] += 1
    entities: dict[str, Any] = {}
    for t in sorted(gold_n):
        n, kh, th = gold_n[t], leak_hit[t], typed_hit[t]
        entities[t] = {
            "n": n,
            "leak_recall_bp": _bp(kh, n),
            "leak_recall_wilson_bp": wilson_bp(kh, n),
            "typed_recall_bp": _bp(th, n),
            "typed_recall_wilson_bp": wilson_bp(th, n),
            "predicted": pred_n[t],
            "precision_bp": _bp(pred_ok[t], pred_n[t]),
            "precision_wilson_bp": wilson_bp(pred_ok[t], pred_n[t]),
        }
    keeps = {
        k: {"n": keep_n[k], "touched": keep_touched[k], "intact_bp": _bp(keep_n[k] - keep_touched[k], keep_n[k])}
        for k in sorted(keep_n)
    }
    total_gold = sum(gold_n.values())
    total_leak = sum(leak_hit.values())
    t_ns.sort()
    return {
        "n_items": n_items,
        "amounts_masked": amounts_masked,
        "entities": entities,
        "micro_leak_recall_bp": _bp(total_leak, total_gold),
        "keep": keeps,
        "over_mask_amount_count": keep_touched["AMOUNT"],
        "taxonomy": dict(sorted(taxonomy.items())),
        "latency_us_p50": (t_ns[len(t_ns) // 2] // 1000) if t_ns else 0,
        "latency_us_p95": (t_ns[int(len(t_ns) * 0.95)] // 1000) if t_ns else 0,
        "_failing_ids": {k: sorted(set(v))[:12] for k, v in sorted(fail_ids.items())},
    }


def make_masker(amounts: bool = False) -> Any:
    """The default masker with a fixed synthetic key (determinism)."""
    from supervisor.adapters.masking.vn_regex import VnRegexMasker

    key = b"pii-eval-synthetic-key"
    if amounts:
        try:
            return VnRegexMasker(key, "eval", mask_amounts=True)
        except TypeError:
            return None  # masker version without the amount switch (vn_regex-2)
    return VnRegexMasker(key, "eval")


def run_all(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    keep = make_masker()
    amt = make_masker(amounts=True)
    version = str(getattr(keep, "mask_version", "unknown")).split(":")[0]
    report: dict[str, Any] = {"masker": version, "splits": {}}
    for split in ("dev", "heldout"):
        items = load_items(split, data_dir)
        r = evaluate(keep, items)
        if amt is not None:
            ra = evaluate(amt, items, amounts_masked=True)
            r["amount_entity_mode"] = {
                "AMOUNT": ra["entities"].get("AMOUNT"),
                "over_mask_other_count": sum(
                    v for k, v in ra["taxonomy"].items() if k.startswith("over-mask")
                ),
            }
        report["splits"][split] = r
    return report


def _strip_ids(report: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(report))
    for s in out["splits"].values():
        s.pop("_failing_ids", None)
    return out


def format_table(report: dict[str, Any]) -> str:
    lines = [f"masker {report['masker']}"]
    for split, r in report["splits"].items():
        lines.append(f"-- {split}: {r['n_items']} items, micro leak recall {r['micro_leak_recall_bp']} bp")
        lines.append("entity        n  leak_rec_bp  wilson95          typed_bp  prec_bp  wilson95")
        for t in ENTITY_TYPES:
            e = r["entities"].get(t)
            if not e:
                continue
            lines.append(
                f"{t:<12} {e['n']:>3}  {e['leak_recall_bp']:>10}  {str(e['leak_recall_wilson_bp']):<16}"
                f"  {e['typed_recall_bp']:>8}  {str(e['precision_bp']):>7}  {e['precision_wilson_bp']}"
            )
        for k, v in r["keep"].items():
            lines.append(f"keep {k:<8} n={v['n']:>3} touched={v['touched']} intact_bp={v['intact_bp']}")
        lines.append(f"over_mask_amount_count={r['over_mask_amount_count']}")
        if r["taxonomy"]:
            lines.append("taxonomy: " + ", ".join(f"{k}={v}" for k, v in r["taxonomy"].items()))
        if "amount_entity_mode" in r:
            lines.append(f"amount-entity mode: {r['amount_entity_mode']['AMOUNT']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.pii_eval",
        description="Score the vn_regex masker on the Vietnamese PII golden set (data/eval/pii_vn).",
    )
    p.add_argument("--generate", action="store_true", help="rewrite the golden set from the seed")
    p.add_argument("--record", metavar="PATH", help="write the JSON report (baseline) to PATH")
    p.add_argument("--json", action="store_true", help="print the JSON report")
    p.add_argument("--show-failures", action="store_true", help="list failing DEV item ids per class")
    p.add_argument("--commit", default="unrecorded", help="commit id stored with --record")
    ns = p.parse_args(sys.argv[1:] if argv is None else argv)
    if ns.generate:
        from supervisor.pii_eval.generate import write

        for path in write():
            print(f"[OK] wrote {path.name}")
    report = run_all()
    if ns.json:
        print(json.dumps(_strip_ids(report), indent=2, sort_keys=True))
    else:
        print(format_table(report))
    if ns.show_failures:
        for k, ids in report["splits"]["dev"]["_failing_ids"].items():
            print(f"  dev {k}: {', '.join(ids)}")
    if ns.record:
        doc = {
            "recorded_at": time.strftime("%Y-%m-%d", time.gmtime()),
            "commit": ns.commit,
            "thresholds": "ILLUSTRATIVE until the bank sets them",
            **_strip_ids(report),
        }
        Path(ns.record).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[OK] baseline written to {ns.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
