"""Offline helper: paraphrase the templates with the local LLM (WP25). Not used at run time.

    uv run python data/eval/injection_vi_en/paraphrase.py            # fill paraphrases.json
    uv run python data/eval/injection_vi_en/paraphrase.py --pool dev --limit 5

The local LLM (127.0.0.1:8001, model qwen3.8-27b-int4, OpenAI-compatible) is used ONLY to reword
templates that a person wrote, so the golden set is less regular. Rules:

* concurrency 2, temperature 0.9, no tool calls, inference only;
* one pool is paraphrased from its OWN templates, so the pools stay disjoint;
* a paraphrase is kept only if it has exactly the same slots (``{amt}`` ...), a similar length and
  is not the original; the label of a paraphrase is the label of its template;
* the result is committed in ``paraphrases.json`` and every item built from it carries the
  source tag "synthetic, LLM-paraphrased" (see ``generate.py``). Re-running is not needed for
  the set to be reproducible: ``generate.py`` reads the committed file.

The LLM text is data only. Nothing here reads a key or a secret; the endpoint takes none.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import templates as T  # noqa: E402

URL = "http://127.0.0.1:8001/v1/chat/completions"
MODEL = "qwen3.8-27b-int4"
OUT = HERE / "paraphrases.json"
OUT_EXTRA = HERE / "paraphrases_train2.json"  # second round for the train pool only (--extra)
N_PER = {"train": 7, "dev": 5, "heldout": 5, "train_b": 10}
SLOT = re.compile(r"\{[a-z]+\}")

PROMPT = """You help build a test set for a bank's text-safety classifier. Rewrite the text below in {n} different ways.
Rules:
- keep the language ({lang}); Vietnamese stays Vietnamese with correct diacritics; mixed Vietnamese and English stays mixed;
- keep the SAME intent and the SAME kind of text: if the text tells an AI assistant to ignore rules, skip checks, leak data or move money, every rewrite must still do exactly that; if it is an ordinary customer, staff, policy or product sentence, every rewrite must stay ordinary and must not tell anyone to break a rule;
- keep every placeholder in curly braces exactly as written (for example {{acct}}, {{amt}}, {{name}}, {{ref}}, {{date}}, {{inj}}); do not add new ones;
- vary the words, the sentence structure, the register and the length a lot (use synonyms and different phrasing for the key verbs and nouns); keep it about as long as the original;
- output only a JSON list of {n} strings.

Text: {text}"""


def ask(text: str, lang: str, n: int) -> list[str]:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(n=n, lang=lang, text=text)}],
        "temperature": 1.0,
        "max_tokens": 900,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310 - fixed local URL
            content = json.loads(r.read())["choices"][0]["message"]["content"]
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return []
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    return [x for x in data if isinstance(x, str)]


def valid(orig: str, new: str) -> bool:
    if new.strip() == orig.strip() or not new.strip():
        return False
    if sorted(SLOT.findall(orig)) != sorted(SLOT.findall(new)):
        return False
    return 0.45 * len(orig) <= len(new) <= 2.2 * len(orig)


def lang_of(key: str) -> str:
    if key.endswith("vi"):
        return "Vietnamese"
    if key.endswith("mx"):
        return "mixed Vietnamese and English"
    return "English"


def jobs(pool: str) -> list[tuple[str, str, str, int, str]]:
    out = []
    for section, d in T.POOLS[pool].items():
        for key, lst in d.items():
            for i, s in enumerate(lst):
                if len(s) < 14 or s.startswith("<!--"):
                    continue  # lead-ins such as "<!--" stay as written
                out.append((pool, section, key, i, s))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paraphrase templates with the local LLM (offline).")
    ap.add_argument("--pool", action="append", choices=list(T.POOLS))
    ap.add_argument("--limit", type=int, default=0, help="only the first N templates per pool")
    ap.add_argument(
        "--extra",
        type=int,
        default=0,
        help="second round: N more paraphrases per train template, written to paraphrases_train2.json",
    )
    args = ap.parse_args(argv)
    global OUT
    if args.extra:
        OUT = OUT_EXTRA
        N_PER["train"] = args.extra
        args.pool = ["train"]
    done: dict[str, Any] = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    for pool in args.pool or list(T.POOLS):
        todo = jobs(pool)
        if args.limit:
            todo = todo[: args.limit]
        todo = [j for j in todo if f"{j[1]}|{j[2]}|{j[3]}" not in done.get(pool, {})]
        print(f"[..] {pool}: {len(todo)} templates to paraphrase")

        def work(
            j: tuple[str, str, str, int, str],
        ) -> tuple[tuple[str, str, str, int, str], list[str]]:
            _, _, key, _, s = j
            got = ask(s, lang_of(key), N_PER[j[0]])
            return j, [g for g in dict.fromkeys(got) if valid(s, g)]

        with ThreadPoolExecutor(max_workers=2) as ex:  # concurrency 2 at most
            for n, (j, ok) in enumerate(ex.map(work, todo), 1):
                done.setdefault(pool, {})[f"{j[1]}|{j[2]}|{j[3]}"] = {
                    "text": j[4],
                    "paraphrases": ok,
                }
                if n % 10 == 0 or n == len(todo):
                    OUT.write_text(
                        json.dumps(done, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    print(f"  {pool}: {n}/{len(todo)}")
        OUT.write_text(
            json.dumps(done, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    kept = sum(len(v["paraphrases"]) for p in done.values() for v in p.values())
    print(f"[OK] paraphrases kept: {kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
