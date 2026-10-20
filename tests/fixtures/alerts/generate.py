"""Deterministic generator of the alert-rule fixtures (WP21).

    python tests/fixtures/alerts/generate.py            # rewrite the committed files
    python tests/fixtures/alerts/generate.py --check    # fail if the committed files differ

Two splits, same structure, different seeds and agent names:
  dev      seed 2101, used to choose thresholds in config/alerts.yaml
  heldout  seed 2121, never used to tune anything

Each split: 500 synthetic gate decisions (about 90 percent allow) plus noise of every other
signal kind, and 6 planted incidents. A signal line is
``{"id","kind","ts","f":{...},"lane","seq","entry_hash","label"}`` where ``label`` is the
incident id or null (ground truth for the harness; the rule engine never reads it).

Planted incidents and the alerts each one must raise (and nothing else may fire):
  INC-1 runaway agent   8 blocks in 6 min, then a quarantine   AL-BLOCK-BURST + AL-QUARANTINE
  INC-2 chain tamper    a failed chain verify, repeated 10 min later   AL-CHAIN-VERIFY-FAIL
  INC-3 judge escalation  one real tier 2 verdict             AL-JUDGE-ESCALATION
  INC-4 credential stuffing  24 ingress rejects in 276 s       AL-INGRESS-REJECT-AGENT + -BURST
  INC-5 job failure     the "drift" job fails twice, 15 min apart   AL-JOB-FAILURE
  INC-6 drill failure   the fail-closed drill fails           AL-FAILCLOSED-DRILL-FAIL

Hard negatives (must NOT fire): 4 blocks in 9 min for one agent, 5 blocks over 20 min for
another, a pause (not a quarantine), a mock tier 2 verdict, a tier 1 verdict, 12 spread ingress
rejects in 5 min, good chain verifies, a good drill, successful job runs.
Everything is synthetic. Licence: same as the repository (MIT). Labeller: synthetic.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
T0 = datetime(2026, 10, 19, 8, 0, 0, tzinfo=UTC)
SPAN_S = 4 * 3600
N_DECISIONS = 500

SPLITS = {
    "dev": {"seed": 2101, "agents": [f"dev-agent-{i:02d}" for i in range(12)]},
    "heldout": {"seed": 2121, "agents": [f"ho-agent-{i:02d}" for i in range(12)]},
}


def _ts(offset_s: float) -> str:
    return (T0 + timedelta(seconds=offset_s)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"


class Builder:
    def __init__(self, agents: list[str]) -> None:
        self.agents = agents
        self.rows: list[dict[str, Any]] = []
        self.seq: dict[str, int] = {}

    def add(
        self,
        kind: str,
        t: float,
        fields: dict[str, Any],
        label: str | None = None,
        lane: str | None = None,
    ) -> None:
        lane = lane or fields.get("agent_id") or "root"
        n = self.seq.get(lane, 0)
        self.seq[lane] = n + 1
        sid = f"{lane}:{n}" if kind not in ("verdict", "job_run") else f"{kind}:{len(self.rows)}"
        row: dict[str, Any] = {
            "id": sid,
            "kind": kind,
            "ts": _ts(t),
            "f": fields,
            "label": label,
        }
        if kind not in ("verdict", "job_run"):
            row.update(
                lane=lane,
                seq=n,
                entry_hash=hashlib.sha256(f"{lane}|{n}|{kind}".encode()).hexdigest(),
            )
        self.rows.append(row)

    def decision(self, t: float, agent: str, action: str, label: str | None = None) -> None:
        self.add(
            "gate_decision",
            t,
            {
                "agent_id": agent,
                "action": action,
                "rule_id": "PAY-08" if action == "block" else None,
                "allow": action != "block",
            },
            label,
        )


def build(split: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = SPLITS[split]
    rnd = random.Random(cfg["seed"])
    agents: list[str] = cfg["agents"]
    b = Builder(agents)
    a = list(agents)
    rnd.shuffle(a)
    runaway, near1, near2, judged, others = a[0], a[1], a[2], a[3], a[4:]

    # --- incident times: spread over the span, away from the edges
    slots = sorted(rnd.sample(range(1200, SPAN_S - 1800, 900), 6))
    rnd.shuffle(slots)
    t1, t2, t3, t4, t5, t6 = (float(s) + rnd.randint(0, 300) for s in slots)

    # INC-1: 8 blocks in 6 minutes, then quarantine
    for i in range(8):
        b.decision(t1 + i * 51.0, runaway, "block", "INC-1")
    b.add(
        "gate_state_change",
        t1 + 8 * 51.0 + 20,
        {"agent_id": runaway, "event": "quarantine", "to_state": "QUARANTINED"},
        "INC-1",
    )
    # INC-2: failed verify, repeated 10 minutes later
    b.add("chain_verify", t2, {"ok": False}, "INC-2", lane="root")
    b.add("chain_verify", t2 + 600, {"ok": False}, "INC-2", lane="root")
    # INC-3: one real tier 2 verdict
    b.add(
        "verdict",
        t3,
        {
            "agent_id": judged,
            "tier": 2,
            "label": "suspicious",
            "action": "alert",
            "rule_id": None,
            "is_mock": False,
        },
        "INC-3",
    )
    # INC-4: 24 ingress rejects in 276 s. Every third one hits one agent (8 rejects: the
    # per-agent rule fires), the rest are spread over 7 other agents (at most 3 each), and the
    # global count reaches 20 (the global rule fires).
    victim, spread = others[3], [x for x in others if x != others[3]]
    k = 0
    for i in range(24):
        if i % 3 == 0:
            agent = victim
        else:
            agent = spread[k % len(spread)]
            k += 1
        b.add(
            "ingress_reject",
            t4 + i * 12.0,
            {"agent_id": agent, "reason_code": "bad_signature"},
            "INC-4",
            lane="ingress",
        )
    # INC-5: the drift job fails twice
    b.add("job_run", t5, {"job": "drift", "status": "error"}, "INC-5")
    b.add("job_run", t5 + 900, {"job": "drift", "status": "error"}, "INC-5")
    # INC-6: fail-closed drill fails
    b.add("failmode_drill", t6, {"ok": False}, "INC-6", lane="root")

    # --- hard negatives
    n0 = rnd.randint(1500, 3000)
    for i in range(4):  # 4 blocks in 9 minutes: below the threshold
        b.decision(n0 + i * 180.0, near1, "block")
    n1 = rnd.randint(7000, 9000)
    for i in range(5):  # 5 blocks over 20 minutes: window not met
        b.decision(n1 + i * 300.0, near2, "block")
    b.add(
        "gate_state_change",
        rnd.randint(3000, 5000),
        {"agent_id": others[0], "event": "pause", "to_state": "PAUSED"},
    )
    b.add(
        "verdict",
        rnd.randint(3000, 5000),
        {
            "agent_id": others[1],
            "tier": 2,
            "label": "suspicious",
            "action": "alert",
            "rule_id": None,
            "is_mock": True,
        },
    )
    b.add(
        "verdict",
        rnd.randint(3000, 5000),
        {
            "agent_id": others[2],
            "tier": 1,
            "label": "suspicious",
            "action": "alert",
            "rule_id": None,
            "is_mock": False,
        },
    )
    n2 = rnd.randint(13500, 13700)  # after every incident slot: no overlap with INC-4
    for i in range(12):  # 12 spread rejects in 4 minutes: below the global 20, at most 2 each
        b.add(
            "ingress_reject",
            n2 + i * 20.0,
            {"agent_id": others[i % len(others)], "reason_code": "expired"},
            lane="ingress",
        )
    for i in range(4):  # 4 rejects of one agent in 30 s: below the per-agent 5
        b.add(
            "ingress_reject",
            14100.0 + i * 10.0,
            {"agent_id": near1, "reason_code": "expired"},
            lane="ingress",
        )
    for k in range(6):
        b.add("chain_verify", 600.0 + k * 2400, {"ok": True}, lane="root")
    b.add("failmode_drill", 5000.0, {"ok": True}, lane="root")
    for k in range(30):
        b.add(
            "job_run",
            300.0 + k * 480,
            {"job": rnd.choice(["ingest", "anchor", "drift"]), "status": "ok"},
        )

    # --- fill to N_DECISIONS gate decisions: allows, plus a few isolated blocks
    have = sum(1 for r in b.rows if r["kind"] == "gate_decision")
    last_block: dict[str, float] = {}
    t = 0.0
    while have < N_DECISIONS:
        t = rnd.uniform(0, SPAN_S)
        agent = rnd.choice(others)
        action = "allow"
        if rnd.random() < 0.04 and t - last_block.get(agent, -9999) > 5000:
            action = "block"  # isolated: far from any other block of this agent
            last_block[agent] = t
        elif rnd.random() < 0.02:
            action = "alert"
        b.decision(t, agent, action)
        have += 1
    # isolated random blocks may sit near a planted/near-miss agent only if that agent is in
    # `others`, which it is not, so no extra burst can form.
    b.rows.sort(key=lambda r: (r["ts"], r["id"]))

    expected = {
        "split": split,
        "incidents": [
            {
                "id": "INC-1",
                "alerts": [
                    {"rule_id": "AL-BLOCK-BURST", "group": runaway, "suppressed": 3},
                    {"rule_id": "AL-QUARANTINE", "group": runaway, "suppressed": 0},
                ],
            },
            {
                "id": "INC-2",
                "alerts": [{"rule_id": "AL-CHAIN-VERIFY-FAIL", "group": "*", "suppressed": 1}],
            },
            {
                "id": "INC-3",
                "alerts": [{"rule_id": "AL-JUDGE-ESCALATION", "group": judged, "suppressed": 0}],
            },
            {
                "id": "INC-4",
                "alerts": [
                    {"rule_id": "AL-INGRESS-REJECT-AGENT", "group": victim, "suppressed": 3},
                    {"rule_id": "AL-INGRESS-REJECT-BURST", "group": "*", "suppressed": 4},
                ],
            },
            {
                "id": "INC-5",
                "alerts": [{"rule_id": "AL-JOB-FAILURE", "group": "drift", "suppressed": 1}],
            },
            {
                "id": "INC-6",
                "alerts": [{"rule_id": "AL-FAILCLOSED-DRILL-FAIL", "group": "*", "suppressed": 0}],
            },
        ],
        "n_gate_decisions": N_DECISIONS,
        "n_signals": len(b.rows),
    }
    return b.rows, expected


def render(split: str) -> dict[str, str]:
    rows, expected = build(split)
    jsonl = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows)
    return {
        f"{split}.signals.jsonl": jsonl,
        f"{split}.expected.json": json.dumps(expected, indent=2, sort_keys=True) + "\n",
    }


def main(argv: list[str]) -> int:
    check = "--check" in argv
    bad = 0
    for split in SPLITS:
        for name, text in render(split).items():
            path = HERE / name
            if check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    print(f"[FAIL] {name} differs from the generator")
                    bad += 1
            else:
                path.write_text(text, encoding="utf-8", newline="\n")
                print(f"[OK] wrote {name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
