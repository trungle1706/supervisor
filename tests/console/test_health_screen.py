"""WP12: Health screen - preflight checks as a table with status pills; never a secret."""

from __future__ import annotations

import pytest

from .conftest import Console

SECRET = "dapi" + "0123456789abcdef" * 2


def test_health_table(console: Console) -> None:
    r = console.get("/console/health")
    assert r.status_code == 200, r.text
    for name in ("python", "no DATABRICKS_TOKEN", "config", "llm endpoint"):
        assert f'data-check="{name}"' in r.text, name
    assert 'data-status="OK"' in r.text and 'class="pill ok"' in r.text
    for row in ("h_mode", "h_identity", "h_judge", "h_key", "h_anchor", "h_databricks"):
        assert f'data-row="{row}"' in r.text, row
    assert "dev users file" in r.text and "dev key" in r.text  # laptop labels
    assert "Is Supervisor itself healthy?" in r.text
    vi = console.get("/console/health?lang=vi")
    assert "Bản thân Supervisor có ổn không?" in vi.text


def test_health_never_shows_secrets(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_TOKEN", SECRET)
    r = console.get("/console/health")
    assert r.status_code == 200
    assert SECRET not in r.text
    row = r.text.split('data-check="no DATABRICKS_TOKEN"', 1)[1].split("</tr>", 1)[0]
    assert 'data-status="FAIL"' in r.text and "value not shown" in row
