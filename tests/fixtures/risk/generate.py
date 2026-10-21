"""Writes tests/fixtures/risk/golden.jsonl: 50 synthetic risk scenarios (WP29).

    python tests/fixtures/risk/generate.py          # rewrite golden.jsonl
    python tests/fixtures/risk/generate.py --check # exit 1 when the file on disk differs

The expected values are computed here by a small, separate reference implementation (plain loops,
no import from supervisor.risk), so the scenarios test the product code against an independent
statement of the rubric and not against itself. Rubrics:

* "operational risk manager": a score is likelihood x impact and a band is read from the
  thresholds; an agent is as risky as the worst risk it can reach; a risk that is retired,
  draft, on a retired component or behind an inactive link must not count; a mitigated risk is
  only as low as the facts prove.
* "internal auditor (Three Lines)": a lowered residual score needs working evidence and a
  recorded reason; a broken or removed control must raise the score again; every link must
  point at something that exists today.

Splits: 30 dev, 20 held-out (never tune on held-out). Labeller: synthetic (reference
implementation below) under the two expert rubrics. Source and licence: written for WP29, repo
licence. No real names, no real data. Thresholds are ILLUSTRATIVE.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOW_MAX, MED_MAX, HIGH_MAX = 4, 9, 15  # ILLUSTRATIVE (config/risk.yaml)
RANK = {None: 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def band(score: int) -> str:
    if score <= LOW_MAX:
        return "low"
    if score <= MED_MAX:
        return "medium"
    if score <= HIGH_MAX:
        return "high"
    return "critical"


def worst(*bands: str | None) -> str | None:
    return max(bands, key=lambda b: RANK[b], default=None)


# ----------------------------------------------------------------------------- inherit reference


def inherit_reference(scn: dict) -> dict:
    """Naive fixpoint: an agent's level is the worst band of every active risk on any node it
    reaches through active 'uses' edges; nodes marked gone hold nothing."""
    nodes = {(k, n): s for k, n, s in scn["nodes"]}
    uses: dict[tuple, set] = {}
    for sk, sn, dk, dn, ek, active in scn["edges"]:
        if ek == "uses" and active:
            uses.setdefault((sk, sn), set()).add((dk, dn))
    out = {}
    agents = [(k, n) for (k, n), _ in nodes.items() if k == "system"]
    for ag in agents:
        reach = {ag}
        changed = True
        while changed:
            changed = False
            for a in list(reach):
                for b in uses.get(a, ()):
                    if b not in reach:
                        reach.add(b)
                        changed = True
        inh, res = None, None
        for r in scn["risks"]:
            anchor = tuple(r["anchor"])
            if r["status"] != "active" or nodes.get(anchor, "active") == "gone":
                continue
            if anchor in reach or (anchor not in nodes and anchor == ag):
                inh = worst(inh, band(r["l"] * r["i"]))
                res = worst(res, band(r["rl"] * r["ri"]))
        out[ag[1]] = [inh, res]
    # a loose agent (no node in the graph) that owns a risk
    for r in scn["risks"]:
        anchor = tuple(r["anchor"])
        if anchor[0] == "system" and anchor not in nodes and r["status"] == "active":
            out[anchor[1]] = [band(r["l"] * r["i"]), band(r["rl"] * r["ri"])]
    return {"agents": out}


# ----------------------------------------------------------------------------- evidence reference


def evidence_reference(it: dict) -> dict:
    c = {k: 0 for k in ("agents_n", "controls_working", "controls_failing", "controls_idle")}
    c.update({k: 0 for k in ("rule_links", "pack_links", "monitor_links")})
    c.update(it["counts"])
    links = c["rule_links"] + c["pack_links"] + c["monitor_links"]
    inh = tuple(it["inherent"])
    dec = tuple(it["declared"])
    minw = it.get("min_working", 1)
    if c["agents_n"] == 0 and links > 0:
        state, reason = "no_evidence", "no_supervised_agent"
    elif c["controls_failing"] > 0:
        state, reason = "failing", "control_failing"
    elif links == 0:
        state, reason = "no_evidence", "no_links"
    elif c["controls_working"] >= minw:
        state, reason = "working", "controls_working"
    else:
        state, reason = "no_evidence", "no_working_control"
    if it["treatment"] != "mitigate":
        return {"state": state, "reason": "treatment_declared", "residual": list(dec)}
    return {"state": state, "reason": reason, "residual": list(dec if state == "working" else inh)}


# ----------------------------------------------------------------------------- the 50 scenarios


def risk(anchor, lik, imp, rl=None, ri=None, status="active"):
    return {
        "anchor": anchor, "l": lik, "i": imp, "rl": rl or lik, "ri": ri or imp, "status": status,
    }  # fmt: skip


def agent(name):
    return ["system", name, "active"]


def build() -> list[dict]:
    items: list[dict] = []

    def add(task, split, rubric, inp, expected, note):
        items.append(
            {
                "id": f"RG-{len(items) + 1:03d}",
                "split": split,
                "task": task,
                "source": "synthetic (WP29)",
                "licence": "repo licence",
                "labeller": "synthetic reference implementation + expert rubric",
                "rubric": rubric,
                "note": note,
                "input": inp,
                "expected": expected,
            }
        )

    orm = "operational risk manager"
    aud = "internal auditor (Three Lines)"

    # --- score: 20 (12 dev, 8 held-out), boundaries of every band included
    pairs = [
        (1, 1), (2, 2), (1, 4), (2, 2), (1, 5), (2, 3), (3, 3), (4, 2), (2, 5), (3, 4),
        (5, 2), (4, 4), (3, 5), (4, 5), (5, 4), (5, 5), (1, 3), (2, 4), (5, 1), (3, 2),
    ]  # fmt: skip
    for n, (lik, imp) in enumerate(pairs):
        add(
            "score",
            "dev" if n % 5 < 3 else "held_out",
            orm,
            {"likelihood": lik, "impact": imp},
            {"score": lik * imp, "band": band(lik * imp)},
            f"{lik} x {imp}",
        )

    # --- inherit: 12 (7 dev, 5 held-out)
    def inherit(split, note, nodes, edges, risks):
        scn = {"nodes": nodes, "edges": edges, "risks": risks}
        add("inherit", split, orm, scn, inherit_reference(scn), note)

    def U(sk, sn, dk, dn, active=True, kind="uses"):
        return [sk, sn, dk, dn, kind, active]

    inherit(
        "dev", "own risk on the agent itself",
        [agent("a1")], [], [risk(["system", "a1"], 4, 4)],
    )  # fmt: skip
    inherit(
        "dev", "shared model endpoint: both agents inherit a critical risk",
        [agent("a1"), agent("a2"), ["model_endpoint", "m1", "active"]],
        [U("system", "a1", "model_endpoint", "m1"), U("system", "a2", "model_endpoint", "m1")],
        [risk(["model_endpoint", "m1"], 4, 5)],
    )  # fmt: skip
    inherit(
        "dev", "tool uses an MCP server: the agent inherits through two hops",
        [agent("a1"), ["tool", "t1", "active"], ["mcp_server", "s1", "active"]],
        [U("system", "a1", "tool", "t1"), U("tool", "t1", "mcp_server", "s1")],
        [risk(["mcp_server", "s1"], 3, 4)],
    )  # fmt: skip
    inherit(
        "dev", "a 'reads' edge carries no risk",
        [agent("a1"), ["dataset", "d1", "active"]],
        [U("system", "a1", "dataset", "d1", kind="reads")],
        [risk(["dataset", "d1"], 5, 5)],
    )  # fmt: skip
    inherit(
        "dev", "cycle between two tools: terminates, agent inherits the cycle risk",
        [agent("a1"), ["tool", "t1", "active"], ["tool", "t2", "active"]],
        [
            U("system", "a1", "tool", "t1"),
            U("tool", "t1", "tool", "t2"),
            U("tool", "t2", "tool", "t1"),
        ],
        [risk(["tool", "t2"], 3, 5)],
    )  # fmt: skip
    inherit(
        "dev", "a component retired in the inventory (gone) passes nothing up",
        [agent("a1"), ["tool", "t1", "gone"]],
        [U("system", "a1", "tool", "t1")],
        [risk(["tool", "t1"], 5, 5)],
    )  # fmt: skip
    inherit(
        "dev", "an inactive edge passes nothing up",
        [agent("a1"), ["tool", "t1", "active"]],
        [U("system", "a1", "tool", "t1", active=False)],
        [risk(["tool", "t1"], 5, 5)],
    )  # fmt: skip
    inherit(
        "held_out", "draft and retired risks do not count; the active one does",
        [agent("a1"), ["tool", "t1", "active"]],
        [U("system", "a1", "tool", "t1")],
        [
            risk(["tool", "t1"], 5, 5, status="draft"),
            risk(["tool", "t1"], 5, 5, status="retired"),
            risk(["tool", "t1"], 2, 2),
        ],
    )  # fmt: skip
    inherit(
        "held_out", "two risks on one node: the worse counts",
        [agent("a1"), ["tool", "t1", "active"]],
        [U("system", "a1", "tool", "t1")],
        [risk(["tool", "t1"], 2, 3), risk(["tool", "t1"], 4, 4)],
    )  # fmt: skip
    inherit(
        "held_out", "residual lower than inherent: the two levels differ",
        [agent("a1")], [], [risk(["system", "a1"], 5, 5, 2, 2)],
    )  # fmt: skip
    inherit(
        "held_out", "agent with no node in the graph still owns its risk",
        [agent("a1")], [], [risk(["system", "loose"], 4, 3)],
    )  # fmt: skip
    inherit(
        "held_out", "diamond: two paths to one risk, an unrelated agent is not affected",
        [
            agent("a1"), agent("a2"),
            ["tool", "t1", "active"], ["tool", "t2", "active"], ["model", "mm", "active"],
        ],
        [
            U("system", "a1", "tool", "t1"),
            U("system", "a1", "tool", "t2"),
            U("tool", "t1", "model", "mm"),
            U("tool", "t2", "model", "mm"),
        ],
        [risk(["model", "mm"], 3, 3)],
    )  # fmt: skip

    # --- evidence: 12 (7 dev, 5 held-out)
    def evid(split, note, treatment, inherent, declared, counts, min_working=1):
        it = {
            "treatment": treatment,
            "inherent": inherent,
            "declared": declared,
            "counts": counts,
            "min_working": min_working,
        }
        add("evidence", split, aud, it, evidence_reference(it), note)

    evid("dev", "a rule hit proves the control: residual may fall to the declared value",
         "mitigate", [4, 5], [2, 5],
         {"agents_n": 1, "rule_links": 1, "controls_working": 1})  # fmt: skip
    evid("dev", "a linked rule that never fired proves nothing: residual stays inherent",
         "mitigate", [4, 5], [2, 5],
         {"agents_n": 1, "rule_links": 1, "controls_idle": 1})  # fmt: skip
    evid("dev", "a linked rule that no longer exists is a failing control",
         "mitigate", [4, 5], [2, 5],
         {"agents_n": 1, "rule_links": 1, "controls_failing": 1})  # fmt: skip
    evid("dev", "a failed pack beats a working rule",
         "mitigate", [3, 4], [2, 3],
         {"agents_n": 2, "rule_links": 1, "pack_links": 1, "controls_working": 1,
          "controls_failing": 1})  # fmt: skip
    evid("dev", "no control linked: nothing to prove the claim",
         "mitigate", [3, 3], [2, 2], {"agents_n": 1})  # fmt: skip
    evid("dev", "only SHADOW or retired agents: no supervised agent",
         "mitigate", [3, 3], [2, 2],
         {"agents_n": 0, "rule_links": 1, "controls_idle": 1})  # fmt: skip
    evid(
        "dev",
        "accept keeps the declared residual (equal to inherent by validation)",
        "accept",
        [2, 3],
        [2, 3],
        {"agents_n": 1, "rule_links": 1, "controls_working": 1},
    )
    evid("held_out", "avoid keeps the declared residual even without evidence",
         "avoid", [4, 4], [1, 4], {"agents_n": 1})  # fmt: skip
    evid(
        "held_out",
        "transfer keeps the declared residual",
        "transfer",
        [3, 5],
        [3, 2],
        {"agents_n": 1, "monitor_links": 1, "controls_idle": 1},
    )
    evid("held_out", "two controls required: one working is not enough",
         "mitigate", [4, 4], [2, 3],
         {"agents_n": 1, "rule_links": 1, "pack_links": 1, "controls_working": 1,
          "controls_idle": 1}, min_working=2)  # fmt: skip
    evid("held_out", "two controls required and two working",
         "mitigate", [4, 4], [2, 3],
         {"agents_n": 1, "rule_links": 1, "monitor_links": 1, "controls_working": 2},
         min_working=2)  # fmt: skip
    evid("held_out", "a working monitor alone is enough when one control is required",
         "mitigate", [3, 4], [2, 4],
         {"agents_n": 1, "monitor_links": 1, "controls_working": 1})  # fmt: skip

    # --- link: 6 (4 dev, 2 held-out)
    def link(split, kind, target, ok, note):
        add("link", split, aud, {"kind": kind, "target": target}, {"exists": ok}, note)

    link("dev", "rule", "PAY-02", True, "rule of the baseline policy")
    link("dev", "rule", "PAY-99", False, "no such rule")
    link("dev", "matrix", "VN-TT50-2024-A10.1-01", True, "obligation of the regulation base")
    link("dev", "matrix", "VN-TT50-2099-A1-01", False, "no such obligation")
    link("held_out", "pack", "owasp_agentic_redteam", True, "assurance pack manifest")
    link("held_out", "monitor", "no_such_monitor", False, "no such monitor")
    return items


def render() -> str:
    items = build()
    assert len(items) == 50, len(items)
    assert sum(1 for i in items if i["split"] == "dev") == 30
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
