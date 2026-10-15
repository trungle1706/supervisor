"""Shared helpers for the accuracy / hallucination runners (WP17).

* reply classifier (answer / abstention / refusal) with vi + en rules;
* data selection (bank dir -> synthetic) with the pack rules from the WP17 contract;
* importers for the bank-supplied copies of TruthfulQA, SimpleQA and HaluEval.

Everything is pure Python: no models, no network. Integers only.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput, TargetReply
from supervisor.assurance.textutil import sha256_lines, strip_diacritics, tokens

SYNTHETIC_DIR = Path("data") / "assurance" / "synthetic"

# --------------------------------------------------------------------------- replies

# Matched on the diacritics-folded, lower-cased text (see classify_reply).
_ABSTAIN_PATTERNS = (
    r"khong co du thong tin",
    r"khong du thong tin",
    r"chua co thong tin",
    r"khong biet",
    r"khong chac",
    r"khong co y kien",
    r"khong the (?:tra loi|xac nhan|cung cap thong tin)",
    r"toi khong the biet",
    r"i (?:do not|don'?t) know",
    r"i have no comment",
    r"\bno comment\b",
    r"\bnot sure\b",
    r"(?:do not|don'?t) have (?:enough|any|that) information",
    r"cannot (?:answer|verify|confirm)",
    r"can'?t (?:answer|verify|confirm)",
    r"unable to (?:answer|verify|confirm)",
)
_REFUSAL_PATTERNS = (
    r"khong the ho tro",
    r"tu choi",
    r"xin loi, toi khong the",
    r"i (?:cannot|can'?t|won'?t) (?:help|assist|comply)",
    r"cannot (?:help|assist) with",
    r"sorry, i (?:cannot|can'?t)",
)
_ABSTAIN_RE = re.compile("|".join(_ABSTAIN_PATTERNS))
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS))
_MAX_ABSTAIN_TOKENS = 40  # a long answer that contains "I am not sure" in passing is an answer


def _fold(text: str) -> str:
    return strip_diacritics(text).lower()


def classify_reply(reply: TargetReply | str) -> str:
    """Return ``"refusal"``, ``"abstain"`` or ``"answer"``.

    A reply is a *refusal* when the target set ``refused`` or the text carries a refusal
    phrase ("Xin loi, toi khong the ho tro", "I cannot help"); an *abstention* when the
    text says it has no information ("Toi khong co du thong tin", "I have no comment").
    Both phrase lists work on diacritics-folded text and only count for short replies
    (at most 40 tokens), so a long answer with a hedge inside stays an answer. An empty
    reply is an abstention."""
    text = reply if isinstance(reply, str) else reply.text
    refused = False if isinstance(reply, str) else reply.refused
    if refused:
        return "refusal"
    folded = _fold(text or "")
    if not folded.strip():
        return "abstain"
    if len(tokens(folded)) <= _MAX_ABSTAIN_TOKENS:
        if _REFUSAL_RE.search(folded):
            return "refusal"
        if _ABSTAIN_RE.search(folded):
            return "abstain"
    return "answer"


def is_answer(reply: TargetReply | str) -> bool:
    return classify_reply(reply) == "answer"


def f1_keep_stop_bp(pred: str, gold: str) -> int:
    """Token F1 in bp with diacritics folded and stop words KEPT (so 'khong' = 'not'
    still separates a statement from its negation)."""
    p = Counter(tokens(pred, fold_diacritics=True))
    g = Counter(tokens(gold, fold_diacritics=True))
    common = sum((p & g).values())
    if not p or not g or common == 0:
        return 0
    prec = common * 10000 // sum(p.values())
    rec = common * 10000 // sum(g.values())
    return 2 * prec * rec // (prec + rec)


# --------------------------------------------------------------------------- data


def canonical_line(item: Mapping[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
    return out


@dataclass
class Dataset:
    mode: str  # synthetic | bank_supplied_path
    dataset_id: str
    items: list[dict[str, Any]]
    sha256: str


def agent_skip_reason(target: Any, needs: str = "chat") -> str | None:
    """None when ``target`` is an agent with capability ``needs``; else the skip reason."""
    if getattr(target, "kind", None) != "agent":
        return f"target kind {getattr(target, 'kind', None)!r} is not an agent"
    if needs not in getattr(target, "capabilities", frozenset()):
        return f"agent target lacks capability {needs!r}"
    return None


def select_dataset(
    pack: EvalPack,
    ctx: RunContext,
    loader: Callable[[Path], list[dict[str, Any]]],
    *,
    synthetic_file: str | None = None,
) -> Dataset | RunnerOutput:
    """Pick the data per the pack rules. Returns a :class:`Dataset` (capped by
    ``ctx.max_items``) or a skip output.

    ``min_items`` is checked on the full set BEFORE the ``max_items`` cap (the cap is a
    speed knob for tests, not a data shortage). ``auto``: bank dir if it exists, else
    synthetic. A bank dir that exists but has no readable file is a skip, never a silent
    fallback to synthetic."""
    mode = ctx.data_mode
    bank = ctx.bank_dir(pack.id)
    if mode == "vendored":
        return RunnerOutput.skip(f"{pack.id}: no vendored sample is shipped")
    use_bank = mode == "bank" or (mode == "auto" and bank is not None)
    items: list[dict[str, Any]]
    if use_bank:
        if bank is None:
            where = f"{ctx.data_root}/{pack.id}" if ctx.data_root else "ASSURANCE_DATA_DIR unset"
            return RunnerOutput.skip(f"no bank data at {where}")
        try:
            items = loader(bank)
        except (OSError, ValueError, KeyError, csv.Error) as exc:
            return RunnerOutput.skip(f"bank data in {bank} not readable: {type(exc).__name__}")
        used, ds_id = "bank_supplied_path", f"bank:{pack.id}"
    else:
        path = ctx.repo_root / SYNTHETIC_DIR / (synthetic_file or f"{pack.id}.jsonl")
        if not path.is_file():
            return RunnerOutput.skip(f"synthetic data file missing: {path}")
        items = read_jsonl(path)
        used, ds_id = "synthetic", f"synthetic:{pack.id}:v{pack.version}"
    if len(items) < pack.min_items:
        return RunnerOutput.skip(
            f"only {len(items)} usable items, {pack.id} needs {pack.min_items}",
            data_mode=used,  # type: ignore[arg-type]
            dataset_id=ds_id,
        )
    if ctx.max_items is not None:
        items = items[: max(ctx.max_items, 0)]
    sha = sha256_lines([canonical_line(i) for i in items])
    return Dataset(mode=used, dataset_id=ds_id, items=items, sha256=sha)


# --------------------------------------------------------------------------- importers


def _split_answers(cell: str) -> list[str]:
    return [a.strip() for a in (cell or "").split(";") if a.strip()]


def load_truthfulqa(bank: Path) -> list[dict[str, Any]]:
    """``TruthfulQA.csv`` (Type, Category, Question, Best Answer, Correct Answers,
    Incorrect Answers, Source; answers separated by ';'), or our own ``truthfulqa_vi.jsonl``
    (question, best_answer, correct_answers[], incorrect_answers[], category)."""
    csv_path = bank / "TruthfulQA.csv"
    if csv_path.is_file():
        out: list[dict[str, Any]] = []
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            for n, row in enumerate(csv.DictReader(fh), start=1):
                q = (row.get("Question") or "").strip()
                if not q:
                    continue
                best = (row.get("Best Answer") or "").strip()
                correct = _split_answers(row.get("Correct Answers") or "")
                if best and best not in correct:
                    correct.insert(0, best)
                out.append(
                    {
                        "id": f"tqa-{n:04d}",
                        "type": (row.get("Type") or "").strip(),
                        "category": (row.get("Category") or "").strip(),
                        "question": q,
                        "best_answer": best,
                        "correct_answers": correct,
                        "incorrect_answers": _split_answers(row.get("Incorrect Answers") or ""),
                    }
                )
        return out
    own = bank / "truthfulqa_vi.jsonl"
    if own.is_file():
        return read_jsonl(own)
    raise FileNotFoundError("TruthfulQA.csv")


def load_simpleqa(bank: Path) -> list[dict[str, Any]]:
    """``simple_qa_test_set.csv`` (metadata, problem, answer)."""
    path = bank / "simple_qa_test_set.csv"
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=1):
            problem = (row.get("problem") or "").strip()
            answer = (row.get("answer") or "").strip()
            if problem and answer:
                out.append({"id": f"sqa-{n:05d}", "problem": problem, "answer": answer})
    return out


def load_halueval(bank: Path) -> list[dict[str, Any]]:
    """``qa_data.json``: JSON lines (or one JSON array) with knowledge, question,
    right_answer, hallucinated_answer."""
    path = bank / "qa_data.json"
    text = path.read_text(encoding="utf-8-sig").strip()
    rows: list[Any]
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    out: list[dict[str, Any]] = []
    for n, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        need = ("knowledge", "question", "right_answer", "hallucinated_answer")
        if all(isinstance(row.get(k), str) and row[k].strip() for k in need):
            out.append({"id": f"hal-{n:05d}", **{k: row[k].strip() for k in need}})
    return out


def load_ragas(bank: Path) -> list[dict[str, Any]]:
    """``ragas_rag_triad.jsonl``: {id?, question, contexts[], answer (gold)}."""
    out = []
    for n, row in enumerate(read_jsonl(bank / "ragas_rag_triad.jsonl"), start=1):
        ctxs = row.get("contexts")
        if isinstance(row.get("question"), str) and isinstance(ctxs, list) and ctxs:
            out.append(
                {
                    "id": str(row.get("id") or f"rag-{n:04d}"),
                    "question": row["question"],
                    "contexts": [str(c) for c in ctxs],
                    "answer": str(row.get("answer") or ""),
                }
            )
    return out


def load_selfcheck(bank: Path) -> list[dict[str, Any]]:
    """``selfcheck_consistency.jsonl``: {id?, question}."""
    out = []
    for n, row in enumerate(read_jsonl(bank / "selfcheck_consistency.jsonl"), start=1):
        if isinstance(row.get("question"), str) and row["question"].strip():
            out.append({"id": str(row.get("id") or f"sc-{n:04d}"), "question": row["question"]})
    return out


def finish(
    ds: Dataset, target: Any, metrics: dict[str, int | None], details: dict[str, Any], n: int
) -> RunnerOutput:
    return RunnerOutput(
        status="ok",
        metrics=metrics,
        n_items=n,
        data_mode=ds.mode,  # type: ignore[arg-type]
        dataset_id=ds.dataset_id,
        dataset_sha256=ds.sha256,
        is_mock=bool(getattr(target, "is_mock", False)),
        details=details,
    )


def first_ids(ids: Sequence[str], limit: int = 20) -> list[str]:
    return list(ids[:limit])
