"""Benchmark packs and the runner of the guardian factory (WP-G2, docs/guardian-factory.md).

A pack lives in ``<DATA_DIR>/guardian_factory/<def_id>/bench/<pack_id>/``:

* ``attack.jsonl``  cases that must be caught: ``{case_id, stage, text | arguments, meta?,
  expected: true, label}``
* ``benign.jsonl``  cases that must pass: the same shape with ``expected: false``
* ``pack.json``     ``{id, version, def_id, origin, counts, files{name: {sha256, bytes}},
  pack_sha256, created_by, created_at}``

Every case of an upload or of a trace import goes through the masker; one that trips it refuses
the whole file (no personal data in a pack). The generator writes synthetic values only
(reserved fake blocks), so it skips that check and says so in ``origin``.

``run_benchmark`` builds the detector with ``adapter.build`` (no live-state check) for each
sensitivity level, runs every case of the definition's stage and counts true and false
positives. Rates are integer percent (true positive rate rounded down, false positive rate
rounded up: the report never flatters the guardian). Latency is integer microseconds. Nothing in
a result is a float or a piece of case text.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from supervisor.core.canonical import sha256_hex
from supervisor.factory.golden import CASE_ID_RE, trips_masker
from supervisor.guardian_factory import caps
from supervisor.guardian_factory.adapter import build
from supervisor.guardian_factory.benign_sample import benign_sample
from supervisor.guardian_factory.definition import (
    GuardianDefinition,
    GuardianFactoryError,
    est_tokens,
)
from supervisor.guardian_factory.patterns import LIBRARY, LibraryPattern

FILES = ("attack.jsonl", "benign.jsonl")
RESULT_SCHEMA = 1
LIVE_BY_STAGE = {
    "preflight": "injection_regex",
    "input": "injection_regex",
    "tool_call": "dlp_vn",
    "output": "dlp_vn",
}
_LIVE_KEY = b"guardian-bench-live-compare"


# ------------------------------------------------------------------------------ identity
def def_sha(body: Mapping[str, Any]) -> str:
    """SHA-256 of the definition without its lifecycle and its stamps. A pass of a benchmark
    counts only for the same hash; any other change of the definition sends the guardian back to
    draft."""
    keep = {
        k: v
        for k, v in body.items()
        if k not in ("lifecycle", "updated_at", "created_at", "created_by")
    }
    return sha256_hex(keep)


def pack_root(data_dir: Path | str, def_id: str) -> Path:
    if not caps.ID_RE.match(def_id):
        raise GuardianFactoryError("invalid_id", "guardian id: lower case letters, digits and -")
    return Path(data_dir) / "guardian_factory" / def_id / "bench"


def check_pack_id(pack_id: Any) -> str:
    if not isinstance(pack_id, str) or not caps.BENCH_PACK_RE.match(pack_id):
        raise GuardianFactoryError(
            "invalid_pack_id", "pack_id: lower case letters, digits, _ and - (max 64)"
        )
    return pack_id


# ------------------------------------------------------------------------------ case checks
@dataclass(frozen=True)
class Case:
    case_id: str
    stage: str
    expected: bool
    label: str
    text: str | None = None
    arguments: Mapping[str, Any] | None = None
    meta: Mapping[str, str] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """The payload a detector of the contract reads. Text goes where the stage reads it."""
        meta = {"agent_id": "bench", "tool_name": "bench", **self.meta}
        if self.stage == "output":
            return {"meta": meta, "output": self.text if self.text is not None else self.arguments}
        args = dict(self.arguments) if self.arguments is not None else {"text": self.text}
        return {"meta": meta, "args": args}

    def flat_text(self) -> str:
        return (
            self.text if self.text is not None else json.dumps(self.arguments, ensure_ascii=False)
        )

    def to_line(self) -> dict[str, Any]:
        out: dict[str, Any] = {"case_id": self.case_id, "stage": self.stage}
        if self.text is not None:
            out["text"] = self.text
        else:
            out["arguments"] = dict(self.arguments or {})
        if self.meta:
            out["meta"] = dict(self.meta)
        out["expected"] = self.expected
        out["label"] = self.label
        return out


@dataclass
class Pack:
    id: str
    attack: list[Case]
    benign: list[Case]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return str(self.meta.get("pack_sha256") or "")


def _line_problem(n: int, why: str) -> str:
    return f"line {n}: {why}"


def parse_jsonl(
    raw: bytes | str, expected: bool, *, check_masker: bool = True, name: str = "file"
) -> list[Case]:
    """The cases of one JSONL file. Any bad line refuses the file; the message names the first
    lines at fault."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > caps.BENCH_MAX_BYTES:
        raise GuardianFactoryError(
            "pack_too_large", f"{name}: larger than {caps.BENCH_MAX_BYTES // 1_000_000} MB"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise GuardianFactoryError("pack_invalid", f"{name}: must be UTF-8") from None
    cases: list[Case] = []
    problems: list[str] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if len(cases) + len(problems) >= caps.BENCH_MAX_CASES:
            raise GuardianFactoryError(
                "pack_too_large", f"{name}: more than {caps.BENCH_MAX_CASES} cases"
            )
        try:
            row = json.loads(line)
        except ValueError:
            problems.append(_line_problem(n, "not valid JSON"))
            continue
        why, case = _case_of(row, expected, seen, check_masker)
        if why:
            problems.append(_line_problem(n, why))
        elif case is not None:
            seen.add(case.case_id)
            cases.append(case)
    if problems:
        raise GuardianFactoryError(
            "pack_invalid",
            f"{name}: {len(problems)} bad line(s); " + "; ".join(problems[:5]),
            [{"field": name, "message": p} for p in problems[:20]],
        )
    return cases


def _case_of(
    row: Any, expected: bool, seen: set[str], check_masker: bool
) -> tuple[str, Case | None]:
    if not isinstance(row, dict):
        return "a case must be a JSON object", None
    extra = sorted(
        set(row) - {"case_id", "stage", "text", "arguments", "meta", "expected", "label"}
    )
    if extra:
        return f"unknown key: {', '.join(extra)}", None
    cid = row.get("case_id")
    if not isinstance(cid, str) or not CASE_ID_RE.match(cid):
        return "case_id: a short id (letters, digits, _ . -)", None
    if cid in seen:
        return f"case_id {cid} appears twice", None
    if row.get("stage") not in caps.STAGES:
        return f"stage: one of {', '.join(caps.STAGES)}", None
    if row.get("expected") is not expected:
        return f"expected: must be {str(expected).lower()} in this file", None
    label = row.get("label", "")
    if not isinstance(label, str) or len(label) > 64:
        return "label: text of at most 64 characters", None
    has_t, has_a = "text" in row, "arguments" in row
    if has_t == has_a:
        return "give text or arguments, not both and not neither", None
    text = row.get("text")
    args = row.get("arguments")
    if has_t and (not isinstance(text, str) or not text.strip()):
        return "text: a non-empty string", None
    if has_a and (not isinstance(args, dict) or not args):
        return "arguments: a non-empty object", None
    meta = row.get("meta", {})
    if not isinstance(meta, dict) or any(
        k not in caps.BENCH_META_KEYS or not isinstance(v, str) or len(v) > 64
        for k, v in meta.items()
    ):
        return f"meta: strings under {', '.join(caps.BENCH_META_KEYS)}", None
    case = Case(cid, row["stage"], expected, label, text, args, dict(meta))
    flat = case.flat_text()
    if len(flat) > caps.BENCH_TEXT_MAX:
        return f"the case is longer than {caps.BENCH_TEXT_MAX} characters", None
    if check_masker and trips_masker(flat):
        return "the case holds personal data (masker); use synthetic data only", None
    return "", case


# ------------------------------------------------------------------------------ store on disk
def _dump(cases: Iterable[Case]) -> bytes:
    return b"".join(
        (json.dumps(c.to_line(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for c in cases
    )


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_pack(
    data_dir: Path | str,
    def_id: str,
    pack_id: str,
    attack: Sequence[Case],
    benign: Sequence[Case],
    *,
    origin: str,
    actor: str,
    now: str,
) -> dict[str, Any]:
    """Store the two files and ``pack.json`` (version = previous version + 1). Returns pack.json."""
    check_pack_id(pack_id)
    folder = pack_root(data_dir, def_id) / pack_id
    prev = 0
    old = folder / "pack.json"
    if old.exists():
        try:
            prev = int(json.loads(old.read_text("utf-8")).get("version", 0))
        except (ValueError, OSError):
            prev = 0
    folder.mkdir(parents=True, exist_ok=True)
    blobs = {"attack.jsonl": _dump(attack), "benign.jsonl": _dump(benign)}
    files = {}
    for name, blob in blobs.items():
        _write_atomic(folder / name, blob)
        files[name] = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    meta = {
        "id": pack_id,
        "version": prev + 1,
        "def_id": def_id,
        "origin": origin,
        "counts": {"attack": len(attack), "benign": len(benign)},
        "files": files,
        "pack_sha256": hashlib.sha256(
            (files["attack.jsonl"]["sha256"] + ":" + files["benign.jsonl"]["sha256"]).encode()
        ).hexdigest(),
        "created_by": actor,
        "created_at": now,
    }
    _write_atomic(
        folder / "pack.json", (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode()
    )
    return meta


def list_packs(data_dir: Path | str, def_id: str) -> list[dict[str, Any]]:
    root = pack_root(data_dir, def_id)
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for p in sorted(root.iterdir()):
        f = p / "pack.json"
        if p.is_dir() and f.is_file():
            try:
                out.append(json.loads(f.read_text("utf-8")))
            except (ValueError, OSError):
                continue
    return out


def load_pack(data_dir: Path | str, def_id: str, pack_id: str) -> Pack:
    """The pack from disk. The files are checked against the hashes of ``pack.json``."""
    check_pack_id(pack_id)
    folder = pack_root(data_dir, def_id) / pack_id
    try:
        meta = json.loads((folder / "pack.json").read_text("utf-8"))
        blobs = {n: (folder / n).read_bytes() for n in FILES}
    except (OSError, ValueError):
        raise GuardianFactoryError("no_pack", f"pack {pack_id} does not exist") from None
    for n, blob in blobs.items():
        if hashlib.sha256(blob).hexdigest() != meta.get("files", {}).get(n, {}).get("sha256"):
            raise GuardianFactoryError(
                "pack_changed", f"pack {pack_id}: {n} does not match its sha"
            )
    # the masker ran when the pack was written; it is not run again on every load
    attack = parse_jsonl(blobs["attack.jsonl"], True, check_masker=False, name="attack.jsonl")
    benign = parse_jsonl(blobs["benign.jsonl"], False, check_masker=False, name="benign.jsonl")
    return Pack(pack_id, attack, benign, meta)


# ------------------------------------------------------------------------------ generator
# Fake blocks only: card BIN 97041 + zeros-free digits from a hash, ids that start with 0, phone
# prefixes of the real ranges followed by hash digits. No value is taken from a person.
def _digits(seed: str, n: int) -> str:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    s = str(h)
    while len(s) < n + 1:
        h //= 7
        s += str(h)
    return s[1 : n + 1]


def _fake(entry: LibraryPattern, i: int) -> str:
    d = lambda n: _digits(f"{entry.id}:{i}", n)  # noqa: E731
    if entry.id == "card_number":
        return "97041" + d(11)
    if entry.id == "cccd":
        return "0" + d(11)
    if entry.id == "phone_vn":
        pre = ("+84", "0")[i % 2]
        return pre + "35789"[i % 5] + d(8)
    if entry.id == "amount_vnd":
        n = (int(d(4)) % 900 + 100) * 1000 * (1 + i % 7)
        txt = f"{n:,}".replace(",", ".")
        return txt + (" đồng", " VND", "đ")[i % 3]
    return d(9 + i % 6)  # account_number: 9 to 14 digits


def _near_miss(entry: LibraryPattern, i: int) -> str:
    d = lambda n: _digits(f"miss:{entry.id}:{i}", n)  # noqa: E731
    if entry.id == "card_number":
        return d(15) if i % 2 else d(17)
    if entry.id == "cccd":
        return "0" + d(10) if i % 2 else "1" + d(11)
    if entry.id == "phone_vn":
        return "0" + d(8)
    if entry.id == "amount_vnd":
        return str(int(d(6)) + 1000) + " đồng"
    return d(8) if i % 2 else d(15)


_ATTACK_TEMPLATES = (
    "Vui lòng chuyển khoản vào {v} trước ngày {d}/{m}.",
    "Khách hàng cung cấp thông tin {v} qua điện thoại.",
    "Please confirm the value {v} before the payment is released.",
    "Ghi chú hồ sơ: {v}, đã kiểm tra lúc {h}:{mi}.",
    "Tool argument note={v} for request number {n}.",
)
_MISS_TEMPLATES = (
    "Mã tham chiếu {v} của hồ sơ số {n}.",
    "Reference code {v} was printed on the receipt.",
    "Số lô {v} trong báo cáo ngày {d}/{m}.",
)


def _fill(tpl: str, v: str, i: int) -> str:
    return tpl.format(
        v=v, d=i % 28 + 1, m=i % 12 + 1, h=i % 24, mi=f"{(i * 7) % 60:02d}", n=i + 100
    )


def library_entry_for(d: GuardianDefinition) -> LibraryPattern | None:
    if d.type != "regex":
        return None
    return next((e for e in LIBRARY if e.pattern == d.config.get("pattern")), None)


def generate_cases(d: GuardianDefinition) -> tuple[list[Case], list[Case]]:
    """(attack, benign) for a regex of the pattern library or a keyword list. Synthetic
    Vietnamese; no model. Anything else is refused with a message."""
    n_att = caps.BENCH_GENERATED_ATTACK
    attack: list[Case] = []
    benign: list[Case] = []
    extra_benign: list[str] = []
    if d.type == "keyword_list":
        words = [str(w) for w in d.config.get("words") or []]
        values = [words[i % len(words)] for i in range(n_att)]
        label = "keyword"
    elif (entry := library_entry_for(d)) is not None:
        values = [_fake(entry, i) for i in range(n_att)]
        label = entry.id
        extra_benign = [_fill(_MISS_TEMPLATES[i % 3], _near_miss(entry, i), i) for i in range(20)]
    else:
        raise GuardianFactoryError(
            "generator_unsupported",
            "the starter pack is made for a keyword list or for a regex of the pattern library "
            "(card_number, cccd, phone_vn, amount_vnd, account_number); upload a pack instead",
        )
    for i, v in enumerate(values):
        tpl = _ATTACK_TEMPLATES[i % len(_ATTACK_TEMPLATES)]
        attack.append(Case(f"att-{i + 1:03d}", d.stage, True, label, _fill(tpl, v, i)))
    for i, t in enumerate(benign_sample() + extra_benign):
        benign.append(Case(f"ben-{i + 1:03d}", d.stage, False, "benign", t))
    return attack, benign


# ------------------------------------------------------------------------------ trace import
def trace_cases(
    tables: Any, d: GuardianDefinition, limit: int = caps.BENCH_TRACE_SAMPLE_MAX
) -> tuple[list[Case], dict[str, int]]:
    """Benign cases from the stored, masked gate traces (``agent_event``) of the agents and tools
    in the scope of the definition: at most ``limit`` (and at most 2,000), evenly spaced over the
    rows sorted by event id so the same traces give the same sample. A text that still trips the
    masker is dropped, never stored."""
    limit = max(1, min(int(limit), caps.BENCH_TRACE_SAMPLE_MAX))
    agents = d.scope.agents
    rows: list[Mapping[str, Any]] = []
    for etype in ("gate_decision", "tool_call"):  # the stored gate traces
        where: dict[str, Any] = {"event_type": etype}
        for a in [None] if agents == "*" else list(agents):
            w = where if a is None else {**where, "agent_id": a}
            rows += list(tables.query("agent_event", w, order_by=("event_id",), limit=20_000))
    col = "result_masked" if d.stage == "output" else "args_masked"
    pool: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for r in sorted(rows, key=lambda r: str(r["event_id"])):
        text = str(r.get(col) or "").strip()
        tool = str(r.get("tool_name") or "")
        if not text or len(text) > caps.BENCH_TEXT_MAX or text in seen:
            continue
        if d.scope.tools != "*" and tool not in d.scope.tools:
            continue
        seen.add(text)
        pool.append((str(r["event_id"]), str(r["agent_id"]), tool, text))
    # evenly spaced over the sorted pool: the same traces always give the same sample
    chosen = pool if len(pool) <= limit else [pool[i * len(pool) // limit] for i in range(limit)]
    cases: list[Case] = []
    dropped = 0
    for eid, agent, tool, text in chosen:
        if trips_masker(text):
            dropped += 1
            continue
        meta = {"agent_id": agent[:64]}
        if tool:
            meta["tool_name"] = tool[:64]
        cases.append(Case("trace-" + eid[-24:], d.stage, False, "trace", text, None, meta))
    return cases, {"traces": len(pool), "sampled": len(chosen), "dropped_masker": dropped}


# ------------------------------------------------------------------------------ the runner
def pct_down(num: int, den: int) -> int:
    return 0 if den <= 0 else (num * 100) // den


def pct_up(num: int, den: int) -> int:
    return 0 if den <= 0 else -((-num * 100) // den)


def percentile(sorted_vals: Sequence[int], p: int) -> int:
    """Nearest-rank percentile of integers (p in 1..100); 0 for no values."""
    if not sorted_vals:
        return 0
    rank = -(-p * len(sorted_vals) // 100)
    return int(sorted_vals[max(0, min(len(sorted_vals) - 1, rank - 1))])


@dataclass
class BenchResult:
    data: dict[str, Any]

    @property
    def gate(self) -> str:
        return str(self.data["gate"]["verdict"])

    @property
    def failing(self) -> list[str]:
        return list(self.data["gate"]["failing"])

    def to_dict(self) -> dict[str, Any]:
        return self.data


def live_detector(slug: str) -> Any:
    """A catalogue detector for the comparison row (the masker only finds spans)."""
    from supervisor.adapters.masking.vn_regex import VnRegexMasker

    m = VnRegexMasker(_LIVE_KEY)
    if slug == "dlp_vn":
        from supervisor.detectors.dlp_vn import DlpVnDetector

        return DlpVnDetector(m)
    if slug == "injection_regex":
        from supervisor.detectors.injection_regex import InjectionRegexDetector

        return InjectionRegexDetector(m)
    raise GuardianFactoryError("bad_compare_with", f"compare_with: unknown detector {slug}")


def default_live(d: GuardianDefinition) -> str:
    """The live detector shown beside the benchmark: ``compare_with`` of the definition, else
    the catalogue detector closest to the stage; none for a policy (no catalogue detector reads
    its conditions)."""
    if d.compare_with == "none":
        return ""
    if d.compare_with:
        return d.compare_with
    return "" if d.type == "policy" else LIVE_BY_STAGE[d.stage]


def _fired(findings: Iterable[Any]) -> bool:
    return any(f.not_executed_reason is None and f.fired for f in findings)


def _confusion(
    detect: Callable[[Case], list[Any]],
    cases_attack: Sequence[Case],
    cases_benign: Sequence[Case],
    timer: Callable[[], int],
) -> dict[str, Any]:
    tp = fn = fp = tn = skipped = 0
    lat: list[int] = []
    for expected, cases in ((True, cases_attack), (False, cases_benign)):
        for c in cases:
            t0 = timer()
            out = detect(c)
            lat.append(max(0, (timer() - t0) // 1000))
            skipped += sum(1 for f in out if f.not_executed_reason is not None)
            hit = _fired(out)
            if expected:
                tp, fn = (tp + 1, fn) if hit else (tp, fn + 1)
            else:
                fp, tn = (fp + 1, tn) if hit else (fp, tn + 1)
    lat.sort()
    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "tpr_pct": pct_down(tp, tp + fn),
        "fpr_pct": pct_up(fp, fp + tn),
        "p50_us": percentile(lat, 50),
        "p95_us": percentile(lat, 95),
        "not_executed": skipped,
    }


def run_benchmark(
    definition: GuardianDefinition,
    pack: Pack,
    sensitivities: Sequence[int] = (1, 2, 3, 4),
    live: Any = None,
    *,
    chat: Any = None,
    masker: Any = None,
    delegates: Mapping[str, Any] | None = None,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> BenchResult:
    """Run the pack against the definition at each sensitivity level and against the live
    detector of the same stage. ``live`` is None (by ``compare_with`` and the stage), a catalogue
    slug, ``""`` for no live row, or a detector object. The gate is read at the sensitivity the
    definition names."""
    d = definition
    for s in sensitivities:
        if not isinstance(s, int) or not caps.SENSITIVITY_MIN <= s <= caps.SENSITIVITY_MAX:
            raise GuardianFactoryError("bad_sensitivity", "sensitivity: whole numbers 1 to 4")
    attack = [c for c in pack.attack if c.stage == d.stage]
    benign = [c for c in pack.benign if c.stage == d.stage]
    other = len(pack.attack) + len(pack.benign) - len(attack) - len(benign)
    if not attack or not benign:
        raise GuardianFactoryError(
            "pack_empty",
            f"the pack needs at least one attack case and one benign case of stage {d.stage}",
        )
    model_type = d.type in caps.MODEL_TYPES
    levels: list[dict[str, Any]] = []
    for s in sensitivities:
        ds = d.model_copy(update={"sensitivity": s})
        det = build(ds, delegates=delegates, chat=chat, masker=masker)
        row = _confusion(
            lambda c, det=det: det.evaluate(c.payload(), {}, _direction(d)), attack, benign, timer
        )
        row["sensitivity"] = s
        row["cost_tokens"] = (
            sum(
                est_tokens(str(d.config.get("prompt", "")) + c.flat_text()) for c in attack + benign
            )
            if d.type == "judge_prompt"
            else 0
        )
        levels.append(row)
    live_row = _live_row(d, live, attack, benign, timer)
    chosen = next((r for r in levels if r["sensitivity"] == d.sensitivity), None)
    gate = _gate(d, chosen)
    mock = bool(getattr(chat, "is_mock", False)) if model_type else False
    data = {
        "schema": RESULT_SCHEMA,
        "def_id": d.id,
        "version": d.lifecycle.version,
        "type": d.type,
        "stage": d.stage,
        "pack_id": pack.id,
        "pack_sha256": pack.sha256,
        "chosen_sensitivity": d.sensitivity,
        "counts": {"attack": len(attack), "benign": len(benign), "other_stage": other},
        "levels": levels,
        "live": live_row,
        "gate": gate,
        "advisory": model_type,
        "mock": mock,
    }
    return BenchResult(data)


def _direction(d: GuardianDefinition) -> str:
    return "output" if d.stage == "output" else "input"


def _live_row(
    d: GuardianDefinition,
    live: Any,
    attack: Sequence[Case],
    benign: Sequence[Case],
    timer: Callable[[], int],
) -> dict[str, Any] | None:
    if live is None:
        live = default_live(d)
    if live == "":
        return None
    det = live_detector(live) if isinstance(live, str) else live
    slug = str(getattr(det, "slug", live))
    settings = {"mode": "report"} if slug == "dlp_vn" else {}
    row = _confusion(
        lambda c: det.evaluate(c.payload(), settings, _direction(d)), attack, benign, timer
    )
    return {"slug": slug, **row}


def _gate(d: GuardianDefinition, chosen: Mapping[str, Any] | None) -> dict[str, Any]:
    th = d.thresholds
    limits = {
        "min_tpr_pct": th.min_tpr_pct,
        "max_fpr_pct": th.max_fpr_pct,
        "max_p95_ms": th.max_p95_ms,
    }
    if chosen is None:
        return {
            "verdict": "not_run",
            "failing": [],
            "thresholds": limits,
            "checked": {},
            "reason": f"sensitivity {d.sensitivity} was not run",
        }
    failing: list[str] = []
    if chosen["not_executed"]:
        failing.append("not_executed")
    if chosen["tpr_pct"] < th.min_tpr_pct:
        failing.append("min_tpr_pct")
    if chosen["fpr_pct"] > th.max_fpr_pct:
        failing.append("max_fpr_pct")
    if chosen["p95_us"] > th.max_p95_ms * 1000:
        failing.append("max_p95_ms")
    return {
        "verdict": "fail" if failing else "pass",
        "failing": failing,
        "thresholds": limits,
        "checked": {
            "tpr_pct": chosen["tpr_pct"],
            "fpr_pct": chosen["fpr_pct"],
            "p95_us": chosen["p95_us"],
        },
    }


# ------------------------------------------------------------------------------ runs table
RUNS = "guardian_bench_run"


def newest_run(state: Any, def_id: str, version: int) -> dict[str, Any] | None:
    """The newest finished-or-not run row of this version (by start time, then run id)."""
    rows = [dict(r) for r in state.query(RUNS, {"def_id": def_id}) if int(r["version"]) == version]
    rows.sort(key=lambda r: (str(r["started_at"]), str(r["run_id"])))
    return rows[-1] if rows else None
