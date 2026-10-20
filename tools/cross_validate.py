"""Grouped cross-validation for the injection classifier (WP25b). Standard library only.

    uv run python -m tools.cross_validate                       # 3 folds, default hyper-parameters
    uv run python -m tools.cross_validate --epochs 4 --lr 0.03 --l2 1e-4 --hard-weight 2

The folds are leave-one-pool-out over the template pools train (A), dev (B) and train_b (C). A pool
is a set of template families that no other pool shares, so a fold measures the shift from known
families to new families (the same shift the sealed held-out set measures). It never opens the
sealed files (heldout, evasion, adversarial). Output: per-fold and mean recall at the false-alarm
levels of the protocol, per surface, and the out-of-fold threshold table that the presets are
chosen from (rule in data/eval/injection_vi_en/WP25B_PROTOCOL.md).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import Any

from supervisor.detectors.injection_classifier.model import SURFACES
from tools import train_classifier as TC

POOLS = ("train", "dev", "train_b")  # A, B, C
LEVELS = (300, 500, 800)  # false alarm levels in bp


def scores_for(model: Any, samples: list[Any]) -> list[int]:
    return TC.scores_bp(model, samples)


def table(scores: list[int], labels: list[int]) -> list[dict[str, int]]:
    return TC.threshold_table(scores, labels)


def recall_at(rows: list[dict[str, int]], fa: int) -> tuple[int, int]:
    """(recall, threshold) at the smallest threshold with false alarm <= fa."""
    for r in rows:
        if r["false_alarm_bp"] <= fa:
            return r["recall_bp"], r["threshold_bp"]
    return 0, 10_000


def run(
    hyper: dict[str, Any], seed: int, pools: tuple[str, ...] = POOLS, log: bool = True
) -> dict[str, Any]:
    items = {p: TC.load_items(p) for p in pools}
    samples = {p: TC.make_samples(items[p]) for p in pools}
    oof: dict[str, list[int]] = {}
    for held in pools:
        train_samples = [s for p in pools if p != held for s in samples[p]]
        model = TC.train(train_samples, hyper, seed, log=False)
        oof[held] = scores_for(model, samples[held])
        if log:
            print(f"[..] fold {held}: trained on {len(train_samples)} samples", flush=True)
    allitems = [it for p in pools for it in items[p]]
    allscores = [s for p in pools for s in oof[p]]
    out: dict[str, Any] = {"per_surface": {}, "per_fold": {}, "thresholds": {}}
    for surf in (*SURFACES, "all"):
        idx = [i for i, it in enumerate(allitems) if surf == "all" or it["surface"] == surf]
        rows = table([allscores[i] for i in idx], [int(allitems[i]["label"]) for i in idx])
        out["per_surface"][surf] = {fa: recall_at(rows, fa) for fa in LEVELS}
    # per-fold recall at the pooled per-surface thresholds (rule: balanced = FA <= 500)
    for held in pools:
        its = items[held]
        sc = oof[held]
        rec, fal = [], []
        for surf in SURFACES:
            thr = out["per_surface"][surf][500][1]
            pos = [
                s for s, it in zip(sc, its, strict=True) if it["surface"] == surf and it["label"]
            ]
            neg = [
                s
                for s, it in zip(sc, its, strict=True)
                if it["surface"] == surf and not it["label"]
            ]
            rec.append(sum(s >= thr for s in pos) * 10_000 // max(1, len(pos)))
            fal.append(sum(s >= thr for s in neg) * 10_000 // max(1, len(neg)))
        out["per_fold"][held] = {"recall_bp": rec, "false_alarm_bp": fal}
    out["oof"] = {
        "labels": [int(it["label"]) for it in allitems],
        "scores": allscores,
        "surface": [it["surface"] for it in allitems],
    }
    return out


def summarise(res: dict[str, Any]) -> list[str]:
    lines = ["surface            recall@FA300 (thr)  recall@FA500 (thr)  recall@FA800 (thr)"]
    for surf, d in res["per_surface"].items():
        lines.append(f"{surf:<18}" + "".join(f"{d[fa][0]:>10} ({d[fa][1]:>5})   " for fa in LEVELS))
    for held, d in res["per_fold"].items():
        lines.append(f"fold {held:<8} recall {d['recall_bp']} false alarm {d['false_alarm_bp']}")
    surf_mean = {
        fa: int(statistics.mean(res["per_surface"][x][fa][0] for x in SURFACES)) for fa in LEVELS
    }
    lines.append(
        f"KEY mean of the three surfaces: recall@FA300 {surf_mean[300]} @FA500 {surf_mean[500]} @FA800 {surf_mean[800]}"
    )
    allr = [statistics.mean(d["recall_bp"]) for d in res["per_fold"].values()]
    lines.append(
        f"mean recall over folds at the per-surface FA<=500 thresholds: {int(statistics.mean(allr))} "
        f"(spread {int(max(allr) - min(allr))})"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.cross_validate", description=__doc__)
    ap.add_argument("--epochs", type=int, default=TC.HYPER["epochs"])
    ap.add_argument("--lr", type=float, default=TC.HYPER["lr"])
    ap.add_argument("--l2", type=float, default=TC.HYPER["l2"])
    ap.add_argument("--hard-weight", type=float, default=TC.HYPER["hard_weight"])
    ap.add_argument("--bags", type=int, default=1)
    ap.add_argument("--seed", type=int, default=TC.SEED)
    ap.add_argument("--json", metavar="PATH", help="write the result (without OOF scores) as JSON")
    args = ap.parse_args(argv)
    hyper = dict(
        TC.HYPER,
        epochs=args.epochs,
        lr=args.lr,
        l2=args.l2,
        hard_weight=args.hard_weight,
        bags=args.bags,
    )
    res = run(hyper, args.seed)
    print("\n".join(summarise(res)))
    if args.json:
        slim = {k: v for k, v in res.items() if k != "oof"}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(slim, fh, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
