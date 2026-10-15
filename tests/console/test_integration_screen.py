"""WP15: Integration tab - off by default, reads reports from disk, escapes patch text."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.config import REPO_ROOT
from supervisor.console import integration_reports as ir

from .conftest import Console

REPORT = {
    "schema_version": 1,
    "agent_id": "card_support",
    "name": "card_support",
    "version": "1.0",
    "framework": "langchain",
    "found": {
        "framework": {"name": "langchain", "evidence": "app.py:3"},
        "llm_calls": [
            {
                "provider": "openai",
                "family": "gpt",
                "model": "gpt-x",
                "via": "sdk",
                "at": "app.py:9",
            }
        ],
        "tools": [
            {"name": "block_card", "risk_class": "money", "risk_source": "heuristic"},
        ],
        "data_access": [{"kind": "sql", "direction": "read", "target": "cards", "at": "a.py:1"}],
        "pii_fields": [{"name": "cccd", "at": "a.py:2"}],
        "tracing": ["otel"],
    },
    "needed": {
        "semconv": [{"operation": "execute_tool", "attributes": ["gen_ai.tool.name"]}],
        "gate_sites": [
            {
                "tool": "block_card",
                "risk_class": "money",
                "decorator": "@supervised_tool",
                "mode": "decorator",
                "at": "app.py:20",
            }
        ],
        "catalogue": [{"id": "cap.money", "name": "Money", "kind": "rule", "lane": "gate"}],
        "settings": [{"key": "SUPERVISOR_GATE_URL", "purpose": "gate", "example": "http://x"}],
        "test_plan": [{"dimension": "accuracy", "reason": "answers"}],
    },
    "readiness": {
        "total": 42,
        "areas": [
            {"id": "tracing", "weight": 20, "points": 8, "inputs": {}, "reason": "no semconv"}
        ],
    },
    "patches": [
        {
            "path": "app.py",
            "kind": "tool_gate",
            "description": "gate block_card",
            "file": "patches/01-app-py.patch",
        }
    ],
}
EVIL = "--- a/app.py\n+++ b/app.py\n+<script>alert(1)</script>\n"


@pytest.fixture
def reports(console: Console, tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    (root / "card_support" / "patches").mkdir(parents=True)
    (root / "card_support" / ir.REPORT_FILE).write_text(json.dumps(REPORT), encoding="utf-8")
    (root / "card_support" / "patches" / "01-app-py.patch").write_text(EVIL, encoding="utf-8")
    (root / "bad").mkdir()
    (root / "bad" / ir.REPORT_FILE).write_text("{not json", encoding="utf-8")
    console.ctx.settings.integration_reports_dir = root
    return root


def test_off_by_default(console: Console) -> None:
    assert console.ctx.settings.console_integration_enabled is False
    home = console.get("/console/agents")
    assert home.status_code == 200 and "/console/integration" not in home.text
    for url in (
        "/console/integration",
        "/console/integration/card_support",
        "/console/integration/card_support/patches/01-x.patch",
    ):
        r = console.get(url)
        assert r.status_code == 400 and "CONSOLE_INTEGRATION_ENABLED=1" in r.text, url


def test_list_page(console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    nav = console.get("/console/agents")
    assert "/console/integration?lang=" in nav.text
    r = console.get("/console/integration")
    assert r.status_code == 200
    assert 'data-report="card_support"' in r.text and "card_support" in r.text
    assert "42" in r.text and "langchain" in r.text
    assert 'data-report="bad"' in r.text and "cannot be read" in r.text
    vi = console.get("/console/integration?lang=vi")
    assert "Tư vấn tích hợp" in vi.text


def test_empty_list(console: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    console.ctx.settings.integration_reports_dir = tmp_path / "nothing"
    r = console.get("/console/integration")
    assert r.status_code == 200 and "data-integration-empty" in r.text


def test_report_page_and_patch(
    console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    r = console.get("/console/integration/card_support")
    assert r.status_code == 200, r.text
    assert 'data-score="42"' in r.text and "no semconv" in r.text
    assert "block_card" in r.text and "gen_ai.tool.name" in r.text
    assert "SUPERVISOR_GATE_URL" in r.text and "cap.money" in r.text
    assert 'data-patch="01-app-py.patch"' in r.text
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    p = console.get("/console/integration/card_support/patches/01-app-py.patch")
    assert p.status_code == 200 and p.headers["content-type"].startswith("text/plain")
    assert p.text == EVIL and p.headers["x-content-type-options"] == "nosniff"


def test_malformed_report_shows_message(
    console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    r = console.get("/console/integration/bad")
    assert r.status_code == 200 and "data-integration-error" in r.text
    (reports / "bad" / ir.REPORT_FILE).write_text("[1, 2]", encoding="utf-8")
    r = console.get("/console/integration/bad")
    assert r.status_code == 200 and "not a JSON object" in r.text
    # wrong shapes inside a valid object do not break the page either
    (reports / "bad" / ir.REPORT_FILE).write_text(
        json.dumps({"found": [], "needed": "x", "readiness": 3, "patches": "no"}),
        encoding="utf-8",
    )
    assert console.get("/console/integration/bad").status_code == 200
    assert console.get("/console/integration").status_code == 200


def test_path_escape_rejected(
    console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    (reports.parent / "secret.patch").write_text("x", encoding="utf-8")
    for url in (
        "/console/integration/.hidden",
        "/console/integration/card%2F..%2F..%2Fx",
        "/console/integration/nope",
        "/console/integration/card_support/patches/..%2F..%2Fsecret.patch",
        "/console/integration/card_support/patches/secret.txt",
        "/console/integration/card_support/patches/nope.patch",
    ):
        assert console.get(url).status_code in (400, 404), url
    for bad in ("..", "a/b", "a\\b", "", ".x", "x" * 70):
        with pytest.raises(ir.IntegrationInputError):
            ir.load_report(console.ctx.settings, bad)
    for bad in ("../secret.patch", "a/b.patch", "x.txt", "", ".patch"):
        with pytest.raises(ir.IntegrationInputError):
            ir.patch_path(console.ctx.settings, "card_support", bad)


def test_symlinked_patch_out_of_folder_rejected(
    console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    secret = reports.parent / "secret.patch"
    secret.write_text("x", encoding="utf-8")
    link = reports / "card_support" / "patches" / "link.patch"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("no symlinks here")
    assert console.get("/console/integration/card_support/patches/link.patch").status_code == 400


def test_roles(console: Console, reports: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    assert console.get("/console/integration", user="auditor.dung").status_code == 200
    assert console.get("/console/integration", user="nobody.at.all").status_code != 200


def test_real_advice_is_shown(
    console: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.advisory.integration.advise import advise
    from supervisor.advisory.integration.render import write_outputs

    monkeypatch.setattr(console.ctx.settings, "console_integration_enabled", True)
    target = REPO_ROOT / "data" / "corpus" / "repos" / "langchain_card_support"
    adv = advise(target)
    root = tmp_path / "real"
    write_outputs(adv, root / "card", target=target)
    console.ctx.settings.integration_reports_dir = root
    assert adv.patches
    page = console.get("/console/integration/card")
    assert page.status_code == 200, page.text
    assert f'data-score="{adv.report.readiness.total}"' in page.text
    assert page.text.count("data-patch=") == len(adv.patches)
    assert "missing" not in page.text.lower() or "not in the report folder" not in page.text
    first = Path(adv.report.patches[0].file).name
    assert console.get(f"/console/integration/card/patches/{first}").status_code == 200
