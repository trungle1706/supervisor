"""WP-W3: internal documents in RegKB. Off path, upload limits and types, the masker, the section
splitter on three synthetic policies, drafts, the instrument file, the loader, the matrix.

The fake chat adapter is the only fake and stands in for the gateway model; it records every
message it gets so a test can prove that no personal data reached it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.config import REPO_ROOT, load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.regkb import internal as it
from supervisor.regkb import load_kb
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.internal_text import split_sections
from supervisor.regkb.loader import internal_docs_dir

FIX = REPO_ROOT / "tests" / "fixtures" / "regkb_internal"
PHONE = "0912 345 678"
CCCD = "001099012345"


def fixture_text(name: str) -> str:
    return (FIX / f"policy_{name}.txt").read_text("utf-8")


class Chain:
    """In-memory EvidenceSink."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def record(self, record_type: str, record_ref: str, payload: Mapping[str, Any]) -> str:
        self.records.append((record_type, record_ref, dict(payload)))
        return "0" * 64


class FakeChat:
    is_mock = False
    family = "fake"

    def __init__(self, model_id: str = "fake-int-model-1") -> None:
        self.model_id = model_id
        self.messages: list[list[dict[str, str]]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.messages.append([dict(m) for m in messages])
        user = json.loads(messages[1]["content"])
        text = user["section_text"]
        if "Tài liệu này chỉ nhằm" in text or user["section"] == "Điều 1":
            return {"imposes_duty": False}
        body = text.split(" ", 2)[-1]
        return {
            "imposes_duty": True,
            "duties": ["risk_classification", "internal_policy"],
            "subject": "The owning unit",
            "trigger": "Before use",
            "evidence_asked": "The classification record",
            "quote": body[:70].strip(),
            "summary_en": "A test duty.",
            "dimensions": ["model", "not_a_dimension"],
        }


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        regkb_internal=True,
        lawagent_enabled=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def chain() -> Chain:
    return Chain()


@pytest.fixture
def svc(adapters: Adapters, chain: Chain) -> it.InternalDocs:
    masker = VnRegexMasker(b"k" * 32, "k1")
    return it.InternalDocs(
        adapters.state, adapters.clock, adapters.settings, masker=masker, evidence=chain
    )


def upload(svc: it.InternalDocs, name: str = "numbered", **over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "title": "Quy dinh mau",
        "owner_group": "Model Risk",
        "version_label": "v1",
        "actor": "reviewer.an",
    }
    args.update(over)
    return svc.upload(f"{name}.txt", fixture_text(name).encode("utf-8"), **args)


# ---------------------------------------------------------------------------- off path


class SpyState:
    """Fails the test when the table is touched."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"state.{name} was called while the flag is off")


def test_off_path_refuses_and_touches_nothing(tmp_path: Path) -> None:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    assert settings.regkb_internal is False and settings.regkb_internal_max_mb == 10
    svc = it.InternalDocs(SpyState(), None, settings, masker=VnRegexMasker(b"k" * 32, "k1"))
    with pytest.raises(it.InternalError) as exc:
        svc.upload("a.txt", b"x" * 100, title="t", owner_group="g", version_label="v", actor="u")
    assert exc.value.code == "regkb_internal_off" and "regkb_internal_off" in str(exc.value)
    with pytest.raises(it.InternalError):
        svc.draft("ABCDEF012345", FakeChat())
    assert not (tmp_path / "data" / "regkb").exists()


def test_needs_lawagent_too(tmp_path: Path) -> None:
    only = load_settings(
        sql_backend="sqlite", data_dir=tmp_path, llm_base_url="", regkb_internal=True
    )
    assert not it.enabled(only)
    assert internal_docs_dir(only) is None


def test_loader_ignores_internal_files_while_off(
    svc: it.InternalDocs, adapters: Adapters, tmp_path: Path
) -> None:
    doc = upload(svc)
    row = svc.drafts.add([_row(doc["doc_id"], "S2", "Đơn vị sở hữu phải đăng ký mọi trợ lý AI")])[0]
    svc.drafts.decide(row["draft_id"], "confirmed", "approver.em")
    svc.after_decision(doc["doc_id"], "approver.em")
    off = adapters.settings.model_copy(update={"regkb_internal": False})
    assert internal_docs_dir(off) is None
    base = load_kb()  # the flag is off in the environment of the tests
    assert not [i for i in base.instruments if i.id.startswith("VN-INT-")]
    on = load_kb(docs_dir=svc.root)
    assert [i.id for i in on.instruments if i.id.startswith("VN-INT-")] == [doc["instrument_id"]]
    assert on.version != base.version  # the hash includes internal instruments only when loaded


# ---------------------------------------------------------------------------- upload


def test_upload_stores_files_row_sidecar_and_chain(svc: it.InternalDocs, chain: Chain) -> None:
    doc = upload(svc)
    ddir = svc.doc_dir(doc["doc_id"])
    assert {p.name for p in ddir.iterdir()} == {"text.txt", "text.masked.txt", ".meta.json"}
    raw = (ddir / "text.txt").read_bytes()
    meta = json.loads((ddir / ".meta.json").read_text("utf-8"))
    import hashlib

    assert meta["sha256"] == hashlib.sha256(raw).hexdigest() == doc["sha256"]
    assert meta["title"] == "Quy dinh mau" and meta["owner_group"] == "Model Risk"
    assert meta["version_label"] == "v1" and meta["uploaded_by"] == "reviewer.an"
    assert doc["status"] == "uploaded" and doc["instrument_id"] == f"VN-INT-{doc['doc_id']}"
    assert doc["section_count"] == 5
    kinds = [r[0] for r in chain.records]
    assert kinds == ["regkb_internal"]
    payload = chain.records[0][2]
    assert payload["action"] == "upload" and payload["sha256"] == doc["sha256"]
    assert payload["sections"] == 5
    assert not any(isinstance(v, float) for v in payload.values())
    assert PHONE not in json.dumps(payload) and CCCD not in json.dumps(payload)


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("a.docx", b"x" * 100, "bad_type"),
        ("a.exe", b"x" * 100, "bad_type"),
        ("a.txt", b"", "empty_file"),
        ("a.txt", b"%PDF-1.4 not text at all but a pdf" * 5, "bad_type"),
        ("a.md", b"PK\x03\x04" + b"x" * 100, "bad_type"),
        ("a.txt", b"\x00\x01\x02" * 100, "unreadable"),
        ("a.pdf", b"this is not a pdf at all" * 5, "bad_type"),
        ("a.txt", b"ngan qua", "too_short"),
    ],
)
def test_upload_refuses_with_a_code(
    svc: it.InternalDocs, name: str, data: bytes, code: str
) -> None:
    with pytest.raises(it.InternalError) as exc:
        svc.upload(name, data, title="t", owner_group="g", version_label="v", actor="u")
    assert exc.value.code == code
    assert svc.list() == []
    assert not svc.root.exists() or not list(svc.root.iterdir())


def test_upload_size_limit(svc: it.InternalDocs) -> None:
    data = b"a" * (10 * 1024 * 1024 + 1)
    with pytest.raises(it.InternalError) as exc:
        svc.upload("big.txt", data, title="t", owner_group="g", version_label="v", actor="u")
    assert exc.value.code == "too_large"
    small = svc.settings.model_copy(update={"regkb_internal_max_mb": 1})
    svc2 = it.InternalDocs(svc.state, svc.clock, small, masker=svc.masker)
    with pytest.raises(it.InternalError) as exc:
        svc2.upload(
            "big.md", b"a" * (1024 * 1024 + 1), title="t", owner_group="g", version_label="v",
            actor="u",
        )  # fmt: skip
    assert exc.value.code == "too_large"


def test_upload_needs_owner_group_masker_and_person(svc: it.InternalDocs) -> None:
    with pytest.raises(it.InternalError) as exc:
        upload(svc, owner_group="  ")
    assert exc.value.code == "owner_group_required"
    with pytest.raises(it.InternalError) as exc:
        upload(svc, actor="")
    assert exc.value.code == "actor_required"
    with pytest.raises(it.InternalError) as exc:
        upload(svc, title="x" * 300)
    assert exc.value.code == "field_too_long"
    nomask = it.InternalDocs(svc.state, svc.clock, svc.settings, masker=None)
    with pytest.raises(it.InternalError) as exc:
        upload(nomask)
    assert exc.value.code == "masker_off"


def test_pdf_goes_through_the_repo_reader(
    svc: it.InternalDocs, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.detectors import intake as di

    monkeypatch.setattr(di, "read_pdf", lambda data, deadline: fixture_text("legal"))
    doc = svc.upload(
        "policy.PDF", b"%PDF-1.4\n" + b"0" * 50, title="t", owner_group="g", version_label="v",
        actor="u",
    )  # fmt: skip
    assert doc["section_count"] == 4

    def empty(data: bytes, deadline: float) -> str:
        return "  "

    monkeypatch.setattr(di, "read_pdf", empty)
    with pytest.raises(it.InternalError) as exc:
        svc.upload("s.pdf", b"%PDF-1.4\n" + b"0" * 50, title="t", owner_group="g",
                   version_label="v", actor="u")  # fmt: skip
    assert exc.value.code == "pdf_no_text_layer"


def test_pdf_without_the_optional_reader_is_a_code(svc: it.InternalDocs) -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        with pytest.raises(it.InternalError) as exc:
            svc.upload("s.pdf", b"%PDF-1.4\n" + b"0" * 50, title="t", owner_group="g",
                       version_label="v", actor="u")  # fmt: skip
        assert exc.value.code == "pdf_reader_missing"
    else:  # pragma: no cover - pypdf is optional
        pytest.skip("pypdf is installed")


# ---------------------------------------------------------------------------- the masker


def test_masked_text_has_no_phone_or_cccd_and_the_model_never_sees_them(
    svc: it.InternalDocs,
) -> None:
    doc = upload(svc)
    ddir = svc.doc_dir(doc["doc_id"])
    raw = (ddir / "text.txt").read_text("utf-8")
    masked = (ddir / "text.masked.txt").read_text("utf-8")
    assert PHONE in raw and CCCD in raw  # the raw text stays for the person
    assert PHONE not in masked and CCCD not in masked and "0912" not in masked
    assert "Nguyễn Văn Mẫu" not in masked
    chat = FakeChat()
    svc.draft(doc["doc_id"], chat)
    assert chat.messages  # the model was called for the sections
    blob = json.dumps(chat.messages, ensure_ascii=False)
    for secret in (PHONE, CCCD, "0912", "345 678", "Nguyễn Văn Mẫu"):
        assert secret not in blob
    # the reader API gives masked text too
    assert CCCD not in json.dumps(svc.get(doc["doc_id"]), ensure_ascii=False)
    first = svc.section(doc["doc_id"], 1)
    assert first["masked"] is True and CCCD not in first["text"]


def test_a_changed_masked_file_is_refused(svc: it.InternalDocs) -> None:
    doc = upload(svc)
    path = svc.doc_dir(doc["doc_id"]) / "text.masked.txt"
    path.write_text(path.read_text("utf-8") + "\nThêm một dòng.", encoding="utf-8")
    with pytest.raises(it.InternalError) as exc:
        svc.draft(doc["doc_id"], FakeChat())
    assert exc.value.code == "files_changed"


# ---------------------------------------------------------------------------- splitter


def test_splitter_numbered_headings() -> None:
    secs = split_sections(fixture_text("numbered"))
    assert [s.label for s in secs] == ["1", "2", "2.1", "2.2", "3"]
    assert [s.n for s in secs] == [1, 2, 3, 4, 5]
    assert secs[2].heading == "2.1 Phân loại mức rủi ro"
    assert "Đơn vị sở hữu phải phân loại" in secs[2].text and "2.2" not in secs[2].text


def test_splitter_legal_headings_drop_group_titles() -> None:
    secs = split_sections(fixture_text("legal"))
    assert [s.label for s in secs] == ["Điều 1", "Điều 2", "Điều 3", "Điều 4"]
    assert not any(s.label.startswith(("Chương", "Mục")) for s in secs)
    assert secs[3].text.startswith("Điều 4. Can thiệp của con người")


def test_splitter_falls_back_to_paragraph_blocks() -> None:
    secs = split_sections(fixture_text("plain"))
    assert [s.label for s in secs] == ["P1", "P2", "P3"]
    assert "chỉ nhằm cung cấp thông tin" in secs[2].text  # the short last block joined P3


def test_splitter_edge_cases() -> None:
    assert split_sections("") == []
    text = "15 tháng sau ngày ký thì áp dụng. " * 6  # a bare number is not a heading
    assert [s.label for s in split_sections(text)] == ["P1"]
    long = (
        "Điều 1. Dài\n"
        + "\n".join(f"Dòng số {i} " + "x" * 400 for i in range(40))
        + "\nĐiều 2. Hai\nHết."
    )
    secs = split_sections(long)
    assert secs[0].label == "Điều 1" and secs[1].label == "Điều 1 (part 2)"
    assert all(len(s.text) <= 9000 for s in secs)
    assert secs[-1].label == "Điều 2"


# ---------------------------------------------------------------------------- drafts


def _row(doc_id: str, ref: str, quote: str) -> dict[str, Any]:
    return {
        "instrument_id": f"VN-INT-{doc_id}",
        "article": ref,
        "duty_id": "risk_classification",
        "subject": "The owning unit",
        "trigger": "Before use",
        "evidence_asked": "The classification record",
        "text_vi": quote,
        "summary_en": "A test duty.",
        "source": "model",
        "model_id": "fake",
        "prompt_version": it.PROMPT_VERSION,
        "run_id": "lr_test",
    }


def test_draft_rows_land_in_regkb_draft_with_quotes_inside_their_section(
    svc: it.InternalDocs,
) -> None:
    doc = upload(svc, "legal")
    chat = FakeChat()
    summary = svc.draft(doc["doc_id"], chat)
    assert summary.sections_read == 4 and summary.no_duty == 1 and summary.kept == 3
    rows = svc.drafts.list(doc["instrument_id"])
    assert len(rows) == 3 and all(r["status"] == "draft" for r in rows)
    secs = {s.ref: s for s in svc.sections(doc["doc_id"])}
    for r in rows:
        assert r["instrument_id"] == f"VN-INT-{doc['doc_id']}" and r["source"] == "model"
        assert r["article"] in secs and r["text_vi"] in secs[r["article"]].text
        assert r["duty_id"] == "risk_classification,internal_policy"
        assert r["model_id"] == "fake-int-model-1" and r["prompt_version"] == it.PROMPT_VERSION
    extra = svc.draft_meta(doc["doc_id"])
    assert all(v["dimensions"] == ["model"] for v in extra.values())  # the unknown id is gone
    assert svc.get(doc["doc_id"])["status"] == "drafted"
    # a second run writes nothing again
    again = svc.draft(doc["doc_id"], FakeChat())
    assert again.kept == 0 and again.skipped_existing == 3
    assert len(svc.drafts.list(doc["instrument_id"])) == 3


def test_rules_drop_bad_replies() -> None:
    sec = split_sections(fixture_text("legal"))[1]
    duties = {"risk_classification": {}}
    good = {
        "imposes_duty": True,
        "duties": ["risk_classification"],
        "subject": "s",
        "trigger": "t",
        "evidence_asked": "e",
        "summary_en": "m",
        "quote": "Mọi mô hình mới phải được bộ phận thẩm định",
        "dimensions": ["ethics"],
    }
    assert it.check_internal_draft(good, sec, duties).ok
    for change, reason in (
        ({"quote": "Câu này không có trong mục nào cả đâu"}, "quote_not_in_section"),
        ({"quote": "ngắn"}, "bad_quote_length"),
        ({"duties": ["nope"]}, "unknown_duty"),
        ({"duties": []}, "bad_duty_count"),
        ({"subject": ""}, "missing_field"),
        ({"imposes_duty": False}, "no_duty"),
    ):
        res = it.check_internal_draft({**good, **change}, sec, duties)
        assert not res.ok and res.reason == reason
    # a quote that sits in ANOTHER section is not accepted
    other = split_sections(fixture_text("legal"))[2].text[20:80]
    assert it.check_internal_draft({**good, "quote": other}, sec, duties).reason == (
        "quote_not_in_section"
    )


def test_a_model_error_on_one_section_does_not_stop_the_run(svc: it.InternalDocs) -> None:
    doc = upload(svc, "legal")

    class Flaky(FakeChat):
        def complete_json(self, messages, json_schema, timeout_s):  # type: ignore[no-untyped-def]
            if json.loads(messages[1]["content"])["section"] == "Điều 2":
                raise RuntimeError("boom")
            return super().complete_json(messages, json_schema, timeout_s)

    summary = svc.draft(doc["doc_id"], Flaky())
    assert summary.model_errors == 1 and summary.kept == 2


# ---------------------------------------------------------------------------- the instrument


def _confirm_all(svc: it.InternalDocs, doc: dict[str, Any], who: str = "approver.em") -> None:
    svc.draft(doc["doc_id"], FakeChat())
    for r in svc.drafts.list(doc["instrument_id"], "draft"):
        svc.drafts.decide(r["draft_id"], "confirmed", who)
    svc.after_decision(doc["doc_id"], who)


def test_confirm_builds_a_valid_instrument_the_loader_loads(
    svc: it.InternalDocs, chain: Chain
) -> None:
    doc = upload(svc, "legal")
    _confirm_all(svc, doc)
    path = svc.doc_dir(doc["doc_id"]) / "instrument.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    inst = data["instrument"]
    assert inst["id"] == doc["instrument_id"] and inst["kind"] == "internal"
    assert inst["binding"] == "internal" and inst["verification"] == "VERIFIED_INTERNAL"
    assert inst["issuer"] == "Model Risk" and inst["number"] == "v1"
    src = inst["sources"][0]
    assert src["sha256"] == doc["sha256"] and src["local_path"].endswith("/text.txt")
    assert [o["verification"] for o in data["obligations"]] == ["VERIFIED_INTERNAL"] * 3
    ob = data["obligations"][0]
    assert ob["id"].startswith(f"{doc['instrument_id']}-S") and ob["id"].endswith("-01")
    assert ob["confirmed_by"] == "approver.em" and ob["duties"] == [
        "risk_classification",
        "internal_policy",
    ]
    assert it.validate_instrument_text(path.read_text("utf-8"), doc["doc_id"],
                                       svc.doc_dir(doc["doc_id"]) / "text.txt") == []  # fmt: skip
    kb = load_kb(docs_dir=svc.root)
    got = kb.instrument(doc["instrument_id"])
    assert got.binding == "internal" and got.kind == "internal"
    assert len(kb.obligations_of(doc["instrument_id"])) == 3
    assert svc.get(doc["doc_id"])["status"] == "confirmed"
    actions = [(r[2]["action"], r[2].get("confirmed")) for r in chain.records]
    assert actions == [("upload", None), ("confirm", 3)]
    assert not any(isinstance(v, float) for v in chain.records[-1][2].values())


def test_dropping_everything_removes_the_instrument(svc: it.InternalDocs) -> None:
    doc = upload(svc, "legal")
    _confirm_all(svc, doc)
    assert (svc.doc_dir(doc["doc_id"]) / "instrument.yaml").is_file()
    svc.retire(doc["doc_id"], "admin.chi")
    assert not (svc.doc_dir(doc["doc_id"]) / "instrument.yaml").exists()
    assert svc.get(doc["doc_id"])["status"] == "retired"
    assert [i for i in load_kb(docs_dir=svc.root).instruments if i.id.startswith("VN-INT-")] == []


def test_loader_rejects_a_changed_source_and_a_forged_internal_file(
    svc: it.InternalDocs, tmp_path: Path
) -> None:
    doc = upload(svc, "legal")
    _confirm_all(svc, doc)
    raw = svc.doc_dir(doc["doc_id"]) / "text.txt"
    good = raw.read_text("utf-8")
    raw.write_text(good + "\nthêm", encoding="utf-8")
    with pytest.raises(RegKBError) as exc:
        load_kb(docs_dir=svc.root)
    assert "sha256 does not match" in "\n".join(exc.value.errors)  # type: ignore[attr-defined]
    raw.write_text(good, encoding="utf-8")
    assert load_kb(docs_dir=svc.root)
    # VERIFIED_INTERNAL and binding internal are refused in the external folders
    forged = yaml.safe_load((svc.doc_dir(doc["doc_id"]) / "instrument.yaml").read_text("utf-8"))
    forged["instrument"]["id"] = "VN-FORGED-2026"
    for o in forged["obligations"]:
        o["id"] = o["id"].replace(doc["instrument_id"], "VN-FORGED-2026")
        o["sources"] = [dict(forged["instrument"]["sources"][0])]
    root = tmp_path / "regs"
    (root / "vn").mkdir(parents=True)
    (root / "intl").mkdir()
    (root / "vn" / "forged.yaml").write_text(yaml.safe_dump(forged, allow_unicode=True), "utf-8")
    with pytest.raises(RegKBError) as exc:
        load_kb(root)
    assert "only for internal documents" in "\n".join(exc.value.errors)  # type: ignore[attr-defined]


def test_matrix_sees_the_internal_rows(svc: it.InternalDocs) -> None:
    from supervisor.advisory.compliance.demo import demo_product
    from supervisor.advisory.compliance.matrix import build_matrix

    doc = upload(svc, "legal")
    _confirm_all(svc, doc)
    kb = load_kb(docs_dir=svc.root)
    matrix = build_matrix(kb, demo_product("payments"), chat=None)
    ids = [r.obligation_id for r in matrix.rows if r.instrument_id == doc["instrument_id"]]
    assert len(ids) == 3
    row = next(r for r in matrix.rows if r.instrument_id == doc["instrument_id"])
    assert row.applies == "yes" and row.binding is True
    assert doc["instrument_id"] in matrix.header.internal_instruments
