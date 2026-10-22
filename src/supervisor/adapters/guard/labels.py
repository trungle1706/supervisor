"""Label and score normalisation shared by the guard adapters (WP-D3)."""

from __future__ import annotations

from typing import Any

from supervisor.core.errors import GuardModelError
from supervisor.core.ports import GuardScore

BENIGN = frozenset({"benign", "safe", "legit", "legitimate", "label_0", "0", "none", "clean"})
JAILBREAK = frozenset({"jailbreak", "jail_break", "direct_injection"})
INDIRECT = frozenset({"injection", "indirect_injection", "prompt_injection", "indirect"})
MALICIOUS = frozenset({"malicious", "unsafe", "attack", "label_1", "1", "harmful"})


def bp_from_probability(value: Any) -> int:
    """A probability in [0, 1] as basis points. Anything else is a bad answer."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GuardModelError("guard model answered a score that is not a number")
    if not 0.0 <= float(value) <= 1.0:
        raise GuardModelError("guard model answered a score outside 0 to 1")
    return int(round(float(value) * 10_000))


def normalise_label(label: Any) -> str:
    """``benign | jailbreak | indirect_injection | malicious``; an unknown label is an error
    (a wrong label map must show up, not pass as benign)."""
    key = str(label).strip().lower().replace("-", "_").replace(" ", "_")
    if key in BENIGN:
        return "benign"
    if key in JAILBREAK:
        return "jailbreak"
    if key in INDIRECT:
        return "indirect_injection"
    if key in MALICIOUS:
        return "malicious"
    raise GuardModelError("guard model answered a label this version does not know")


def top_attack(entries: list[tuple[str, int]]) -> GuardScore:
    """From ``(label, score_bp)`` pairs of ONE text: the strongest attack label. When only the
    benign class is listed, the rest of its mass is the attack score (``malicious``)."""
    attacks = [(lab, bp) for lab, bp in entries if lab != "benign"]
    if attacks:
        lab, bp = max(attacks, key=lambda x: x[1])
        return {"label": lab, "score_bp": bp}  # type: ignore[typeddict-item]
    benign = max((bp for lab, bp in entries if lab == "benign"), default=10_000)
    rest = 10_000 - benign
    if rest <= 0:
        return {"label": "benign", "score_bp": 0}
    return {"label": "malicious", "score_bp": rest}
