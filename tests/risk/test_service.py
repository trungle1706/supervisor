"""WP29: the service (create, update, link, import, export) with a real SQLite store."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from supervisor.core.errors import NotFoundError
from supervisor.risk.model import RiskError
from supervisor.risk.service import RiskService

from .conftest import STARTERS, ListSink, risk_data


def test_create_get_and_scores(svc: RiskService, sink: ListSink) -> None:
    out = svc.create(
        risk_data(),
        "reviewer.an",
        risk_id="R-1",
        links=[("rule", "PAY-02"), ("pack", "pii_canary")],
    )
    assert out["risk_id"] == "R-1" and out["created_by"] == "reviewer.an"
    assert (out["inherent_score"], out["inherent_band"]) == (20, "critical")
    assert out["declared_residual_score"] == 10
    assert out["residual_score"] == 20 and out["evidence_reason"] == "no_evidence_yet"
    assert out["links"] == [
        {"kind": "rule", "target": "PAY-02"},
        {"kind": "pack", "target": "pii_canary"},
    ]
    assert out["agents"] == ["payments"]
    (rec,) = sink.of("risk_change")
    assert (
        rec["action"] == "create" and rec["actor"] == "reviewer.an" and rec["inherent_score"] == 20
    )
    assert all(isinstance(v, (int, str)) for v in rec.values())


def test_generated_id_and_duplicate(svc: RiskService) -> None:
    rid = svc.create(risk_data(), "t")["risk_id"]
    assert rid.startswith("RSK-")
    svc.create(risk_data(), "t", risk_id="R-2")
    with pytest.raises(RiskError, match="already exists"):
        svc.create(risk_data(), "t", risk_id="R-2")


def test_create_with_unknown_link_creates_nothing(svc: RiskService) -> None:
    with pytest.raises(RiskError, match="does not exist"):
        svc.create(risk_data(), "t", risk_id="R-3", links=[("rule", "NOPE-1")])
    assert svc.list_risks() == []


def test_update_marks_the_risk_as_hand_kept_and_chains(svc: RiskService, sink: ListSink) -> None:
    svc.create(risk_data(), "t", risk_id="R-1", source="starter")
    out = svc.update("R-1", {"owner": "New Owner", "residual_likelihood": 1}, "reviewer.an")
    assert out["owner"] == "New Owner" and out["source"] == "manual"
    assert out["declared_residual_score"] == 5
    assert sink.of("risk_change")[-1]["action"] == "update"


def test_update_validates_the_whole_record(svc: RiskService) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    with pytest.raises(RiskError, match="cannot be above"):
        svc.update("R-1", {"residual_likelihood": 5}, "t")
    with pytest.raises(RiskError, match="cannot change"):
        svc.update("R-1", {"created_by": "x"}, "t")
    with pytest.raises(RiskError, match="accept"):
        svc.update("R-1", {"treatment": "accept"}, "t")
    with pytest.raises(NotFoundError):
        svc.update("R-404", {"owner": "x"}, "t")


def test_update_with_a_stale_row_version_is_refused(svc: RiskService) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    svc.update("R-1", {"owner": "A"}, "t")
    with pytest.raises(RiskError, match="changed by someone else"):
        svc.update("R-1", {"owner": "B"}, "t", expected_version=1)


def test_retire_is_an_update_and_drops_the_agents(svc: RiskService, sink: ListSink) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    out = svc.update("R-1", {"status": "retired"}, "t")
    assert out["status"] == "retired" and out["agents"] == []
    assert sink.of("risk_change")[-1]["action"] == "retire"


def test_links_add_remove_and_repeat(svc: RiskService, sink: ListSink) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    assert svc.add_link("R-1", "monitor", "oversight", "t")["added"] is True
    assert svc.add_link("R-1", "monitor", "oversight", "t")["added"] is False
    assert svc.links("R-1") == [{"kind": "monitor", "target": "oversight"}]
    assert svc.remove_link("R-1", "monitor", "oversight", "t")["removed"] is True
    assert svc.remove_link("R-1", "monitor", "oversight", "t")["removed"] is False
    assert svc.links("R-1") == []
    assert svc.add_link("R-1", "monitor", "oversight", "t")["added"] is True  # comes back
    assert [r["action"] for r in sink.of("risk_change")] == ["create", "link", "unlink", "link"]


def test_link_targets_must_exist(svc: RiskService) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    for kind, target in (
        ("rule", "PAY-777"),
        ("matrix", "VN-NOPE-1"),
        ("pack", "nope_pack"),
        ("monitor", "nope"),
        ("case", "CASE-404"),
    ):
        with pytest.raises(RiskError, match="does not exist"):
            svc.add_link("R-1", kind, target, "t")
    with pytest.raises(RiskError):
        svc.add_link("R-1", "weather", "x", "t")
    with pytest.raises(NotFoundError):
        svc.add_link("R-404", "rule", "PAY-02", "t")


def test_filters(svc: RiskService) -> None:
    svc.create(risk_data(), "t", risk_id="R-1")
    svc.create(
        risk_data(
            agent_id="credit_prequal", category="pii", owner="Lending", title="Other",
            inherent_likelihood=2, inherent_impact=2, residual_likelihood=1, residual_impact=1,
        ),
        "t",
        risk_id="R-2",
    )  # fmt: skip
    ids = lambda f: [r["risk_id"] for r in svc.list_risks(f)]  # noqa: E731
    assert ids({"agent": "payments"}) == ["R-1"]
    assert ids({"category": "pii"}) == ["R-2"]
    assert ids({"owner": "Lending"}) == ["R-2"]
    assert ids({"band": "critical"}) == ["R-1"]  # no evidence yet: residual = inherent
    assert ids({"q": "other"}) == ["R-2"]
    assert ids({"status": "retired"}) == []
    assert ids({}) == ["R-1", "R-2"]  # worst residual first
    with pytest.raises(RiskError):
        svc.list_risks({"band": "purple"})
    with pytest.raises(RiskError):
        svc.list_risks({"nope": "x"})


# ---- import ---------------------------------------------------------------------------------


def test_starter_import_is_idempotent(svc: RiskService) -> None:
    first = svc.import_path(STARTERS, "cli", source="starter")
    assert first.errors == [] and first.created == 19 and first.links_added > 50
    again = svc.import_path(STARTERS, "cli", source="starter")
    assert (again.created, again.updated, again.unchanged) == (0, 0, 19)
    assert again.links_added == 0 and again.links_removed == 0
    assert len(svc.list_risks()) == 19


def test_import_changes_links_and_leaves_hand_kept_risks_alone(
    svc: RiskService, tmp_path: Path
) -> None:
    svc.import_path(STARTERS, "cli", source="starter")
    svc.update("RSK-PAY-001", {"owner": "Hand Kept"}, "reviewer.an")
    f = tmp_path / "x.yaml"
    text = (STARTERS / "payments.yaml").read_text(encoding="utf-8")
    changed = text.replace("rule: [PAY-01, PAY-02, PAY-06]", "rule: [PAY-02]")
    f.write_text(changed.replace("owner: Payments Ops", "owner: Changed", 1), encoding="utf-8")
    res = svc.import_path(f, "cli", source="starter")
    assert res.skipped_manual == 1 and "edited by hand" in res.notes[0]
    assert svc.get("RSK-PAY-001")["owner"] == "Hand Kept"
    forced = svc.import_path(f, "cli", source="starter", overwrite_manual=True)
    assert forced.updated >= 1 and forced.links_removed == 2
    assert [x["target"] for x in svc.get("RSK-PAY-001")["links"] if x["kind"] == "rule"] == [
        "PAY-02"
    ]


def test_import_is_all_or_nothing(svc: RiskService, tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text(
        "version: 1\nrisks:\n"
        "  - {id: OK-1, agent: payments, title: fine, category: pii, treatment: avoid, owner: o,\n"
        "     inherent: {likelihood: 2, impact: 2}, status: draft}\n"
        "  - {id: BAD-1, agent: payments, title: broken, category: nope, treatment: avoid,\n"
        "     owner: o, inherent: {likelihood: 2, impact: 2}}\n",
        encoding="utf-8",
    )
    res = svc.import_path(f, "cli")
    assert len(res.errors) == 1 and "category" in res.errors[0] and res.created == 0
    assert svc.list_risks() == []


def test_dry_run_writes_nothing(svc: RiskService) -> None:
    res = svc.import_path(STARTERS, "cli", source="starter", dry_run=True)
    assert res.errors == [] and res.created == 0 and svc.list_risks() == []


@pytest.mark.parametrize(
    "text",
    ["not: [valid", "risks: 5", "- just\n- a list\n", "risks:\n  - 5\n", "x" * 3_000_000],
)
def test_bad_import_files_are_user_errors(svc: RiskService, tmp_path: Path, text: str) -> None:
    f = tmp_path / "b.yaml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(RiskError):
        svc.import_path(f, "cli")


def test_import_folder_without_yaml_is_an_error(svc: RiskService, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(RiskError, match="no .yaml"):
        svc.import_path(tmp_path / "empty", "cli")


# ---- export ---------------------------------------------------------------------------------


def test_export_json_csv_and_files(svc: RiskService, tmp_path: Path) -> None:
    svc.import_path(STARTERS, "cli", source="starter")
    doc = svc.export_json()
    assert doc["thresholds"]["illustrative"] is True and len(doc["risks"]) == 19
    json.dumps(doc)  # plain data
    risks_csv, links_csv = svc.export_csv()
    rows = list(csv.DictReader(io.StringIO(risks_csv)))
    assert len(rows) == 19 and {"inherent_band", "residual_band", "evidence_state"} <= set(rows[0])
    assert len(list(csv.DictReader(io.StringIO(links_csv)))) == sum(
        len(r["links"]) for r in doc["risks"]
    )
    paths = svc.write_exports(tmp_path / "out")
    assert sorted(p.name for p in paths) == ["risk_links.csv", "risks.csv", "risks.json"]
    assert [p.name for p in svc.write_exports(tmp_path / "j", "json")] == ["risks.json"]


def test_export_neutralises_spreadsheet_formulas(svc: RiskService) -> None:
    svc.create(risk_data(title='=cmd|"/c calc"!A1', owner="@SUM(1)"), "t", risk_id="R-1")
    text, _ = svc.export_csv()
    assert "'=cmd" in text and "'@SUM" in text
    assert "\n=" not in text and ",=cmd" not in text


def test_agent_summary_and_counts(svc: RiskService) -> None:
    svc.import_path(STARTERS, "cli", source="starter")
    s = svc.agent_summary("payments")
    assert s["residual_level"] == "critical" and s["inherent_score"] == 20
    assert {r["risk_id"] for r in s["risks"]} >= {"RSK-PAY-001", "RSK-SHR-001"}
    own = [r for r in s["risks"] if r["own"]]
    assert len(own) == 6
    assert svc.counts()["active"] == 19
    assert RiskService.agent_summary  # extension point for WP31
