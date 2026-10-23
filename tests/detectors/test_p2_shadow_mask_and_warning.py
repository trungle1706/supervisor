"""WP-P2: masking in SHADOW is kept (see test_gate_v2) and the start-up warning."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from supervisor.config import REPO_ROOT, load_settings
from supervisor.gateway.policy import load_policy_dir
from supervisor.wiring import make_detector_gate


def _gate(tmp_path: Path, **kw: object) -> object:
    s = load_settings(data_dir=tmp_path / "d", detectors_enabled=True, sql_backend="sqlite", **kw)
    return make_detector_gate(s, load_policy_dir(REPO_ROOT / "policies"))


def test_warns_when_dlp_transform_is_on_and_inline_redaction_is_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="supervisor.wiring"):
        _gate(tmp_path)
    assert any("INLINE_REDACTION_ENABLED" in r.getMessage() for r in caplog.records)


def test_no_warning_when_inline_redaction_is_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="supervisor.wiring"):
        _gate(tmp_path, inline_redaction_enabled=True)
    assert not any("INLINE_REDACTION_ENABLED" in r.getMessage() for r in caplog.records)


def test_no_warning_when_detectors_are_off(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    s = load_settings(data_dir=tmp_path / "d", sql_backend="sqlite")
    with caplog.at_level(logging.WARNING, logger="supervisor.wiring"):
        assert make_detector_gate(s, load_policy_dir(REPO_ROOT / "policies")) is None
    assert not caplog.records
