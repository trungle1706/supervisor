# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-G2: the benchmark API and the Benchmark panel: off path, RBAC, 400 not 500, HTMX, audit."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.core import rbac
from tests.guardian_factory.conftest import adapters, console, gf, regex_def, seeded  # noqa: F401

AN = "reviewer.an"  # reviewer, data group
EM = "approver.em"  # approver, not in the data group
HOA = "viewer.hoa"
CHI = "admin.chi"
HX = {"HX-Request": "true"}
DEF = "account-numbers"
NEW_ROUTES = [
    ("GET", f"/v1/guardian-defs/{DEF}/bench-packs"),
    ("POST", f"/v1/guardian-defs/{DEF}/bench-packs"),
    ("POST", f"/v1/guardian-defs/{DEF}/benchmark"),
    ("GET", f"/v1/guardian-defs/{DEF}/benchmark/gbr_x"),
    ("POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked"),
    ("GET", f"/console/guardian-factory/{DEF}/benchmark"),
    ("POST", f"/console/guardian-factory/{DEF}/bench-packs/generate"),
    ("POST", f"/console/guardian-factory/{DEF}/bench-packs/import-traces"),
    ("POST", f"/console/guardian-factory/{DEF}/bench-packs/upload"),
    ("POST", f"/console/guardian-factory/{DEF}/benchmark"),
    ("POST", f"/console/guardian-factory/{DEF}/mark-benchmarked"),
]


def api(c: Any, method: str, url: str, body: Any = None, user: str = AN) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def make(c: Any, **over: Any) -> None:
    r = api(c, "POST", "/v1/guardian-defs", regex_def(**over))
    assert r.status_code == 201, r.text


def settle(c: Any, def_id: str = DEF) -> None:
    c.ctx.guardian_bench.join(def_id)


def gen(c: Any, pack: str = "starter", user: str = AN) -> Any:
    return api(
        c, "POST", f"/v1/guardian-defs/{DEF}/bench-packs", {"op": "generate", "pack_id": pack}, user
    )


def run_to_pass(c: Any) -> dict[str, Any]:
    make(c, benchmark_pack="starter")
    assert gen(c).status_code == 201
    r = api(c, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {})
    assert r.status_code == 202, r.text
    settle(c)
    return api(c, "GET", f"/v1/guardian-defs/{DEF}/benchmark/{r.json()['run_id']}").json()


# ============================================================ off path


def test_off_every_new_route_answers_400_and_reads_no_table(
    console: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    orig_q, orig_g = console.ctx.state.query, console.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_g(table, *a, **k)

    monkeypatch.setattr(console.ctx.state, "query", spy_q)
    monkeypatch.setattr(console.ctx.state, "get", spy_g)
    for method, path in NEW_ROUTES:
        r = console.client.request(
            method,
            path,
            json={} if path.startswith("/v1") else None,
            headers={"X-Dev-User": AN, **HX},
        )
        assert r.status_code == 400, (method, path, r.status_code)
        assert "guardian_factory_off" in r.text, (method, path)
        assert 'id="gf-bench"' not in r.text
    assert not [t for t in calls if t.startswith("guardian_")], calls
    assert not (console.ctx.settings.data_dir / "guardian_factory").exists()


# ============================================================ JSON API


def test_api_generate_run_poll_and_mark(gf: Any) -> None:
    run = run_to_pass(gf)
    assert run["status"] == "done" and run["gate"] == "pass" and run["failing_threshold"] == ""
    levels = run["result"]["levels"]
    assert [x["sensitivity"] for x in levels] == [1, 2, 3, 4]
    assert run["result"]["live"]["slug"] == "injection_regex"
    packs = api(gf, "GET", f"/v1/guardian-defs/{DEF}/bench-packs", user="viewer.hoa")
    assert packs.status_code == 200
    assert [(p["id"], p["attack"], p["benign"], p["origin"]) for p in packs.json()["items"]] == [
        ("starter", 100, 140, "generated")
    ]
    r = api(gf, "POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked")
    assert r.status_code == 200 and r.json()["state"] == "benchmarked"
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked").status_code == 400
    # a change sends it back to draft
    r = api(
        gf, "POST", f"/v1/guardian-defs/{DEF}", regex_def(benchmark_pack="starter", name="Other")
    )
    assert r.status_code == 200 and r.json()["state"] == "draft"
    r = api(gf, "POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked")
    assert r.status_code == 400 and "no_passing_run" in r.json()["error"]


def test_api_failing_gate_names_the_threshold(gf: Any) -> None:
    make(
        gf,
        benchmark_pack="weak",
        thresholds={"min_tpr_pct": 90, "max_fpr_pct": 5, "max_p95_ms": 50},
    )
    body = {
        "op": "upload",
        "pack_id": "weak",
        "attack_jsonl": json.dumps(
            {"case_id": "a1", "stage": "input", "text": "no digits", "expected": True}
        ),
        "benign_jsonl": json.dumps(
            {"case_id": "b1", "stage": "input", "text": "xin chao", "expected": False}
        ),
    }
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/bench-packs", body).status_code == 201
    r = api(gf, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {})
    settle(gf)
    run = api(gf, "GET", f"/v1/guardian-defs/{DEF}/benchmark/{r.json()['run_id']}").json()
    assert run["gate"] == "fail" and run["failing_threshold"] == "min_tpr_pct"
    assert run["result"]["gate"]["checked"]["tpr_pct"] == 0
    r = api(gf, "POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked")
    assert r.status_code == 400 and "min_tpr_pct" in r.json()["error"]


def test_api_refusals_are_400_never_500(gf: Any) -> None:
    make(gf)
    url = f"/v1/guardian-defs/{DEF}/bench-packs"
    case = {"case_id": "a1", "stage": "input", "text": "goi 0912345678 ngay", "expected": True}
    cases: list[tuple[Any, str]] = [
        ({"op": "upload", "pack_id": "p", "attack_jsonl": json.dumps(case)}, "personal data"),
        ({"op": "upload", "pack_id": "p"}, "attack.jsonl"),
        ({"op": "upload", "pack_id": "p", "attack_jsonl": 5}, "JSONL text"),
        ({"op": "upload", "pack_id": "BAD ID", "attack_jsonl": "{}"}, "pack_id"),
        ({"op": "upload", "pack_id": "p", "attack_jsonl": "{bad"}, "not valid JSON"),
        ({"op": "dance", "pack_id": "p"}, "op"),
        ({"op": "generate", "pack_id": "p", "colour": "red"}, "unknown key"),
        ({"op": "import_traces", "pack_id": "p", "limit": "x"}, "limit"),
        ({"op": "upload", "pack_id": "p", "attack_jsonl": "x" * 6_000_000}, "pack_too_large"),
    ]
    for body, why in cases:
        r = api(gf, "POST", url, body)
        assert r.status_code == 400 and why in r.json()["error"], (body.get("op"), r.text[:200])
    for raw in (b"[1]", b"{oops"):
        r = gf.client.post(url, content=raw, headers={"X-Dev-User": AN})
        assert r.status_code == 400
    assert (
        api(gf, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {}).status_code == 400
    )  # no pack set
    assert (
        api(gf, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {"pack_id": "ghost"}).status_code
        == 400
    )
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {"x": 1}).status_code == 400
    assert api(gf, "GET", f"/v1/guardian-defs/{DEF}/benchmark/gbr_missing").status_code == 404
    assert api(gf, "GET", "/v1/guardian-defs/nope/bench-packs").status_code == 404
    assert api(gf, "POST", "/v1/guardian-defs/nope/benchmark", {}).status_code == 404
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked").status_code == 400
    assert gf.ctx.state.query("guardian_bench_run", {}) == []
    make(gf, id="nobody", scope={"agents": ["no-such-agent"], "tools": "*", "data_classes": []})
    body = {"op": "import_traces", "pack_id": "p"}
    r = api(gf, "POST", "/v1/guardian-defs/nobody/bench-packs", body)
    assert r.status_code == 400 and "no_traces" in r.json()["error"]


def test_run_rows_hold_integers_and_chain_records_are_written(gf: Any) -> None:
    run_to_pass(gf)
    row = gf.ctx.state.query("guardian_bench_run", {})[0]
    result = (
        json.loads(row["result_json"])
        if isinstance(row["result_json"], str)
        else row["result_json"]
    )

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            [walk(x) for x in v.values()]
        elif isinstance(v, list):
            [walk(x) for x in v]
        else:
            assert not isinstance(v, float)

    walk(result)
    assert row["gate"] == "pass" and row["status"] == "done" and row["finished_at"]


# ============================================================ RBAC


def test_viewer_reads_but_cannot_write(gf: Any) -> None:
    run_to_pass(gf)
    assert api(gf, "GET", f"/v1/guardian-defs/{DEF}/bench-packs", user=HOA).status_code == 200
    assert api(gf, "GET", f"/console/guardian-factory/{DEF}/benchmark", user=HOA).status_code == 200
    for method, path in (
        ("POST", f"/v1/guardian-defs/{DEF}/bench-packs"),
        ("POST", f"/v1/guardian-defs/{DEF}/benchmark"),
        ("POST", f"/v1/guardian-defs/{DEF}/mark-benchmarked"),
    ):
        assert (
            api(gf, method, path, {"op": "generate", "pack_id": "x"}, user=HOA).status_code == 403
        )
    r = gf.get(f"/console/guardian-factory/{DEF}/benchmark", user=HOA, headers=HX)
    assert (
        'data-action="bench-run"' not in r.text and 'data-action="mark-benchmarked"' not in r.text
    )


def test_only_group_members_run_their_group_benchmark(gf: Any) -> None:
    make(gf, benchmark_pack="starter")
    assert gen(gf, user=EM).status_code == 403
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/benchmark", {}, user=EM).status_code == 403
    assert gen(gf, user=CHI).status_code == 201  # an admin edits all
    r = gf.post(f"/console/guardian-factory/{DEF}/bench-packs/generate", {"pack_id": "z"}, user=EM)
    assert r.status_code == 403


def test_rbac_rows_exist() -> None:
    assert rbac.ROUTES[("GET", "/v1/guardian-defs/{def_id}/bench-packs")] == "guardians.view"
    assert rbac.ROUTES[("POST", "/v1/guardian-defs/{def_id}/bench-packs")] == "guardians.edit"
    assert rbac.ROUTES[("POST", "/v1/guardian-defs/{def_id}/benchmark")] == "guardians.edit"
    assert rbac.ROUTES[("GET", "/v1/guardian-defs/{def_id}/benchmark/{run_id}")] == "guardians.view"
    assert rbac.ROUTES[("POST", "/v1/guardian-defs/{def_id}/mark-benchmarked")] == "guardians.edit"
    assert rbac.ROUTES[("GET", "/console/guardian-factory/{def_id}/benchmark")] == "guardians.view"
    for p in ("bench-packs/{op}", "benchmark", "mark-benchmarked"):
        assert (
            rbac.ROUTES[("POST", f"/console/guardian-factory/{{def_id}}/{p}")] == "guardians.edit"
        )


# ============================================================ console panel


def test_panel_on_the_editor_page_and_as_a_fragment(gf: Any) -> None:
    r = gf.get("/console/guardian-factory/new")
    assert r.status_code == 200 and 'data-panel="benchmark"' in r.text
    make(gf, benchmark_pack="starter")
    r = gf.get(f"/console/guardian-factory/{DEF}")
    assert (
        'id="gf-bench"' in r.text and 'data-no-packs="1"' in r.text and 'data-no-run="1"' in r.text
    )
    assert 'data-action="bench-generate"' in r.text and 'data-action="bench-upload"' in r.text
    assert 'data-action="bench-import"' in r.text and 'data-action="bench-run"' in r.text
    frag = gf.get(f"/console/guardian-factory/{DEF}/benchmark", headers=HX)
    assert frag.status_code == 200 and "<html" not in frag.text and 'id="gf-bench"' in frag.text
    full = gf.get(f"/console/guardian-factory/{DEF}/benchmark")
    assert "<html" in full.text and 'id="gf-bench"' in full.text
    assert gf.get("/console/guardian-factory/missing/benchmark").status_code == 404


def test_console_generate_run_result_table_and_mark(gf: Any) -> None:
    make(gf, benchmark_pack="starter")
    base = f"/console/guardian-factory/{DEF}"
    r = gf.post(f"{base}/bench-packs/generate", {"pack_id": "starter"})
    assert r.status_code == 200 and 'data-pack="starter"' in r.text and "pack starter v1" in r.text
    assert "<td>100</td><td>140</td>" in r.text
    r = gf.post(f"{base}/benchmark", {"pack_id": "starter"})
    assert r.status_code == 200 and "benchmark gbr_" in r.text
    settle(gf)
    r = gf.get(f"{base}/benchmark", headers=HX)
    assert 'data-status="done"' in r.text and 'data-polling="1"' not in r.text
    assert 'data-gate="pass"' in r.text
    for lvl in (1, 2, 3, 4):
        assert f'data-level="{lvl}"' in r.text
    assert 'data-live="injection_regex"' in r.text and 'data-chosen="1"' in r.text
    assert "TPR %" in r.text and "p95 (us)" in r.text
    assert 'data-action="mark-benchmarked"' in r.text
    r = gf.post(f"{base}/mark-benchmarked", {})
    assert r.status_code == 200 and 'data-state="benchmarked"' in r.text
    assert 'data-action="mark-benchmarked"' not in r.text
    # the editor of a benchmarked guardian stays editable; a change resets it to draft
    r = gf.post(
        base,
        {
            "name": "Renamed",
            "description": "d",
            "owner_group": "data",
            "type": "regex",
            "stage": "input",
            "action_on_fail": "redact",
            "sensitivity": "2",
            "scope_agents": "*",
            "scope_tools": "*",
            "scope_data_classes": "",
            "benchmark_pack": "starter",
            "min_tpr_pct": "90",
            "max_fpr_pct": "5",
            "max_p95_ms": "50",
            "shadow_days": "0",
            "config_json": json.dumps(
                {"pattern": r"(?<!\d)\d{9,14}(?!\d)", "mask_token": "<ACCOUNT>"}
            ),
        },
    )
    assert r.status_code == 200 and 'data-state="draft"' in r.text


def test_panel_polls_while_a_run_is_active_and_shows_a_failed_run(gf: Any) -> None:
    make(gf, benchmark_pack="starter")
    gen(gf)
    # a queued row is shown as running, with the polling attributes
    gf.ctx.state.insert(
        "guardian_bench_run",
        {
            "run_id": "gbr_q",
            "def_id": DEF,
            "version": 1,
            "pack_id": "starter",
            "pack_sha256": "a" * 64,
            "def_sha256": "b" * 64,
            "status": "running",
            "started_at": gf.ctx.clock.now(),
            "finished_at": None,
            "result_json": "{}",
            "gate": "not_run",
            "failing_threshold": None,
            "created_by": "x",
        },
    )
    r = gf.get(f"/console/guardian-factory/{DEF}/benchmark", headers=HX)
    assert (
        'data-polling="1"' in r.text
        and 'hx-trigger="every 2s"' in r.text
        and 'data-running="1"' in r.text
    )
    gf.ctx.state.update(
        "guardian_bench_run",
        {"run_id": "gbr_q"},
        {"status": "failed", "result_json": '{"error": "boom"}'},
        gf.ctx.state.get("guardian_bench_run", {"run_id": "gbr_q"})["row_version"],
    )
    r = gf.get(f"/console/guardian-factory/{DEF}/benchmark", headers=HX)
    assert 'data-run-failed="1"' in r.text and "boom" in r.text and 'data-polling="1"' not in r.text


def test_console_failing_gate_names_the_threshold(gf: Any) -> None:
    make(gf, benchmark_pack="weak")
    base = f"/console/guardian-factory/{DEF}"
    up = {"op": "upload", "pack_id": "weak"}
    up["attack_jsonl"] = json.dumps(
        {"case_id": "a1", "stage": "input", "text": "none", "expected": True}
    )
    up["benign_jsonl"] = json.dumps(
        {"case_id": "b1", "stage": "input", "text": "xin", "expected": False}
    )
    assert api(gf, "POST", f"/v1/guardian-defs/{DEF}/bench-packs", up).status_code == 201
    gf.post(f"{base}/benchmark", {"pack_id": "weak"})
    settle(gf)
    r = gf.get(f"{base}/benchmark", headers=HX)
    assert 'data-gate="fail"' in r.text and 'data-failing="min_tpr_pct"' in r.text
    assert 'data-mark-problem="1"' in r.text and 'data-action="mark-benchmarked"' not in r.text
    r = gf.post(f"{base}/mark-benchmarked", {})
    assert r.status_code == 400 and "min_tpr_pct" in r.text


def test_console_upload_multipart_limits_and_masker(gf: Any) -> None:
    make(gf)
    url = f"/console/guardian-factory/{DEF}/bench-packs/upload"

    def up(
        name: str,
        body: bytes,
        which: str = "attack",
        user: str = AN,
        extra: dict[str, str] | None = None,
    ) -> Any:
        return gf.client.post(
            url,
            data={"pack_id": "up", "which": which, **(extra or {})},
            files={"file": (name, body, "application/octet-stream")},
            headers={"X-Dev-User": user, **HX},
        )

    good = json.dumps(
        {"case_id": "a1", "stage": "input", "text": "ma ZX12345", "expected": True}
    ).encode()
    r = up("attack.jsonl", good)
    assert r.status_code == 200 and 'data-pack="up"' in r.text
    r = up("benign.jsonl", good.replace(b"true", b"false").replace(b"a1", b"b1"), "benign")
    assert r.status_code == 200
    phone = json.dumps(
        {"case_id": "a2", "stage": "input", "text": "goi 0912345678", "expected": True}
    ).encode()
    r = up("attack.jsonl", phone)
    assert r.status_code == 400 and "personal data" in r.text
    assert up("attack.jsonl", b"x" * 5_200_000).status_code == 400
    assert up("attack.jsonl", good, which="both").status_code == 400
    assert up("attack.jsonl", good, user=HOA).status_code == 403
    r = gf.client.post(
        url, data={"pack_id": "up", "which": "attack"}, headers={"X-Dev-User": AN, **HX}
    )
    assert r.status_code == 400  # not multipart
    r = gf.client.post(url, data={"pack_id": "up"}, headers={"X-Dev-User": AN})  # no HX header
    assert r.status_code == 400
    r = gf.client.post(
        f"/console/guardian-factory/{DEF}/bench-packs/steal",
        data={},
        headers={"X-Dev-User": AN, **HX},
    )
    assert r.status_code == 400


def test_console_import_traces_and_generator_na(gf: Any) -> None:
    make(gf)
    base = f"/console/guardian-factory/{DEF}"
    # the seeded console holds stored, masked gate traces of the demo agents
    r = gf.post(f"{base}/bench-packs/import-traces", {"pack_id": "t", "limit": "10"})
    assert r.status_code == 200 and 'data-pack="t"' in r.text and "0 attack" in r.text
    r = gf.post(f"{base}/bench-packs/import-traces", {"pack_id": "t", "limit": "ten"})
    assert r.status_code == 400
    r = gf.post(f"{base}/bench-packs/import-traces", {"pack_id": "t", "limit": "0"})
    assert r.status_code == 400
    make(gf, id="custom", config={"pattern": r"ZX\d{4}"})
    r = gf.post("/console/guardian-factory/custom/bench-packs/generate", {"pack_id": "s"})
    assert r.status_code == 400 and "generator_unsupported" in r.text


def test_audit_rows_two_per_post(gf: Any) -> None:
    make(gf, benchmark_pack="starter")
    base = f"/console/guardian-factory/{DEF}"
    gf.post(f"{base}/bench-packs/generate", {"pack_id": "starter"})
    gf.post(f"{base}/benchmark", {"pack_id": "starter"})
    settle(gf)
    gf.post(f"{base}/mark-benchmarked", {})
    rows = [
        x
        for x in gf.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] == "guardians.edit"
    ]
    # make() is an API post too: 4 posts in all
    assert [x["outcome"] for x in rows] == ["attempted", "ok"] * 4
    assert len({x["request_id"] for x in rows}) == 4


def test_i18n_keys_exist_in_both_languages(gf: Any) -> None:
    from supervisor.console.i18n_guardian_factory import GF

    keys = [k for k in GF if k.startswith("gf_b_")]
    assert len(keys) >= 40 and all(GF[k][0] and GF[k][1] for k in keys)
    make(gf)
    r = gf.get(f"/console/guardian-factory/{DEF}/benchmark?lang=vi", headers=HX)
    assert "Tạo bộ mẫu" in r.text and "Chạy đánh giá" in r.text
    r = gf.get(f"/console/guardian-factory/{DEF}/benchmark?lang=en", headers=HX)
    assert "Generate starter pack" in r.text
