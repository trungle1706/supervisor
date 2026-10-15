# ruff: noqa: F811, F401
"""WP17 console: the Assurance screen is hidden by default and lists stored runs."""

from __future__ import annotations

import pytest

from tests.console.conftest import Console, adapters, console, seeded  # noqa: F401, F811


def _seed(console: Console) -> None:
    now = console.ctx.clock.now()
    t = console.ctx.tables
    t.append(
        "eval_result",
        [
            {
                "run_id": "run-test-1",
                "ts": now,
                "pack_id": "pii_canary",
                "pack_version": 1,
                "manifest_sha256": "ab" * 32,
                "dimension": "security",
                "target_kind": "agent",
                "target_id": "payments",
                "status": "fail",
                "metrics": {"leak_rate_bp": 900},
                "metric_status": {"leak_rate_bp": "fail"},
                "thresholds": {"leak_rate_bp": {"go": 0, "no_go": 500}},
                "reasons": "leak_rate_bp=900 misses no-go limit 500 (go <= 0)",
                "n_items": 16,
                "data_mode": "synthetic",
                "dataset_id": "pii",
                "dataset_sha256": "cd" * 32,
                "is_mock": True,
                "launch_gate": "required",
                "judge_gate": False,
                "details": {},
                "evidence_hash": "ef" * 32,
            }
        ],
    )
    t.append(
        "eval_run",
        [
            {
                "run_id": "run-test-1",
                "started_at": now,
                "finished_at": now,
                "target_spec": "agent:payments",
                "selector": "all",
                "packs_total": 1,
                "ok": 0,
                "warn": 0,
                "fail": 1,
                "skip": 0,
                "error": 0,
                "is_mock": True,
                "settings_digest": None,
                "out_dir": None,
            }
        ],
    )


def test_assurance_hidden_when_off(console: Console) -> None:
    assert console.ctx.settings.console_assurance_enabled is False
    assert console.get("/console/assurance").status_code == 404
    assert console.get("/console/assurance/run-test-1").status_code == 404
    page = console.get("/console/")
    assert page.status_code == 200 and "/console/assurance" not in page.text


def test_assurance_list_and_detail(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_assurance_enabled", True)
    _seed(console)
    r = console.get("/console/assurance")
    assert r.status_code == 200
    assert 'data-run="run-test-1"' in r.text and "agent:payments" in r.text
    assert "/console/assurance?lang=" in r.text  # nav entry
    d = console.get("/console/assurance/run-test-1")
    assert d.status_code == 200, d.text
    assert 'data-pack="pii_canary"' in d.text and 'data-status="fail"' in d.text
    assert "leak_rate_bp = 900" in d.text and "no-go 500" in d.text
    assert "/console/evidence" in d.text and "efefefefefef" in d.text
    vi = console.get("/console/assurance/run-test-1?lang=vi")
    assert vi.status_code == 200 and "Gói" in vi.text


def test_assurance_errors_are_400(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_assurance_enabled", True)
    assert console.get("/console/assurance/no-such-run").status_code == 400
    assert console.get("/console/assurance/bad$id").status_code == 400
