"""WP-F3: the shadow run (layer 3), the simulation review (marks, labels, report), the CLI and the
optional ``groups:`` of users.yaml."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthError
from supervisor.adapters.auth.dev_header import DevHeaderPrincipal
from supervisor.config import REPO_ROOT
from supervisor.evidence import verify as ev
from supervisor.factory import __main__ as cli
from supervisor.factory import caps, gate, golden, probe, simulation
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from tests.factory.f3_helpers import FakeChat, create_agent, load_golden, make_env, to_live


def answer_any(user: Any) -> dict:
    """Pass every item on the first loaded source, but fail on the system ``sys-d``."""
    out = []
    for it in user["items"]:
        src = (user.get("loaded_sources") or [None])[0]
        if src is None:
            out.append(probe._question(it))
            continue
        verdict = "fail" if user["system_id"] == "sys-d" else "pass"
        out.append(
            {
                "checklist_id": it["checklist_id"],
                "verdict": verdict,
                "pass_rule_met": verdict == "pass",
                "confidence": "high",
                "rationale": "supported",
                "evidence": [
                    {"kind": src["kind"], "ref": src["ref"], "quote": probe._quote(src["text"])}
                ],
            }
        )
    return {"findings": out}


def inputs_for(sid: str, dim: str) -> dict[str, Any]:
    return {
        "system_id": sid,
        "system": {"system_id": sid, "owner_user": "chu-he-thong", "name": f"He thong {sid}"},
        "packs": [{"ref": f"pack-{sid}:1", "label": "do ben", "text": "dat o phien ban hien tai"}],
        "now": "2026-10-28T09:00:00Z",
    }


@pytest.fixture
def env(adapters: Any, sink: Any, tmp_path: Path) -> gate.GateEnv:
    chat = FakeChat()
    chat.agent_answer = answer_any
    return make_env(adapters, sink, chat, tmp_path, inputs_for=inputs_for)


def stored_report(
    env: gate.GateEnv, sid: str, verdicts: list[str], agent: str = "rule-proposal"
) -> None:
    findings = [
        {
            "finding_id": f"f{i}",
            "checklist_id": f"X{i}",
            "verdict": v,
            "evidence": [],
            "rationale": "r",
            "confidence": "low",
        }
        for i, v in enumerate(verdicts)
    ]
    doc = {
        "report_id": "r",
        "agent_id": agent,
        "dimension_id": "model",
        "findings": findings,
        "created_at": "2026-10-27T09:00:00Z",
    }
    d = env.data_dir / "assessments" / sid / "1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.json").write_text(json.dumps(doc), "utf-8")


def person_row(env: gate.GateEnv, sid: str, status: str, by: str) -> None:
    env.state.insert(
        "risk_dimension_status",
        {
            "status_id": f"s-{sid}",
            "system_id": sid,
            "dimension_id": "model",
            "status": status,
            "evidence_json": [],
            "threshold_json": {},
            "updated_by": by,
        },
    )


# ------------------------------------------------------------------------------ shadow


def test_shadow_compares_with_stored_reports_and_with_the_person(env: gate.GateEnv) -> None:
    create_agent(env)
    stored_report(env, "sys-a", ["pass", "pass"])  # candidate pass: agree
    stored_report(env, "sys-b", ["pass", "fail"])  # stored fail, candidate pass: fixed fail
    stored_report(env, "sys-c", ["pass", "question"])  # stored question: disagree
    stored_report(env, "sys-d", ["pass", "pass"])  # stored pass, candidate fail: new fail
    person_row(env, "sys-a", "pass", "reviewer.binh")  # agree
    person_row(env, "sys-b", "fail", "reviewer.binh")  # disagree
    person_row(env, "sys-c", "fail", "rule:orchestrator")  # a proposal, not a person: not compared
    person_row(env, "sys-d", "pass", "reviewer.binh")  # candidate fail: disagree
    run = gate.start(env, "mr-agent", "0.1", "shadow", "reviewer.an", n=10, background=False)
    l3 = run["layer3"]
    assert run["status"] == "done" and run["verdict"] == "not_run"  # shadow alone never decides
    assert (l3["systems"], l3["agree_live"], l3["disagree_live"]) == (4, 1, 3)
    assert (l3["new_fails"], l3["fixed_fails"]) == (1, 1)
    assert (l3["compared_person"], l3["agree_person"], l3["disagree_person"]) == (3, 1, 2)
    assert l3["status"] == "ok" and all(
        isinstance(v, int) for k, v in l3.items() if k != "systems_detail" and k != "status"
    )
    # the candidate reports are stored, not shown
    d = gate.gate_dir(env.data_dir, "mr-agent", run["run_id"]) / "shadow"
    assert sorted(p.name for p in d.iterdir()) == [
        "sys-a.json",
        "sys-b.json",
        "sys-c.json",
        "sys-d.json",
    ]
    assert env.store.get("mr-agent", "0.1")["state"] == "draft"


def test_shadow_takes_the_last_n_and_caps_at_25(env: gate.GateEnv) -> None:
    create_agent(env)
    for i in range(30):
        stored_report(env, f"sys-{i:02d}", ["pass"])
        p = env.data_dir / "assessments" / f"sys-{i:02d}" / "1" / "model.json"
        doc = json.loads(p.read_text())
        doc["created_at"] = f"2026-10-{(i % 27) + 1:02d}T09:00:00Z"
        p.write_text(json.dumps(doc))
    run = gate.start(env, "mr-agent", "0.1", "shadow", "x", n=25, background=False)
    assert run["layer3"]["systems"] == 25 and run["layer3"]["requested"] == 25
    with pytest.raises(gate.GateError):
        gate.start(env, "mr-agent", "0.1", "shadow", "x", n=26, background=False)
    defn = AgentDefinitionV1.model_validate(env.store.get("mr-agent", "0.1")["definition"])
    three = gate.shadow(env, defn, env.model(), 3, env.data_dir / "x")
    assert three["systems"] == 3


def test_shadow_with_no_stored_onboarding_is_no_data_not_a_failure(env: gate.GateEnv) -> None:
    create_agent(env)
    run = gate.start(env, "mr-agent", "0.1", "shadow", "x", background=False)
    assert (
        run["status"] == "done"
        and run["layer3"]["status"] == "no_data"
        and run["layer3"]["systems"] == 0
    )


def test_a_full_run_attaches_the_shadow_report(env: gate.GateEnv) -> None:
    row = create_agent(env)
    load_golden(env, row)
    stored_report(env, "sys-a", ["pass"])
    run = gate.start(env, "mr-agent", "0.1", "full", "x", background=False)
    assert run["layer3"]["systems"] == 1 and run["layer3"]["status"] == "ok"
    doc = json.loads(
        (gate.gate_dir(env.data_dir, "mr-agent", run["run_id"]) / "report.json").read_text()
    )
    assert doc["layer3"]["agree_live"] == 1


# ------------------------------------------------------------------------------ simulation


def run_sim(env: gate.GateEnv, systems: list[str] | None = None) -> dict[str, Any]:
    create_agent(env)
    return gate.start(
        env,
        "mr-agent",
        "0.1",
        "simulation",
        "reviewer.an",
        systems=systems or ["sys-a", "sys-d"],
        background=False,
    )


def test_simulation_runs_on_chosen_systems_and_never_promotes(env: gate.GateEnv) -> None:
    run = run_sim(env)
    assert run["status"] == "done" and run["verdict"] == "not_run"
    assert run["layer2"]["review"]["systems"] == 2 and run["layer2"]["review"]["findings"] == 12
    assert env.store.get("mr-agent", "0.1")["state"] == "draft"
    data = simulation.review_data(env, "mr-agent", run["run_id"])
    names = [s["name"] for s in data["systems"]]
    assert names == ["sys-a", "sys-d"] and data["unmarked"] == 12 and data["total"] == 12
    f = data["systems"][0]["findings"][0]
    assert f["verdict"] == "pass" and f["evidence"][0]["text"] and f["evidence"][0]["ref"]


def test_simulation_marks_become_calibration_labels_and_a_signed_report(env: gate.GateEnv) -> None:
    run = run_sim(env)
    rid = run["run_id"]
    simulation.mark(
        env,
        "mr-agent",
        rid,
        "sys-a",
        "f-MR-01",
        "agree",
        "",
        "ok, evidence is right",
        "reviewer.binh",
    )
    simulation.mark(
        env,
        "mr-agent",
        rid,
        "sys-d",
        "f-MR-01",
        "disagree",
        "question",
        "owner is missing",
        "reviewer.binh",
    )
    simulation.mark(env, "mr-agent", rid, "sys-d", "f-MR-02", "unsure", "", "", "reviewer.binh")
    labels = golden.load_labels(env.data_dir, "mr-agent")
    got = {(r["ref"], r["finding_id"]): (r["human_verdict"], r["source"]) for r in labels}
    assert got == {
        (f"{rid}/sys-a", "f-MR-01"): ("pass", "simulation"),
        (f"{rid}/sys-d", "f-MR-01"): (
            "question",
            "simulation",
        ),  # the reviewer's verdict, not the agent's fail
    }
    data = simulation.review_data(env, "mr-agent", rid)
    assert data["counts"] == {"agree": 1, "disagree": 1, "unsure": 1} and data["unmarked"] == 9
    path = gate.gate_dir(env.data_dir, "mr-agent", rid) / "review_report.json"
    assert ev.verify_signed_doc(path).failures == 0
    doc = json.loads(path.read_text())
    assert doc["review"]["marked"] == 3 and doc["verdict"] == "not_run"
    assert "owner is missing" not in json.dumps(doc)  # notes are hashed in the report
    row = gate.get_run(env, rid)
    assert (
        row["report_sha256"] == doc["content_sha256"] and row["layer2"]["review"]["disagree"] == 1
    )
    # a later mark of the same finding replaces the label; unsure removes it
    simulation.mark(env, "mr-agent", rid, "sys-a", "f-MR-01", "unsure", "", "", "reviewer.binh")
    assert len(golden.load_labels(env.data_dir, "mr-agent")) == 1


def test_a_simulation_note_is_masked_and_cut(env: gate.GateEnv) -> None:
    run = run_sim(env)
    simulation.mark(
        env,
        "mr-agent",
        run["run_id"],
        "sys-a",
        "f-MR-01",
        "agree",
        "",
        "goi 0912345678 de hoi",
        "reviewer.binh",
    )
    marks = json.loads(
        (gate.gate_dir(env.data_dir, "mr-agent", run["run_id"]) / "marks.json").read_text()
    )
    assert "0912345678" not in json.dumps(marks) and "[pii]" in marks["sys-a|f-MR-01"]["note"]
    with pytest.raises(gate.GateError) as exc:
        simulation.mark(
            env, "mr-agent", run["run_id"], "sys-a", "f-MR-01", "agree", "", "x" * 301, "r"
        )
    assert exc.value.code == "note_too_long"


def test_simulation_mark_refusals(env: gate.GateEnv) -> None:
    run = run_sim(env)
    rid = run["run_id"]
    cases = [
        (("sys-a", "f-MR-01", "great", "", ""), "bad_mark"),
        (("sys-a", "f-MR-01", "disagree", "", ""), "verdict_needed"),
        (("sys-a", "f-MR-01", "disagree", "maybe", ""), "verdict_needed"),
        (("sys-zz", "f-MR-01", "agree", "", ""), "not_found"),
        (("sys-a", "f-ZZ", "agree", "", ""), "not_found"),
    ]
    for (system, finding, mark, verdict, note), code in cases:
        with pytest.raises(gate.GateError) as exc:
            simulation.mark(env, "mr-agent", rid, system, finding, mark, verdict, note, "r")
        assert exc.value.code == code
    with pytest.raises(gate.GateError) as exc2:
        simulation.mark(
            env, "mr-agent", "gate_" + "0" * 20, "sys-a", "f-MR-01", "agree", "", "", "r"
        )
    assert exc2.value.code == "not_found"
    with pytest.raises(gate.GateError):
        simulation.mark(env, "mr-agent", "../etc", "sys-a", "f-MR-01", "agree", "", "", "r")


def test_simulation_labels_feed_the_calibration(env: gate.GateEnv) -> None:
    create_agent(env)
    systems = [f"sys-{c}" for c in "abcdefg"]
    run = gate.start(
        env, "mr-agent", "0.1", "simulation", "x", systems=systems[:4], background=False
    )
    n = 0
    for s in systems[:4]:
        for i in range(1, 7):
            if n < 22 and s != "sys-d":
                simulation.mark(
                    env,
                    "mr-agent",
                    run["run_id"],
                    s,
                    f"f-MR-0{i}",
                    "agree",
                    "",
                    "",
                    "reviewer.binh",
                )
                n += 1
    labels = golden.load_labels(env.data_dir, "mr-agent")
    assert len(labels) == 18 and all(r["source"] == "simulation" for r in labels)
    run2 = gate.start(
        env, "mr-agent", "0.1", "simulation", "x", systems=systems[4:], background=False
    )
    for s in systems[4:]:
        for i in range(1, 7):
            simulation.mark(
                env, "mr-agent", run2["run_id"], s, f"f-MR-0{i}", "agree", "", "", "reviewer.binh"
            )
    defn = AgentDefinitionV1.model_validate(env.store.get("mr-agent", "0.1")["definition"])
    cal = gate.calibrate(env, env.model(), defn, {})
    assert cal["labels_total"] == 36 and cal["labels_used"] == 36 and cal["labels_skipped"] == 0
    assert cal["kappa_hundredths"] == 100 and cal["ok"]


def test_simulation_needs_systems_of_the_inventory(env: gate.GateEnv) -> None:
    def broken(sid: str, dim: str) -> dict[str, Any]:
        raise LookupError(sid)

    env.inputs_for = broken
    run = run_sim(env, ["ghost"])
    assert (
        run["layer2"]["review"]["systems_failed"] == 1 and run["layer2"]["review"]["findings"] == 0
    )


# ------------------------------------------------------------------------------ the CLI


def test_cli_sample_run(env: gate.GateEnv, capsys: pytest.CaptureFixture[str]) -> None:
    row = create_agent(env)
    load_golden(env, row)
    rc = cli.main(["gate", "mr-agent", "--kind", "sample", "--n", "5"], gate_env=env)
    out = capsys.readouterr().out
    assert rc == 0 and "[OK] verdict pass (a sample never promotes)" in out and out.isascii()
    assert env.store.get("mr-agent", "0.1")["state"] == "draft"


def test_cli_full_run_promotes_to_tested(
    env: gate.GateEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    row = create_agent(env)
    load_golden(env, row)
    rc = cli.main(["gate", "mr-agent", "--kind", "full"], gate_env=env)
    out = capsys.readouterr().out
    assert rc == 0 and "[OK] verdict pass" in out and "kappa 100" in out
    assert env.store.get("mr-agent", "0.1")["state"] == "tested"


def test_cli_failures_exit_one_with_ascii(
    env: gate.GateEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    create_agent(env)
    assert cli.main(["gate", "mr-agent", "--kind", "full"], gate_env=env) == 1
    assert "[FAIL] golden_not_ready" in capsys.readouterr().out
    assert cli.main(["gate", "nope-agent", "--kind", "sample"], gate_env=env) == 1
    assert "[FAIL] not_found" in capsys.readouterr().out
    env.chat.agent_answer = lambda u: {"findings": []}  # type: ignore[attr-defined]
    load_golden(env, env.store.get("mr-agent", "0.1"))
    assert cli.main(["gate", "mr-agent", "--kind", "sample"], gate_env=env) == 1
    assert "[FAIL] verdict fail" in capsys.readouterr().out


def test_cli_with_the_flag_off(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_FACTORY_GATE", raising=False)
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    assert cli.main(["gate", "mr-agent"]) == 1
    assert "[FAIL] factory_gate_off" in capsys.readouterr().out


def test_cli_still_validates_files(capsys: pytest.CaptureFixture[str]) -> None:
    data = Path(__file__).parent / "data" / "agent_single_pass.yaml"
    assert cli.main(["validate", str(data)]) == 0
    assert "[OK]" in capsys.readouterr().out


# ------------------------------------------------------------------------------ users.yaml groups


def test_users_file_groups(tmp_path: Path) -> None:
    f = tmp_path / "users.yaml"
    f.write_text(
        textwrap.dedent(
            """
            default_user: a
            users:
              a: {name: "An", roles: [reviewer], groups: [model_risk, cyber]}
              b: {name: "Binh", roles: [reviewer]}
            """
        ),
        "utf-8",
    )
    users = DevHeaderPrincipal.from_file(f).users
    assert (
        users["a"].groups == frozenset({"model_risk", "cyber"}) and users["b"].groups == frozenset()
    )
    for bad in ("groups: model_risk", "groups: [Model Risk]", "groups: [1]"):
        f.write_text(f"users:\n  a: {{name: An, roles: [reviewer], {bad}}}\n", "utf-8")
        with pytest.raises(AuthError, match="groups"):
            DevHeaderPrincipal.from_file(f)


def test_the_shipped_users_file_has_leads_with_groups() -> None:
    users = DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users
    assert users["lead.model"].groups == frozenset({"model_risk"})
    assert users["second.line"].groups == frozenset({"platform"})
    assert users["reviewer.an"].groups == frozenset()  # no groups: the role mapping applies
    assert caps.SECOND_LINE_GROUPS == ("platform",)


def test_a_live_agent_is_found_by_the_orchestrator_catalogue(env: gate.GateEnv) -> None:
    to_live(env)
    assert env.store.live_agent_for("model")["definition"]["lifecycle"]["state"] == "live"
