"""WP-UX3: traces (span tree), policies, credentials, users, audit log and integrations pages."""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from supervisor.console import nav, traces

from .conftest import Console

PHONE = "0912345678"
SECRET_KEY = "S3cr3t-key-value-0123456789-abcdefghijklmnop"


@pytest.fixture
def ux(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in nav.PAGES.values():
        monkeypatch.setattr(console.ctx.settings, flag, True)
    return console


def _event(
    console: Console,
    trace: str,
    span: str,
    parent: str | None,
    etype: str,
    *,
    level: str = "masked",
    args: str | None = None,
    result: str | None = None,
    tool: str | None = None,
    offset: int = 0,
    agent: str = "payments",
    classification: str | None = None,
    status: str = "completed",
) -> str:
    eid = uuid.uuid4().hex
    ts = console.ctx.clock.now() + dt.timedelta(milliseconds=offset)
    console.ctx.tables.append(
        "agent_event",
        [
            {
                "event_id": eid,
                "ts": ts,
                "trace_id": trace,
                "span_id": span,
                "parent_span_id": parent,
                "agent_id": agent,
                "event_type": etype,
                "tool_name": tool,
                "args_masked": args,
                "result_masked": result,
                "status": status,
                "latency_ms": 5,
                "env": "test",
                "source": "sdk",
                "capture_level": level,
                "classification": classification,
            }
        ],
    )
    return eid


def _verdict(
    console: Console,
    trace: str,
    event: str,
    *,
    tier: int = 0,
    checker: str = "gate:tier0a",
    action: str = "block",
    label: str = "matched",
    rule: str | None = "PAY-02",
    advisory: bool = False,
    mock: bool = False,
    family: str | None = None,
    rationale: str = "because",
) -> None:
    console.ctx.tables.append(
        "verdict",
        [
            {
                "verdict_id": uuid.uuid4().hex,
                "ts": console.ctx.clock.now(),
                "trace_id": trace,
                "event_id": event,
                "agent_id": "payments",
                "tier": tier,
                "checker_id": checker,
                "is_mock": mock,
                "advisory": advisory,
                "label": label,
                "action": action,
                "rule_id": rule,
                "model_family": family,
                "rationale_masked": rationale,
            }
        ],
    )


@pytest.fixture
def tree(ux: Console) -> str:
    """root message -> llm_call + tool_call(transfer) -> nothing after the gate stop."""
    t = "trace-ux3-tree"
    _event(ux, t, "s1", None, "message", level="masked", args="hello", offset=1)
    _event(ux, t, "s2", "s1", "llm_call", level="digest", args="PRIVATE-DIGEST-TEXT", offset=2)
    tc = _event(
        ux, t, "s3", "s1", "tool_call", tool="transfer", level="masked", offset=3,
        args=f"to {PHONE} amount 5", result=f"ok {PHONE}",
    )  # fmt: skip
    gate = _event(
        ux, t, "s4", "s3", "gate_decision", tool="transfer", offset=4, classification="block",
        status="denied", level="digest",
    )  # fmt: skip
    _verdict(ux, t, gate, action="block", rule="PAY-02")
    _verdict(ux, t, tc, checker="gate:tier0b", action="alert", label="injection", rule=None)
    _verdict(
        ux, t, tc, tier=1, checker="judge:t1", action="log", label="risky", rule=None,
        advisory=True, mock=True, family="qwen", rationale="judge says so",
    )  # fmt: skip
    return t


def test_traces_list_columns_filters_and_status(ux: Console, tree: str) -> None:
    html = ux.get("/console/traces/rows").text
    assert f'data-row="{tree}"' in html
    row = html.split(f'data-row="{tree}"')[1].split("</tr>")[0]
    assert ">4<" in row  # four spans
    assert "block" in row.lower() and "blocked" in row.lower()
    assert tree in ux.get("/console/traces/rows?status=blocked&agent=payments").text
    assert f'data-row="{tree}"' not in ux.get("/console/traces/rows?status=paused").text
    assert f'data-row="{tree}"' in ux.get(f"/console/traces/rows?q={tree[:10]}").text
    assert f'data-row="{tree}"' not in ux.get("/console/traces/rows?q=zzzz-none").text
    assert 'aria-sort="ascending"' in ux.get("/console/traces/rows?sort=spans&dir=asc").text
    for bad in ("status=weird", "range=forever", "page=0", "page=abc", "q=%3Cb%3E", "agent=a%20b"):
        assert ux.get(f"/console/traces/rows?{bad}").status_code == 400, bad


def test_span_tree_structure_and_marks(ux: Console, tree: str) -> None:
    r = ux.get(f"/console/traces/{tree}")
    assert r.status_code == 200
    html = r.text
    levels = re.findall(r'aria-level="(\d)"', html)
    assert levels == ["1", "2", "2", "3"]  # message > llm_call, tool_call > gate_decision
    assert html.index("message") < html.index("llm_call") < html.index("tool_call transfer")
    assert "gate_decision transfer" in html
    assert re.search(r'<span class="pill bad" title="block">B</span>', html)
    assert '<span class="pill neutral" title="judge">J</span>' in html or ">J<" in html
    # the stop is selected by default: the right panel opens on the gate decision
    assert 'aria-current="true"' in html
    assert "Selected span" in html and "PAY-02" in html


def test_span_panel_partial_and_verdict_kinds(ux: Console, tree: str) -> None:
    r = ux.get(f"/console/traces/{tree}/span/s3")
    assert r.status_code == 200 and "<html" not in r.text
    assert "tool_call transfer" in r.text
    assert "Tier 0b finding" in r.text and "injection" in r.text
    low = r.text.lower()
    assert "judge" in low and "mock" in low and "advisory" in low
    assert "judge says so" in r.text
    gate = ux.get(f"/console/traces/{tree}/span/s4").text
    assert "PAY-02" in gate and "Gate rule" in gate
    assert ux.get(f"/console/traces/{tree}/span/nope").status_code == 400
    assert ux.get(f"/console/traces/{tree}?span=nope").status_code == 400
    assert ux.get("/console/traces/no-such-trace").status_code == 400
    assert ux.get("/console/traces/a%20b").status_code in (400, 404)


def test_capture_level_decides_what_text_is_shown_and_never_raw_pii(ux: Console, tree: str) -> None:
    masked = ux.get(f"/console/traces/{tree}/span/s3").text
    assert PHONE not in masked  # the masker runs again before the excerpt is shown
    assert "PHONE" in masked and "Arguments (masked)" in masked
    digest = ux.get(f"/console/traces/{tree}/span/s2").text
    assert "PRIVATE-DIGEST-TEXT" not in digest and "Digest level" in digest
    full = ux.get(f"/console/traces/{tree}").text
    assert PHONE not in full and "PRIVATE-DIGEST-TEXT" not in full


def test_raw_level_event_still_shows_masked_column_only(ux: Console) -> None:
    t = "trace-ux3-raw"
    _event(ux, t, "r1", None, "tool_call", tool="transfer", level="raw", args=f"call {PHONE}")
    html = ux.get(f"/console/traces/{t}").text
    assert PHONE not in html
    # no masker configured -> no text at all (fail safe, like the recorder)


def test_no_masker_shows_no_text(ux: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ux.ctx.settings, "masker_kind", "none")
    t = "trace-ux3-nomask"
    _event(ux, t, "n1", None, "tool_call", tool="transfer", level="masked", args=f"call {PHONE}")
    html = ux.get(f"/console/traces/{t}").text
    assert PHONE not in html and "Digest level" in html


def test_cycles_missing_parents_and_the_span_cap(ux: Console) -> None:
    t = "trace-ux3-weird"
    _event(ux, t, "a", "b", "message", offset=1)
    _event(ux, t, "b", "a", "llm_call", offset=2)  # a cycle
    _event(ux, t, "c", "ghost", "tool_call", tool="x", offset=3)  # parent not in the trace
    assert ux.get(f"/console/traces/{t}").status_code == 200
    nodes, extra = traces.build_tree(
        [
            {"event_id": str(i), "ts": ux.ctx.clock.now(), "span_id": f"s{i}",
             "parent_span_id": None, "event_type": "message", "tool_name": None}
            for i in range(traces.MAX_SPANS + 7)
        ]
    )  # fmt: skip
    assert len(nodes) == traces.MAX_SPANS and extra == 7


def test_traces_flag_viewer_roles(console: Console) -> None:
    assert console.get("/console/traces/x").status_code == 400  # flag off


# ------------------------------------------------------------------ policies


def test_policies_lists_rules_versions_and_filters(ux: Console) -> None:
    html = ux.get("/console/policies", user="viewer.hoa").text
    assert "Deployed policy versions" in html and "in force" in html
    for rid in ("PAY-07", "PAY-02", "SVC-01", "CRD-02"):
        assert rid in html
    assert "_manifest" not in html
    rows = ux.get("/console/policies/rows?action=pause").text
    assert "PAY-07" in rows and "PAY-02" not in rows
    assert "PAY-07" not in ux.get("/console/policies/rows?severity=high").text
    assert "SVC-01" not in ux.get("/console/policies/rows?agent=payments").text
    assert "PAY-02" in ux.get("/console/policies/rows?agent=payments").text
    assert "PAY-02" in ux.get("/console/policies/rows?risk=money").text
    assert "CRD-02" not in ux.get("/console/policies/rows?risk=money").text
    assert "PAY-02" in ux.get("/console/policies/rows?q=single").text
    assert 'aria-sort="descending"' in ux.get("/console/policies/rows?sort=severity&dir=desc").text
    for bad in ("action=x", "severity=x", "risk=x", "page=77", "q=%3C"):
        assert ux.get(f"/console/policies/rows?{bad}").status_code == 400, bad


def test_policy_drawer_yaml_refs_and_versions(ux: Console) -> None:
    d = ux.get("/console/policies/PAY-02/drawer?tab=details").text
    assert "Internal limit" in d and "payments" in d and "Catalogue capabilities" in d
    assert "single_limit" in d  # a gate-rule manifest for money
    y = ux.get("/console/policies/PAY-02/drawer?tab=yaml").text
    assert "100000000" in y and "agent_scope" in y
    v = ux.get("/console/policies/PAY-02/drawer?tab=versions").text
    assert "in force" in v
    assert ux.get("/console/policies?drawer=PAY-02&dtab=yaml").status_code == 200
    assert ux.get("/console/policies/NOPE-1/drawer").status_code == 400
    assert ux.get("/console/policies/PAY-02/drawer?tab=zzz").status_code == 400


def test_policies_is_read_only(ux: Console) -> None:
    html = ux.get("/console/policies").text
    main = html.split('id="main"')[1].split("</main>")[0]
    assert "hx-post" not in main and 'method="post"' not in main.lower()
    for method in ("post", "put", "delete"):
        r = getattr(ux.client, method)("/console/policies", headers={"X-Dev-User": "admin.chi"})
        assert r.status_code in (404, 405)


# ------------------------------------------------------------------ credentials


@pytest.fixture
def keys_file(ux: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "agent_keys.yaml"
    path.write_text(
        "agents:\n"
        "  payments:\n"
        "    keys:\n"
        "      - {key_id: k-20261001120000, state: current, secret: "
        f"{SECRET_KEY}, expires_at: null}}\n"
        "      - {key_id: k-20260901120000, state: previous, secret: "
        f"{SECRET_KEY}OLD, expires_at: '2026-01-01T00:00:00Z'}}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    ident = tmp_path / "agent_identities.yaml"
    ident.write_text(
        "principals:\n  - principal: 8f3a1c2e-aaaa-bbbb-cccc-0123456789ab\n"
        "    agents: [payments]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ux.ctx.settings, "ingress_keys_file", path)
    monkeypatch.setattr(ux.ctx.settings, "ingress_identities_file", ident)
    monkeypatch.setattr(ux.ctx.settings, "ingress_key_store", "file")
    return path


def test_credentials_show_metadata_and_never_a_secret(ux: Console, keys_file: Path) -> None:
    r = ux.get("/console/credentials", user="admin.chi")
    assert r.status_code == 200
    html = r.text
    assert "k-20261001120000" in html and "k-20260901120000" in html
    assert "current" in html and "previous" in html
    assert "2026-10-01 19:00" in html or "2026-10-01" in html  # issued from the key id
    assert SECRET_KEY not in html and "S3cr3t" not in html
    assert "8f3a1c2e-aaaa-bbbb-cccc-0123456789ab" not in html  # principal is shortened
    assert "8f3a...89ab" in html
    assert "ingress_auth rotate" in html
    assert "INGRESS_AUTH_ENABLED is off" in html  # the flag is off in the test store
    # the owner role may open it too; the secret is not in any header either
    r2 = ux.get("/console/credentials", user="payops-lead@example.invalid")
    assert r2.status_code == 200 and SECRET_KEY not in json.dumps(dict(r2.headers))


def test_credentials_message_when_ingress_is_on(
    ux: Console, keys_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ux.ctx.settings, "ingress_auth_enabled", True)
    html = ux.get("/console/credentials", user="admin.chi").text
    assert "INGRESS_AUTH_ENABLED is off" not in html


def test_credentials_unreadable_store_is_a_message(
    ux: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "keys.yaml"
    bad.write_text("agents: [not, a, mapping]\n", encoding="utf-8")
    bad.chmod(0o600)
    monkeypatch.setattr(ux.ctx.settings, "ingress_keys_file", bad)
    monkeypatch.setattr(ux.ctx.settings, "ingress_key_store", "file")
    r = ux.get("/console/credentials", user="admin.chi")
    assert r.status_code == 200 and "Cannot read" in r.text


def test_credentials_loose_file_mode_is_a_message_without_the_path(
    ux: Console, keys_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys_file.chmod(0o644)
    r = ux.get("/console/credentials", user="admin.chi")
    assert r.status_code == 200 and "Cannot read" in r.text
    assert str(keys_file) not in r.text and SECRET_KEY not in r.text


# ------------------------------------------------------------------ users


def test_users_page_dev_users_roles_and_matrix(ux: Console) -> None:
    html = ux.get("/console/users", user="admin.chi").text
    assert "reviewer.an" in html and "admin.chi" in html and "users.yaml" in html
    from supervisor.core import rbac

    for perm in rbac.PERMISSIONS:
        assert f"{perm}</span>" in html
    assert "playground.run" in html and "audit.view" in html
    # admin.chi holds two roles: one row, both roles
    row = html.split('<td class="mono">admin.chi</td>')[1].split("</tr>")[0]
    assert "admin" in row and "reviewer" in row


def test_users_page_databricks_role_map(ux: Console, tmp_path: Path) -> None:
    from supervisor.adapters.auth import set_provider
    from supervisor.adapters.auth.databricks_app import DatabricksAppPrincipal

    prov = DatabricksAppPrincipal(
        {"admin": ["boss@bank.example"], "viewer": ["v@bank.example", "FILL-ME-x@y"]},
        {"admin": ["supervisor-admins"]},
        service_principal_id="11111111-2222-3333-4444-555555555555",
    )
    ux.ctx.provider = prov
    set_provider(prov)
    r = ux.get("/console/users", user=None, headers={"X-Forwarded-Email": "boss@bank.example"})
    assert r.status_code == 200
    assert "boss@bank.example" in r.text and "v@bank.example" in r.text
    assert "supervisor-admins" in r.text and "auth.yaml" in r.text
    assert "FILL-ME" not in r.text  # a placeholder never matches anyone
    assert "11111111-2222-3333-4444-555555555555" not in r.text  # shortened
    assert "token" not in r.text.lower().replace("tokens", "")


# ------------------------------------------------------------------ audit log


def _audit_rows(ux: Console) -> list[dict[str, Any]]:
    return ux.ctx.tables.query("console_action", order_by=("ts",))


def test_audit_log_lists_filters_and_drawer(ux: Console) -> None:
    ux.get("/console/")  # intake: a case exists
    case = next(c for c in ux.ctx.cases.list_cases() if "PAY-07" in c["summary"])
    ux.post(
        f"/console/cases/{case['case_id']}/comment",
        {"text": "note", "row_version": case["row_version"]},
        user="reviewer.an",
    )
    ux.post(f"/console/cases/{case['case_id']}/assign", {"assignee": "x"}, user="viewer.hoa")
    r = ux.get("/console/audit", user="auditor.dung")
    assert r.status_code == 200 and "audit-tbl" in r.text
    rows = ux.get("/console/audit/rows", user="auditor.dung").text
    assert "case.comment" in rows and "reviewer.an" in rows
    only = ux.get("/console/audit/rows?actor=reviewer.an&permission=case.comment", user="admin.chi")
    assert "case.comment" in only.text and "viewer.hoa" not in only.text
    err = ux.get("/console/audit/rows?outcome=ok", user="admin.chi").text
    assert "outcome" not in err or "attempted" not in err.split("<tbody")[1]
    assert (
        f"case:{case['case_id']}"
        in ux.get(f"/console/audit/rows?target={case['case_id'][:8]}", user="auditor.dung").text
    )
    assert (
        'data-row="' not in ux.get("/console/audit/rows?target=zzzz-none", user="auditor.dung").text
    )
    ids = re.findall(r'data-row="([0-9a-f]+)"', rows)
    ok_row = next(
        x for x in _audit_rows(ux) if x["permission"] == "case.comment" and x["outcome"] == "ok"
    )
    d = ux.get(f"/console/audit/{ok_row['action_id']}/drawer", user="auditor.dung").text
    assert ok_row["before_hash"] in d and ok_row["after_hash"] in d
    assert ok_row["request_id"] in d and "Rows of the same request" in d
    assert ids and ux.get(f"/console/audit?drawer={ids[0]}", user="auditor.dung").status_code == 200
    assert ux.get("/console/audit/zzzz/drawer", user="auditor.dung").status_code == 400
    for bad in ("outcome=x", "range=x", "page=999", "actor=a%20b", "permission=%3C"):
        assert ux.get(f"/console/audit/rows?{bad}", user="auditor.dung").status_code == 400, bad


def test_audit_log_is_read_only_and_denies_other_roles(ux: Console) -> None:
    for user in ("viewer.hoa", "reviewer.an", "operator.khanh"):
        assert ux.get("/console/audit", user=user).status_code == 403
        assert ux.get("/console/audit/rows", user=user).status_code == 403
        assert ux.get("/console/audit/abc/drawer", user=user).status_code == 403
    before = len(_audit_rows(ux))
    ux.get("/console/audit", user="auditor.dung")
    assert len(_audit_rows(ux)) == before  # a GET never writes


def test_audit_paging(ux: Console) -> None:
    for i in range(30):
        ux.ctx.tables.append(
            "console_action",
            [
                {
                    "action_id": uuid.uuid4().hex,
                    "ts": ux.ctx.clock.now() + dt.timedelta(seconds=i),
                    "request_id": uuid.uuid4().hex,
                    "actor": "bulk.user",
                    "actor_kind": "user",
                    "auth_method": "dev_header",
                    "roles": ["viewer"],
                    "permission": "inbox.read",
                    "method": "POST",
                    "path": "/console/inbox/x/read",
                    "outcome": "ok",
                }
            ],
        )
    p1 = ux.get("/console/audit/rows?actor=bulk.user&page=1", user="auditor.dung").text
    p2 = ux.get("/console/audit/rows?actor=bulk.user&page=2", user="auditor.dung").text
    assert len(re.findall(r'data-row="', p1)) == 25 and len(re.findall(r'data-row="', p2)) == 5
    assert (
        ux.get("/console/audit/rows?actor=bulk.user&page=3", user="auditor.dung").status_code == 400
    )


# ------------------------------------------------------------------ integrations


def test_integrations_status_and_no_secret(
    ux: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIEM_ENABLED", "1")
    monkeypatch.setenv("SIEM_SINK", "http")
    monkeypatch.setenv("SIEM_FORMAT", "cef")
    monkeypatch.setenv(
        "SIEM_HTTP_URL", "https://siem.bank.example/services/collector?token=URLSECRET"
    )
    monkeypatch.setenv("SIEM_HTTP_TOKEN", "TOKENSECRET")
    dead = tmp_path / "dead.jsonl"
    dead.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    monkeypatch.setenv("SIEM_DEAD_LETTER_PATH", str(dead))
    monkeypatch.setenv("PAGER_ENABLED", "1")
    html = ux.get("/console/integrations", user="viewer.hoa").text
    for word in ("SIEM sink", "Webhook notifier", "Pager", "ITSM", "SCIM"):
        assert word in html
    assert "siem.bank.example" in html and "cef" in html
    assert "URLSECRET" not in html and "TOKENSECRET" not in html and "collector" not in html
    siem = html.split('data-row="siem"')[1].split("</tr>")[0]
    assert ">2<" in siem  # two dead letters, counted from the file
    assert html.count("stub (fake)") == 3  # pager, ITSM, SCIM
    assert "Read-only" in html or "read-only" in html


def test_integrations_defaults_all_off(ux: Console) -> None:
    html = ux.get("/console/integrations", user="viewer.hoa").text
    siem = html.split('data-row="siem"')[1].split("</tr>")[0]
    assert "off" in siem
    web = html.split('data-row="webhook"')[1].split("</tr>")[0]
    assert "off" in web and ">0<" in web.replace(">0 ", ">0<")


def test_integrations_webhook_counts_notices(ux: Console) -> None:
    ux.ctx.runtime.adapters.state.insert(
        "notice",
        {
            "notice_id": "N-WH-1",
            "ts": ux.ctx.clock.now(),
            "channel": "webhook:ops",
            "subject": "s",
            "body": "b",
            "status": "dead_letter",
        },
    )
    html = ux.get("/console/integrations", user="viewer.hoa").text
    web = html.split('data-row="webhook"')[1].split("</tr>")[0]
    assert "pill bad" in web  # one dead letter
