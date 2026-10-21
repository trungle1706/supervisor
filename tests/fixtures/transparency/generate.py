"""Writes tests/fixtures/transparency/golden.jsonl: 54 synthetic report scenarios (WP31).

    python tests/fixtures/transparency/generate.py          # rewrite golden.jsonl
    python tests/fixtures/transparency/generate.py --check  # exit 1 when the file on disk differs

A scenario is (demo agent, variant, profile). The profile sets the facts: all sources on, risk
register off, inventory off, a chain check that fails, a chain check that passes, two open
cases. The expected values are written here from a plain statement of the rubric (which
sections a variant may show, when a section is empty, which words the not-shown list must hold),
without importing supervisor.transparency, so the product code is checked against a separate
statement and not against itself. Two expert rubrics:

* "regulator inspector (SBV)": every Decision 33 class and obligation id the report relies on is
  cited; a gap (flag off, no data, mock judge, failed chain check) is stated and never implied;
  a hash lets the inspector check the file.
* "data protection officer": the customer version holds no agent id, rule id, obligation id,
  hash or person; personal data in a case title never appears raw; a name in a model card is
  not copied to the regulator or customer version.

Splits: dev agents payments and customer_service (36 scenarios), held-out agent credit_prequal
(18). Never tune on held-out. Labeller: synthetic (this reference). Source and licence: written
for WP31, repo licence. Workspace: tests/fixtures/inventory/workspace_7.json (WP24) plus the
three demo agents' manifests. Thresholds are ILLUSTRATIVE.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
AGENTS = {
    # agent: (split, Decision 33 class the matrix gives it, kind word the customer text uses)
    "payments": ("dev", "high_risk", "payment"),
    "customer_service": ("dev", "needs_answer", "customer_facing"),
    "credit_prequal": ("held_out", "high_risk", "credit_decision"),
}
VARIANTS = ("regulator", "customer", "internal")
# Profiles in the order the harness runs them: ``cases2`` changes the store, so it is last.
PROFILES = ("base", "risk_off", "inventory_off", "chain_fail", "verified", "cases2")
SECTIONS = (
    "identity", "classification", "inventory", "compliance", "cards", "assurance",
    "judge_mrm", "masking", "monitors", "risks", "controls", "evidence", "cases", "backlog",
    "not_shown",
)  # fmt: skip
# which sections each variant may show at all (the allow-list rubric)
SHOWN = {
    "regulator": set(SECTIONS) - {"backlog"},
    "internal": set(SECTIONS),
    "customer": {
        "identity", "classification", "assurance", "masking", "monitors", "risks", "evidence",
        "not_shown",
    },
}  # fmt: skip


def d33_ids() -> list[str]:
    """Obligation ids of the Decision 33 list that name the two high-risk entries (the report
    cites them): read straight from the regulation file."""
    text = (REPO / "regulations" / "vn" / "decision-33-2026.yaml").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r"VN-QD33-2026-PL4\.[12]-\d\d", text)))
    assert len(ids) == 6, ids
    return ids


def expected(agent: str, variant: str, profile: str) -> dict:
    cls = AGENTS[agent][1]
    inv_on = profile != "inventory_off"
    risk_on = profile != "risk_off"
    avail = {
        "identity": True,
        "classification": True,
        "inventory": inv_on,
        "compliance": True,
        "cards": True,
        "assurance": False,  # no assurance run in the fixture workspace
        "judge_mrm": True,
        "masking": True,
        "monitors": True,
        "risks": risk_on,
        "controls": False,  # WP30 is merged but CONTROLS_ENABLED is off in the fixtures
        "evidence": True,
        "cases": True,
        "backlog": True,
        "not_shown": True,
    }
    avail = {s: (avail[s] if s in SHOWN[variant] else False) for s in SECTIONS}
    verify = {"chain_fail": "failed", "verified": "ok"}.get(profile, "not_run")
    has: list[str] = ["advisory_only" if variant != "customer" else "section_not_for_variant"]
    lacks: list[str] = []
    if variant != "customer":
        # controls: section_flag_off (CONTROLS_ENABLED), since the WP30 merge
        has += ["section_flag_off", "judge_advice_only", "mock_judge", "no_personal_data"]
        lacks.append("section_not_built")
    if not inv_on and variant != "customer":
        has.append("section_flag_off")
    if not risk_on:
        has.append("section_flag_off")
    if verify == "failed":
        has.append("chain_verify_failed")
    elif verify == "not_run":
        has.append("chain_not_verified")
    else:
        lacks += ["chain_verify_failed", "chain_not_verified"]
    if variant == "customer":
        lacks.append("mock_judge")
    text_has: list[str] = []
    text_lacks: list[str] = []
    if variant == "regulator":
        text_has += ["{agent_id}", *d33_ids()[:2]]
        text_lacks += ["{owner_user}"]
    if variant == "internal":
        text_has += ["{agent_id}"]
    if variant == "customer":
        text_lacks += ["{agent_id}", "{owner_user}", "{owner_team}", "VN-QD33", "PAY-0", "CRD-0"]
    return {
        "avail": avail,
        "verify_state": verify,
        "d33_class": cls,
        "open_cases": (2 if profile == "cases2" else 0) if variant != "customer" else None,
        "d33_ids_cited": 6 if variant != "customer" else None,
        "not_shown_has": sorted(set(has)),
        "not_shown_lacks": sorted(set(lacks)),
        "text_has": text_has,
        "text_lacks": text_lacks,
    }


def build() -> list[dict]:
    items = []
    n = 0
    for agent, (split, _, _) in AGENTS.items():
        for profile in PROFILES:
            for variant in VARIANTS:
                n += 1
                items.append(
                    {
                        "id": f"tr-{n:03d}",
                        "source": "synthetic: demo agent manifests + inventory workspace_7",
                        "licence": "repo licence",
                        "labeller": "synthetic reference (generate.py)",
                        "rubric": "data protection officer"
                        if variant == "customer"
                        else "regulator inspector (SBV)",
                        "split": split,
                        "task": "report",
                        "agent": agent,
                        "variant": variant,
                        "profile": profile,
                        "expected": expected(agent, variant, profile),
                    }
                )
    return items


def render() -> str:
    items = build()
    assert len(items) == 54, len(items)
    assert sum(1 for i in items if i["split"] == "dev") == 36
    return "".join(json.dumps(i, sort_keys=True) + "\n" for i in items)


def main(argv: list[str]) -> int:
    text = render()
    target = HERE / "golden.jsonl"
    if "--check" in argv:
        return 0 if target.read_text(encoding="utf-8") == text else 1
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] wrote {target} ({len(text.splitlines())} scenarios)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
