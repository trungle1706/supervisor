"""Train the injection classifier of WP25 (standard library only; no torch, no numpy, no network).

    uv run python -m tools.train_classifier                      # train, write weights and card
    uv run python -m tools.train_classifier --epochs 14 --out /tmp/x --no-card
    uv run python -m tools.train_classifier --help

What it does (docs/injection-classifier.md section 3):

1. reads ``data/eval/injection_vi_en/train.jsonl`` (fit) and ``dev.jsonl`` (thresholds). It never
   reads ``heldout.jsonl``, ``evasion.jsonl`` or ``adversarial.jsonl``;
2. turns each item into its scored unit (``units.collect``) and the feature windows of every
   variant (``features.variant_feature_sets``);
3. fits a logistic regression on hashed character n-gram features with Adagrad and L2, max pooling
   over the windows and variants of a unit (multiple-instance training: the window with the
   highest logit takes the gradient), class-balanced, seeded shuffles;
4. rounds the weights to integers (``SCALE``), writes ``weights.json``, and the model card with the
   SHA-256 of the weight file;
5. prints the dev threshold table (false-alarm rate per threshold) used to pick the frozen presets.

The run is deterministic: same data, same seed, same bytes (a test trains a tiny model twice).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from array import array
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.detectors.injection_classifier import features as F
from supervisor.detectors.injection_classifier import units as U
from supervisor.detectors.injection_classifier.model import (
    MODEL_NAME,
    MODELS_DIR,
    SCALE,
    SURFACES,
    LinearModel,
    sha256_file,
    sigmoid_bp,
    write_model,
)

DATA = REPO_ROOT / "data" / "eval" / "injection_vi_en"
SEED = 20261023
VERSION = "1.1.0"
TRAINING_POOLS = frozenset({"train", "dev", "train_b"})
HYPER = {
    "epochs": 3,
    "lr": 0.1,
    "l2": 1e-3,
    "eps": 1e-6,
    "pos_weight": 1.0,
    "hard_weight": 4.0,
    "average": True,
    "bags": 1,
}


def load_items(name: str) -> list[dict[str, Any]]:
    # WP25b review: the guard sits here, not only in main(), so no caller (the CV tool, a test, a
    # script) can read a sealed file through this helper; a ValueError survives python -O.
    if name not in TRAINING_POOLS:
        raise ValueError(f"{name!r} is not a training pool (the other sets are sealed)")
    path = DATA / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def unit_of(item: dict[str, Any]) -> tuple[str, str]:
    """(surface, text) of the unit the item's label is about."""
    payload = dict(item["payload"])
    payload["meta"] = item["meta"]
    surf = item["surface"]
    for u in U.collect(payload, item["direction"]):
        if u.surface == surf:
            return surf, u.text
    return surf, ""


class Sample:
    __slots__ = ("surface", "label", "wins", "hard")

    def __init__(self, surface: str, label: int, wins: list[array], hard: bool = False) -> None:
        self.surface, self.label, self.wins, self.hard = surface, label, wins, hard


def make_samples(items: list[dict[str, Any]]) -> list[Sample]:
    out = []
    for it in items:
        surf, text = unit_of(it)
        wins = (
            [array("I", ids) for var in F.variant_feature_sets(text, surf) for ids in var]
            if text
            else []
        )
        out.append(
            Sample(surf, int(it["label"]), wins or [array("I")], it["category"] == "benign-hard")
        )
    return out


def train_one(
    samples: list[Sample], hyper: dict[str, Any], seed: int, log: bool = True
) -> LinearModel:
    rng = random.Random(seed)  # noqa: S311 - seeded shuffle, not security
    w = [0.0] * F.TOTAL
    g2 = [0.0] * F.TOTAL
    bias = {s: 0.0 for s in SURFACES}
    gb = {s: 0.0 for s in SURFACES}
    lr, l2, eps = hyper["lr"], hyper["l2"], hyper["eps"]
    order = list(range(len(samples)))
    acc_w = [0.0] * F.TOTAL
    acc_b = {k: 0.0 for k in SURFACES}
    n_acc = 0
    for epoch in range(hyper["epochs"]):
        rng.shuffle(order)
        loss = 0.0
        for k in order:
            s = samples[k]
            best, best_z, best_n = None, -1e18, 1
            for ids in s.wins:
                sw = sc = 0.0
                n = 0
                for i in ids:
                    if i < F.BUCKETS:
                        sw += w[i]
                        n += 1
                    else:
                        sc += w[i]
                z = bias[s.surface] + (sw / math.sqrt(n) if n else 0.0) + sc * F.CONCEPT_SCALE
                if z > best_z:
                    best, best_z, best_n = ids, z, n
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, best_z))))
            y = s.label
            loss += -math.log(max(1e-9, p if y else 1 - p))
            err = (p - y) * (
                hyper["pos_weight"] if y else (hyper["hard_weight"] if s.hard else 1.0)
            )
            gb[s.surface] += err * err
            bias[s.surface] -= lr * 0.1 * err / (math.sqrt(gb[s.surface]) + eps)
            inv = 1.0 / math.sqrt(best_n) if best_n else 0.0
            for i in best:  # type: ignore[union-attr]
                g = err * (inv if i < F.BUCKETS else F.CONCEPT_SCALE) + l2 * w[i]
                g2[i] += g * g
                w[i] -= lr * g / (math.sqrt(g2[i]) + eps)
        if hyper.get("average") and epoch >= 1:  # average the weights of epochs 2..N
            n_acc += 1
            for i in range(F.TOTAL):
                if w[i]:
                    acc_w[i] += w[i]
            for k in SURFACES:
                acc_b[k] += bias[k]
        if log:
            print(f"  epoch {epoch + 1:>2}/{hyper['epochs']}  mean loss {loss / len(order):.4f}")
    if n_acc:
        w = [x / n_acc for x in acc_w]
        bias = {k: v / n_acc for k, v in acc_b.items()}
    ints = [int(round(x * SCALE)) for x in w]
    b_int = {s: int(round(bias[s] * SCALE)) for s in SURFACES}
    return LinearModel(VERSION, ints, b_int, {})


def train(samples: list[Sample], hyper: dict[str, Any], seed: int, log: bool = True) -> LinearModel:
    """One model, or the average of ``bags`` models each fitted on a seeded 80 percent subsample
    (bagging by weight averaging: the logit of the average is the average of the logits)."""
    bags = int(hyper.get("bags", 1))
    if bags <= 1:
        return train_one(samples, hyper, seed, log)
    rng = random.Random(seed + 101)  # noqa: S311 - seeded subsampling, not security
    models = []
    for b in range(bags):
        sub = rng.sample(samples, max(1, len(samples) * 4 // 5))
        models.append(train_one(sub, hyper, seed + b, log=False))
        if log:
            print(f"  bag {b + 1}/{bags} done")
    n = len(models)
    weights = [sum(m.weights[i] for m in models) // n for i in range(F.TOTAL)]
    bias = {k: sum(m.bias[k] for m in models) // n for k in SURFACES}
    return LinearModel(VERSION, weights, bias, {})


def scores_bp(model: LinearModel, samples: list[Sample]) -> list[int]:
    out = []
    for s in samples:
        best = -1e18
        for ids in s.wins:
            best = max(best, model.window_logit(list(ids), s.surface))
        out.append(sigmoid_bp(best))
    return out


def threshold_table(scores: list[int], labels: list[int]) -> list[dict[str, int]]:
    pos = [s for s, y in zip(scores, labels, strict=True) if y]
    neg = [s for s, y in zip(scores, labels, strict=True) if not y]
    rows = []
    for t in range(2000, 10001, 250):
        rows.append(
            {
                "threshold_bp": t,
                "recall_bp": sum(s >= t for s in pos) * 10000 // max(1, len(pos)),
                "false_alarm_bp": sum(s >= t for s in neg) * 10000 // max(1, len(neg)),
            }
        )
    return rows


def pick(rows: list[dict[str, int]], max_fa_bp: int) -> int:
    for r in rows:
        if r["false_alarm_bp"] <= max_fa_bp:
            return r["threshold_bp"]
    return 10000


def build_card(
    model: LinearModel,
    wsha: str,
    hyper: dict[str, Any],
    thresholds: dict[str, Any],
    pools: dict[str, int],
    seed: int,
    oof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = {
        name: {
            "path": f"data/eval/injection_vi_en/{name}.jsonl",
            "sha256": hashlib.sha256((DATA / f"{name}.jsonl").read_bytes()).hexdigest(),
            "n_items": n,
        }
        for name, n in pools.items()
    }
    sealed = json.loads((DATA / "SEALED.json").read_text(encoding="utf-8"))["sha256"]
    return {
        "model_id": MODEL_NAME,
        "version": model.version,
        "weights_file": "weights.json",
        "weights_sha256": wsha,
        "format": "linear logistic regression over hashed character n-gram, word, stem and concept features (pure Python)",
        "feature_version": F.FEATURE_VERSION,
        "buckets": F.TOTAL,
        "scale": SCALE,
        "surfaces": list(SURFACES),
        "licence": "synthetic, this repo (weights derived from synthetic data only)",
        "owner_roles": {
            "model_owner": "FILL-ME (MRM_MODEL_OWNER)",
            "model_developer": "FILL-ME (MRM_MODEL_DEVELOPER)",
            "validator": "FILL-ME (MRM_VALIDATOR)",
            "approver": "FILL-ME (MRM_APPROVER)",
        },
        "approval": {
            "approver": "FILL-ME (MRM_APPROVER)",
            "weights_sha256": None,
            "note": "fail_closed for the classifier is honoured only when CLASSIFIER_FAIL_CLOSED_APPROVED=1 and "
            "this block names an approver and the weights_sha256 approved (it must equal the loaded weights)",
        },
        "intended_use": (
            "Advisory score for prompt injection (direct, indirect, tool poisoning) in Vietnamese and "
            "English in tool arguments, tool results and tool descriptions. It may only PAUSE money and "
            "credit tools above the frozen pause threshold, and only through GATE-CLASSIFIER-PAUSE "
            "(a human resumes). It never blocks (R1)."
        ),
        "out_of_scope": [
            "languages other than Vietnamese and English",
            "image, audio or file content",
            "multi-turn attacks (WP27)",
            "any use as the only control",
        ],
        "training": {
            "files": files,
            "data_note": (
                "the card hashes are those of the committed files; the files were committed before the "
                "final run (WP25b closes review finding F6)"
            ),
            "labeller": "synthetic (templates written for this repo); most items use templates reworded offline by the local LLM ('synthetic, LLM-paraphrased')",
            "seed": seed,
            "hyperparameters": hyper,
            "command": "uv run python -m tools.cross_validate --thresholds-out T.json; uv run python -m tools.train_classifier --thresholds T.json",
            "selection": "grouped cross-validation, leave-one-pool-out over train, dev and train_b (data/eval/injection_vi_en/WP25B_PROTOCOL.md)",
        },
        "thresholds_bp": thresholds,
        "thresholds_note": (
            "per surface, from the out-of-fold scores of the 3 folds: strict = false alarm <= 800 bp, "
            "balanced <= 500 bp, lenient <= 300 bp, pause (global) <= 50 bp; rounded up to 50 bp. "
            "The final weights are trained on all three pools, so scores run a little higher than in "
            "the folds. ILLUSTRATIVE until the bank sets them."
        ),
        "oof_summary": oof or {},
        "sealed_sets": sealed,
        "validation": {"status": "not validated yet; run python -m supervisor.detectors.harness"},
        "known_limits": [
            "trained on synthetic template text: real attacks are less regular",
            "spaced-out letters and other languages are not recognised",
            "a long document dilutes a short instruction (windows of 150 characters, max over windows; text over 12000 characters keeps head, tail and the cue-richest middle segments)",
            "no state across calls: split attacks need the caller to pass prior calls",
        ],
        "change_log": [
            {
                "version": "1.0.0",
                "change": "first model (feat-2), trained on train.jsonl, thresholds from dev",
            },
            {
                "version": model.version,
                "change": "feat-3: surface weight blocks, instruction-form cues, stems, typo tolerance, plausibility decoding; new training pool train_b; thresholds per surface from out-of-fold scores",
            },
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tools.train_classifier",
        description="Train the injection_vi_en linear classifier (stdlib only, deterministic).",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="folder for weights.json (default: data/models/...)"
    )
    ap.add_argument("--epochs", type=int, default=HYPER["epochs"])
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument(
        "--pools",
        default="train,dev,train_b",
        help="comma list of pools to fit (never a sealed one)",
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="use only the first N training items (tests)"
    )
    ap.add_argument(
        "--thresholds",
        type=Path,
        default=None,
        help="JSON written by tools.cross_validate --thresholds-out (needed to write the card)",
    )
    ap.add_argument("--no-card", action="store_true", help="do not write model_card.json")
    args = ap.parse_args(argv)
    hyper = dict(HYPER, epochs=args.epochs)
    names = [x for x in args.pools.split(",") if x]
    if not set(names) <= TRAINING_POOLS:
        print("[FAIL] only the training pools may be fitted (the others are sealed)")
        return 2
    items: list[dict[str, Any]] = []
    sizes: dict[str, int] = {}
    for name in names:
        got = load_items(name)
        if args.limit:
            got = got[: args.limit]
        sizes[name] = len(got)
        items += got
    print(f"[..] features for {len(items)} items from {names}")
    samples = make_samples(items)
    print("[..] training")
    model = train(samples, hyper, args.seed)
    out = args.out or (MODELS_DIR / VERSION)
    wpath = write_model(model, out)
    wsha = sha256_file(wpath)
    print(f"[OK] weights: {wpath}  sha256={wsha}  nonzero={sum(1 for x in model.weights if x)}")
    if not args.no_card:
        if args.thresholds is None:
            print("[FAIL] --thresholds is needed to write the card (or pass --no-card)")
            return 2
        th = json.loads(args.thresholds.read_text(encoding="utf-8"))
        thresholds = {k: th[k] for k in ("strict", "balanced", "lenient", "pause")}
        card = build_card(model, wsha, hyper, thresholds, sizes, args.seed, th.get("oof"))
        (out / "model_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"[OK] card: {out / 'model_card.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
