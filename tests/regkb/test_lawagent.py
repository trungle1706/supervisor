"""WP-L1: the law agent. Parser, rules, diff mode, store, run with a fake chat adapter, export.

The fake chat adapter below is the only fake in these tests and only here: it stands in for the
gateway model so the rules and the store can be tested without a network. A stored row says
source=model with the fake's model_id, as a real run would.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import REPO_ROOT, load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.regkb import lawagent as la
from supervisor.regkb import load_kb
from supervisor.regkb.drafts import DraftError, DraftStore
from supervisor.regkb.loader import _load_yaml

INSTRUMENT = "VN-DEC142-2026"
TEXT_PATH = REPO_ROOT / "regulations" / "sources" / INSTRUMENT / "142-2026-nd-cp.txt"
DUTIES = _load_yaml(REPO_ROOT / "regulations" / "schema" / "duties.yaml")["duties"]


@pytest.fixture(scope="module")
def text() -> str:
    return TEXT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data", llm_base_url="")
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def store(adapters: Adapters) -> DraftStore:
    return DraftStore(adapters.state, adapters.clock)


class FakeChat:
    """Stands in for the gateway model in unit tests. Not a mock of the product: is_mock False."""

    is_mock = False
    family = "fake"

    def __init__(self, model_id: str = "fake-law-model-1") -> None:
        self.model_id = model_id
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        user = json.loads(messages[1]["content"])
        article_text = user["article_text"]
        self.calls.append(user)
        body = article_text.split(". ", 1)[1] if ". " in article_text else article_text
        good = body[:90].strip()
        base = {
            "clause": "",
            "subject": "The deployer of the AI system",
            "trigger": "When the system is deployed",
            "evidence_asked": "The record kept by the bank",
            "summary_en": "A test duty.",
        }
        return {
            "drafts": [
                {**base, "duty_id": "risk_classification", "quote": good},
                {
                    **base,
                    "duty_id": "risk_classification",
                    "quote": "Câu này không có trong điều luật nào cả",
                },
                {**base, "duty_id": "not_a_duty", "quote": good},
            ]
        }


# ---------------------------------------------------------------------------- parser


def test_parser_finds_the_46_articles_of_decree_142(text: str) -> None:
    arts = la.split_articles(text)
    assert [a.number for a in arts] == list(range(1, 47))
    assert arts[0].heading == "Điều 1. Phạm vi điều chỉnh"
    assert arts[45].heading == "Điều 46. Điều khoản chuyển tiếp"
    # the annex forms have their own "Điều 1..7" headings; they are not articles of the decree
    assert "Báo cáo sự cố nghiêm trọng" not in arts[45].text
    assert "Nơi nhận" not in arts[45].text
    assert all(a.body_sha256 and len(a.body_sha256) == 64 for a in arts)


def test_parser_ignores_cross_references_and_chapter_titles() -> None:
    sample = (
        "Chương I\nQUY ĐỊNH CHUNG\nĐiều 1. Phạm vi\nNội dung một.\n"
        "Điều 5. nhắc lại điều khác\n"  # not the next number: part of article 1
        "Điều 2. Đối tượng\nNội dung hai.\nChương II\nTIÊU ĐỀ CHƯƠNG\nĐiều 3. Ba\nXong.\n"
        "Nơi nhận:\n- Lưu\nĐiều 4. Mẫu trong phụ lục\n"
    )
    arts = la.split_articles(sample)
    assert [a.number for a in arts] == [1, 2, 3, 4]
    assert "Điều 5. nhắc lại điều khác" in arts[0].text
    assert "TIÊU ĐỀ CHƯƠNG" not in arts[1].text and "TIÊU ĐỀ CHƯƠNG" not in arts[2].text
    assert arts[2].text == "Điều 3. Ba Xong."
    assert arts[3].body == ""  # the signature block closed article 3; article 4 is the next number


def test_article_refs_and_ranges() -> None:
    assert la.make_article_ref(12) == "Điều 12"
    assert la.make_article_ref(12, "3") == "12.3"
    assert la.parse_article_ref("Điều 12") == (12, "")
    assert la.parse_article_ref("12.3") == (12, "3")
    assert la.parse_article_ref("5.2a") == (5, "2a")
    with pytest.raises(ValueError):
        la.parse_article_ref("Article 5")
    assert la.parse_range("1-3,7", list(range(1, 10))) == [1, 2, 3, 7]
    with pytest.raises(ValueError):
        la.parse_range("40-50", list(range(1, 47)))
    with pytest.raises(ValueError):
        la.parse_range("a-b", [1])


# ---------------------------------------------------------------------------- rules


@pytest.fixture(scope="module")
def articles(text: str) -> dict[int, la.Article]:
    return {a.number: a for a in la.split_articles(text)}


def _raw(article: la.Article, **over: Any) -> dict[str, Any]:
    body = article.body
    base = {
        "duty_id": "risk_classification",
        "clause": "",
        "subject": "Deployer",
        "trigger": "Before use",
        "evidence_asked": "Classification record",
        "quote": body[:80],
        "summary_en": "Classify the system.",
    }
    base.update(over)
    return base


def test_rules_keep_a_good_draft_and_fold_white_space(articles: dict[int, la.Article]) -> None:
    art = articles[5]
    # the stored text wraps lines; the quote written on one line still matches
    res = la.check_draft(
        _raw(art, quote="  " + art.body[:80].replace(" ", "  ") + " "), art, articles, DUTIES
    )
    assert res.ok and res.row is not None
    assert res.row["article"] == "Điều 5" and res.row["text_vi"] == art.body[:80].strip()
    assert la.check_draft(_raw(art, clause="3"), art, articles, DUTIES).row["article"] == "5.3"  # type: ignore[index]


def test_rules_drop_a_bad_quote(articles: dict[int, la.Article]) -> None:
    art = articles[5]
    for quote in ("Câu này không có trong điều luật nào cả", art.body[:60] + " thêm chữ", "ngắn"):
        res = la.check_draft(_raw(art, quote=quote), art, articles, DUTIES)
        assert not res.ok and res.reason in ("quote_not_in_article", "bad_quote_length")
    # a quote that is in another article is not in this one
    other = articles[6].body[:80]
    assert other not in art.text
    assert (
        la.check_draft(_raw(art, quote=other), art, articles, DUTIES).reason
        == "quote_not_in_article"
    )
    # whole-text case: the check is on the article, not on a changed spelling
    assert (
        la.check_draft(_raw(art, quote=art.body[:80].upper()), art, articles, DUTIES).reason
        == "quote_not_in_article"
    )


def test_rules_drop_a_bad_duty_clause_field_and_article(articles: dict[int, la.Article]) -> None:
    art = articles[5]
    assert (
        la.check_draft(_raw(art, duty_id="made_up"), art, articles, DUTIES).reason == "unknown_duty"
    )
    assert la.check_draft(_raw(art, clause="third"), art, articles, DUTIES).reason == "bad_clause"
    assert la.check_draft(_raw(art, subject=" "), art, articles, DUTIES).reason == "missing_field"
    ghost = la.Article(99, "Điều 99. x", "y", "Điều 99. x y", "0" * 64)
    assert la.check_draft(_raw(art), ghost, articles, DUTIES).reason == "unknown_article"


# ---------------------------------------------------------------------------- run with a fake chat


def test_run_writes_only_checked_drafts_and_counts_the_rest(text: str, store: DraftStore) -> None:
    chat = FakeChat()
    lines: list[str] = []
    s = la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=chat,
        store=store,
        numbers=[3, 4, 5],
        progress=lines.append,
    )
    assert len(chat.calls) == 3
    assert (s.articles_read, s.model_drafts, s.kept, s.dropped) == (3, 9, 3, 6)
    assert s.drop_reasons == {"quote_not_in_article": 3, "unknown_duty": 3}
    assert not s.mock and s.model_errors == 0
    rows = store.list(INSTRUMENT)
    assert len(rows) == 3
    for r in rows:
        assert r["status"] == "draft" and r["confirmed_by"] is None
        assert r["source"] == "model" and r["model_id"] == "fake-law-model-1"
        assert r["prompt_version"] == la.PROMPT_VERSION and r["run_id"] == s.run_id
        assert r["duty_id"] == "risk_classification" and len(r["text_vi"]) <= 2000
    assert {r["article"] for r in rows} == {"Điều 3", "Điều 4", "Điều 5"}
    assert any("Dieu" not in ln and "kept" in ln for ln in lines)
    # nothing became an obligation
    assert not any(o.id.startswith(INSTRUMENT + "-A3-") for o in load_kb().obligations.values())


def test_run_does_not_write_the_same_draft_again_and_respects_a_drop(
    text: str, store: DraftStore
) -> None:
    kw = {
        "instrument_id": INSTRUMENT,
        "text": text,
        "duties": DUTIES,
        "chat": FakeChat(),
        "store": store,
    }
    first = la.run_agent(**kw, numbers=[5])
    assert first.kept == 1
    again = la.run_agent(**kw, numbers=[5])
    assert (again.kept, again.skipped_existing) == (0, 1)
    row = store.list(INSTRUMENT)[0]
    store.decide(row["draft_id"], "dropped", "approver.x")
    third = la.run_agent(**kw, numbers=[5])
    assert (third.kept, third.skipped_decided) == (0, 1)
    assert len(store.list(INSTRUMENT)) == 1


def test_run_counts_a_model_error_and_goes_on(text: str, store: DraftStore) -> None:
    class Flaky(FakeChat):
        def complete_json(self, messages, json_schema, timeout_s):  # type: ignore[no-untyped-def]
            if (
                "Điều 4" in messages[1]["content"]
                and '"article": "Điều 4"' in messages[1]["content"]
            ):
                raise RuntimeError("gateway down")
            return super().complete_json(messages, json_schema, timeout_s)

    s = la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=Flaky(),
        store=store,
        numbers=[3, 4, 5],
    )
    assert s.model_errors == 1 and s.kept == 2


def test_run_rejects_an_unknown_article(text: str, store: DraftStore) -> None:
    with pytest.raises(Exception, match="no article 99"):
        la.run_agent(
            instrument_id=INSTRUMENT,
            text=text,
            duties=DUTIES,
            chat=FakeChat(),
            store=store,
            numbers=[99],
        )


def test_a_mock_model_is_labelled(text: str, store: DraftStore) -> None:
    from supervisor.adapters.llm.mock import MockChat

    s = la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=MockChat(),
        store=store,
        numbers=[2],
    )
    assert s.mock and "mock" in s.model_id
    assert s.lines()[0].startswith("[WARN] MOCK MODEL")


# ---------------------------------------------------------------------------- store


def test_store_decide_rules(text: str, store: DraftStore) -> None:
    la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=FakeChat(),
        store=store,
        numbers=[5],
    )
    row = store.list(INSTRUMENT)[0]
    with pytest.raises(DraftError):
        store.decide(row["draft_id"], "draft", "p")
    with pytest.raises(DraftError):
        store.decide(row["draft_id"], "confirmed", "")
    with pytest.raises(DraftError):
        store.decide("rkd_nope", "confirmed", "p")
    with pytest.raises(DraftError, match="another window"):
        store.decide(row["draft_id"], "confirmed", "p", expected_version=99)
    done = store.decide(row["draft_id"], "confirmed", "approver.x")
    assert done["status"] == "confirmed" and done["confirmed_by"] == "approver.x"
    assert done["confirmed_at"] is not None
    with pytest.raises(DraftError, match="already confirmed"):
        store.decide(row["draft_id"], "dropped", "approver.y")


def test_store_refuses_a_long_quote_and_a_bad_source(store: DraftStore) -> None:
    base = {
        "instrument_id": INSTRUMENT, "article": "Điều 1", "duty_id": "logging", "subject": "s",
        "trigger": "t", "evidence_asked": "e", "text_vi": "x" * 2001, "summary_en": "s",
        "source": "model", "run_id": "r",
    }  # fmt: skip
    with pytest.raises(DraftError):
        store.add([base])
    with pytest.raises(DraftError):
        store.add([{**base, "text_vi": "ok", "source": "human"}])


# ---------------------------------------------------------------------------- diff mode


def test_compare_lists_added_changed_removed(text: str) -> None:
    assert la.compare(text, text).empty
    old = "Điều 1. Một\nNội dung một.\nĐiều 2. Hai\nNội dung hai.\nĐiều 3. Ba\nNội dung ba.\n"
    new = (
        "Điều 1. Một\nNội dung một.\nĐiều 2. Hai\nNội dung hai đã đổi.\n"
        "Điều 3. Ba\nNội  dung\nba.\nĐiều 4. Bốn\nMới.\n"
    )
    d = la.compare(old, new)
    assert [c.number for c in d.added] == [4] and d.added[0].heading == "Điều 4. Bốn"
    assert [c.number for c in d.changed] == [2]  # article 3 differs only in white space
    assert d.changed[0].old_sha256 != d.changed[0].new_sha256
    assert d.removed == ()
    back = la.compare(new, old)
    assert [c.number for c in back.removed] == [4] and back.removed[0].new_sha256 is None
    heading_only = la.compare("Điều 1. A\nx.\n", "Điều 1. B\nx.\n")
    assert [c.number for c in heading_only.changed] == [1]
    assert json.dumps(d.as_dict())  # plain data for Phase 11


def test_compare_on_the_real_text_with_one_article_edited(text: str) -> None:
    art = la.split_articles(text)[9]
    edited = text.replace(art.body.split(" ")[0], art.body.split(" ")[0] + "X", 1)
    d = la.compare(text, edited)
    assert d.added == () and d.removed == ()
    assert len(d.changed) >= 1


# ---------------------------------------------------------------------------- export


def _confirm_all(text: str, store: DraftStore, who: str = "approver.hoa") -> list[dict[str, Any]]:
    la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=FakeChat(),
        store=store,
        numbers=[5, 6],
    )
    for r in store.list(INSTRUMENT):
        store.decide(r["draft_id"], "confirmed", who)
    return store.list(INSTRUMENT, "confirmed")


def test_export_shape(text: str, store: DraftStore) -> None:
    kb = load_kb()
    rows = _confirm_all(text, store)
    obs = la.export_obligations(rows, kb, INSTRUMENT)
    assert len(obs) == 2
    inst = kb.instrument(INSTRUMENT)
    primary = next(s for s in inst.sources if s.kind == "primary")
    for o in obs:
        assert o["id"].startswith(INSTRUMENT + "-A")
        assert o["id"] not in kb.obligations
        assert o["verification"] == "VERIFIED_PRIMARY" and o["confirmed_by"] == "approver.hoa"
        assert o["sources"][0]["sha256"] == primary.sha256 and o["sources"][0]["kind"] == "primary"
        assert o["duties"] == ["risk_classification"] and o["control_mapping"] == []
        assert o["applies_to"] == {"role": ["deployer"]}
    assert obs[0]["article_ref"] == "Art. 5" and obs[1]["article_ref"] == "Art. 6"
    out = la.export_yaml(obs, INSTRUMENT)
    assert out.startswith("# Not legal advice. Bank counsel must confirm.")
    assert yaml.safe_load(out)["obligations"][0]["id"] == obs[0]["id"]


def test_export_ignores_drafts_and_drops(text: str, store: DraftStore) -> None:
    la.run_agent(
        instrument_id=INSTRUMENT,
        text=text,
        duties=DUTIES,
        chat=FakeChat(),
        store=store,
        numbers=[5, 6, 7],
    )
    a, b, _c = store.list(INSTRUMENT)
    store.decide(a["draft_id"], "confirmed", "p1")
    store.decide(b["draft_id"], "dropped", "p1")
    obs = la.export_obligations(store.list(INSTRUMENT), load_kb(), INSTRUMENT)
    assert len(obs) == 1 and obs[0]["confirmed_by"] == "p1"


def test_exported_yaml_passes_the_regkb_validator(
    text: str, store: DraftStore, tmp_path: Path
) -> None:
    """Paste the exported items into the instrument file: load_kb validates schema and rules,
    including that every VERIFIED_PRIMARY VN obligation has text_vi and the source sha matches."""
    kb = load_kb()
    obs = la.export_obligations(_confirm_all(text, store), kb, INSTRUMENT)
    exported = tmp_path / "confirmed.yaml"
    exported.write_text(la.export_yaml(obs, INSTRUMENT), encoding="utf-8")

    root = tmp_path / "regulations"
    (root / "vn").mkdir(parents=True)
    src = root / "sources" / INSTRUMENT
    src.mkdir(parents=True)
    shutil.copy(TEXT_PATH, src / TEXT_PATH.name)
    data = yaml.safe_load(
        (REPO_ROOT / "regulations" / "vn" / "decree-142-2026.yaml").read_text("utf-8")
    )
    n_before = len(data["obligations"])
    data["obligations"] += yaml.safe_load(exported.read_text("utf-8"))["obligations"]
    (root / "vn" / "decree-142-2026.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    checked = load_kb(root)  # raises SchemaError or SemanticError on any problem
    mine = [o for o in checked.obligations.values() if o.confirmed_by == "approver.hoa"]
    assert len(checked.obligations) == n_before + 2 and len(mine) == 2
    assert all(o.verification == "VERIFIED_PRIMARY" and o.text_vi for o in mine)
    # the quote is in the stored text (same check as tests/regkb/test_quotes.py)
    norm = la.normalise_ws(text)
    assert all(la.normalise_ws(o.text_vi or "") in norm for o in mine)
    # the confirmed_by field changes the version hash only when present
    assert checked.version != kb.version


def test_real_data_hash_is_unchanged_by_the_new_optional_field() -> None:
    kb = load_kb()
    assert all(o.confirmed_by is None for o in kb.obligations.values())
    assert "confirmed_by" not in json.dumps(kb.snapshot())


def test_obligation_ids_are_unique_and_valid_for_clauses() -> None:
    taken: set[str] = set()
    ids = [
        la.obligation_id("VN-X-1", "Điều 5", taken),
        la.obligation_id("VN-X-1", "Điều 5", taken),
        la.obligation_id("VN-X-1", "5.3", taken),
        la.obligation_id("VN-X-1", "5.2a", taken),
    ]
    assert ids == ["VN-X-1-A5-01", "VN-X-1-A5-02", "VN-X-1-A5.03-01", "VN-X-1-A5.02A-01"]


# ---------------------------------------------------------------------------- CLI


def test_cli_is_off_by_default_and_compare_is_pure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    monkeypatch.delenv("LAWAGENT_ENABLED", raising=False)
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    assert la.main(["--instrument", INSTRUMENT]) == 2
    out = capsys.readouterr().out
    assert out.isascii() and out.splitlines()[0] == la.BANNER and "[SKIP]" in out
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("Điều 1. A\nx.\n", encoding="utf-8")
    b.write_text("Điều 1. A\ny.\nĐiều 2. B\nz.\n", encoding="utf-8")
    assert la.main(["--compare", str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "added: 1" in out and "changed: 1" in out and la.BANNER in out


def test_cli_refuses_a_mock_model_and_runs_with_allow_mock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    monkeypatch.setenv("LAWAGENT_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("LLM_BASE_URL", "")
    assert la.main(["--instrument", INSTRUMENT, "--articles", "1-2"]) == 2
    out = capsys.readouterr().out
    assert out.isascii() and "[FAIL]" in out and "mock" in out and out.splitlines()[0] == la.BANNER
    out_json = tmp_path / "drafts.json"
    code = la.main(
        ["--instrument", INSTRUMENT, "--articles", "1-2", "--allow-mock", "--out", str(out_json)]
    )
    out = capsys.readouterr().out
    assert code == 0 and out.isascii() and "MOCK MODEL" in out and out.rstrip().endswith(la.BANNER)
    payload = json.loads(out_json.read_text("utf-8"))
    assert payload["summary"]["mock"] is True and payload["banner"] == la.BANNER
    assert la.main(["--instrument", "VN-NOPE-1", "--articles", "1"]) == 2
    assert la.main(["--instrument", INSTRUMENT, "--articles", "40-60"]) == 2
