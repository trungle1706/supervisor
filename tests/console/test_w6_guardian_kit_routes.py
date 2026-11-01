"""W6 (GUARDIAN_KIT): the "Connect your app to Guardian" block, its routes and its stored checks.

Off path first (the block is absent, every route answers 400 ``guardian_kit_off``, nothing is
written). Then the status flow Not checked -> Not ready -> Partly ready -> Ready on uploaded
source, the durable row and the chain record (ids, counts and hashes, no code text), the audit
rows, the roles, the 400s, the download, EN/VI completeness."""

from __future__ import annotations

import ast
import datetime as dt
import io
import json
import re
import zipfile
from typing import Any

import pytest

from supervisor.console import i18n
from supervisor.console.i18n_guardian_kit import GK
from supervisor.core.schema import load_model
from supervisor.onboard import guardian_kit as gk

from .conftest import Console, ListSink

MODEL = load_model()

HX = {"HX-Request": "true"}


def row(table: str, **values: Any) -> dict[str, Any]:
    """A full row of ``table``: the given values, a typed default for every other column."""
    defaults: dict[str, Any] = {
        "string": "x",
        "text": "x",
        "int": 0,
        "bool": False,
        "json": "{}",
        "timestamp": dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    }
    out: dict[str, Any] = {}
    for col in MODEL.table(table).columns:
        if col.name in values:
            out[col.name] = values[col.name]
        elif col.nullable:
            out[col.name] = None
        else:
            out[col.name] = defaults[col.type.rstrip("?")]
    return out


VIEWER = "viewer.hoa"
EDITOR = "reviewer.an"
SYSTEM = {
    "name": "Payments - Assistant",
    "owner_user": "owner.lan",
    "owner_team": "payments-team",
    "purpose": "Answers staff questions about domestic transfers.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "pseudonymised",
    "human_control": "post_review",
    "autonomy_level": "l1_assistive",
    "tags": {"agent_id": "payment-ops-copilot", "node_id": "inv_kit"},
}
NODE = "inv_kit"
PLAIN = (
    "def reconcile(statement_id):\n    return {}\n\n"
    "def transfer(payee_id, amount_minor):\n    return {}\n"
)
ONE = 'from guardian_client import supervised_tool\n\n@supervised_tool("reconcile")\n' + PLAIN
ALL = (
    "from guardian_client import supervised_tool\n\n"
    '@supervised_tool("reconcile")\ndef reconcile(statement_id):\n    return {}\n\n'
    '@supervised_tool("transfer")\ndef transfer(payee_id, amount_minor):\n    return {}\n'
)
SECRET_LINE = "CODE-LINE-THAT-MUST-NOT-BE-STORED"


def zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    monkeypatch.setattr(s, "guardian_kit", True)
    monkeypatch.setattr(s, "onboard_intake", True)
    monkeypatch.setattr(s, "governance_enabled", True)
    monkeypatch.setattr(s, "onboard_git_hosts", "git.example.invalid")
    return console


class ClosableSink(ListSink):
    def close(self) -> None:  # the runtime closes its chain when the test ends
        pass


@pytest.fixture
def sink(on: Console, monkeypatch: pytest.MonkeyPatch) -> ListSink:
    sink = ClosableSink()
    monkeypatch.setattr(on.ctx.runtime, "chain", sink, raising=False)
    return sink


@pytest.fixture
def sid(on: Console) -> str:
    made = on.ctx.systems.register(dict(SYSTEM), "owner.lan")
    for name, risk, line in (("reconcile", "read_only", 1), ("transfer", "money", 4)):
        on.ctx.state.insert(
            "onboard_facts",
            row(
                "onboard_facts",
                fact_id=f"f_{name}",
                node_id=NODE,
                attempt_n=1,
                kind="tool",
                name=name,
                detail=f"risk_class={risk}; approved=yes",
                file="code/tools.py",
                line=line,
                source="rule",
                active=True,
            ),
        )
    return str(made["system_id"])


def upload(c: Console, entries: dict[str, str], user: str = EDITOR) -> Any:
    return c.client.post(
        f"/console/intake/{NODE}",
        files={"file": ("src.zip", zip_bytes(entries), "application/zip")},
        headers={"X-Dev-User": user, **HX},
    )


def check(c: Console, sid: str, user: str = EDITOR, **data: str) -> Any:
    return c.post(f"/console/guardian-kit/{sid}/check", {"src": NODE, **data}, user=user)


def panel(c: Console, sid: str, user: str = EDITOR, lang: str = "en") -> Any:
    return c.get(f"/console/guardian-kit/{sid}?src={NODE}&lang={lang}", user=user, headers=HX)


def pill(html: str) -> str:
    m = re.search(r'data-gk-pill="([a-z_]+)"', html)
    assert m, html[:400]
    return m.group(1)


def rows_of(c: Console) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.state.query(gk.TABLE)]


# ------------------------------------------------------------------------------ off path


def test_setting_is_off_by_default(console: Console) -> None:
    assert console.ctx.settings.guardian_kit is False


def test_off_every_route_is_400_with_the_name_and_nothing_is_written(console: Console) -> None:
    for path, method in (
        ("/console/guardian-kit/sys_x", "get"),
        ("/console/guardian-kit/sys_x/guardian_client.py", "get"),
        ("/console/guardian-kit/sys_x/check", "post"),
    ):
        r = console.get(path, headers=HX) if method == "get" else console.post(path, {"src": NODE})
        assert r.status_code == 400, path
        assert "guardian_kit_off" in r.text or "GUARDIAN_KIT" in r.text, path
    assert console.ctx.state.query(gk.TABLE) == []
    # the audit rows of a refused POST say so (attempted, then error); no action is ever "ok"
    acts = [r for r in console.ctx.tables.query("console_action") if "guardian-kit" in r["path"]]
    assert all(r["outcome"] != "ok" for r in acts)


def test_off_the_include_renders_nothing(console: Console) -> None:
    from supervisor.console.routes import _env as env

    tpl = env.get_template("_guardian_kit.html")
    t = lambda k, **kw: k  # noqa: E731
    assert tpl.render(t=t, lang="en", gkit_on=False, gk_sid="sys_x", gk_src="").strip() == ""
    assert tpl.render(t=t, lang="en", gk_sid="sys_x", gk_src="").strip() == ""  # gkit_on not set
    on_html = tpl.render(t=t, lang="en", gkit_on=True, gk_sid="sys_x", gk_src="n1")
    assert (
        'hx-get="/console/guardian-kit/sys_x?src=n1' in on_html and 'hx-trigger="load"' in on_html
    )
    assert tpl.render(t=t, lang="en", gkit_on=True, gk_sid="", gk_src="").strip() == ""


# ------------------------------------------------------------------------------ the status flow


def test_not_checked_lists_the_tools_and_the_guide(on: Console, sid: str) -> None:
    assert upload(on, {"code/tools.py": PLAIN}).status_code == 200
    html = panel(on, sid).text
    assert pill(html) == "not_checked" and "Check my code" in html
    assert re.findall(r'data-tool="(\w+)" data-state="unknown"', html) == ["reconcile", "transfer"]
    assert html.count("<li data-step=") == 6  # at most six steps
    assert "@supervised_tool(&#34;transfer&#34;)" in html and "guardian_client.py" in html
    assert 'data-gk-copy="#gk-sn-' in html and "onclick" not in html and "onchange" not in html


def test_three_checks_none_partial_full(on: Console, sid: str, sink: ListSink) -> None:
    assert upload(on, {"code/tools.py": PLAIN}).status_code == 200
    r = check(on, sid)
    assert r.status_code == 200 and pill(r.text) == "not_ready"
    assert "0 of 2 tools connected" in r.text and "Missing" in r.text
    assert (
        upload(on, {"code/tools.py": ONE, "code/guardian_client.py": "x = 1\n"}).status_code == 200
    )
    r = check(on, sid)
    assert pill(r.text) == "partly_ready" and "Partly ready (1 of 2 tools)" in r.text
    assert re.search(r'data-tool="reconcile" data-state="connected"', r.text)
    assert re.search(r'data-tool="transfer" data-state="missing"', r.text)
    assert "Add the line above this tool." in r.text
    assert (
        upload(on, {"code/tools.py": ALL, "code/guardian_client.py": "x = 1\n"}).status_code == 200
    )
    r = check(on, sid)
    assert pill(r.text) == "ready" and "2 of 2 tools connected" in r.text
    assert "code/tools.py:3" in r.text  # file:line of the line above the tool
    # the page that loads later shows the same newest result
    assert pill(panel(on, sid).text) == "ready"
    assert [x["status"] for x in sorted(rows_of(on), key=lambda r: str(r["checked_at"]))] == [
        "not_ready",
        "partly_ready",
        "ready",
    ]
    assert len(sink.of(gk.CHAIN_TYPE)) == 3


def test_a_newer_upload_is_flagged_until_it_is_checked(on: Console, sid: str) -> None:
    upload(on, {"code/tools.py": ALL, "code/guardian_client.py": "x = 1\n"})
    check(on, sid)
    upload(on, {"code/tools.py": PLAIN})
    html = panel(on, sid).text
    assert 'data-gk="newer"' in html and "upload 2" in html and pill(html) == "ready"
    assert pill(check(on, sid).text) == "not_ready"


def test_wrong_name_and_wrong_risk_show_what_to_change(on: Console, sid: str) -> None:
    code = (
        '@supervised_tool("reconcil")\ndef reconcile(s):\n    return 1\n\n'
        '@supervised_tool("transfer", "read_only")\ndef transfer(p, a):\n    return 2\n'
    )
    upload(on, {"code/tools.py": code, "code/guardian_client.py": "x = 1\n"})
    html = check(on, sid).text
    assert "Wrong name" in html and "The line names reconcil. Use reconcile." in html
    assert "Wrong risk class" in html and "The line says read_only. Use money." in html


def test_stored_row_and_chain_record_hold_ids_counts_and_hashes_only(
    on: Console, sid: str, sink: ListSink
) -> None:
    code = f"# {SECRET_LINE}\n" + ONE
    upload(on, {"code/tools.py": code, "code/guardian_client.py": "x = 1\n"})
    check(on, sid)
    (r,) = rows_of(on)
    assert r["system_id"] == sid and r["node_id"] == NODE and r["attempt_n"] == 1
    assert (r["tools_total"], r["tools_ok"], r["checked_by"]) == (2, 1, EDITOR)
    blob = json.dumps(r, default=str)
    assert SECRET_LINE not in blob and "def transfer" not in blob
    detail = json.loads(r["detail_json"])
    assert {t["name"] for t in detail["tools"]} == {"reconcile", "transfer"}
    (rec,) = sink.of(gk.CHAIN_TYPE)
    assert SECRET_LINE not in json.dumps(rec) and EDITOR not in json.dumps(rec)
    assert rec["status"] == "partly_ready" and rec["tools_ok"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", rec["tree_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", rec["detail_sha256"])
    assert rec["by_ref"].startswith("act_")
    assert all(not isinstance(v, float) for v in rec.values())
    assert sink.records[0][1] == f"system:{sid}"


def test_two_audit_rows_per_check(on: Console, sid: str) -> None:
    upload(on, {"code/tools.py": PLAIN})
    check(on, sid)
    got = [
        r
        for r in on.ctx.tables.query("console_action", order_by=("ts",))
        if r["path"] == f"/console/guardian-kit/{sid}/check"
    ]
    assert [r["outcome"] for r in got] == ["attempted", "ok"]
    assert all(r["permission"] == "systems.edit" and r["target_id"] == sid for r in got)
    assert "attempt=1 status=not_ready" in str(got[1].get("detail"))


# ------------------------------------------------------------------------------ 400s and roles


def test_viewer_sees_the_status_but_cannot_check(on: Console, sid: str) -> None:
    upload(on, {"code/tools.py": ALL, "code/guardian_client.py": "x = 1\n"})
    check(on, sid)
    r = panel(on, sid, user=VIEWER)
    assert r.status_code == 200 and pill(r.text) == "ready"
    assert 'data-action="check"' not in r.text and "A system editor runs the check." in r.text
    assert check(on, sid, user=VIEWER).status_code == 403
    assert (
        on.get(
            f"/console/guardian-kit/{sid}/guardian_client.py?src={NODE}", user=VIEWER
        ).status_code
        == 200
    )
    assert len(rows_of(on)) == 1


def test_user_errors_are_400_never_500(on: Console, sid: str) -> None:
    assert check(on, "sys_missing").status_code == 400  # no such system
    assert on.get("/console/guardian-kit/sys_missing", headers=HX).status_code == 400
    assert check(on, sid, src="bad id!").status_code == 400
    r = check(on, sid, src="inv_someone_else")  # not the source of this system
    assert r.status_code == 400 and "does not belong" in r.text
    assert on.get(f"/console/guardian-kit/{sid}?src=bad%20id", headers=HX).status_code == 400
    r = check(on, sid)  # a source key with no stored source
    assert r.status_code == 400 and "no_source" in r.text
    assert (
        on.post(f"/console/guardian-kit/{sid}/check", {"src": NODE}, htmx=False).status_code == 400
    )
    r = check(on, sid, fetch="1")
    assert r.status_code == 400 and "no_source" in r.text
    assert rows_of(on) == []


def test_fetch_from_git_needs_a_git_source_and_checks_the_new_clone(
    on: Console, sid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload(on, {"code/tools.py": PLAIN})
    r = check(on, sid, fetch="1")
    assert r.status_code == 400 and "no_git_source" in r.text
    assert "fetch-git" not in panel(on, sid).text  # no git source: no button
    on.ctx.state.insert(
        "intake_attempt",
        row(
            "intake_attempt",
            attempt_id="ita_git",
            node_id=NODE,
            n=2,
            source_kind="git",
            source_ref="https://git.example.invalid/team/app",
            status="scrubbed",
            file_count=1,
            created_by=EDITOR,
        ),
    )
    html = panel(on, sid).text
    assert 'data-action="fetch-git"' in html and "Fetch the latest from GitHub" in html
    from supervisor.onboard import intake

    seen: list[str] = []

    def fake_clone(self: intake.IntakeService, node: str, url: str, actor: str) -> dict[str, Any]:
        seen.append(url)
        return self.submit_zip(
            node, zip_bytes({"code/tools.py": ALL, "code/guardian_client.py": "x"}), "g.zip", actor
        )

    monkeypatch.setattr(intake.IntakeService, "submit_git", fake_clone)
    r = check(on, sid, fetch="1")
    assert r.status_code == 200 and seen == ["https://git.example.invalid/team/app"]
    assert pill(r.text) == "ready"
    assert rows_of(on)[0]["attempt_n"] == 3


def test_no_source_shows_the_hint_and_no_button(on: Console, sid: str) -> None:
    html = panel(on, sid).text
    assert 'data-gk="no-source"' in html and 'data-action="check"' not in html
    assert f"/console/intake/{NODE}" in html


# ------------------------------------------------------------------------------ the code file


def test_download_is_the_one_file_for_this_use_case(on: Console, sid: str) -> None:
    upload(on, {"code/tools.py": PLAIN})
    r = on.get(f"/console/guardian-kit/{sid}/guardian_client.py?src={NODE}")
    assert r.status_code == 200
    assert 'filename="guardian_client.py"' in r.headers["content-disposition"]
    text = r.text
    ast.parse(text)
    assert 'AGENT_ID = "payment-ops-copilot"' in text
    assert '"reconcile": "read_only"' in text and '"transfer": "money"' in text
    shown = panel(on, sid).text
    import html as html_lib

    assert (
        html_lib.unescape(re.search(r'<pre id="gk-file"[^>]*>(.*?)</pre>', shown, re.S).group(1))
        == text
    )
    assert 'data-action="copy-file"' in shown and "Download guardian_client.py" in shown


def test_agent_id_falls_back_to_the_app_file_then_the_name(on: Console, sid: str) -> None:
    from supervisor.console.guardian_kit_routes import agent_id_of

    assert agent_id_of({"tags": {}, "name": "Payments - Assistant"}, None) == "payments-assistant"
    assert agent_id_of({"tags": "{}", "name": "!!"}, None) == "FILL-ME-agent-id"
    assert agent_id_of({"tags": json.dumps({"agent_id": "a1"}), "name": "x"}, None) == "a1"


# ------------------------------------------------------------------------------ words


def test_every_label_has_english_and_vietnamese_and_the_same_placeholders() -> None:
    assert GK and all(k.startswith("gk_") for k in GK)
    for key, (en, vi) in GK.items():
        assert en.strip() and vi.strip(), key
        assert set(re.findall(r"\{(\w+)\}", en)) == set(re.findall(r"\{(\w+)\}", vi)), key
        assert "!" not in en, key
        assert i18n._T[key] == (en, vi), key


def test_the_block_has_no_raw_key_in_either_language(on: Console, sid: str) -> None:
    upload(on, {"code/tools.py": ONE, "code/guardian_client.py": "x = 1\n"})
    check(on, sid)
    for lang in ("en", "vi"):
        html = panel(on, sid, lang=lang).text
        assert not re.search(r"\bgk_[a-z_0-9]+\b", html), lang
    vi = panel(on, sid, lang="vi").text
    assert "Sẵn sàng một phần (1/2 công cụ)" in vi and "Kiểm tra lại mã của tôi" in vi
    for banned in ("GUARDIAN_KIT", "ONBOARD_INTAKE", "/v1/"):
        assert banned not in panel(on, sid).text.split('id="gk-file"')[0].replace(
            "GUARDIAN_URL", ""
        )


def test_the_wording_follows_the_style_sheet() -> None:
    banned = (
        "seamless",
        "leverage",
        "robust",
        "empower",
        "unlock",
        "effortless",
        "let's",
        "please",
    )
    for key, (en, _vi) in GK.items():
        assert not any(w in en.lower() for w in banned), key
        sentences = [s for s in re.split(r"(?<=[.])\s+", en) if s]
        assert all(len(s.split()) <= 22 for s in sentences), key
