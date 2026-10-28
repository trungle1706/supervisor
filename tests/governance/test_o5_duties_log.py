"""WP-O5: the duties step submit writes one agent log row (step duties, by rule) when
ONBOARD_POSTDEPLOY is on, and none when it is off."""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import Console
from .test_l2_duties_step import draft_to_duties, duties, page, reg  # noqa: F401  (fixtures)
from .test_n3_register import step, submit


def _submit_duties_draft(c: Console) -> None:
    did = draft_to_duties(c, {"money_movement": "1", "human_control": "pre_approval"})
    assert (
        step(c, did, 4, {"Q-cross_border": "no", "Q-model_hosting": "on_prem"}).status_code == 200
    )
    assert step(c, did, 5).status_code == 200
    assert step(c, did, 6, {"bind_form": "1"}).status_code == 200
    page(c, did, 7)
    assert submit(c, did).status_code == 200


def _log(c: Console) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.tables.query("onboard_log", {"step": "duties"})]


def test_duties_submit_logs_one_row_by_rule(
    duties: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(duties.ctx.settings, "onboard_postdeploy", True)
    _submit_duties_draft(duties)
    (row,) = _log(duties)
    assert (row["step"], row["by_kind"], row["actor"]) == ("duties", "rule", "rule")
    assert "duty rows" in row["what"] and row["pointer"].startswith("system ")


def test_duties_submit_off_writes_no_log_row(duties: Console) -> None:  # noqa: F811
    assert duties.ctx.settings.onboard_postdeploy is False
    _submit_duties_draft(duties)
    assert _log(duties) == []
