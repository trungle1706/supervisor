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
VERSION = "1.0.0"
HYPER = {
    "epochs": 6,
    "lr": 0.03,
    "l2": 1e-4,
    "eps": 1e-6,
    "pos_weight": 1.0,
    "hard_weight": 2.0,
    "average": True,
}


def load_items(name: str) -> list[dict[str, Any]]:
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
            [array("I", ids) for var in F.variant_feature_sets(text) for ids in var] if text else []
        )
        out.append(
            Sample(surf, int(it["label"]), wins or [array("I")], it["category"] == "benign-hard")
        )
    return out


def train(samples: list[Sample], hyper: dict[str, Any], seed: int, log: bool = True) -> LinearModel:
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
    thresholds: dict[str, int],
    sizes: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    manifest = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
    return {
        "model_id": MODEL_NAME,
        "version": model.version,
        "weights_file": "weights.json",
        "weights_sha256": wsha,
        "format": "linear logistic regression over hashed character n-gram features (pure Python)",
        "feature_version": F.FEATURE_VERSION,
        "buckets": F.BUCKETS,
        "scale": SCALE,
        "surfaces": list(SURFACES),
        "licence": "synthetic, this repo (weights derived from synthetic data only)",
        "owner_roles": {
            "model_owner": "FILL-ME (MRM_MODEL_OWNER)",
            "model_developer": "FILL-ME (MRM_MODEL_DEVELOPER)",
            "validator": "FILL-ME (MRM_VALIDATOR)",
            "approver": "FILL-ME (MRM_APPROVER)",
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
            "data": "data/eval/injection_vi_en/train.jsonl",
            "data_sha256": manifest["train.jsonl"]["sha256"],
            "n_items": sizes["train"],
            "dev_data_sha256": manifest["dev.jsonl"]["sha256"],
            "labeller": "synthetic (templates written for this repo); most items use templates reworded offline by the local LLM ('synthetic, LLM-paraphrased')",
            "seed": seed,
            "hyperparameters": hyper,
            "command": "uv run python -m tools.train_classifier",
        },
        "thresholds_bp": thresholds,
        "thresholds_note": "chosen on the dev split by false-alarm rate; ILLUSTRATIVE until the bank sets them",
        "validation": {"status": "not validated yet; run python -m supervisor.detectors.harness"},
        "known_limits": [
            "trained on synthetic template text: real attacks are less regular",
            "spaced-out letters and other languages are not recognised",
            "a long document dilutes a short instruction (windows of 150 characters, max over windows; text over 12000 characters keeps head, tail and the cue-richest middle segments)",
            "no state across calls: split attacks need the caller to pass prior calls",
        ],
        "change_log": [{"version": model.version, "change": "first model"}],
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
        "--limit", type=int, default=0, help="use only the first N training items (tests)"
    )
    ap.add_argument("--no-card", action="store_true", help="do not write model_card.json")
    args = ap.parse_args(argv)
    hyper = dict(HYPER, epochs=args.epochs)
    train_items = load_items("train")
    if args.limit:
        train_items = train_items[: args.limit]
    dev_items = load_items("dev")
    print(f"[..] features for {len(train_items)} train and {len(dev_items)} dev items")
    tr, dv = make_samples(train_items), make_samples(dev_items)
    print("[..] training")
    model = train(tr, hyper, args.seed)
    out = args.out or (MODELS_DIR / VERSION)
    wpath = write_model(model, out)
    wsha = sha256_file(wpath)
    labels = [s.label for s in dv]
    sc = scores_bp(model, dv)
    rows = threshold_table(sc, labels)
    print("threshold_bp  recall_bp  false_alarm_bp   (dev split)")
    for r in rows:
        print(f"{r['threshold_bp']:>12} {r['recall_bp']:>10} {r['false_alarm_bp']:>15}")
    suggest = {
        # the selection rule of the model card (thresholds_note): the lowest threshold whose dev
        # false alarm is at most 800 / 500 / 300 / 50 bp
        "strict": pick(rows, 800),
        "balanced": pick(rows, 500),
        "lenient": pick(rows, 300),
        "pause": pick(rows, 50),
    }
    print(f"suggested thresholds (dev false alarm <= 800 / 500 / 300 / 50 bp): {suggest}")
    print(f"[OK] weights: {wpath}  sha256={wsha}  nonzero={sum(1 for x in model.weights if x)}")
    if not args.no_card:
        thresholds = (
            json.loads((out / "model_card.json").read_text(encoding="utf-8"))["thresholds_bp"]
            if (out / "model_card.json").is_file()
            else suggest
        )
        card = build_card(model, wsha, hyper, thresholds, {"train": len(train_items)}, args.seed)
        (out / "model_card.json").write_text(
            json.dumps(card, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"[OK] card: {out / 'model_card.json'} (thresholds_bp from {'the old card' if (out / 'model_card.json').is_file() else 'this run'})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
