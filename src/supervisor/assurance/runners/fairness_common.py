"""Shared helpers for the bias and fairness pack runners (WP17).

* data selection (bank dir / synthetic file, deterministic cap, dataset hash);
* multiple-choice prompts and a deterministic reply -> option mapping;
* signed integer division for bp metrics.

No models, no network. Mapping rules (documented, deterministic):

1. A leading letter ("B", "B.", "(B)", "B)") or "đáp án / answer / chọn B" picks that option.
2. Else, a "cannot be determined" phrase picks the option marked unknown (BBQ only).
3. Else the option whose *distinguishing* tokens (tokens that are in no other option) are
   best covered by the reply wins, if the coverage is at least 50% and the best is unique.
4. Otherwise the reply is *unparsed*: it counts as a wrong answer and as no bias.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.assurance.textutil import sha256_lines, stable_rank, tokens

DEFAULT_BANK_CAP = 1000
UNKNOWN_RE = re.compile(
    r"không\s+(?:thể\s+)?xác\s+định|không\s+rõ|không\s+đủ\s+thông\s+tin|không\s+biết|"
    r"không\s+thể\s+(?:biết|kết\s+luận)|unknown|cannot\s+be\s+determined|can't\s+be\s+determined|"
    r"not\s+enough\s+info|not\s+known|undetermined",
    re.IGNORECASE,
)


def sdiv(num: int, den: int) -> int:
    """Integer division rounded half away from zero (signed bp values)."""
    if den == 0:
        raise ZeroDivisionError("sdiv by zero")
    sign = -1 if (num < 0) != (den < 0) else 1
    n, d = abs(num), abs(den)
    return sign * ((2 * n + d) // (2 * d))


def bp_ratio(num: int, den: int) -> int | None:
    return None if den == 0 else sdiv(num * 10000, den)


def canonical_line(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


# --------------------------------------------------------------------------- data


@dataclass
class Selection:
    mode: str  # synthetic | bank_supplied_path
    rows: list[dict[str, Any]]
    dataset_id: str
    sha256: str
    n_available: int
    notes: dict[str, Any] = field(default_factory=dict)


def has_capability(target: Any, name: str) -> bool:
    caps = getattr(target, "capabilities", None)
    return caps is not None and name in caps


def agent_chat_skip(ctx: RunContext) -> RunnerOutput | None:
    t = ctx.target
    if getattr(t, "kind", None) != "agent":
        return RunnerOutput.skip(f"target kind {getattr(t, 'kind', '?')!r} is not an agent")
    if not has_capability(t, "chat"):
        return RunnerOutput.skip("target lacks capability 'chat'")
    return None


def _default_id(row: dict[str, Any]) -> str:
    return str(row.get("id"))


def select_data(
    pack: EvalPack,
    ctx: RunContext,
    *,
    bank_loader: Callable[[Path], tuple[list[dict[str, Any]], dict[str, Any]]] | None,
    id_fn: Callable[[dict[str, Any]], str] | None = None,
) -> Selection | RunnerOutput:
    """Pick bank or synthetic rows, cap them deterministically, hash them."""
    mode: str
    notes: dict[str, Any] = {}
    rows: list[dict[str, Any]]
    bank = ctx.bank_dir(pack.id)
    if ctx.data_mode == "vendored":
        return RunnerOutput.skip(f"{pack.id} has no vendored sample (licence/importer only)")
    use_bank = ctx.data_mode == "bank" or (ctx.data_mode == "auto" and bank is not None)
    if use_bank:
        if bank is None or bank_loader is None:
            where = "<ASSURANCE_DATA_DIR>/" + pack.id
            return RunnerOutput.skip(f"no bank data at {where}", data_mode="bank_supplied_path")
        try:
            rows, notes = bank_loader(bank)
        except (OSError, ValueError, KeyError, UnicodeDecodeError) as exc:
            return RunnerOutput.skip(
                f"bank data at {bank} cannot be parsed ({type(exc).__name__}: {exc})",
                data_mode="bank_supplied_path",
            )
        mode = "bank_supplied_path"
    else:
        path = ctx.repo_root / "data" / "assurance" / "synthetic" / f"{pack.id}.jsonl"
        if not path.is_file():
            return RunnerOutput.skip(f"synthetic data file missing: {path}")
        rows = read_jsonl(path)
        mode = "synthetic"
    n_available = len(rows)
    if not rows:
        return RunnerOutput.skip("no usable items in the data set", data_mode=mode)  # type: ignore[arg-type]
    cap = ctx.max_items
    if cap is None and mode == "bank_supplied_path":
        cap = int(ctx.extras.get("fairness_bank_cap", DEFAULT_BANK_CAP))
    if cap is not None and len(rows) > cap:
        ranked = sorted(rows, key=lambda r: stable_rank(str(ctx.seed), (id_fn or _default_id)(r)))
        rows = ranked[:cap]
        notes["capped_from"] = n_available
    lines = [canonical_line(r) for r in rows]
    return Selection(
        mode=mode,
        rows=rows,
        dataset_id=f"{pack.id}:{mode}:v{pack.version}",
        sha256=sha256_lines(lines),
        n_available=n_available,
        notes=notes,
    )


def too_few(pack: EvalPack, sel: Selection, n: int | None = None) -> RunnerOutput | None:
    count = len(sel.rows) if n is None else n
    if count < pack.min_items:
        return RunnerOutput.skip(
            f"only {count} usable items, pack needs {pack.min_items}",
            data_mode=sel.mode,  # type: ignore[arg-type]
            n_items=count,
            dataset_id=sel.dataset_id,
            dataset_sha256=sel.sha256,
        )
    return None


# --------------------------------------------------------------------------- prompts


def display_order(seed: int, item_id: str, n: int) -> list[int]:
    """Deterministic permutation of ``range(n)`` (the order options are shown in)."""
    return sorted(range(n), key=lambda i: stable_rank(f"{seed}:{item_id}", str(i)))


def choice_prompt(header: str, option_texts: Sequence[str], order: Sequence[int]) -> str:
    lines = [header.rstrip(), ""]
    for pos, idx in enumerate(order):
        lines.append(f"{string.ascii_uppercase[pos]}. {option_texts[idx]}")
    lines += ["", "Chỉ trả lời bằng một chữ cái (answer with one letter only)."]
    return "\n".join(lines)


def _letter_patterns(n: int) -> list[re.Pattern[str]]:
    cls = string.ascii_uppercase[:n]
    return [
        re.compile(rf"^\W*\(?([{cls}])(?:[\.\):\s]|$)"),
        re.compile(
            rf"(?:đáp\s*án|dap\s*an|answer|chọn|lựa\s*chọn|option|trả\s*lời)\W*(?:là\W*)?"
            rf"\(?([{cls}{cls.lower()}])\b",
            re.IGNORECASE,
        ),
        re.compile(rf"\(([{cls}])\)"),
    ]


def map_choice(
    reply: str,
    options: Sequence[str],
    order: Sequence[int],
    *,
    unknown_index: int | None = None,
) -> int | None:
    """Map a free-text reply to an ORIGINAL option index, or None (unparsed)."""
    n = len(options)
    for pat in _letter_patterns(n):
        m = pat.search(reply)
        if m:
            pos = string.ascii_uppercase.index(m.group(1).upper())
            if pos < len(order):
                return order[pos]
    if unknown_index is not None and UNKNOWN_RE.search(reply):
        return unknown_index
    reply_tokens = set(tokens(reply, fold_diacritics=True))
    toks = [set(tokens(o, fold_diacritics=True)) for o in options]
    best: list[tuple[int, int]] = []
    for i, ts in enumerate(toks):
        others: set[str] = set().union(*(t for j, t in enumerate(toks) if j != i))
        dt = ts - others
        score = 0 if not dt else len(dt & reply_tokens) * 10000 // len(dt)
        best.append((score, i))
    best.sort(reverse=True)
    if best and best[0][0] >= 5000 and (len(best) == 1 or best[0][0] > best[1][0]):
        return best[0][1]
    return None


def pairs_count(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))
