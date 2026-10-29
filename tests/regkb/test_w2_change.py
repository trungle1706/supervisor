"""WP-W2: the diff mode of the law agent, the apply of a change, the override and the loader.

No network and no real model: a fake ChatModel with a call counter. The text of record is the
stored Decree 142 text of the repository; the incoming text is that text with one sentence of one
article changed (synthetic edit). The package is written by hand under DATA_DIR/regkb/incoming.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import REPO_ROOT, load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.regkb import change, lawagent
from supervisor.regkb.drafts import DraftStore
from supervisor.regkb.errors import RegKBError
from supervisor.regkb.loader import change_overrides_dir, load_kb

NOW = datetime(2026, 10, 29, 9, 0, 0, tzinfo=UTC)
IID = "VN-DEC142-2026"
STORED = REPO_ROOT / "regulations" / "sources" / IID / "142-2026-nd-cp.txt"
QUOTE_5 = "Bên triển khai phải chủ động phối hợp với nhà cung cấp để rà soát"
QUOTE_5B = "Nhà cung cấp phải thực hiện phân loại hệ thống trí tuệ nhân tạo trước khi đưa hệ thống"
FILE_NAME = f"{IID}/2026-10-28/142-2026-nd-cp.txt"


# ------------------------------------------------------------------------------ small texts


def art(n: int, body: str) -> str:
    return f"Điều {n}. Tiêu đề {n}\n{body}\n"


def mini(*arts: tuple[int, str]) -> str:
    return "".join(art(n, b) for n, b in arts)


def edit_article(text: str, number: int, old: str, new: str) -> str:
    """Replace the first ``old`` (white space tolerant) after the heading of an article."""
    head = re.search(rf"^Điều {number}\.", text, re.M)
    assert head is not None
    pattern = r"\s+".join(re.escape(w) for w in old.split())
    m = re.compile(pattern).search(text, head.end())
    assert m is not None, old
    return text[: m.start()] + new + text[m.end() :]


def new_text_art5() -> str:
    old = STORED.read_text(encoding="utf-8")
    return edit_article(old, 5, "Bên triển khai phải phối hợp với nhà cung cấp để rà soát", QUOTE_5)


def new_text_art11() -> str:
    old = STORED.read_text(encoding="utf-8")
    return edit_article(
        old,
        11,
        "Nhà cung cấp phải thực hiện rà soát",
        "Nhà cung cấp phải kịp thời thực hiện rà soát",
    )


# ------------------------------------------------------------------------------ rig


class FakeChat:
    """The gateway model: counts calls, answers by article number."""

    model_id = "fake-gateway"
    is_mock = False

    def __init__(self, answers: dict[int, list[dict[str, str]]] | None = None) -> None:
        self.answers = answers or {}
        self.calls = 0

    def complete_json(self, messages: list[dict[str, str]], schema: Any, timeout: float) -> Any:
        self.calls += 1
        body = json.loads(messages[1]["content"])
        number = int(body["article"].split()[1])
        return {"drafts": self.answers.get(number, [])}


def draft_of(duty: str, quote: str, clause: str = "3") -> dict[str, str]:
    return {
        "duty_id": duty,
        "clause": clause,
        "subject": "Deployer",
        "trigger": "when a system changes",
        "evidence_asked": "The review record",
        "quote": quote,
        "summary_en": "The deployer reviews the class with the provider.",
    }


class Records:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, kind: str, ref: str, payload: dict[str, Any]) -> None:
        self.items.append((kind, ref, payload))


def write_package(data_dir: Path, text: str, tag: str = "a") -> str:
    """A stored package (as the W1 import leaves it) with one text_changed item."""
    sha = hashlib.sha256(f"pkg-{tag}-{text[:50]}".encode()).hexdigest()
    base = data_dir / "regkb" / "incoming" / sha
    target = base / "incoming" / FILE_NAME
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    target.with_name("142-2026-nd-cp.meta.json").write_text(
        json.dumps(
            {
                "url": "https://vbpl.vn/example/142-2026",
                "title": "Nghi dinh 142/2026/ND-CP (synthetic incoming)",
                "fetched_at": "2026-10-28T09:00:00Z",
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    (base / "import.json").write_text(
        json.dumps(
            {
                "package_sha256": sha,
                "run_id": "rw_test",
                "imported_at": "2026-10-28T10:00:00Z",
                "imported_by": "admin.chi",
                "applied": False,
            }
        ),
        encoding="utf-8",
    )
    (base / "watch-2026-10-28.json").write_text(
        json.dumps(
            {
                "format": "regwatch-report-1",
                "summary": {"changes_found": 1},
                "instruments": [
                    {
                        "instrument_id": IID,
                        "changes": [
                            {
                                "kind": "text_changed",
                                "instrument_id": IID,
                                "incoming": [FILE_NAME],
                                "detail": "synthetic",
                                "url": "https://vbpl.vn/example/142-2026",
                                "date": "2026-10-28",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return sha


class Rig:
    def __init__(self, a: Adapters, data_dir: Path) -> None:
        self.a = a
        self.data_dir = data_dir
        self.records = Records()

    @property
    def settings(self) -> Any:
        return self.a.settings

    def package(self, text: str, tag: str = "a") -> str:
        return write_package(self.data_dir, text, tag)

    def diff(self, sha: str, chat: FakeChat | None = None, **over: Any) -> dict[str, Any]:
        args: dict[str, Any] = {
            "data_dir": self.data_dir,
            "state": self.a.state,
            "clock": self.a.clock,
            "settings": self.settings,
            "instrument_id": IID,
            "package_sha": sha,
            "actor": "approver.hoa",
            "chat": chat or FakeChat(),
        }
        args.update(over)
        return change.run_diff(**args)

    def apply(self, sha: str) -> dict[str, Any]:
        return change.apply_change(
            data_dir=self.data_dir,
            state=self.a.state,
            clock=self.a.clock,
            settings=self.settings,
            package_sha=sha,
            instrument_id=IID,
            actor="approver.hoa",
            record=self.records,
        )

    def confirm_all(self, sha: str) -> list[dict[str, Any]]:
        rows = change.linked_drafts(self.a.state, change.change_id_of(sha, IID))
        store = DraftStore(self.a.state, self.a.clock)
        for r in rows:
            store.decide(r["draft_id"], "confirmed", "approver.hoa")
        return rows


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    data = tmp_path / "data"
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=data,
        llm_base_url="",
        governance_enabled=True,
        lawagent_enabled=True,
        regkb_change_loop=True,
    )
    a = build_adapters(settings, clock=FixedClock(NOW))
    bootstrap_schema.run(a.settings, a)
    try:
        yield Rig(a, data)
    finally:
        a.close()


# ------------------------------------------------------------------------------ the article diff


def test_diff_three_synthetic_pairs() -> None:
    base = mini((1, "Bên A phải làm việc một."), (2, "Bên B phải làm việc hai."))
    # 1. unchanged (also when only the white space differs)
    deltas, outside = change.diff_texts(base, base.replace(" ", "  "))
    assert [d.status for d in deltas] == ["unchanged", "unchanged"] and not outside
    assert sum(d.changed_chars for d in deltas) == 0
    # 2. one changed article
    deltas, _ = change.diff_texts(base, base.replace("việc hai", "việc ba bốn"))
    assert [(d.number, d.status) for d in deltas] == [(1, "unchanged"), (2, "changed")]
    assert isinstance(deltas[1].changed_chars, int) and deltas[1].changed_chars > 0
    assert deltas[1].old_sha256 != deltas[1].new_sha256
    # 3. one added and one removed (article 3 is added at the end; article 2 is dropped from the
    # copy that stops at article 1, so run both directions)
    longer = mini((1, "Bên A phải làm việc một."), (2, "Bên B phải làm việc hai."), (3, "Mới."))
    added, _ = change.diff_texts(base, longer)
    assert [(d.number, d.status) for d in added] == [
        (1, "unchanged"),
        (2, "unchanged"),
        (3, "added"),
    ]
    removed, _ = change.diff_texts(longer, base)
    assert [(d.number, d.status) for d in removed][-1] == (3, "removed")
    # the splitter reads consecutive numbers only, so a gap never opens a new article


def test_a_text_that_differs_only_outside_the_articles_is_flagged() -> None:
    base = mini((1, "Bên A phải làm việc một.")) + "Nơi nhận:\nCơ quan 1\n"
    other = mini((1, "Bên A phải làm việc một.")) + "Nơi nhận:\nCơ quan 2\n"
    deltas, outside = change.diff_texts(base, other)
    assert all(d.status == "unchanged" for d in deltas) and outside is True
    assert change.classification_hit("VN-QD33-2026", deltas, outside) is True
    assert change.classification_hit(IID, deltas, outside) is False


def test_classification_trigger_list() -> None:
    mk = lambda n, s: change.ArticleDelta(n, s, None, None, None, None, 1)  # noqa: E731
    assert change.classification_hit(IID, [mk(9, "changed")])
    assert change.classification_hit(IID, [mk(11, "removed")])
    assert not change.classification_hit(IID, [mk(5, "changed")])
    assert not change.classification_hit(IID, [mk(9, "unchanged")])
    assert change.classification_hit("VN-AI-2025", [mk(7, "added")])
    assert change.classification_hit("VN-TT53-2026", [mk(4, "changed")])
    assert not change.classification_hit("VN-TT53-2026", [mk(5, "changed")])
    assert change.classification_hit("VN-QD33-2026", [mk(1, "changed")])


def test_article_numbers_of_an_article_ref() -> None:
    assert lawagent.article_numbers("Art. 5(3)") == [5]
    assert lawagent.article_numbers("Art. 5(1), 6(2)") == [5, 6]
    assert lawagent.article_numbers("Decree 142/2026 Art. 5-7") == [5, 6, 7]
    assert lawagent.article_numbers("Appendix IV, entry 1 (condition 2)") == []
    assert lawagent.article_numbers("Art. 7(1), (2)") == [7]


# ------------------------------------------------------------------------------ off path


def test_off_path_refuses_and_writes_nothing(tmp_path: Path) -> None:
    data = tmp_path / "data"
    off = load_settings(sql_backend="sqlite", data_dir=data, llm_base_url="")
    assert off.regkb_change_loop is False
    with pytest.raises(change.ChangeError, match="change_loop_off"):
        change.require_on(off)
    a = build_adapters(off, clock=FixedClock(NOW))
    bootstrap_schema.run(a.settings, a)
    try:
        chat = FakeChat()
        with pytest.raises(change.ChangeError, match="change_loop_off"):
            change.run_diff(
                data_dir=data,
                state=a.state,
                clock=a.clock,
                settings=off,
                instrument_id=IID,
                package_sha="a" * 64,
                actor="x",
                chat=chat,
            )
        with pytest.raises(change.ChangeError, match="change_loop_off"):
            change.apply_change(
                data_dir=data,
                state=a.state,
                clock=a.clock,
                settings=off,
                package_sha="a" * 64,
                instrument_id=IID,
                actor="x",
            )
        assert chat.calls == 0 and not (data / "regkb").exists()
        assert a.state.query("regkb_change") == []
    finally:
        a.close()


def test_the_flag_needs_lawagent_and_governance(tmp_path: Path) -> None:
    s = load_settings(
        sql_backend="sqlite", data_dir=tmp_path, llm_base_url="", regkb_change_loop=True
    )
    assert change.enabled(s) is False
    with pytest.raises(change.ChangeError, match="change_loop_off"):
        change.require_on(s)


def test_loader_ignores_overrides_while_the_flag_is_off(tmp_path: Path) -> None:
    off = load_settings(sql_backend="sqlite", data_dir=tmp_path, llm_base_url="")
    on = load_settings(
        sql_backend="sqlite", data_dir=tmp_path, llm_base_url="", regkb_change_loop=True
    )
    assert change_overrides_dir(off) is None
    assert change_overrides_dir(on) == tmp_path.resolve() / "regkb" / "overrides"


# ------------------------------------------------------------------------------ the diff run


def test_diff_drafts_only_changed_articles_with_quotes_inside_the_article(rig: Rig) -> None:
    sha = rig.package(new_text_art5())
    chat = FakeChat(
        {
            5: [
                draft_of("risk_classification", QUOTE_5),
                draft_of("human_oversight", "Câu này không có trong điều đang đọc."),
            ]
        }
    )
    report = rig.diff(sha, chat)
    s = report["summary"]
    assert (s["changed"], s["added"], s["removed"]) == (1, 0, 0) and s["unchanged"] == 45
    assert chat.calls == 1  # only the changed article was sent to the model
    assert s["drafts_made"] == 1 and s["dropped_by_rules"] == 1  # the quote outside was dropped
    assert isinstance(s["changed_chars"], int) and s["changed_chars"] > 0
    assert report["articles"][4]["number"] == 5 and report["articles"][4]["status"] == "changed"
    assert s["classification_hit"] is False
    (d,) = report["drafts"]
    row = DraftStore(rig.a.state, rig.a.clock).get(d["draft_id"])
    assert row is not None and row["status"] == "draft" and row["instrument_id"] == IID
    article = {a.number: a for a in lawagent.split_articles(new_text_art5())}[5]
    assert row["text_vi"] in article.text
    link = rig.a.state.get("regkb_change_draft", {"draft_id": d["draft_id"]})
    assert link is not None and link["change_ref"] == f"{sha}:{row['article']}"
    # the obligation whose article changed is marked
    assert [o["id"] for o in report["affected_obligations"]] == [f"{IID}-A5.03-01"] or (
        f"{IID}-A5.03-01" in [o["id"] for o in report["affected_obligations"]]
    )
    assert all(o["reason"] == "article_changed" for o in report["affected_obligations"])
    # report files with sha
    out = change.changes_dir(rig.data_dir, sha, IID)
    meta = json.loads((out / "diff.meta.json").read_text())
    assert meta["diff_json_sha256"] == hashlib.sha256((out / "diff.json").read_bytes()).hexdigest()
    assert meta["diff_md_sha256"] == hashlib.sha256((out / "diff.md").read_bytes()).hexdigest()
    assert "Điều 5" in (out / "diff.md").read_text(encoding="utf-8")
    # the change row
    row = change.get_row(rig.a.state, sha, IID)
    assert row is not None and row["status"] == "diffed" and row["articles_changed"] == 1
    assert row["articles"] == [5] and row["classification_hit"] is False


def test_unchanged_text_makes_no_model_call(rig: Rig) -> None:
    sha = rig.package(STORED.read_text(encoding="utf-8"), tag="same")
    chat = FakeChat({5: [draft_of("risk_classification", QUOTE_5)]})
    report = rig.diff(sha, chat)
    s = report["summary"]
    assert (s["changed"], s["added"], s["removed"]) == (0, 0, 0) and s["drafts_made"] == 0
    assert chat.calls == 0 and report["model"]["calls"] == 0
    assert rig.a.state.query("regkb_draft") == []
    with pytest.raises(change.ChangeError, match="nothing_to_apply"):
        rig.apply(sha)


def test_diff_refusals(rig: Rig) -> None:
    with pytest.raises(change.ChangeError, match="no_package"):
        rig.diff("b" * 64)
    with pytest.raises(change.ChangeError, match="bad_package"):
        rig.diff("nothex")
    sha = rig.package(new_text_art5())
    with pytest.raises(change.ChangeError, match="bad_incoming"):
        rig.diff(sha, incoming=f"{IID}/../x.txt")
    with pytest.raises(change.ChangeError, match="unknown_instrument|bad_instrument"):
        rig.diff(sha, instrument_id="VN-NOPE-2026")


def test_diff_from_a_local_file(rig: Rig, tmp_path: Path) -> None:
    f = tmp_path / "incoming.txt"
    f.write_text(new_text_art5(), encoding="utf-8")
    chat = FakeChat({5: [draft_of("risk_classification", QUOTE_5)]})
    report = rig.diff(hashlib.sha256(b"x").hexdigest(), chat, package_sha=None, incoming_file=f)
    assert report["package_sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
    assert report["summary"]["changed"] == 1 and chat.calls == 1


def test_a_classification_article_sets_the_flag(rig: Rig) -> None:
    sha = rig.package(new_text_art11(), tag="art11")
    report = rig.diff(sha)
    assert report["summary"]["changed"] == 1
    assert report["summary"]["classification_hit"] is True
    row = change.get_row(rig.a.state, sha, IID)
    assert row is not None and row["classification_hit"] is True and row["articles"] == [11]


# ------------------------------------------------------------------------------ apply


def test_apply_writes_the_override_and_the_loader_applies_it(rig: Rig) -> None:
    regs = REPO_ROOT / "regulations" / "vn" / "decree-142-2026.yaml"
    before_bytes = regs.read_bytes()
    base_version = load_kb(overrides_dir=rig.data_dir / "regkb" / "nothing").version
    sha = rig.package(new_text_art5())
    chat = FakeChat(
        {
            5: [
                draft_of("risk_classification", QUOTE_5),
                draft_of("human_oversight", QUOTE_5B, clause="2"),
            ]
        }
    )
    rig.diff(sha, chat)
    assert len(rig.confirm_all(sha)) == 2
    result = rig.apply(sha)
    assert (result["obligations_added"], result["obligations_updated"]) == (1, 1)
    assert result["obligations_removed"] == 0
    assert result["version_before"] == base_version != result["version_after"]
    # the committed files are untouched
    assert regs.read_bytes() == before_bytes
    # the override
    path = change.override_path(rig.data_dir, IID)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["format"] == "regkb-override-1" and doc["instrument_id"] == IID
    assert doc["text"]["sha256"] == hashlib.sha256(new_text_art5().encode()).hexdigest()
    assert (rig.data_dir / doc["text"]["path"]).is_file()
    ids = [o["id"] for o in doc["obligations"]]
    assert f"{IID}-A5.03-01" in ids and len(ids) == 2
    # the loader: with the override, the version changes and the text is the new quote
    root = rig.data_dir / "regkb" / "overrides"
    kb = load_kb(overrides_dir=root)
    assert kb.version == result["version_after"] != base_version
    updated = kb.get(f"{IID}-A5.03-01")
    assert updated.text_vi is not None and "chủ động" in updated.text_vi
    assert updated.confirmed_by == "approver.hoa" and updated.verification == "VERIFIED_PRIMARY"
    assert updated.control_mapping  # the mapping of the old row is kept
    primary = [s for s in kb.instrument(IID).sources if s.kind == "primary"]
    assert primary[0].sha256 == doc["text"]["sha256"]
    assert primary[0].local_path == doc["text"]["path"]
    # the text of record is now the incoming text
    text, sha_now, _ = change.current_text(rig.data_dir, kb, IID)
    assert sha_now == doc["text"]["sha256"] and "chủ động phối hợp" in text
    # without the override folder the version is the committed one again
    assert load_kb(overrides_dir=rig.data_dir / "regkb" / "nothing").version == base_version
    # the row, the chain record
    row = change.get_row(rig.a.state, sha, IID)
    assert row is not None and row["status"] == "applied" and row["applied_by"] == "approver.hoa"
    assert (row["obligations_added"], row["obligations_updated"]) == (1, 1)
    ((kind, ref, payload),) = rig.records.items
    assert kind == "regkb_change" and ref == row["change_id"]
    assert set(payload) == {
        "package_sha256",
        "instrument_id",
        "articles_changed",
        "obligations_added",
        "obligations_updated",
        "obligations_removed",
        "actor_ref",
    }
    assert payload["articles_changed"] == 1 and payload["obligations_added"] == 1
    for k, v in payload.items():
        assert isinstance(v, (str, int)) and not isinstance(v, (bool, float)), k
    assert "approver.hoa" not in json.dumps(payload)  # an actor ref, not the user id
    # a second apply is refused
    with pytest.raises(change.ChangeError, match="already_applied"):
        rig.apply(sha)
    with pytest.raises(change.ChangeError, match="already_applied"):
        rig.diff(sha)


def test_the_override_goes_through_the_validator_and_the_quote_check(rig: Rig) -> None:
    sha = rig.package(new_text_art5())
    rig.diff(sha, FakeChat({5: [draft_of("risk_classification", QUOTE_5)]}))
    rig.confirm_all(sha)
    rig.apply(sha)
    path = change.override_path(rig.data_dir, IID)
    root = rig.data_dir / "regkb" / "overrides"
    good = path.read_text(encoding="utf-8")

    def errors_of(folder: Path) -> str:
        with pytest.raises(RegKBError) as info:
            load_kb(overrides_dir=folder)
        return " | ".join(getattr(info.value, "errors", [str(info.value)]))

    def broken(edit: Any) -> None:
        doc = yaml.safe_load(good)
        edit(doc)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    # a quote that is not in the incoming text
    broken(lambda d: d["obligations"][0].__setitem__("text_vi", "Một câu không có trong văn bản."))
    assert "not a quote" in errors_of(root)
    # an unknown duty (the semantic rules of the loader)
    broken(lambda d: d["obligations"][0].__setitem__("duties", ["no_such_duty"]))
    assert "unknown duty" in errors_of(root)
    # a field the schema does not know
    broken(lambda d: d["obligations"][0].__setitem__("surprise", 1))
    assert "surprise" in errors_of(root)
    # the text file changed after the apply: the sha no longer matches
    path.write_text(good, encoding="utf-8")
    load_kb(overrides_dir=root)
    text_file = rig.data_dir / yaml.safe_load(good)["text"]["path"]
    text_file.write_text("changed", encoding="utf-8")
    assert "sha256 does not match" in errors_of(root)


def test_apply_refuses_an_invalid_confirmed_draft_and_writes_no_override(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = rig.package(new_text_art5())
    rig.diff(sha, FakeChat({5: [draft_of("risk_classification", QUOTE_5)]}))
    rows = rig.confirm_all(sha)
    # a person edits the stored quote after the check (a tampered row): the apply catches it
    rig.a.state.update(
        "regkb_draft",
        {"draft_id": rows[0]["draft_id"]},
        {"text_vi": "Một câu không có trong văn bản."},
        int(rig.a.state.get("regkb_draft", {"draft_id": rows[0]["draft_id"]})["row_version"]),
    )
    with pytest.raises(change.ChangeError, match="override_invalid"):
        rig.apply(sha)
    assert not change.override_path(rig.data_dir, IID).exists()
    row = change.get_row(rig.a.state, sha, IID)
    assert row is not None and row["status"] == "diffed"
    assert rig.records.items == []
    assert not list((rig.data_dir / "regkb").glob(".stage-*"))


def test_apply_needs_a_diff_and_a_current_text_of_record(rig: Rig) -> None:
    with pytest.raises(change.ChangeError, match="no_diff"):
        rig.apply("c" * 64)
    sha1 = rig.package(new_text_art5(), tag="one")
    sha2 = rig.package(new_text_art11(), tag="two")
    rig.diff(sha1)
    rig.diff(sha2)
    rig.apply(sha1)
    # the second diff was made against the old text of record: it is stale now
    with pytest.raises(change.ChangeError, match="stale_diff"):
        rig.apply(sha2)


def test_removed_articles_mark_their_obligations_and_apply_drops_them(rig: Rig) -> None:
    old = STORED.read_text(encoding="utf-8")
    cut = re.search(r"^Điều 46\.", old, re.M)
    assert cut is not None
    # remove the last article: obligations on Art. 46 (if any) are article_removed
    kb = change.kb_of(rig.data_dir)
    on46 = [o.id for o in kb.obligations_of(IID) if lawagent.article_numbers(o.article_ref) == [46]]
    sha = rig.package(old[: cut.start()], tag="cut")
    report = rig.diff(sha)
    assert report["summary"]["removed"] == 1 and report["summary"]["changed"] == 0
    assert [
        o["id"] for o in report["affected_obligations"] if o["reason"] == "article_removed"
    ] == (on46)
    assert FakeChat().calls == 0
    result = rig.apply(sha)
    assert result["obligations_removed"] == len(on46)
    after = load_kb(overrides_dir=rig.data_dir / "regkb" / "overrides")
    assert all(i not in after.obligations for i in on46)


def test_the_diff_page_data_pairs_old_and_new_text(rig: Rig) -> None:
    sha = rig.package(new_text_art5())
    report = rig.diff(sha, FakeChat({5: [draft_of("risk_classification", QUOTE_5)]}))
    pairs = change.side_by_side(rig.data_dir, sha, IID, report)
    assert [p["number"] for p in pairs] == [5]
    assert "chủ động" in pairs[0]["new_text"] and "chủ động" not in pairs[0]["old_text"]
    items = change.pending_items(rig.data_dir, rig.a.state)
    assert [(i["instrument_id"], i["status"], i["can_diff"]) for i in items] == [
        (IID, "diffed", True)
    ]
    banner = change.banner(rig.a.state, rig.data_dir, NOW)
    assert banner == {"pending": 1, "applied": []}


# ------------------------------------------------------------------------------ the command line


def _cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, loop: bool) -> Path:
    data = tmp_path / "clidata"
    for k, v in {
        "SUPERVISOR_ENV_FILE": "/dev/null",
        "SQL_BACKEND": "sqlite",
        "DATA_DIR": str(data),
        "LLM_BASE_URL": "",
        "LAWAGENT_ENABLED": "1",
        "GOVERNANCE_ENABLED": "1",
        "REGKB_CHANGE_LOOP": "1" if loop else "0",
    }.items():
        monkeypatch.setenv(k, v)
    return data


def test_cli_diff_is_skipped_while_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli_env(monkeypatch, tmp_path, loop=False)
    f = tmp_path / "in.txt"
    f.write_text(new_text_art5(), encoding="utf-8")
    assert lawagent.main(["--diff", IID, "--incoming", str(f)]) == 2
    out = capsys.readouterr().out
    assert "[SKIP]" in out and "REGKB_CHANGE_LOOP=1" in out
    assert not (tmp_path / "clidata" / "regkb").exists()


def test_cli_diff_of_an_unchanged_text_needs_no_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _cli_env(monkeypatch, tmp_path, loop=True)
    f = tmp_path / "same.txt"
    f.write_text(STORED.read_text(encoding="utf-8"), encoding="utf-8")
    out_json = tmp_path / "report.json"
    code = lawagent.main(["--diff", IID, "--incoming", str(f), "--out", str(out_json)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "46 unchanged, 0 changed, 0 added, 0 removed" in out and "model calls 0" in out
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["summary"]["drafts_made"] == 0
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    assert (data / "regkb" / "changes" / sha / IID / "diff.json").is_file()
    # a missing --incoming and a mock gateway are both refused with [FAIL]
    assert lawagent.main(["--diff", IID]) == 2
    g = tmp_path / "changed.txt"
    g.write_text(new_text_art5(), encoding="utf-8")
    capsys.readouterr()
    assert lawagent.main(["--diff", IID, "--incoming", str(g)]) == 2
    assert "mock_model" in capsys.readouterr().out
