"""WP12 review fixes: onboarding guards, CSRF on new POSTs, read-model edges, scrubbing."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from typing import Any

import pytest

from supervisor.console import health, onboard_runs, readmodels

from .conftest import Console, add_gate_block

UTC = dt.UTC


def test_median_and_ict_midnight() -> None:
    assert readmodels.median([]) is None
    assert readmodels.median([5]) == 5
    assert readmodels.median([3, 1, 2, 4]) == 2  # nearest rank, one of the values
    # ICT midnight is 17:00 UTC of the previous day
    assert readmodels.day_start(dt.datetime(2026, 10, 15, 16, 59, tzinfo=UTC)) == dt.datetime(
        2026, 10, 14, 17, 0, tzinfo=UTC
    )
    assert readmodels.day_start(dt.datetime(2026, 10, 15, 17, 0, tzinfo=UTC)) == dt.datetime(
        2026, 10, 15, 17, 0, tzinfo=UTC
    )


def test_stops_are_counted_once_and_always_in_the_strip(console: Console) -> None:
    before = readmodels.gate_today(console.ctx, console.ctx.clock.now())
    event_id = add_gate_block(console.runtime.adapters)
    after = readmodels.gate_today(console.ctx, console.ctx.clock.now())
    assert after["stopped"] == before["stopped"] + 1 and after["blocked"] == before["blocked"] + 1
    stops = {v["event_id"] for v in readmodels.stop_verdicts(console.ctx, 500)}
    assert event_id in stops


def test_new_posts_need_htmx(console: Console) -> None:
    for url in ("/console/chain/export", "/console/onboard/start", "/console/chain/verify"):
        r = console.post(url, {}, user="admin.chi", htmx=False)
        assert r.status_code == 400 and "htmx" in r.text, url


def test_file_routes_reject_traversal(console: Console) -> None:
    for url in (
        "/console/onboard/files/../profile.json",
        "/console/onboard/files/..%2F..%2Fetc/profile.json",
        "/console/onboard/files/.hidden/profile.json",
        "/console/onboard/files/payments/secret.txt",
    ):
        r = console.get(url, headers={"HX-Request": "true"})
        assert r.status_code in (400, 404), url
    with pytest.raises(onboard_runs.OnboardInputError):
        onboard_runs.artefact_path(console.ctx.settings, "..", "profile.json")


def test_onboard_target_must_be_in_a_git_repo(tmp_path: Path) -> None:
    plain = tmp_path / "agent_x"
    plain.mkdir()
    with pytest.raises(onboard_runs.OnboardInputError, match="git repository"):
        onboard_runs.resolve_target(str(plain))
    link = tmp_path / "link"
    link.symlink_to(plain)
    with pytest.raises(onboard_runs.OnboardInputError, match="git repository"):
        onboard_runs.resolve_target(str(link))  # realpath: a symlink cannot escape the check


def test_second_start_is_refused_while_running(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.adapters.llm.mock import MockChat

    gate = threading.Event()

    def slow_run(*_a: Any, **kw: Any) -> Any:
        kw["echo"]("[OK] stub step with token=abc123secret")
        gate.wait(10)
        raise RuntimeError("stub stopped access_token=zzz999")

    monkeypatch.setattr("supervisor.onboard.run.run_onboarding", slow_run)
    monkeypatch.setattr(console.ctx.settings, "console_onboard_enabled", True)
    monkeypatch.setattr(onboard_runs, "pick_chat", lambda _s: MockChat(model_id="mock-onb-t"))
    first = console.post("/console/onboard/start", {"target": "src/supervisor_agents/payments"})
    assert first.status_code == 200, first.text
    busy = console.post("/console/onboard/start", {"target": "src/supervisor_agents/payments"})
    assert busy.status_code == 400 and "already in progress" in busy.text
    gate.set()
    job = console.ctx.onboard.latest()
    for _ in range(100):
        if job.status != "running":
            break
        threading.Event().wait(0.05)
    assert job.status == "failed" and job.finished_at is not None
    text = "\n".join(job.lines) + job.error
    assert "abc123secret" not in text and "zzz999" not in text  # scrubbed before display


def test_health_hides_url_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        health._clean("http://user:pw@127.0.0.1:11434/v1 ok") == "http://***@127.0.0.1:11434/v1 ok"
    )


def test_broken_artefact_does_not_break_the_page(console: Console) -> None:
    out = Path(console.ctx.settings.data_dir) / "onboard" / "broken_agent"
    out.mkdir(parents=True)
    (out / "profile.json").write_text('{"tool_risk_classes": ["not", "a", "dict"]}', "utf-8")
    r = console.get("/console/onboard")
    assert r.status_code == 200
