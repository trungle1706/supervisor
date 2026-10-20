"""Identity of the tiered judge for model-risk management (WP19).

The *validated unit* is the tiered judge (Tier 1 monitor + Tier 2 judge) as one model:
two model ids/versions, two prompt templates, one rubric. A validation record
(``model_validation`` table) is keyed by three strings, all computed here:

* ``model_version``  composite: ``t1=<model_id>@<version>;t2=<model_id>@<version>``.
  A change of either tier's model id or version is a new model version.
* ``prompt_hash``    SHA-256 over the Tier 1 and Tier 2 prompt hashes
  (``judge.prompts.prompt_hash``: templates + output schema + policy catalog + version).
* ``rubric_version`` ``RUBRIC_VERSION`` plus a 12-hex digest of what the rubric is made
  of: the label set, the policy catalog and the Tier 1 / Tier 2 thresholds. Editing any
  of them changes the string even if nobody bumps ``RUBRIC_VERSION``.

The mask version and the golden-set hash are recorded on the validation row but are not
part of the key: validation runs on synthetic, already-masked eval traces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.judge.prompts import LABELS, POLICY_CATALOG, PROMPT_VERSION, prompt_hash

JUDGE_ID = "judge.tiered"
RUBRIC_VERSION = "judge-rubric-v1"

# Files whose bytes define the golden / eval data version (relative to the repo root).
GOLDEN_FILES: tuple[str, ...] = (
    "agents/redteam/incidents.jsonl",
    "data/golden/golden_set.jsonl",
    "data/golden/judge_injection_templates.jsonl",
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def composite_prompt_hash(t1_hash: str | None = None, t2_hash: str | None = None) -> str:
    """SHA-256 of ``t1:<hash>|t2:<hash>`` (defaults: the current templates)."""
    h1 = t1_hash if t1_hash is not None else prompt_hash(1)
    h2 = t2_hash if t2_hash is not None else prompt_hash(2)
    return _sha(f"t1:{h1}|t2:{h2}")


def rubric_version(t1_threshold_bp: int, t2_threshold_bp: int) -> str:
    """``RUBRIC_VERSION`` + digest of labels, policy catalog and the two thresholds."""
    blob = json.dumps(
        {
            "v": RUBRIC_VERSION,
            "labels": list(LABELS),
            "policies": [list(p) for p in POLICY_CATALOG],
            "t1_threshold_bp": int(t1_threshold_bp),
            "t2_threshold_bp": int(t2_threshold_bp),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return f"{RUBRIC_VERSION}+{_sha(blob)[:12]}"


def composite_model_version(
    t1_model_id: str, t1_version: str, t2_model_id: str, t2_version: str
) -> str:
    return f"t1={t1_model_id}@{t1_version};t2={t2_model_id}@{t2_version}"


def golden_set_hash(root: Path | None = None) -> str:
    """SHA-256 over the eval data files (name + bytes). A missing file hashes as 'missing'."""
    base = root or REPO_ROOT
    h = hashlib.sha256()
    for rel in GOLDEN_FILES:
        p = base / rel
        h.update(rel.encode("utf-8") + b"\0")
        h.update(p.read_bytes() if p.is_file() else b"missing")
        h.update(b"\0")
    return h.hexdigest()


@dataclass(frozen=True)
class JudgeIdentity:
    judge_id: str
    t1_model_id: str
    t1_model_version: str
    t1_family: str
    t1_family_source: str
    t2_model_id: str
    t2_model_version: str
    t2_family: str
    t2_family_source: str
    is_mock: bool
    prompt_version: str
    t1_prompt_hash: str
    t2_prompt_hash: str
    prompt_hash: str  # composite
    model_version: str  # composite
    rubric_version: str
    mask_version: str
    golden_set_hash: str

    def key(self) -> tuple[str, str, str]:
        """What a passing validation record must match: (model_version, prompt_hash, rubric)."""
        return (self.model_version, self.prompt_hash, self.rubric_version)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def identity_from_router(
    router: Any,
    *,
    t1_threshold_bp: int,
    t2_threshold_bp: int,
    mask_version: str,
    golden_root: Path | None = None,
) -> JudgeIdentity:
    """Identity of a ``JudgeRouter`` (reads ``router.t1`` / ``router.t2`` JudgeModel)."""
    t1, t2 = router.t1, router.t2
    h1, h2 = prompt_hash(1), prompt_hash(2)
    return JudgeIdentity(
        judge_id=JUDGE_ID,
        t1_model_id=t1.model_id,
        t1_model_version=t1.model_version,
        t1_family=t1.family,
        t1_family_source=t1.family_source,
        t2_model_id=t2.model_id,
        t2_model_version=t2.model_version,
        t2_family=t2.family,
        t2_family_source=t2.family_source,
        is_mock=bool(router.is_mock),
        prompt_version=PROMPT_VERSION,
        t1_prompt_hash=h1,
        t2_prompt_hash=h2,
        prompt_hash=composite_prompt_hash(h1, h2),
        model_version=composite_model_version(
            t1.model_id, t1.model_version, t2.model_id, t2.model_version
        ),
        rubric_version=rubric_version(t1_threshold_bp, t2_threshold_bp),
        mask_version=mask_version,
        golden_set_hash=golden_set_hash(golden_root),
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, str):  # Databricks returns strings
        return value.strip().lower() in ("true", "1")
    return bool(value)


def same_key(record: Mapping[str, Any], ident: JudgeIdentity) -> bool:
    """True when a ``model_validation`` row is for this identity (any decision)."""
    key = (
        str(record.get("model_version")),
        str(record.get("prompt_hash")),
        str(record.get("rubric_version")),
    )
    return key == ident.key()


def matches(record: Mapping[str, Any], ident: JudgeIdentity) -> bool:
    """True when a ``model_validation`` row is a passing (GO) record for this identity."""
    return (
        same_key(record, ident)
        and _truthy(record.get("passed"))
        and str(record.get("decision")) == "GO"
    )


__all__ = [
    "GOLDEN_FILES",
    "JUDGE_ID",
    "RUBRIC_VERSION",
    "JudgeIdentity",
    "composite_model_version",
    "composite_prompt_hash",
    "golden_set_hash",
    "identity_from_router",
    "matches",
    "same_key",
    "rubric_version",
]
