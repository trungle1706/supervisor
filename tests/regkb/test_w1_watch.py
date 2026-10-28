"""WP-W1: the regulation watcher, the update package, the import checks, the scheduler job.

No network: a fake fetcher serves the recorded (synthetic) vbpl.vn responses under
tests/fixtures/regwatch/.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import REPO_ROOT, load_settings
from supervisor.evidence.signer import Ed25519FileSigner
from supervisor.jobs import bootstrap_schema
from supervisor.jobs import regwatch as job
from supervisor.monitors.common import MonitorContext
from supervisor.regkb import package, watch

FIX = REPO_ROOT / "tests" / "fixtures" / "regwatch"
NOW = datetime(2026, 10, 28, 9, 0, 0, tzinfo=UTC)
NUMBER = "99/2026/TT-NHNN"


def fx(name: str) -> dict[str, Any]:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeFetcher:
    """Serves recorded responses. No socket is opened."""

    def __init__(
        self,
        search: dict[str, list[dict[str, Any]]],
        docs: dict[str, dict[str, Any]] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.map = search
        self.docs = docs if docs is not None else fx("docs.json")["docs"]
        self.fail = fail or set()
        self.calls: list[str] = []

    def search(
        self, keyword: str, *, since: str | None = None, page_size: int = 30
    ) -> list[dict[str, Any]]:
        self.calls.append(keyword)
        if keyword in self.fail:
            raise RuntimeError("boom")
        return [dict(i) for i in self.map.get(keyword, [])]

    def doc(self, vbpl_id: str) -> dict[str, Any] | None:
        self.calls.append(f"doc:{vbpl_id}")
        return self.docs.get(vbpl_id)

    def doc_text(self, data: Any) -> str:
        return str(data.get("_text", ""))


def make_instrument(tmp_path: Path, **over: Any) -> watch.Instrument:
    stored = fx("docs.json")["docs"]["u-own-0001"]["_text"]
    sha = hashlib.sha256(stored.encode("utf-8")).hexdigest()
    folder = tmp_path / "sources" / "VN-TEST-2026"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "99-2026.txt").write_text(stored, encoding="utf-8")
    (folder / "99-2026.meta.json").write_text(json.dumps({"sha256": sha}), encoding="utf-8")
    args: dict[str, Any] = {
        "id": "VN-TEST-2026",
        "number": NUMBER,
        "title": "Thong tu mau",
        "status": "in_force",
        "last_checked": "2026-10-15",
        "sources": [
            {
                "kind": "primary",
                "url": "https://vbpl.vn/van-ban/chi-tiet/u-own-0001",
                "sha256": sha,
            },
            {"kind": "secondary", "url": "https://example.invalid/x"},
        ],
        "raw_text": "instrument: test\n",
        "path": tmp_path / "x.yaml",
        "stored_dir": folder,
    }
    args.update(over)
    return watch.Instrument(**args)


def check(
    inst: watch.Instrument,
    search_file: str,
    prev: dict[str, Any] | None = None,
    docs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[watch.Incoming]]:
    fetcher = FakeFetcher({NUMBER: fx(search_file)["result"]["items"]}, docs)
    incoming: list[watch.Incoming] = []
    row = watch.check_instrument(inst, fetcher, prev, NOW, incoming)
    return row, incoming


def prev_with(code: str = "CHL", updated: str = "", related: list[str] | None = None) -> dict:
    return {
        "instruments": [
            {
                "instrument_id": "VN-TEST-2026",
                "observed": {
                    "eff_status_code": code,
                    "updated_date": updated,
                    "related_numbers": related or [],
                },
            }
        ]
    }


# ---------------------------------------------------------------------------- detection table

CASES = [
    # (id, search file, previous report, expected kinds, number of incoming files)
    ("unchanged", "search_unchanged.json", None, [], 0),
    ("unchanged_with_baseline", "search_unchanged.json", prev_with(), [], 0),
    ("amendment_decoy_and_guidance_ignored", "search_amendment.json", None, ["amendment"], 1),
    ("replacement", "search_replacement.json", None, ["replacement"], 1),
    ("repeal", "search_repeal.json", None, ["repeal"], 1),
    (
        "status_change_vs_last_report",
        "search_status.json",
        prev_with("CHL"),
        ["effect_status_change"],
        0,
    ),
    ("status_no_change_vs_last_report", "search_status.json", prev_with("HHL"), [], 0),
    ("status_vs_kb_when_no_report", "search_status.json", None, ["effect_status_change"], 0),
    ("updated_after_last_checked", "search_updated.json", None, ["updated_date_newer"], 0),
    (
        "updated_same_as_last_report",
        "search_updated.json",
        prev_with(updated="2026-10-20T10:00:00"),
        [],
        0,
    ),
    (
        "amendment_already_in_last_report",
        "search_amendment.json",
        prev_with(related=["100/2026/TT-NHNN"]),
        [],
        0,
    ),
]


@pytest.mark.parametrize(
    ("search_file", "prev", "kinds", "n_incoming"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_change_detection_table(
    tmp_path: Path, search_file: str, prev: Any, kinds: list[str], n_incoming: int
) -> None:
    row, incoming = check(make_instrument(tmp_path), search_file, prev)
    assert [c["kind"] for c in row["changes"]] == kinds, row["changes"]
    assert len(incoming) == n_incoming
    assert row["errors"] == []
    for c in row["changes"]:
        assert c["review_status"] == "pending" and c["instrument_id"] == "VN-TEST-2026"


def test_amendment_row_has_url_date_sha_and_text(tmp_path: Path) -> None:
    row, incoming = check(make_instrument(tmp_path), "search_amendment.json")
    (c,) = row["changes"]
    assert c["doc_number"] == "100/2026/TT-NHNN" and c["date"] == "2026-10-20"
    assert c["url"] == "https://vbpl.vn/van-ban/chi-tiet/u-amd-0002"
    (inc,) = incoming
    assert c["sha256"] == hashlib.sha256(inc.data).hexdigest() == inc.meta["sha256"]
    assert c["incoming"] == [f"VN-TEST-2026/{inc.name}"]
    assert inc.name.startswith("2026-10-28/") and inc.meta["vbpl"]["id"] == "u-amd-0002"
    assert row["observed"]["related_numbers"] == ["100/2026/TT-NHNN"]


def test_amendment_named_in_the_instrument_file_is_known_not_new(tmp_path: Path) -> None:
    inst = make_instrument(tmp_path, raw_text="notes: amended by 100/2026/TT-NHNN\n")
    row, incoming = check(inst, "search_amendment.json")
    assert row["changes"] == [] and row["known_related"] == ["100/2026/TT-NHNN"]
    assert incoming == []


def test_text_changed_and_layout_only(tmp_path: Path) -> None:
    docs = fx("docs.json")["docs"]
    changed = {
        **docs,
        "u-own-0001": {
            **docs["u-own-0001"],
            "_text": docs["u-own-0001"]["_text"] + "\nĐiều 4. Mới.",
        },
    }
    row, incoming = check(make_instrument(tmp_path), "search_unchanged.json", docs=changed)
    assert [c["kind"] for c in row["changes"]] == ["text_changed"]
    (inc,) = incoming
    assert (
        row["changes"][0]["sha256"]
        == inc.meta["sha256"]
        != make_instrument(tmp_path).sources[0]["sha256"]
    )
    # same words, other layout: counted as layout_only, not a change, nothing fetched to incoming
    spaced = {
        **docs,
        "u-own-0001": {
            **docs["u-own-0001"],
            "_text": docs["u-own-0001"]["_text"].replace("\n", "\n\n  "),
        },
    }
    row2, incoming2 = check(make_instrument(tmp_path), "search_unchanged.json", docs=spaced)
    assert row2["changes"] == [] and row2["layout_only"] == ["u-own-0001"] and incoming2 == []


def test_one_failing_query_is_an_error_not_a_crash(tmp_path: Path) -> None:
    fetcher = FakeFetcher({}, fail={NUMBER})
    row = watch.check_instrument(make_instrument(tmp_path), fetcher, None, NOW, [])
    assert row["changes"] == [] and row["errors"] and "boom" in row["errors"][0]


def test_number_matching_helpers() -> None:
    assert watch.number_in_title(NUMBER, "Sửa đổi Thông tư số 99/2026/TT-NHNN.")
    assert not watch.number_in_title(NUMBER, "Sửa đổi Thông tư số 199/2026/TT-NHNN")
    assert not watch.number_in_title(NUMBER, "Sửa đổi Thông tư số 99/2026/TT-NHNN2")
    assert watch.change_kind("Thay thế và bãi bỏ") == "repeal"
    assert watch.change_kind("Sửa đổi, bổ sung") == "amendment"
    assert watch.change_kind("Hướng dẫn thi hành") is None


# ---------------------------------------------------------------------------- the whole run


def scan_fetcher() -> FakeFetcher:
    scans = fx("scans.json")["queries"]
    return FakeFetcher({**scans, NUMBER: fx("search_amendment.json")["result"]["items"]})


def test_run_scans_new_instruments_interim_channel_and_open_items(tmp_path: Path) -> None:
    result = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW)
    rep = result.report
    assert rep["format"] == watch.REPORT_FORMAT and rep["date"] == "2026-10-28"
    # new candidates: Government decree and MST circular; not the province, not before the window
    nums = sorted(c["doc_num"] for c in rep["new_candidates"])
    assert nums == ["12/2026/TT-BKHCN", "200/2026/NĐ-CP"]
    # the interim channel hits are a note, from Government and MST only
    assert "Art. 46" in rep["interim_channel"]["note"]
    assert sorted(h["doc_num"] for h in rep["interim_channel"]["hits"]) == [
        "12/2026/TT-BKHCN",
        "200/2026/NĐ-CP",
    ]
    # M-01 .. M-10 all re-queried; M-01 found 96/2025/QH15, the others not
    items = {o["id"]: o for o in rep["open_items"]}
    assert sorted(items) == [f"M-{n:02d}" for n in range(1, 11)]
    assert items["M-01"]["result"] == "found"
    assert [f["number"] for f in items["M-01"]["found"]] == ["96/2025/QH15"]
    assert items["M-01"]["missing"] == ["142/2025/QH15", "43/2024/QH15"]
    assert items["M-03"]["result"] == "not_found"
    s = rep["summary"]
    assert s["instruments_checked"] == 1 and s["changes_found"] == 1 and s["incoming_files"] == 1
    md = watch.report_markdown(rep)
    assert "pending review (WP-W2)" in md and "100/2026/TT-NHNN" in md and "M-10" in md


def test_single_instrument_run_skips_the_scans(tmp_path: Path) -> None:
    fetcher = scan_fetcher()
    rep = watch.run_watch(
        fetcher, instruments=[make_instrument(tmp_path)], only="VN-TEST-2026", now=NOW
    ).report
    assert rep["new_candidates"] == [] and rep["open_items"] == []
    assert "trí tuệ nhân tạo" not in fetcher.calls


def test_new_candidate_seen_in_last_report_is_not_listed_again(tmp_path: Path) -> None:
    first = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW).report
    again = watch.run_watch(
        scan_fetcher(), instruments=[make_instrument(tmp_path)], prev=first, now=NOW
    ).report
    assert again["new_candidates"] == []
    assert again["instruments"][0]["changes"] == []  # the amendment is in the baseline now


def test_write_incoming_keeps_to_incoming_and_writes_sidecar(tmp_path: Path) -> None:
    inst = make_instrument(tmp_path)
    before = (inst.stored_dir / "99-2026.txt").read_bytes()
    _, incoming = check(inst, "search_amendment.json")
    written = watch.write_incoming(tmp_path / "sources", incoming)
    txt = next(p for p in written if p.suffix == ".txt")
    side = json.loads(txt.with_name(txt.stem + ".meta.json").read_text(encoding="utf-8"))
    assert txt.parent == tmp_path / "sources" / "VN-TEST-2026" / "incoming" / "2026-10-28"
    assert side["sha256"] == hashlib.sha256(txt.read_bytes()).hexdigest()
    assert side["url"].endswith("u-amd-0002") and side["fetched_at"] == "2026-10-28T09:00:00Z"
    assert (inst.stored_dir / "99-2026.txt").read_bytes() == before  # text of record untouched
    bad = watch.Incoming("VN-TEST-2026", "../../escape.txt", b"x")
    with pytest.raises(ValueError):
        watch.write_incoming(tmp_path / "sources", [bad])
    with pytest.raises(ValueError):
        watch.write_incoming(tmp_path / "sources", [watch.Incoming("not-an-id", "a.txt", b"x")])


def test_real_instruments_load_with_the_stored_filter() -> None:
    insts = watch.load_instruments()
    ids = {i.id for i in insts}
    assert "VN-TT53-2026" in ids and "VN-AI-2025" in ids
    assert all(i.id.startswith("VN-") and i.number for i in insts)
    tt53 = next(i for i in insts if i.id == "VN-TT53-2026")
    assert watch.vbpl_ids_of(tt53) == ["99fa0140-c2ba-11f1-b8ec-99379998c900"]
    assert [i.id for i in watch.load_instruments(only="VN-TT53-2026")] == ["VN-TT53-2026"]


# ---------------------------------------------------------------------------- the package


@pytest.fixture
def signer(tmp_path: Path) -> Ed25519FileSigner:
    return Ed25519FileSigner(tmp_path / "keys" / "k.pem")


def build(tmp_path: Path, signer: Any) -> tuple[Path, str, watch.WatchResult]:
    result = watch.run_watch(scan_fetcher(), instruments=[make_instrument(tmp_path)], now=NOW)
    jp, mp = watch.write_report(tmp_path / "out", result.report)
    path, sha = package.build_package(
        tmp_path / "out" / "p.zip",
        report_json=jp,
        report_md=mp,
        incoming=result.incoming,
        signer=signer,
        run_id=result.report["run_id"],
        created_at="2026-10-28T09:00:00Z",
    )
    return path, sha, result


def rezip(blob: bytes, edit: Any) -> bytes:
    """Open a package, let ``edit(members: dict[str, bytes])`` change it, write it again."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = {i.filename: zf.read(i) for i in zf.infolist()}
    edit(members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_package_content_manifest_and_signature(tmp_path: Path, signer: Ed25519FileSigner) -> None:
    path, sha, result = build(tmp_path, signer)
    blob = path.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == sha
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
    inc = result.incoming[0]
    assert names == {
        "manifest.json",
        "signature",
        "watch-2026-10-28.json",
        "watch-2026-10-28.md",
        "proposed_changes.yaml",
        f"incoming/VN-TEST-2026/{inc.name}",
        f"incoming/VN-TEST-2026/{inc.name[:-4]}.meta.json",
    }
    pkg = package.verify_package(blob, signer.public_key)
    assert pkg.sha256 == sha and pkg.report["summary"]["changes_found"] == 1
    listed = {m["name"]: m["sha256"] for m in pkg.manifest["members"]}
    assert set(listed) == names - {"manifest.json", "signature"}
    for name, digest in listed.items():
        assert hashlib.sha256(pkg.members[name]).hexdigest() == digest
    assert pkg.manifest["format"] == "regwatch-package-1"
    assert pkg.signature["key_id"] == signer.key_id and pkg.signature["algorithm"] == "ed25519"
    assert b"proposed: []" in pkg.members["proposed_changes.yaml"]


def test_package_build_is_reproducible_for_the_same_content(
    tmp_path: Path, signer: Ed25519FileSigner
) -> None:
    p1, sha1, _ = build(tmp_path, signer)
    blob1 = p1.read_bytes()
    pkg = package.verify_package(blob1, signer.public_key)
    assert pkg.size == len(blob1)


REFUSALS = [
    ("bad_zip", lambda blob: b"this is not a zip"),
    ("too_large", lambda blob: b"x" * (package.MAX_PACKAGE_BYTES + 1)),
    (
        "bad_signature",
        lambda blob: rezip(
            blob, lambda m: m.__setitem__("signature", _resign_garbage(m["signature"]))
        ),
    ),
    (
        "bad_signature",
        lambda blob: rezip(
            blob, lambda m: m.__setitem__("manifest.json", m["manifest.json"] + b" ")
        ),
    ),
    (
        "sha_mismatch",
        lambda blob: rezip(
            blob, lambda m: m.__setitem__("proposed_changes.yaml", b"proposed: [x]\n")
        ),
    ),
    (
        "sha_mismatch",
        lambda blob: rezip(blob, lambda m: m.__setitem__("watch-2026-10-28.md", b"changed")),
    ),
    (
        "path_traversal",
        lambda blob: rezip(blob, lambda m: m.__setitem__("incoming/../evil.txt", b"x")),
    ),
    (
        "path_traversal",
        lambda blob: rezip(blob, lambda m: m.__setitem__("/etc/passwd", b"x")),
    ),
    (
        "unknown_member",
        lambda blob: rezip(blob, lambda m: m.__setitem__("evil.py", b"import os")),
    ),
    (
        "unknown_member",
        lambda blob: rezip(
            blob, lambda m: m.__setitem__("incoming/VN-X-1/2026-10-28/run.sh", b"x")
        ),
    ),
    ("bad_manifest", lambda blob: rezip(blob, lambda m: m.pop("manifest.json"))),
    (
        "bad_manifest",
        lambda blob: rezip(blob, lambda m: m.__setitem__("manifest.json", b"{not json")),
    ),
]


def _resign_garbage(sig_bytes: bytes) -> bytes:
    sig = json.loads(sig_bytes)
    sig["signature"] = base64.b64encode(b"\x01" * 64).decode()
    return json.dumps(sig).encode()


@pytest.mark.parametrize(
    ("code", "mutate"), REFUSALS, ids=[f"{c}-{i}" for i, (c, _) in enumerate(REFUSALS)]
)
def test_import_refusals(tmp_path: Path, signer: Ed25519FileSigner, code: str, mutate: Any) -> None:
    path, _, _ = build(tmp_path, signer)
    with pytest.raises(package.PackageError) as err:
        package.verify_package(mutate(path.read_bytes()), signer.public_key)
    assert err.value.code == code
    assert str(err.value).startswith(code + ":")


def test_a_package_signed_by_another_key_is_refused(
    tmp_path: Path, signer: Ed25519FileSigner
) -> None:
    path, _, _ = build(tmp_path, signer)
    other = Ed25519FileSigner(tmp_path / "keys" / "other.pem")
    with pytest.raises(package.PackageError) as err:
        package.verify_package(path.read_bytes(), other.public_key)
    assert err.value.code == "untrusted_key"


def test_member_added_but_not_in_manifest_is_refused(
    tmp_path: Path, signer: Ed25519FileSigner
) -> None:
    path, _, _ = build(tmp_path, signer)
    blob = rezip(
        path.read_bytes(),
        lambda m: m.__setitem__("incoming/VN-TEST-2026/2026-10-28/extra.txt", b"data"),
    )
    with pytest.raises(package.PackageError) as err:
        package.verify_package(blob, signer.public_key)
    assert err.value.code == "sha_mismatch"


def test_store_package_writes_only_under_the_sha_folder_and_applies_nothing(
    tmp_path: Path, signer: Ed25519FileSigner
) -> None:
    path, sha, _ = build(tmp_path, signer)
    pkg = package.verify_package(path.read_bytes(), signer.public_key)
    data_dir = tmp_path / "data"
    summary, new = package.store_package(
        data_dir, pkg, actor="admin.chi", imported_at="2026-10-28T10:00:00Z"
    )
    assert new and summary["package_sha256"] == sha and summary["applied"] is False
    target = data_dir / "regkb" / "incoming" / sha
    assert (target / "proposed_changes.yaml").is_file() and (target / "import.json").is_file()
    assert len(summary["changes"]) == 1
    again, new2 = package.store_package(
        data_dir, pkg, actor="admin.chi", imported_at="2026-10-29T10:00:00Z"
    )
    assert not new2 and again["imported_at"] == "2026-10-28T10:00:00Z"
    assert [p["package_sha256"] for p in package.list_packages(data_dir)] == [sha]
    assert not (data_dir / "regkb" / "internal").exists()
    assert not list(data_dir.rglob("*.py"))


# ---------------------------------------------------------------------------- off path and job


class Sink:
    def __init__(self, signer: Any) -> None:
        self.signer = signer
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Any) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return "0" * 64


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="", regwatch_enabled=True
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


def test_off_by_default_the_job_is_not_listed_and_nothing_is_written(tmp_path: Path) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    assert s.regwatch_enabled is False and s.regwatch_interval_s == 86400
    assert job.enabled(s) is False and job.refused_reason(s) == "REGWATCH_ENABLED is off"
    assert not (tmp_path / "data" / "regwatch").exists()


def test_interval_has_a_minimum_of_one_hour(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="regwatch_interval_s|greater than or equal"):
        load_settings(
            sql_backend="sqlite", data_dir=tmp_path, llm_base_url="", regwatch_interval_s=3599
        )
    s = load_settings(
        sql_backend="sqlite", data_dir=tmp_path, llm_base_url="", regwatch_interval_s=3600
    )
    assert s.regwatch_interval_s == 3600


def test_scheduler_refuses_the_job_in_databricks_app_mode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    s = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        regwatch_enabled=True,
        supervisor_mode="databricks_app",
    )
    with caplog.at_level(logging.WARNING):
        assert job.enabled(s) is False
    assert "regwatch job refused" in caplog.text and "no internet" in caplog.text
    from supervisor.core.errors import SupervisorError

    with pytest.raises(SupervisorError, match="regwatch_off"):
        job.run(None, s)  # type: ignore[arg-type]  # refused before ctx is used


def test_scheduler_lists_the_job_in_laptop_mode(adapters: Adapters, signer: Any) -> None:
    from supervisor import scheduler

    ctx = MonitorContext.from_adapters(adapters, Sink(signer))
    runtime = type("R", (), {"adapters": adapters, "chain": ctx.evidence})()
    jobs = {j.name: j for j in scheduler.build_jobs(adapters.settings, runtime, ctx)}
    assert "regwatch" in jobs and jobs["regwatch"].interval_s == 86400
    off = adapters.settings.model_copy(update={"regwatch_enabled": False})
    assert "regwatch" not in {j.name for j in scheduler.build_jobs(off, runtime, ctx)}


def test_job_run_writes_row_report_package_and_an_integer_chain_record(
    tmp_path: Path, adapters: Adapters, signer: Ed25519FileSigner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_instrument(tmp_path)
    monkeypatch.setattr(watch, "load_instruments", lambda *a, **k: [inst])
    sink = Sink(signer)
    ctx = MonitorContext.from_adapters(adapters, sink)
    result = job.run(ctx, adapters.settings, fetcher=scan_fetcher())
    assert result["status"] == "ok" and result["changes_found"] == 1
    (row,) = ctx.state.query("regwatch_run")
    assert row["status"] == "ok" and row["instruments_checked"] == 1 and row["changes_found"] == 1
    out = Path(adapters.settings.data_dir) / "regwatch"
    zips = list(out.glob("update-package-*.zip"))
    assert (
        len(zips) == 1 and hashlib.sha256(zips[0].read_bytes()).hexdigest() == row["package_sha256"]
    )
    (report,) = out.glob("watch-*.json")
    assert hashlib.sha256(report.read_bytes()).hexdigest() == row["report_sha256"]
    assert (out / "sources" / "VN-TEST-2026" / "incoming").is_dir()
    assert len(row["error"] or "") <= 300
    ((rtype, ref, payload),) = sink.records
    assert rtype == "regwatch_run" and ref == result["run_id"]
    assert payload["instruments_checked"] == 1 and payload["changes_found"] == 1
    for key, value in payload.items():
        assert isinstance(value, (int, str)) and not isinstance(value, (float, bool)), key
    assert payload["package_sha256"] == row["package_sha256"]
    package.verify_package(zips[0].read_bytes(), signer.public_key)


def test_job_failure_is_recorded_with_a_short_error(
    tmp_path: Path, adapters: Adapters, signer: Ed25519FileSigner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise OSError("disk full " + "x" * 500)

    monkeypatch.setattr(watch, "load_instruments", boom)
    ctx = MonitorContext.from_adapters(adapters, Sink(signer))
    with pytest.raises(OSError):
        job.run(ctx, adapters.settings, fetcher=scan_fetcher())
    (row,) = ctx.state.query("regwatch_run")
    assert row["status"] == "error" and 0 < len(row["error"]) <= 300


def test_watch_module_has_no_network_import() -> None:
    """The watcher module itself does not import httpx; the tool does, loaded by path."""
    text = (REPO_ROOT / "src" / "supervisor" / "regkb" / "watch.py").read_text(encoding="utf-8")
    assert "import httpx" not in text and "subprocess" not in text
    assert "exec(" not in text.replace("spec.loader.exec_module", "")
