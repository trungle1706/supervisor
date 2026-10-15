"""WP12: Onboard screen - off by default, a mock run from the console, last-run cards."""

from __future__ import annotations

import time
from typing import Any

import pytest

from supervisor.console import onboard_runs

from .conftest import Console


def test_onboard_page_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_onboard_enabled is False
    r = console.get("/console/onboard")
    assert r.status_code == 200
    assert 'data-onboard-off="1"' in r.text and "CONSOLE_ONBOARD_ENABLED=1" in r.text
    assert r.text.count('class="wstep') == 6
    assert "No onboarding run yet." in r.text
    s = console.post("/console/onboard/start", {"target": "src/supervisor_agents/payments"})
    assert s.status_code == 400 and "Onboard from the console is off" in s.text


def test_onboard_target_validation(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_onboard_enabled", True)
    for target, needle in (("", "give the folder"), ("no/such/dir", "folder not found")):
        r = console.post("/console/onboard/start", {"target": target})
        assert r.status_code == 400 and needle in r.text, r.text
    r = console.post(
        "/console/onboard/start", {"target": "src/supervisor_agents/payments"}, user="auditor.dung"
    )
    assert r.status_code == 400 and "needs role" in r.text
    with pytest.raises(onboard_runs.OnboardInputError):
        onboard_runs.artefact_path(console.ctx.settings, "payments", "../../etc/passwd")


def test_onboard_start_mock_run(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.adapters.llm.mock import MockChat

    monkeypatch.setattr(console.ctx.settings, "console_onboard_enabled", True)
    monkeypatch.setattr(onboard_runs, "pick_chat", lambda _s: MockChat(model_id="mock-onb-t"))
    r = console.post("/console/onboard/start", {"target": "src/supervisor_agents/credit_prequal"})
    assert r.status_code == 200, r.text
    assert 'data-job="' in r.text and "credit_prequal" in r.text
    job: Any = console.ctx.onboard.latest()
    assert job is not None and job.mock
    busy = console.post("/console/onboard/start", {"target": "src/supervisor_agents/payments"})
    if job.status == "running":
        assert busy.status_code == 400 and "already in progress" in busy.text
    deadline = time.monotonic() + 240
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.5)
    assert job.status == "done", "\n".join(job.lines)
    page = console.get("/console/onboard")
    assert 'data-run="credit_prequal"' in page.text
    assert "Last run · credit_prequal" in page.text
    assert ("GO" in page.text) and "red-team cases caught" in page.text
    assert 'data-human-gate="' in page.text and "Decision 33" in page.text
    assert "/console/onboard/files/credit_prequal/profile.json" in page.text
    f = console.get("/console/onboard/files/credit_prequal/launch_report.json")
    assert f.status_code == 200 and f.headers["x-content-type-options"] == "nosniff"
    assert "catch_rate_bp" in f.text
    # every wizard step is done after a full run
    assert page.text.count('class="wstep done"') == 5
    # the run used the console's own chain writer: the whole chain still verifies offline
    v = console.post("/console/chain/verify")
    assert v.status_code == 200 and 'data-verify="ok"' in v.text, v.text
