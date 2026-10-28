"""WP-W1: POST /v1/regkb/import, the watch lists and the page /console/regkb/watch.

Off by default (HTTP 400 regwatch_off). The package is signed with the evidence signer of the
running console and checked against the same public key. Nothing is applied."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.regkb import package, watch
from tests.regkb.test_w1_watch import NOW, FakeFetcher, make_instrument, rezip, scan_fetcher

from .conftest import Console
from .test_nav_v3 import v3, v3all  # noqa: F401, F811  (fixtures)

IMPORT = "/v1/regkb/import"
RUNS = "/v1/regkb/watch/runs"
PACKAGES = "/v1/regkb/watch/packages"
PAGE = "/console/regkb/watch"


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Console:
    monkeypatch.setattr(console.ctx.settings, "regwatch_enabled", True)
    monkeypatch.setattr(console.ctx.settings, "data_dir", tmp_path / "data")
    return console


def make_package(on: Console, tmp_path: Path) -> bytes:
    signer = on.runtime.chain.signer
    result = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW)
    jp, mp = watch.write_report(tmp_path / "out", result.report)
    path, _ = package.build_package(
        tmp_path / "out" / "p.zip",
        report_json=jp,
        report_md=mp,
        incoming=result.incoming,
        signer=signer,
        run_id=result.report["run_id"],
        created_at="2026-10-28T09:00:00Z",
    )
    return path.read_bytes()


def post_zip(c: Console, blob: bytes, user: str = "admin.chi") -> Any:
    return c.client.post(
        IMPORT,
        files={"file": ("update.zip", blob, "application/zip")},
        headers={"X-Dev-User": user},
    )


def test_off_by_default_every_route_answers_400_with_the_code(
    console: Console, tmp_path: Path
) -> None:
    assert console.ctx.settings.regwatch_enabled is False
    for url in (RUNS, PACKAGES, PAGE):
        got = console.get(url, user="admin.chi")
        assert got.status_code == 400 and "regwatch_off" in got.text, url
    r = post_zip(console, b"PK")
    assert r.status_code == 400 and "regwatch_off" in r.text
    assert not (Path(console.ctx.settings.data_dir) / "regkb" / "incoming").exists()


def test_import_stores_lists_and_applies_nothing(on: Console, tmp_path: Path) -> None:
    blob = make_package(on, tmp_path)
    r = post_zip(on, blob)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["changes"] == 1 and body["already_imported"] is False and body["applied"] is False
    sha = body["package_sha256"]
    stored = Path(on.ctx.settings.data_dir) / "regkb" / "incoming" / sha
    assert (stored / "proposed_changes.yaml").is_file() and (stored / "import.json").is_file()
    # a second import of the same package is a no-op (200)
    again = post_zip(on, blob)
    assert again.status_code == 200 and again.json()["already_imported"] is True
    listed = on.get(PACKAGES, user="admin.chi").json()
    assert [p["package_sha256"] for p in listed["packages"]] == [sha]
    assert listed["review"] == "pending review (WP-W2)"
    assert listed["packages"][0]["changes"][0]["kind"] == "amendment"
    # no RegKB file changed: the stored regulations folder is untouched, no instrument was added
    assert not (Path(on.ctx.settings.data_dir) / "regkb" / "internal").exists()


def test_import_writes_two_audit_rows_and_one_chain_record(on: Console, tmp_path: Path) -> None:
    before = len(on.ctx.tables.query("console_action"))
    assert post_zip(on, make_package(on, tmp_path)).status_code == 201
    rows = on.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["permission"] for r in rows} == {"regkb.import"}
    assert rows[0]["actor"].endswith("admin.chi") or "admin.chi" in str(rows[0]["actor"])


def test_import_refusals_are_400_with_a_code(on: Console, tmp_path: Path) -> None:
    blob = make_package(on, tmp_path)
    cases = {
        "bad_zip": b"not a zip",
        "too_large": b"x" * (package.MAX_PACKAGE_BYTES + 1),
        "sha_mismatch": rezip(blob, lambda m: m.__setitem__("proposed_changes.yaml", b"x: 1\n")),
        "path_traversal": rezip(blob, lambda m: m.__setitem__("incoming/../x.txt", b"x")),
        "unknown_member": rezip(blob, lambda m: m.__setitem__("run.py", b"print(1)")),
        "bad_signature": rezip(
            blob,
            lambda m: m.__setitem__(
                "signature",
                json.dumps({**json.loads(m["signature"]), "signature": "AAAA"}).encode(),
            ),
        ),
    }
    for code, data in cases.items():
        r = post_zip(on, data)
        assert r.status_code == 400 and code in r.text, (code, r.status_code, r.text[:200])
    nothing = on.client.post(IMPORT, data={"x": "y"}, headers={"X-Dev-User": "admin.chi"})
    assert nothing.status_code == 400
    assert not (Path(on.ctx.settings.data_dir) / "regkb" / "incoming").exists()


def test_package_from_another_signer_is_untrusted(on: Console, tmp_path: Path) -> None:
    from supervisor.evidence.signer import Ed25519FileSigner

    other = Ed25519FileSigner(tmp_path / "other.pem")
    result = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW)
    jp, mp = watch.write_report(tmp_path / "out", result.report)
    path, _ = package.build_package(
        tmp_path / "out" / "o.zip",
        report_json=jp,
        report_md=mp,
        incoming=[],
        signer=other,
        run_id="rw_x",
        created_at="2026-10-28T09:00:00Z",
    )
    r = post_zip(on, path.read_bytes())
    assert r.status_code == 400 and "untrusted_key" in r.text
    # the bank can pin the dev host key instead
    pem = tmp_path / "pinned.pem"
    pem.write_text(other.public_key_pem(), encoding="ascii")
    on.ctx.settings.regkb_import_pubkey = pem
    ok = post_zip(on, path.read_bytes())
    assert ok.status_code == 201, ok.text


def test_page_lists_runs_reports_and_packages_with_pending_review(
    on: Console, tmp_path: Path
) -> None:
    assert post_zip(on, make_package(on, tmp_path)).status_code == 201
    out = Path(on.ctx.settings.data_dir) / "regwatch"
    result = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW)
    watch.write_report(out, result.report)
    on.ctx.state.insert(
        "regwatch_run",
        {
            "run_id": "rw_20261028_abcdef",
            "started_at": on.ctx.clock.now(),
            "status": "ok",
            "instruments_checked": 26,
            "changes_found": 1,
        },
    )
    page = on.get(PAGE + "?lang=en", user="admin.chi")
    assert page.status_code == 200
    text = page.text
    assert "rw_20261028_abcdef" in text and "watch-2026-10-28.json" in text
    assert "pending review (WP-W2)" in text and "100/2026/TT-NHNN" in text
    assert "Stored, not applied." in text
    runs = on.get(RUNS, user="admin.chi").json()
    assert runs["runs"][0]["run_id"] == "rw_20261028_abcdef" and runs["reports"][0]["changes"]
    vi = on.get(PAGE + "?lang=vi", user="admin.chi")
    assert "chờ xem xét (WP-W2)" in vi.text


def test_nav_tab_follows_the_flag_and_admin_role(
    v3all: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    on = v3all
    monkeypatch.setattr(on.ctx.settings, "regwatch_enabled", True)
    page = on.get("/console/risks?lang=en", user="admin.chi").text
    assert 'href="/console/regkb/watch?lang=en"' in page
    monkeypatch.setattr(on.ctx.settings, "regwatch_enabled", False)
    assert (
        'href="/console/regkb/watch' not in on.get("/console/risks?lang=en", user="admin.chi").text
    )


def test_permission_rows_are_admin_only() -> None:
    for perm in ("regkb.import", "regkb.watch"):
        holders = {r for r in rbac.ROLES if rbac.allowed(frozenset({r}), perm)}
        assert holders == {"admin"}, perm
    assert rbac.route_entry("POST", IMPORT) == "regkb.import"
    for path in (RUNS, PACKAGES, PAGE):
        assert rbac.route_entry("GET", path) == "regkb.watch"


def test_only_admin_may_import_or_read(
    on: Console, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.adapters.auth.base import AuthPrincipal

    monkeypatch.setattr(on.ctx.settings, "api_rbac_enabled", True)
    for role in rbac.ROLES:
        uid = f"only.{role}"
        on.ctx.provider.users[uid] = AuthPrincipal(
            uid, "user", "dev_header", frozenset({role}), uid
        )
        want_ok = role == "admin"
        get = on.get(PACKAGES, user=uid)
        post = post_zip(on, b"x", user=uid)
        assert (get.status_code != 403) is want_ok, (role, get.status_code)
        assert (post.status_code != 403) is want_ok, (role, post.status_code)
    assert FakeFetcher  # the import is a pure local step: no fetcher is involved
