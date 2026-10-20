"""The linear model: weight file, integrity check, scoring (WP25, ADR D27).

A model is a JSON file ``data/models/injection_vi_en/<version>/weights.json`` plus a model card
``model_card.json`` in the same folder. The card holds the SHA-256 of the weight file. The loader
REFUSES a weight file whose SHA-256 differs from the card, whose feature version differs from
``features.FEATURE_VERSION``, or whose version differs from the card (``ModelIntegrityError``).

Weights are integers (scale ``SCALE``), so the sum over features is exact whatever the order.
The only float steps are one square root and divisions (IEEE 754, correctly rounded on every
platform); the exponential of the sigmoid uses ``decimal`` (correctly rounded, platform
independent) and the result is rounded to an integer score in basis points. Same input, same
weights: same score (tested).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.detectors.injection_classifier import features as F

MODEL_NAME = "injection_vi_en"
MODEL_FORMAT = "injection_vi_en-linear-1"
MODELS_DIR = REPO_ROOT / "data" / "models" / MODEL_NAME
SCALE = 10_000  # integer weights = round(w * SCALE)
SURFACES: tuple[str, ...] = ("args", "tool_results", "tool_description")


class ModelIntegrityError(RuntimeError):
    """The weight file does not match its card (hash, version or feature version)."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sigmoid_bp(z: float) -> int:
    """10000 * sigmoid(z) rounded half-even to an integer. The exponential is computed with the
    ``decimal`` module (correctly rounded, the same on every platform) rather than the C library
    ``exp``, whose last bit may differ between platforms (WP25 review)."""
    if z >= 30:
        return 10_000
    if z <= -30:
        return 0
    with localcontext() as ctx:
        ctx.prec = 34
        value = Decimal(10_000) / (1 + (-Decimal(z)).exp())
        return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def logit(sum_w: int, n: int, bias: int, sum_c: int = 0) -> float:
    """Logit of one window: bias + (sum of n-gram weights) / sqrt(number of n-gram features) +
    (sum of concept weights, not normalised)."""
    if n <= 0:
        return (bias + sum_c) / SCALE
    return (bias + sum_w / math.sqrt(n) + sum_c) / SCALE


@dataclass(frozen=True)
class Scored:
    score_bp: int
    logit: float
    variant: int  # index of the variant that gave the maximum
    window: int  # index of the window in that variant


class LinearModel:
    """Hashed character n-gram features, one weight per bucket, one bias per surface."""

    def __init__(
        self, version: str, weights: list[int], bias: dict[str, int], meta: dict[str, Any]
    ) -> None:
        self.version = version
        self.weights = weights
        self.bias = bias
        self.meta = meta

    # ------------------------------------------------------------------ scoring
    def window_logit(self, ids: tuple[int, ...] | list[int], surface: str) -> float:
        w = self.weights
        sw = sc = n = 0
        for i in ids:
            if i < F.BUCKETS:
                sw += w[i]
                n += 1
            else:
                sc += w[i]
        return logit(sw, n, self.bias[surface], sc * F.CONCEPT_SCALE)

    def score_variants(
        self, variants: list[list[list[int]]], surface: str
    ) -> tuple[float, int, int]:
        """(best logit, variant index, window index) over variants and windows."""
        best = (-1e9, 0, 0)
        for vi, wins in enumerate(variants):
            for wi, ids in enumerate(wins):
                z = self.window_logit(ids, surface)
                if z > best[0]:
                    best = (z, vi, wi)
        return best

    def cheap_score(self, segment: str, surface: str) -> int:
        """First-stage score of a text segment, used to choose which parts of a long text to read:
        the concept weights of its concept features (no n-grams) times 100, plus its cue-word count.
        An integer; deterministic."""
        from supervisor.detectors.injection_classifier import concepts as C

        ids = [F.BUCKETS + i for i in C.concept_features(F.plain_form(segment), surface)]
        return sum(self.weights[i] for i in ids) * 100 // SCALE + F.cue_count(segment)

    def score_text(self, text: str, surface: str) -> Scored:
        """Score one text (all its variants and windows). Texts too short score the bias."""
        if not F.usable(text):
            z = self.bias[surface] / SCALE
            return Scored(sigmoid_bp(z), z, 0, 0)
        rank = None
        if len(text) > F.MAX_UNIT_CHARS:  # long text: choose middle segments by a cheap model score
            rank = lambda seg: self.cheap_score(seg, surface)  # noqa: E731
        z, vi, wi = self.score_variants(F.variant_feature_sets(text, surface, rank), surface)
        return Scored(sigmoid_bp(z), z, vi, wi)

    def score_bp(self, text: str, surface: str) -> int:
        return self.score_text(text, surface).score_bp

    # ------------------------------------------------------------------ files
    def to_json(self) -> str:
        sparse = {str(i): w for i, w in enumerate(self.weights) if w}
        doc = {
            "format": MODEL_FORMAT,
            "feature_version": F.FEATURE_VERSION,
            "version": self.version,
            "buckets": F.TOTAL,
            "scale": SCALE,
            "bias": {k: self.bias[k] for k in SURFACES},
            "meta": self.meta,
            "weights": sparse,
        }
        return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def model_dir(version: str, base: Path | None = None) -> Path:
    return (base or MODELS_DIR) / version


def write_model(model: LinearModel, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "weights.json"
    path.write_text(model.to_json(), encoding="utf-8", newline="\n")
    return path


def load_model(version: str, base: Path | None = None) -> LinearModel:
    """Load ``<base>/<version>/weights.json`` after checking it against ``model_card.json``."""
    d = model_dir(version, base)
    wpath, cpath = d / "weights.json", d / "model_card.json"
    try:
        card = json.loads(cpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelIntegrityError(f"model card unreadable: {type(exc).__name__}") from exc
    try:
        raw = wpath.read_bytes()
    except OSError as exc:
        raise ModelIntegrityError(f"weight file unreadable: {type(exc).__name__}") from exc
    want = str(card.get("weights_sha256", ""))
    got = hashlib.sha256(raw).hexdigest()
    if not want or got != want:
        raise ModelIntegrityError("weight file sha256 differs from the model card: refused")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ModelIntegrityError("weight file is not valid JSON") from exc
    if doc.get("format") != MODEL_FORMAT:
        raise ModelIntegrityError("unknown weight file format")
    if doc.get("version") != version or card.get("version") != version:
        raise ModelIntegrityError("model version differs between folder, card and weights")
    if doc.get("feature_version") != F.FEATURE_VERSION or doc.get("buckets") != F.TOTAL:
        raise ModelIntegrityError("weights were made with another feature version: refused")
    if doc.get("scale") != SCALE:
        raise ModelIntegrityError("weight scale differs")
    weights = [0] * F.TOTAL
    for k, v in doc["weights"].items():
        i = int(k)
        if not 0 <= i < F.TOTAL or type(v) is not int:
            raise ModelIntegrityError("bad weight entry")
        weights[i] = v
    bias = doc["bias"]
    if set(bias) != set(SURFACES) or any(type(v) is not int for v in bias.values()):
        raise ModelIntegrityError("bad bias entry")
    return LinearModel(version, weights, dict(bias), dict(doc.get("meta", {})))
