"""Lexical retriever (BM25 Okapi, standard library only) over the synthetic policy documents.

Pattern taken from the upstream (CampusAsk): chunk by section, keep title/section/page metadata,
BM25 over normalised tokens, cited answers. Here the tokens are Vietnamese syllables with the
diacritics folded, plus syllable bigrams (Vietnamese words are mostly two syllables).
No embeddings, no model download, no numpy.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

DOC_DIR = Path(__file__).resolve().parent / "policies_kb"
STOP = {"la", "va", "cua", "co", "cho", "the", "nao", "gi", "bao", "nhieu", "khong", "duoc", "nhu",
        "khi", "mot", "cac", "nhung", "toi", "minh", "em", "anh", "chi", "hay", "voi", "trong", "de", "thi"}


def fold(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", fold(text))]
    uni = [w for w in words if w not in STOP]
    bi = [f"{a}_{b}" for a, b in zip(words, words[1:]) if a not in STOP and b not in STOP]
    return uni + bi


class KnowledgeBase:
    def __init__(self, doc_dir: Path = DOC_DIR, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.chunks: list[dict] = []
        for path in sorted(Path(doc_dir).glob("*.md")):
            self._load(path)
        self._tf = [Counter(tokens(c["section"] + " " + c["text"])) for c in self.chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 1.0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def _load(self, path: Path) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ").strip()
        meta = lines[1] if len(lines) > 1 else ""
        code = meta.split("|")[0].replace("Mã:", "").strip() or path.stem
        section, buf = "", []

        def flush() -> None:
            if section and buf:
                self.chunks.append({"doc_id": code, "title": title, "section": section,
                                    "text": " ".join(buf).strip(), "file": path.name})

        for ln in lines[2:]:
            if ln.startswith("## "):
                flush()
                section, buf = ln[3:].strip(), []
            elif ln.strip():
                buf.append(ln.strip())
        flush()

    @property
    def doc_count(self) -> int:
        return len({c["doc_id"] for c in self.chunks})

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        q = tokens(query)
        top_k = max(1, min(int(top_k), 8))
        scored = []
        for i, tf in enumerate(self._tf):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                norm = f + self.k1 * (1 - self.b + self.b * self._len[i] / self._avg)
                s += self._idf.get(t, 0.0) * f * (self.k1 + 1) / norm
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        out = []
        for s, i in scored[:top_k]:
            c = dict(self.chunks[i])
            c["score"] = round(s, 3)
            out.append(c)
        return out
