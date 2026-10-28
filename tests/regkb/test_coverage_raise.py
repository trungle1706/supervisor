"""WP-L5: coverage raise of Decree 142/2026 and Circular 53/2026.

Rules for the control_mapping of these two instruments (Not legal advice):

* A Supervisor control that is not `full` says what is missing ("Missing: ...").
* A bank process entry says the manual step ("Manual step: ...") and is `partial`.
* A duty with no Supervisor control says why ("No Supervisor control: ..." or "No control: ...").
* `full` is rare: the control alone must meet the evidence need of the duty.
* The ids added to controls.yaml name the doc section that describes them.
"""

from __future__ import annotations

from collections import Counter

import pytest
import yaml

from supervisor.regkb import KnowledgeBase, load_kb
from tests.conftest import REPO_ROOT

INSTRUMENTS = ("VN-DEC142-2026", "VN-TT53-2026")
# (full, partial, none) by Supervisor controls only, and with bank process steps counted.
EXPECTED_SUPERVISOR = {"VN-DEC142-2026": (1, 19, 6), "VN-TT53-2026": (0, 49, 4)}
EXPECTED_WITH_PROCESS = {"VN-DEC142-2026": (1, 24, 1), "VN-TT53-2026": (0, 53, 0)}
# Before WP-L5 (git a21e5ac): no full, 19 / 47 partial, 7 / 6 none, every process entry `none`.
BEFORE_SUPERVISOR = {"VN-DEC142-2026": (0, 19, 7), "VN-TT53-2026": (0, 47, 6)}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_kb()


def _level(controls) -> str:
    cov = {c.coverage for c in controls}
    return "full" if "full" in cov else "partial" if "partial" in cov else "none"


def _counts(kb: KnowledgeBase, iid: str, *, with_process: bool) -> tuple[int, int, int]:
    tally = Counter(
        _level([c for c in o.control_mapping if with_process or c.kind != "process"])
        for o in kb.obligations_of(iid)
    )
    return tally["full"], tally["partial"], tally["none"]


@pytest.mark.parametrize("iid", INSTRUMENTS)
def test_counts_after_the_raise(kb: KnowledgeBase, iid: str) -> None:
    assert _counts(kb, iid, with_process=False) == EXPECTED_SUPERVISOR[iid]
    assert _counts(kb, iid, with_process=True) == EXPECTED_WITH_PROCESS[iid]


@pytest.mark.parametrize("iid", INSTRUMENTS)
def test_the_raise_did_not_lower_anything(kb: KnowledgeBase, iid: str) -> None:
    full, partial, none = _counts(kb, iid, with_process=False)
    b_full, b_partial, b_none = BEFORE_SUPERVISOR[iid]
    assert full >= b_full and full + partial >= b_full + b_partial and none <= b_none


@pytest.mark.parametrize("iid", INSTRUMENTS)
def test_every_row_names_its_gap(kb: KnowledgeBase, iid: str) -> None:
    for o in kb.obligations_of(iid):
        level = _level([c for c in o.control_mapping if c.kind != "process"])
        notes = [c.note or "" for c in o.control_mapping]
        if level == "full":
            assert any(c.coverage == "full" and c.note for c in o.control_mapping), o.id
        elif level == "partial":
            assert any("Missing:" in n for n in notes), f"{o.id}: no entry names what is missing"
        else:
            assert any("No Supervisor control:" in n or "No control:" in n for n in notes), (
                f"{o.id}: a duty with no Supervisor control must say why"
            )


@pytest.mark.parametrize("iid", INSTRUMENTS)
def test_process_entries_name_the_manual_step(kb: KnowledgeBase, iid: str) -> None:
    for o in kb.obligations_of(iid):
        for c in o.control_mapping:
            assert c.note, f"{o.id} {c.kind}:{c.id}: a note is needed"
            if c.kind == "process" and c.coverage != "none":
                assert c.coverage == "partial", f"{o.id} {c.id}: a bank process is partial at most"
                assert c.note.startswith("Manual step:"), f"{o.id} {c.id}: {c.note[:40]!r}"
            if c.coverage == "none":
                assert c.note.startswith("No control:"), f"{o.id} {c.id}: none needs a named reason"


@pytest.mark.parametrize("iid", INSTRUMENTS)
def test_full_is_rare_and_only_for_a_supervisor_control(kb: KnowledgeBase, iid: str) -> None:
    fulls = [
        (o.id, c.id)
        for o in kb.obligations_of(iid)
        for c in o.control_mapping
        if c.coverage == "full"
    ]
    assert all(
        c.kind != "process"
        for o in kb.obligations_of(iid)
        for c in o.control_mapping
        if c.coverage == "full"
    )
    assert len(fulls) <= 3, fulls


def test_text_and_dates_were_not_touched(kb: KnowledgeBase) -> None:
    """Quotes, tags and article references stay as read (the quote tests check the text)."""
    for iid in INSTRUMENTS:
        for o in kb.obligations_of(iid):
            assert o.verification == "VERIFIED_PRIMARY" and o.text_vi and o.article_ref, o.id


def test_new_control_ids_name_a_doc_section() -> None:
    """Entries added in WP-L5 carry doc: '<file> | <heading text>'; the file has that heading."""
    spec = yaml.safe_load((REPO_ROOT / "regulations/schema/controls.yaml").read_text("utf-8"))
    wanted = {
        "console": [
            "workflow_actions",
            "state_actions",
            "attach_view",
            "law_agent_drafts",
            "duties_actions",
            "schema_selfcheck",
            "systems",
            "incidents",
            "transparency",
            "assurance",
        ],
        "evidence": [
            "guardian_off_approval",
            "intake_scrub",
            "facts_card",
            "predeploy_report",
            "duties_step",
            "duties_gap",
            "incident_record",
            "incident_clock",
            "transparency_report",
            "assurance_results",
            "risk_register",
            "control_catalogue",
            "task_record",
            "lifecycle_approval",
            "classification_record",
            "ai_system_record",
            "threshold_check",
        ],
    }
    for section, ids in wanted.items():
        for cid in ids:
            doc = spec[section][cid].get("doc")
            assert doc and " | " in doc, f"{section}.{cid}: doc pointer missing"
            rel, heading = (x.strip() for x in doc.split("|", 1))
            path = REPO_ROOT / rel
            assert path.is_file(), f"{section}.{cid}: {rel} does not exist"
            lines = [
                ln for ln in path.read_text("utf-8").splitlines() if ln.lstrip().startswith("#")
            ]
            assert any(heading in ln for ln in lines) or heading in path.read_text("utf-8"), (
                f"{section}.{cid}: heading {heading!r} not in {rel}"
            )


def test_new_process_ids_have_one_line_descriptions(kb: KnowledgeBase) -> None:
    spec = yaml.safe_load((REPO_ROOT / "regulations/schema/controls.yaml").read_text("utf-8"))
    for pid in (
        "change_management",
        "ai_inventory_review",
        "risk_classification_approval",
        "ai_bom_management",
        "customer_control_tool",
        "impact_assessment_file",
        "go_live_decision",
        "board_reporting",
        "three_lines_model",
        "elending_compliance",
        "media_marking",
        "emergency_stop_drill",
        "retirement_procedure",
        "user_guidance",
        "customer_explanation",
    ):
        label = spec["process"][pid]["label"]
        assert label and "\n" not in label and len(label) < 140, pid
        assert any(
            c.kind == "process" and c.id == pid
            for o in kb.obligations.values()
            for c in o.control_mapping
        ), pid


def test_every_new_control_id_is_used_or_listed(kb: KnowledgeBase) -> None:
    """An id added in WP-L5 that no obligation maps is allowed only if listed here."""
    spec = yaml.safe_load((REPO_ROOT / "regulations/schema/controls.yaml").read_text("utf-8"))
    used = {(c.kind, c.id) for o in kb.obligations.values() for c in o.control_mapping}
    unmapped_on_purpose = {
        ("console", "law_agent_drafts"),  # keeps the knowledge base itself current; no bank duty
    }
    unused = [
        f"{section}.{cid}"
        for section in ("console", "evidence")
        for cid, item in spec[section].items()
        if "doc" in item  # entries added in WP-L5
        and (section, cid) not in used
        and (section, cid) not in unmapped_on_purpose
    ]
    assert unused == []
