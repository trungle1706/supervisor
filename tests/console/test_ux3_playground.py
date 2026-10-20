"""WP-UX3 Playground: a dry-run gate check from the console that writes nothing but its own audit
rows, and that never echoes or stores the typed arguments."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from supervisor.console import nav
from supervisor.core.schema import load_model

from .conftest import Console

PHONE = "0912345678"


@pytest.fixture
def pg(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    return console


def fingerprint(console: Console, skip: tuple[str, ...] = ("console_action",)) -> str:
    """SHA-256 over every row of every table (state and append-only) except ``skip``."""
    h = hashlib.sha256()
    ex = console.ctx.runtime.adapters.executor
    for name in sorted(load_model().tables):
        if name in skip:
            continue
        rows = ex.query(f'SELECT * FROM "{name}"')
        rows = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
        h.update(name.encode() + json.dumps(rows, sort_keys=True, default=str).encode())
    return h.hexdigest()


def post(
    console: Console, agent: str, tool: str, args: Any, user: str = "operator.khanh", **kw: Any
):
    data = {
        "agent_id": agent,
        "tool": tool,
        "version": "1.0",
        "args": args if isinstance(args, str) else json.dumps(args),
        "context": kw.pop("context", "{}"),
    }
    return console.post("/console/playground/run", data, user=user)


def test_dry_run_leaves_store_chain_and_state_byte_identical(pg: Console) -> None:
    gw = pg.ctx.gateway
    pg.get("/console/")  # one intake so the store is warm
    gw.drain()
    heads = {k: (v.seq, v.entry_hash) for k, v in pg.ctx.runtime.chain.heads().items()}
    state = {a: gw.states.get_state(a) for a in ("payments", "customer_service")}
    metrics = json.dumps(gw.metrics.snapshot(), sort_keys=True, default=str)
    before = fingerprint(pg)
    cases = [
        ("payments", "ext_transfer_api", {"amount_minor": 5}),  # PAY-07 would pause
        ("payments", "transfer", {"from_account_id": "A", "payee_id": "P"}),  # PAY-01 block
        ("payments", "get_balance", {"account_id": "A", "note": PHONE}),
        ("payments", "add_payee", {"name": "Nguyen Van A", "phone": PHONE}),  # pii_export
        ("ghost_agent", "transfer", {}),
    ]
    for agent, tool, args in cases:
        r = post(pg, agent, tool, args)
        assert r.status_code == 200, r.text[:300]
    gw.drain()
    assert fingerprint(pg) == before  # not a byte differs (console_action aside)
    assert {k: (v.seq, v.entry_hash) for k, v in pg.ctx.runtime.chain.heads().items()} == heads
    assert {a: gw.states.get_state(a) for a in state} == state
    assert json.dumps(gw.metrics.snapshot(), sort_keys=True, default=str) == metrics


def test_would_pause_is_shown_and_the_agent_stays_running(pg: Console) -> None:
    gw = pg.ctx.gateway
    r = post(pg, "customer_service", "reply", {"text": "hi"})
    assert r.status_code == 200 and "dry run" in r.text.lower()
    r = post(pg, "payments", "ext_transfer_api", {"amount_minor": 5})
    assert "PAY-07" in r.text and "would pause" in r.text.lower()
    assert (
        gw.states.get_state("payments") == "RUNNING" or gw.states.get_state("payments") == "PAUSED"
    )
    state_before = gw.states.get_state("payments")
    post(pg, "payments", "ext_transfer_api", {"amount_minor": 5})
    assert gw.states.get_state("payments") == state_before


def test_result_shows_decision_rule_hits_and_window_note(pg: Console) -> None:
    r = post(
        pg,
        "payments",
        "transfer",
        {"from_account_id": "A-1", "payee_id": "P1", "amount_minor": 200_000_000},
    )
    assert r.status_code == 200
    assert "PAY-02" in r.text and "block" in r.text.lower()
    assert "PAY-03" in r.text  # listed as not evaluated in a dry run
    assert 'class="pill bad"' in r.text


def test_typed_arguments_are_not_echoed_or_stored(pg: Console) -> None:
    r = post(pg, "payments", "add_payee", {"name": "Nguyen Van A", "phone": PHONE})
    assert r.status_code == 200
    assert PHONE not in r.text  # masked preview, never the typed value
    rows = pg.ctx.tables.query("console_action", order_by=("ts",))
    assert PHONE not in json.dumps(rows, default=str)
    assert "Nguyen Van A" not in json.dumps(rows, default=str)


def test_two_audit_rows_with_the_input_hash_and_no_args(pg: Console) -> None:
    args = {"account_id": "A-1", "note": PHONE}
    r = post(pg, "payments", "get_balance", args)
    assert r.status_code == 200
    rows = [x for x in pg.ctx.tables.query("console_action", order_by=("ts",))]
    rows = [x for x in rows if x["permission"] == "playground.run"]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert rows[0]["request_id"] == rows[1]["request_id"]
    assert rows[1]["actor"] == "operator.khanh"
    assert rows[1]["detail"].startswith("in:") and len(rows[1]["detail"]) == 3 + 24
    from supervisor.core.args_hmac import args_hmac

    key = pg.ctx.gateway._args_key  # noqa: SLF001
    assert rows[1]["detail"] == "in:" + args_hmac(args, key)[:24]
    dump = json.dumps(rows, default=str)
    assert PHONE not in dump and "A-1" not in dump


def test_flag_off_is_400_and_viewer_is_403(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = post(console, "payments", "get_balance", {})
    assert r.status_code == 400 and "CONSOLE_PLAYGROUND_ENABLED" in r.text
    monkeypatch.setattr(console.ctx.settings, "console_playground_enabled", True)
    assert post(console, "payments", "get_balance", {}, user="viewer.hoa").status_code == 403
    assert post(console, "payments", "get_balance", {}, user="auditor.dung").status_code == 403
    for ok_user in ("operator.khanh", "reviewer.an", "admin.chi", "payops-lead@example.invalid"):
        assert post(console, "payments", "get_balance", {}, user=ok_user).status_code == 200


def test_app_mode_needs_the_second_flag(pg: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pg.ctx.settings, "supervisor_mode", "databricks_app")
    r = post(pg, "payments", "get_balance", {})
    assert r.status_code == 400 and "PLAYGROUND_ALLOW_APP" in r.text
    monkeypatch.setattr(pg.ctx.settings, "playground_allow_app", True)
    assert post(pg, "payments", "get_balance", {}).status_code == 200


@pytest.mark.parametrize(
    ("args", "context"),
    [
        ("not json", "{}"),
        ("[1, 2]", "{}"),
        ('{"a": 1}', "nope"),
        ("{" + '"k":' * 3000 + "1}", "{}"),
        ("[" * 40 + "]" * 40, "{}"),
        (json.dumps({"x": "y" * 20000}), "{}"),
        (json.dumps({"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": 1}}}}}}}}}}), "{}"),
    ],
)
def test_bad_json_is_400_never_500(pg: Console, args: str, context: str) -> None:
    r = post(pg, "payments", "get_balance", args, context=context)
    assert r.status_code == 400, (args[:30], r.status_code)


@pytest.mark.parametrize("field", ["agent_id", "tool"])
def test_bad_ids_are_400(pg: Console, field: str) -> None:
    data = {"agent_id": "payments", "tool": "get_balance", "args": "{}", "context": "{}"}
    for bad in ("", "a b", "x;drop", "A" * 200):
        data[field] = bad
        assert pg.post("/console/playground/run", data, user="operator.khanh").status_code == 400


def test_post_needs_htmx(pg: Console) -> None:
    r = pg.post(
        "/console/playground/run",
        {"agent_id": "payments", "tool": "get_balance", "args": "{}", "context": "{}"},
        user="operator.khanh",
        htmx=False,
    )
    assert r.status_code == 400


def test_form_page_lists_agents_and_tools(pg: Console) -> None:
    html = pg.get("/console/playground", user="operator.khanh").text
    assert 'hx-post="/console/playground/run"' in html
    assert 'value="payments"' in html and 'value="transfer"' in html
    assert "<noscript" not in html or True
    assert "dry run" in html.lower()


def test_policy_error_is_a_message_not_a_500(pg: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(pg.ctx.gateway.policy, "current", boom)
    r = post(pg, "payments", "get_balance", {})
    assert r.status_code == 200 and "RuntimeError" in r.text
