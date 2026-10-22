"""WP-D1: latency of the document intake (docs/latency.md, section "Document intake").

Run:  python -m tools.bench_documents                 # 100 KB of text in a PDF, a DOCX and a TXT
      python -m tools.bench_documents --kb 50 --runs 40

For each file kind it times, in integer microseconds (``time.perf_counter_ns``, nearest-rank
percentiles):

* extract: ``IntakeService.run`` (decode, unzip or parse the file, take the text);
* score: ``DetectorRegistry.run`` with ``dlp_vn`` and ``injection_regex`` on the extracted text,
  with the document budget (``document_max_scan_bytes``, default 256 KB) set to twice the
  document size, so nothing is cut;
* total: both.

Offline, no network, the synthetic text of the PII golden set. The PDF kind needs the extra
``documents`` (``pypdf``).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import time
from typing import Any

from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.config import REPO_ROOT
from supervisor.core.detectors import DetectorSetting, RunConfig
from supervisor.detectors import build_registry
from supervisor.detectors.intake import IntakeService
from supervisor.detectors.intake_fixtures import simple_docx, simple_pdf


def _text(kb: int) -> list[str]:
    """About ``kb`` KB of synthetic Vietnamese text in lines of about 100 characters."""
    src = [
        json.loads(x)["text"]
        for x in (REPO_ROOT / "data" / "eval" / "pii_vn" / "dev.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if x.strip()
    ]
    lines: list[str] = []
    size = 0
    i = 0
    while size < kb * 1024:
        line = src[i % len(src)]
        lines.append(line)
        size += len(line.encode("utf-8")) + 1
        i += 1
    return lines


def _pct(values: list[int], p: int) -> int:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered) / 100)) - 1]


def _cfg(limit: int) -> RunConfig:
    return RunConfig(
        detectors={
            "dlp_vn": DetectorSetting(True, {"preset": "balanced"}),
            "injection_regex": DetectorSetting(True, {"preset": "balanced"}),
        },
        timeout_ms=5000,
        document_max_scan_bytes=limit,
    )


def bench(kb: int, runs: int) -> list[dict[str, Any]]:
    lines = _text(kb)
    pages = ["\n".join(lines[i : i + 40]) for i in range(0, len(lines), 40)]
    kinds: dict[str, dict[str, Any]] = {
        "txt": {"name": "a.txt", "media_type": "text/plain", "text": "\n".join(lines)},
        "docx": {"name": "a.docx", "bytes_b64": base64.b64encode(simple_docx(lines)).decode()},
        "pdf": {"name": "a.pdf", "bytes_b64": base64.b64encode(simple_pdf(pages)).decode()},
    }
    masker = VnRegexMasker(b"bench-key", "bench")
    registry = build_registry(masker)
    limit = kb * 1024 * 2
    cfg = _cfg(limit)
    service = IntakeService()
    out = []
    for kind, doc in kinds.items():
        extract, score = [], []
        chars = 0
        for n in range(runs + 3):  # the first three runs are warm-up
            t0 = time.perf_counter_ns()
            res = service.run([doc])
            t1 = time.perf_counter_ns()
            if res.unread:
                out.append({"kind": kind, "error": res.meta[0].get("reason", "unread")})
                break
            payload = {"documents": res.documents, "meta": {"risk_class": "pii_export"}}
            registry.run(payload, "input", cfg, risk_class="pii_export")
            t2 = time.perf_counter_ns()
            chars = len(res.documents[0]["text"])
            if n >= 3:
                extract.append((t1 - t0) // 1000)
                score.append((t2 - t1) // 1000)
        else:
            total = [a + b for a, b in zip(extract, score, strict=True)]
            out.append(
                {
                    "kind": kind,
                    "file_bytes": len(base64.b64decode(doc["bytes_b64"]))
                    if "bytes_b64" in doc
                    else len(doc["text"].encode("utf-8")),
                    "text_chars": chars,
                    "runs": runs,
                    "extract_p50_us": _pct(extract, 50),
                    "extract_p95_us": _pct(extract, 95),
                    "score_p50_us": _pct(score, 50),
                    "score_p95_us": _pct(score, 95),
                    "total_p50_us": _pct(total, 50),
                    "total_p95_us": _pct(total, 95),
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.bench_documents", description=__doc__)
    ap.add_argument("--kb", type=int, default=100, help="size of the text in KB (default 100)")
    ap.add_argument("--runs", type=int, default=30, help="measured runs per kind (default 30)")
    args = ap.parse_args(argv)
    rows = bench(args.kb, args.runs)
    print(f"document intake, {args.kb} KB of text, {args.runs} runs, integer microseconds")
    print("kind   file_bytes  text_chars  extract p50/p95    score p50/p95      total p50/p95")
    for r in rows:
        if "error" in r:
            print(f"{r['kind']:<6} [SKIP] {r['error']}")
            continue
        print(
            f"{r['kind']:<6} {r['file_bytes']:>10}  {r['text_chars']:>10}  "
            f"{r['extract_p50_us']:>7}/{r['extract_p95_us']:<8}  "
            f"{r['score_p50_us']:>7}/{r['score_p95_us']:<8}  "
            f"{r['total_p50_us']:>7}/{r['total_p95_us']:<8}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
