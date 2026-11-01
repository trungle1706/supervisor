"""W3: executive findings of the risk assessment (ORCH_EXEC_FINDINGS, ORCH_EXEC_LLM).

Layer A (rules) is tested with synthetic facts for every key of the shared vocabulary and with the
stored reports of the demo; Layer B (model rewrite) with fake models, never the network."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.governance import risk_dimensions as rd
from supervisor.onboard import executive as ex

DEMO = Path(__file__).parent / "data" / "w3_demo"


def fact(kind: str, name: str, detail: str = "", file: str = "code/a.py", line: int = 7) -> dict:
    return {
        "fact_id": f"f{abs(hash((kind, name))) % 10**6}",
        "node_id": "n1",
        "attempt_n": 1,
        "kind": kind,
        "name": name,
        "detail": detail,
        "file": file,
        "line": line,
        "quote": "SECRET-QUOTE-VALUE",
        "source": "rule",
        "confidence": "high",
    }


def facts_of(*rows: dict) -> dict:
    return {"version": 1, "nodes": ["n1"], "facts": list(rows)}


SYS = {
    "human_control": "pre_approval",
    "personal_data": "identifiable",
    "risk_level": "unspecified",
}
GATE = [
    fact(
        "tool", "transfer", "risk_class=money; approved=yes; reversibility: not reversible", line=49
    ),
    fact(
        "autonomy",
        "L3",
        "tools with side effects and no human approval step in code: transfer",
        line=50,
    ),
]


def keys(facts: Mapping | None, system: Mapping | None = None) -> set[str]:
    return {o["key"] for o in ex.observations(facts, system if system is not None else SYS)}


def obs(key: str, facts: Mapping, system: Mapping | None = None) -> dict:
    found = [o for o in ex.observations(facts, system or SYS) if o["key"] == key]
    assert len(found) == 1, key
    return found[0]


# ------------------------------------------------------------------ Layer A: every fact key


def test_money_tool_no_gate() -> None:
    o = obs("money_tool_no_gate", facts_of(*GATE))
    assert o["status"] == "fail" and o["severity"] == "high" and o["owner"] == "system_owner"
    assert set(o["dims"]) == {"cybersecurity", "ethics", "legal_compliance"}
    en = o["headline"]["en"]
    assert "payments (transfer)" in en and "no approval step" in en
    assert "although the registration says every action is approved first" in en
    assert o["fact_refs"] == ["code/a.py:49", "code/a.py:50"]
    assert "cannot take a payment back" in o["impact"]["en"]
    # the registration clause only when the registration says pre-approval
    o2 = obs("money_tool_no_gate", facts_of(*GATE), {**SYS, "human_control": "none"})
    assert "although" not in o2["headline"]["en"]
    # the decision33 gate flag alone fires it too
    d33 = fact("decision33", "high_risk", "proposal only; human_gate_in_code=False")
    assert "money_tool_no_gate" in keys(facts_of(GATE[0], d33))
    # no money tool, or a gate: no finding
    assert "money_tool_no_gate" not in keys(facts_of(GATE[1]))
    assert "money_tool_no_gate" not in keys(
        facts_of(GATE[0], fact("autonomy", "L2", "a human approves every step"))
    )


def test_declared_control_mismatch() -> None:
    f = facts_of(GATE[1])
    o = obs("declared_control_mismatch", f)
    assert o["status"] == "fail" and "transfer" in o["headline"]["en"]
    assert set(o["dims"]) == {"legal_compliance", "ethics"}
    assert "declared_control_mismatch" in keys(f, {**SYS, "human_control": "post_review"})
    assert "declared_control_mismatch" not in keys(f, {**SYS, "human_control": "none"})
    assert "declared_control_mismatch" not in keys(facts_of(fact("autonomy", "L1", "read only")))


def test_personal_data_fields() -> None:
    rows = [
        fact("claim", "Handles personal data field 'payee_name'", "category=personal_data"),
        fact("claim", "Handles personal data field 'cccd'", "category=personal_data"),
        fact("claim", "purpose", "Agent 1"),
    ]
    o = obs("personal_data_fields", facts_of(*rows))
    assert o["dims"] == ["data_governance"] and o["status"] == "open"
    assert o["severity"] == "high"  # an identity number
    assert "2 personal data fields: payee_name, cccd" in o["headline"]["en"]
    assert "identity numbers (cccd)" in o["headline"]["en"]
    assert "số định danh" in o["headline"]["vi"]
    plain = obs("personal_data_fields", facts_of(rows[0]))
    assert plain["severity"] == "medium" and "identity" not in plain["headline"]["en"]
    assert "personal_data_fields" not in keys(facts_of(rows[2]))


def test_personal_data_mismatch() -> None:
    rows = [fact("claim", "Handles personal data field 'email'", "category=personal_data")]
    assert "personal_data_mismatch" not in keys(facts_of(*rows))
    o = obs("personal_data_mismatch", facts_of(*rows), {**SYS, "personal_data": "none"})
    assert o["status"] == "fail" and set(o["dims"]) == {"data_governance", "legal_compliance"}
    assert o["owner_by_dim"] == {"legal_compliance": "legal"}


def test_pii_export_tool() -> None:
    row = fact(
        "tool", "add_payee", "risk_class=pii_export; reversibility: disclosure cannot be recalled"
    )
    o = obs("pii_export_tool", facts_of(row))
    assert set(o["dims"]) == {"data_governance", "cybersecurity"}
    assert "add_payee" in o["headline"]["en"] and "cannot be recalled" in o["headline"]["en"]
    assert "pii_export_tool" not in keys(facts_of(fact("tool", "x", "risk_class=read_only")))


def test_model_unknown() -> None:
    rows = [
        fact("endpoint", "qwen3.8-27b-int4", "family=unknown; declared in code"),
        fact("model", "unknown", "provider=openai; family=unknown; via=ChatOpenAI"),
    ]
    o = obs("model_unknown", facts_of(*rows))
    assert set(o["dims"]) == {"model", "supply_chain", "third_party"}
    assert "(qwen3.8-27b-int4)" in o["headline"]["en"] and "(unknown)" not in o["headline"]["en"]
    assert o["owner_by_dim"]["third_party"] == "risk_team"
    assert "model_unknown" not in keys(facts_of(fact("model", "gpt", "family=openai")))


def test_no_tracing() -> None:
    row = fact("weak_spot", "No tracing found (no OpenTelemetry or MLflow use): Watch needs it")
    o = obs("no_tracing", facts_of(row))
    assert set(o["dims"]) == {"model", "cybersecurity"} and o["owner"] == "system_owner"
    assert "no_tracing" not in keys(facts_of(fact("weak_spot", "Something else")))


def test_hardcoded_secret() -> None:
    o = obs("hardcoded_secret", facts_of(fact("secret_use", "aws_access_key", "kind only")))
    assert o["status"] == "fail" and o["dims"] == ["cybersecurity"] and o["owner"] == "security"
    assert "aws_access_key" in o["headline"]["en"]
    assert "hardcoded_secret" not in keys(facts_of(fact("tool", "x", "")))


def test_external_endpoint() -> None:
    rows = [
        fact("external_url", "http://127.0.0.1:8001/v1", "an address"),
        fact("external_url", "https://FILL-ME-workspace-host/serving", "an address"),
        fact("external_url", "http://localhost/x", "an address"),
    ]
    assert "external_endpoint" not in keys(facts_of(*rows))
    rows.append(fact("external_url", "https://api.vendor.example/v1", "an address"))
    o = obs("external_endpoint", facts_of(*rows))
    assert set(o["dims"]) == {"third_party", "cybersecurity"}
    assert "api.vendor.example" in o["headline"]["en"] and "127.0.0.1" not in o["headline"]["en"]


def test_risk_level_mismatch() -> None:
    row = fact(
        "decision33", "high_risk", "proposal only, counsel confirms; human_gate_in_code=True"
    )
    o = obs("risk_level_mismatch", facts_of(row))
    assert o["dims"] == ["legal_compliance"] and "not set" in o["headline"]["en"]
    assert (
        "medium"
        in obs("risk_level_mismatch", facts_of(row), {**SYS, "risk_level": "medium"})["headline"][
            "en"
        ]
    )
    assert "risk_level_mismatch" not in keys(facts_of(row), {**SYS, "risk_level": "high"})
    assert "risk_level_mismatch" not in keys(
        facts_of(fact("decision33", "not_high_risk", "x")), SYS
    )


def test_no_facts_no_observations() -> None:
    assert ex.observations(None, SYS) == [] and ex.observations({"facts": []}, None) == []


def test_every_fact_key_is_covered_by_a_test() -> None:
    assert set(ex.FACT_KEYS) == {
        "money_tool_no_gate",
        "declared_control_mismatch",
        "personal_data_fields",
        "personal_data_mismatch",
        "pii_export_tool",
        "model_unknown",
        "no_tracing",
        "hardcoded_secret",
        "external_endpoint",
        "risk_level_mismatch",
    }


def test_no_value_or_quote_reaches_the_text() -> None:
    rows = [
        *GATE,
        fact("secret_use", "api_key", "kind only"),
        fact("claim", "Handles personal data field 'cccd'", "category=personal_data"),
    ]
    blob = json.dumps(ex.observations(facts_of(*rows), SYS), ensure_ascii=False)
    assert "SECRET-QUOTE-VALUE" not in blob


# ------------------------------------------------------------------ Layer A: report findings


def _report(dim: str, findings: list[dict]) -> dict:
    n = {v: sum(1 for f in findings if f["verdict"] == v) for v in ("pass", "fail", "question")}
    return {
        "dimension_id": dim,
        "findings": findings,
        "created_at": "2026-10-28T09:00:00Z",
        "summary": {"passed": n["pass"], "failed": n["fail"], "questions": n["question"]},
    }


def _pack(pid: str, verdict: str, rationale: str = "") -> dict:
    return {
        "finding_id": f"f-{pid}",
        "checklist_id": f"pack:{pid}",
        "verdict": verdict,
        "evidence": [],
        "rationale": rationale or f"Required test {pid} has not been run yet.",
        "confidence": "low",
    }


def test_tests_missing_is_one_item_with_meaning() -> None:
    rep = _report(
        "cybersecurity",
        [_pack("owasp_agentic_redteam", "question"), _pack("prefilter_evasion", "question")],
    )
    doc = ex.build("cybersecurity", rep, None, None)
    assert [i["key"] for i in doc["items"]] == ["tests_missing"]
    it = doc["items"][0]
    assert it["status"] == "open" and it["finding_ids"] == [
        "f-owasp_agentic_redteam",
        "f-prefilter_evasion",
    ]
    assert it["owner"] == "security"
    assert (
        "2 required tests have not been run yet (agent attack, filter evasion)"
        in it["headline"]["en"]
    )
    assert "does not mean the agent is unsafe" in it["impact"]["en"]
    assert doc["rating"] == "open"  # no evidence is not a finding about the code
    assert "pii" not in it["headline"]["en"].lower()


def test_tests_missing_never_claims_a_code_weakness() -> None:
    rep = _report("data_governance", [_pack("pii_canary", "question")])
    doc = ex.build("data_governance", rep, None, None)
    text = json.dumps(doc["items"][0]["headline"]) + json.dumps(doc["items"][0]["impact"])
    assert "has not been run yet" in text and "no PII protection" not in text
    assert "no evidence" in text.lower() or "no test evidence" in text.lower()


def test_stale_tests_are_worded_as_out_of_date() -> None:
    rep = _report(
        "model",
        [
            _pack(
                "truthfulqa_vi",
                "question",
                "Required test truthfulqa_vi is out of date. Run it again.",
            )
        ],
    )
    it = ex.build("model", rep, None, None)["items"][0]
    assert "no current result" in it["headline"]["en"]


def test_tests_failed_is_high_and_rates_the_type() -> None:
    rep = _report(
        "data_governance", [_pack("pii_canary", "fail", "Required test pii_canary failed.")]
    )
    doc = ex.build("data_governance", rep, None, None)
    it = doc["items"][0]
    assert it["key"] == "tests_failed" and it["status"] == "fail" and it["severity"] == "high"
    assert doc["rating"] == "high"
    assert "leaks planted personal data" in it["impact"]["en"]


def test_optional_missing_tests_are_not_listed() -> None:
    rep = _report("model", [_pack("simpleqa_vi", "question")])
    assert ex.build("model", rep, None, None)["items"] == []


def test_reads_and_person_items() -> None:
    reads = lambda d, v: {  # noqa: E731
        "finding_id": f"reads-{d}",
        "checklist_id": f"reads:{d}",
        "verdict": v,
        "evidence": [],
        "rationale": "x",
        "confidence": "high",
    }
    person = {
        "finding_id": "person-decides",
        "checklist_id": "person:decides",
        "verdict": "question",
        "evidence": [],
        "rationale": "x",
        "confidence": "high",
    }
    rep = _report("legal_compliance", [reads("model", "question"), reads("ethics", "fail"), person])
    doc = ex.build("legal_compliance", rep, None, None)
    by = {i["key"]: i for i in doc["items"]}
    assert set(by) == {"depends_open", "depends_failed", "person_decides"}
    assert by["depends_failed"]["status"] == "fail" and by["depends_failed"]["owner"] == "legal"
    assert "(model)" in by["depends_open"]["headline"]["en"]
    assert by["person_decides"]["severity"] == "low"
    assert [i["key"] for i in doc["items"]][0] == "depends_failed"  # fail before open
    assert doc["rating"] == "high"


def test_catalogue_covers_every_pack_and_monitor() -> None:
    cfg = yaml.safe_load(Path(rd.DEFAULT_CONFIG).read_text(encoding="utf-8"))
    ids = {m["id"] for d in cfg["dimensions"] for m in d["measured_by"]}
    assert ids and ids <= set(ex.TESTS), sorted(ids - set(ex.TESTS))
    for pid, (en, vi, cen, cvi, owner) in ex.TESTS.items():
        assert en and vi and cen and cvi and owner in ex.OWNERS, pid


def test_generic_fallback_for_an_unknown_checklist_id() -> None:
    f = {
        "finding_id": "x1",
        "checklist_id": "ZZ-01",
        "verdict": "fail",
        "evidence": [{"kind": "fact", "ref": "r", "file": "code/x.py", "line": 3}],
        "rationale": "The code stores the card number in a log.",
        "confidence": "high",
    }
    doc = ex.build("cybersecurity", _report("cybersecurity", [f]), None, None)
    it = doc["items"][0]
    assert it["key"] == "check_zz_01" and it["status"] == "fail"
    assert it["headline"]["en"] == "The code stores the card number in a log."
    assert it["fact_refs"] == ["code/x.py:3"] and it["finding_ids"] == ["x1"]


def test_agent_checklist_executive_block_is_used_and_merged_by_key() -> None:
    block = {
        "key": "money_tool_no_gate",
        "headline_fail": {"en": "H fail", "vi": "H fail vi"},
        "headline_open": {"en": "H open", "vi": "H open vi"},
        "impact": {"en": "I", "vi": "I vi"},
        "action": {"en": "A", "vi": "A vi"},
        "owner": "security",
    }
    definition = {"checklist": [{"id": "CY-06", "severity": "high", "executive": block}]}
    f = {
        "finding_id": "g1",
        "checklist_id": "CY-06",
        "verdict": "fail",
        "evidence": [],
        "rationale": "r",
        "confidence": "high",
    }
    rep = _report("cybersecurity", [f])
    alone = ex.build("cybersecurity", rep, None, SYS, definition)["items"][0]
    assert alone["headline"]["en"] == "H fail" and alone["owner"] == "security"
    assert alone["finding_ids"] == ["g1"]
    op = {**f, "verdict": "question"}
    assert (
        ex.build("cybersecurity", _report("cybersecurity", [op]), None, SYS, definition)["items"][
            0
        ]["headline"]["en"]
        == "H open"
    )
    # with the same key from the facts, one item: the text of the facts, the id of the finding
    doc = ex.build("cybersecurity", rep, facts_of(*GATE), SYS, definition)
    mine = [i for i in doc["items"] if i["key"] == "money_tool_no_gate"]
    assert len(mine) == 1 and mine[0]["finding_ids"] == ["g1"]
    assert "payments (transfer)" in mine[0]["headline"]["en"]
    # a broken block falls back to the generic text
    bad = {"checklist": [{"id": "CY-06", "severity": "low", "executive": {"key": "k"}}]}
    it = ex.build("cybersecurity", rep, None, SYS, bad)["items"][0]
    assert it["key"] == "check_cy_06" and it["severity"] == "low"


def test_rank_dedupe_cap_and_rating() -> None:
    rows = [
        *GATE,
        fact("secret_use", "api_key"),
        fact("tool", "add_payee", "risk_class=pii_export"),
        fact("weak_spot", "No tracing found (x)"),
        fact("external_url", "https://v.example/x"),
        fact("model", "m", "family=unknown"),
    ]
    rep = _report(
        "cybersecurity",
        [_pack("prefilter_evasion", "question"), _pack("finance_harm_refusal", "question")],
    )
    doc = ex.build("cybersecurity", rep, facts_of(*rows), SYS)
    assert len(doc["items"]) == ex.MAX_ITEMS
    assert [i["status"] for i in doc["items"]][:2] == ["fail", "fail"]
    sevs = [(i["status"], i["severity"]) for i in doc["items"]]
    order = {"fail": 0, "open": 1}
    sev = {"high": 0, "medium": 1, "low": 2}
    assert sevs == sorted(sevs, key=lambda p: (order[p[0]], sev[p[1]]))
    assert len({i["key"] for i in doc["items"]}) == len(doc["items"])
    assert doc["rating"] == "high"
    assert (
        doc["bottom_line"]["en"].endswith("attention.")
        and "; 5 more points need" in doc["bottom_line"]["en"]
    )


def test_declared_mismatch_is_folded_into_the_money_finding() -> None:
    doc = ex.build("legal_compliance", _report("legal_compliance", []), facts_of(*GATE), SYS)
    assert [i["key"] for i in doc["items"]] == ["money_tool_no_gate"]
    only = ex.build(
        "legal_compliance",
        _report("legal_compliance", []),
        facts_of(GATE[1]),
        SYS,
    )
    assert [i["key"] for i in only["items"]] == ["declared_control_mismatch"]


def test_clear_open_and_empty_ratings() -> None:
    ok = {**_pack("pii_canary", "pass"), "evidence": [{"kind": "pack", "ref": "r"}]}
    clear = ex.build("data_governance", _report("data_governance", [ok]), None, None)
    assert clear["rating"] == "clear" and clear["items"] == []
    assert clear["bottom_line"]["en"].startswith("No problem found")
    empty = ex.build("data_governance", _report("data_governance", []), None, None)
    assert empty["rating"] == "open" and "no result" in empty["bottom_line"]["en"]


def test_build_is_deterministic_and_has_the_frozen_shape() -> None:
    rep = _report("cybersecurity", [_pack("prefilter_evasion", "question")])
    a = ex.build("cybersecurity", rep, facts_of(*GATE), SYS)
    b = ex.build("cybersecurity", json.loads(json.dumps(rep)), facts_of(*GATE), dict(SYS))
    assert a == b and ex.valid(a)
    assert set(a) == {
        "version",
        "dimension_id",
        "rating",
        "bottom_line",
        "items",
        "writer",
        "created_at",
    }
    assert (
        a["version"] == 1 and a["writer"] == "rules" and a["created_at"] == "2026-10-28T09:00:00Z"
    )
    for it in a["items"]:
        assert set(it) == {
            "key",
            "severity",
            "status",
            "headline",
            "impact",
            "action",
            "owner",
            "finding_ids",
            "fact_refs",
        }
        assert it["owner"] in ex.OWNERS
        for k in ("headline", "impact", "action"):
            assert it[k]["en"].strip() and it[k]["vi"].strip()


def test_text_goes_through_the_masker() -> None:
    f = {
        "finding_id": "x1",
        "checklist_id": "ZZ-01",
        "verdict": "question",
        "evidence": [],
        "rationale": "Customer 012345678901 and a@b.vn were seen.",
        "confidence": "low",
    }
    doc = ex.build("model", _report("model", [f]), None, None)
    assert "012345678901" not in json.dumps(doc) and "a@b.vn" not in json.dumps(doc)


# ------------------------------------------------------------------ the demo reports


def _demo() -> tuple[dict, dict, dict[str, dict]]:
    facts = json.loads((DEMO / "facts.json").read_text(encoding="utf-8"))
    system = json.loads((DEMO / "system.json").read_text(encoding="utf-8"))
    reps = {
        d: json.loads((DEMO / f"{d}.json").read_text(encoding="utf-8"))
        for d in ("model", "data_governance", "cybersecurity", "legal_compliance", "ethics")
    }
    return facts, system, reps


def test_demo_reports_give_executive_findings() -> None:
    facts, system, reps = _demo()
    docs = {d: ex.build(d, r, facts, system) for d, r in reps.items()}
    cyber = docs["cybersecurity"]
    assert cyber["rating"] == "high"
    assert cyber["bottom_line"]["en"].startswith(
        "The agent can send payments (transfer) and the code has no approval step before it, "
        "although the registration says every action is approved first"
    )
    assert [i["key"] for i in cyber["items"]] == [
        "money_tool_no_gate",
        "pii_export_tool",
        "no_tracing",
        "tests_missing",
    ]
    assert "4 required tests have not been run yet" in cyber["items"][-1]["headline"]["en"]
    dg = {i["key"] for i in docs["data_governance"]["items"]}
    assert dg == {"personal_data_fields", "pii_export_tool", "tests_missing"}
    assert docs["data_governance"]["rating"] == "high"
    assert {i["key"] for i in docs["model"]["items"]} == {
        "model_unknown",
        "no_tracing",
        "tests_missing",
    }
    legal = {i["key"] for i in docs["legal_compliance"]["items"]}
    assert legal == {"money_tool_no_gate", "risk_level_mismatch", "depends_open", "person_decides"}
    assert {i["key"] for i in docs["ethics"]["items"]} == {"money_tool_no_gate", "tests_missing"}
    for d in docs.values():
        assert ex.valid(d)
        assert "SECRET" not in json.dumps(d)


# ------------------------------------------------------------------ storage


def test_write_read_round_trip_and_bad_files(tmp_path: Path) -> None:
    rep = _report("model", [_pack("truthfulqa_vi", "question")])
    doc = ex.build("model", rep, None, None)
    path = ex.write(tmp_path, doc)
    assert path.endswith("model.exec.json")
    assert ex.read(tmp_path, "model") == doc
    assert ex.read(tmp_path, "ethics") is None
    (tmp_path / "ethics.exec.json").write_text("{not json", encoding="utf-8")
    assert ex.read(tmp_path, "ethics") is None
    (tmp_path / "ethics.exec.json").write_text(json.dumps({"version": 2}), encoding="utf-8")
    assert ex.read(tmp_path, "ethics") is None
    with pytest.raises(ValueError):
        ex.write(tmp_path, {**doc, "dimension_id": "../x"})
    assert ex.read(tmp_path, "../x") is None


def test_sidecar_is_not_taken_for_a_report() -> None:
    # the report glob of the other readers uses "<dimension>.json"; the sidecar has another name
    assert "model.exec.json" != "model.json"
    assert Path("model.exec.json").stem not in rd.DIMENSION_IDS


# ------------------------------------------------------------------ Layer B


class FakeModel:
    is_mock = False
    family = "fake"
    model_id = "fake-model-1"

    def __init__(self, reply: Any = None, boom: bool = False) -> None:
        self.reply, self.boom, self.calls = reply, boom, []

    def complete_json(
        self, messages: Sequence[Mapping[str, str]], schema: Mapping, timeout_s: float
    ):
        self.calls.append((messages, schema, timeout_s))
        if self.boom:
            raise RuntimeError("down")
        return self.reply(messages) if callable(self.reply) else self.reply


def _doc() -> dict:
    facts, system, reps = _demo()
    return ex.build("cybersecurity", reps["cybersecurity"], facts, system)


def _reply(doc: dict, **over: Any) -> dict:
    out = {
        "bottom_line": dict(doc["bottom_line"]),
        "items": [
            {"key": i["key"], "headline": dict(i["headline"]), "impact": dict(i["impact"])}
            for i in doc["items"]
        ],
    }
    out.update(over)
    return out


def test_rewrite_accepts_a_clean_rewrite_and_keeps_the_rest() -> None:
    doc = _doc()
    reply = _reply(doc)
    reply["items"][0]["headline"] = {
        "en": "The agent can send payments (transfer) with no approval step in the code.",
        "vi": "Tác tử có thể chuyển tiền (transfer) mà mã không có bước phê duyệt.",
    }
    model = FakeModel(reply)
    new = ex.rewrite(doc, model)
    assert len(model.calls) == 1 and model.calls[0][2] <= 30
    assert new["items"][0]["headline"]["en"].startswith(
        "The agent can send payments (transfer) with no"
    )
    assert new["writer"] == "ai:fake-model-1"
    for a, b in zip(doc["items"], new["items"], strict=True):
        for k in ("key", "status", "severity", "owner", "finding_ids", "fact_refs", "action"):
            assert a[k] == b[k]
    assert new["rating"] == doc["rating"] and doc["writer"] == "rules"  # the input is untouched


@pytest.mark.parametrize(
    "bad",
    [
        "The agent can send 3 payments (transfer) with no approval step.",  # a number
        "The agent can send payments via payout_api with no approval step.",  # a new id
        "The agent can send payments from app/main.py with no approval step.",  # a file
        "The agent illegally sends payments (transfer).",  # an absolute claim
        "",  # empty
        "Line one.\nLine two.",  # two lines
        "x" * 1000,
    ],
)
def test_rewrite_rejects_added_facts(bad: str) -> None:
    doc = _doc()
    reply = _reply(doc)
    reply["items"][0]["headline"] = {"en": bad, "vi": doc["items"][0]["headline"]["vi"]}
    new = ex.rewrite(doc, FakeModel(reply))
    assert new["items"][0]["headline"] == doc["items"][0]["headline"]
    assert new["writer"] == "rules"


def test_rewrite_ignores_unknown_keys_and_cannot_change_status() -> None:
    doc = _doc()
    reply = _reply(doc)
    reply["items"].append(
        {"key": "invented", "headline": {"en": "x", "vi": "y"}, "impact": {"en": "x", "vi": "y"}}
    )
    reply["items"][0]["status"] = "pass"
    reply["items"][0]["severity"] = "low"
    reply["rating"] = "clear"
    new = ex.rewrite(doc, FakeModel(reply))
    assert new["items"] == doc["items"] and new["rating"] == doc["rating"]
    assert [i["key"] for i in new["items"]] == [i["key"] for i in doc["items"]]


def test_rewrite_bottom_line_check() -> None:
    doc = _doc()
    ok = _reply(
        doc,
        bottom_line={
            "en": "Payments can run with no approval step in the code.",
            "vi": "Thanh toán có thể chạy mà mã không có bước phê duyệt.",
        },
    )
    assert ex.rewrite(doc, FakeModel(ok))["bottom_line"]["en"].startswith("Payments can run")
    bad = _reply(
        doc, bottom_line={"en": "Payments of 5000 can run.", "vi": doc["bottom_line"]["vi"]}
    )
    assert ex.rewrite(doc, FakeModel(bad))["bottom_line"] == doc["bottom_line"]


def test_rewrite_failures_leave_layer_a() -> None:
    doc = _doc()
    assert ex.rewrite(doc, FakeModel(boom=True)) == doc
    assert ex.rewrite(doc, FakeModel(reply="not a mapping")) == doc
    assert ex.rewrite(doc, FakeModel({"items": "x"})) == doc
    empty = ex.build("model", _report("model", []), None, None)
    model = FakeModel({})
    assert ex.rewrite(empty, model) == empty and not model.calls


def test_rewrite_labels_a_mock_model() -> None:
    doc = _doc()
    reply = _reply(doc)
    reply["items"][0]["impact"] = {
        "en": "A wrong instruction could move money with no person checking it first.",
        "vi": doc["items"][0]["impact"]["vi"],
    }
    model = FakeModel(reply)
    model.is_mock, model.model_id = True, "mock-chat-v1"
    assert ex.rewrite(doc, model)["writer"] == "mock"


def test_rewrite_schema_is_strict_and_per_type() -> None:
    doc = _doc()
    model = FakeModel(_reply(doc))
    ex.rewrite(doc, model)
    schema = model.calls[0][1]
    assert schema["additionalProperties"] is False and set(schema["required"]) == {
        "bottom_line",
        "items",
    }
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False and item["properties"]["key"]["enum"] == [
        i["key"] for i in doc["items"]
    ]
    payload = json.loads(model.calls[0][0][1]["content"])
    assert "fact_refs" not in json.dumps(payload) and "code/" not in json.dumps(payload)
    assert "SECRET" not in json.dumps(payload)


def test_line_ok_unit() -> None:
    allowed = "Fields: cccd, payee_name in code/payops/tools.py. 5 fields."
    assert ex.line_ok("Five fields are handled: cccd and payee_name.", "", allowed)
    assert ex.line_ok("5 fields in code/payops/tools.py.", "", allowed)
    assert not ex.line_ok("6 fields.", "", allowed)
    assert not ex.line_ok("Field `iban` is handled.", "", allowed)
    assert not ex.line_ok("The field account_number is handled.", "", allowed)
    assert not ex.line_ok(None, "", allowed)
    assert ex.line_ok("A leak is possible; vi phạm is not claimed", "", allowed) is False
