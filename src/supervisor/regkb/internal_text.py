"""Section splitter for internal documents (WP-W3). Pure functions, no file, no model.

    sections = split_sections(masked_text)

The input is the MASKED text of a policy, standard or procedure. The output is a list of
``Section`` with a 1-based ordinal ``n`` (stable for one text), the ``label`` the document uses
("Điều 5", "3.2", "Mục 2") and the section text. A model quote is checked against ``Section.text``.

Rules, in this order:

1. A line that starts a section (after white space is trimmed):
   * ``Điều N`` / ``Điều N.`` / ``Điều N:``   label ``Điều N``
   * ``Chương X``, ``Phần X``, ``Mục X``      label as written (``Mục 2``, ``Chương II``)
   * ``N.`` or ``N)`` followed by a word        label ``N``       (1 or 2 digits)
   * ``N.N``, ``N.N.N`` ... (up to 4 levels)    label ``N.N``     (1 or 2 digits per level)
   A bare number with no dot or bracket ("15 tháng") never starts a section.
2. The text before the first heading is the section ``Preamble`` when it has at least 120
   characters.
3. A section with no text besides its heading is dropped. A ``Chương``, ``Phần`` or ``Mục``
   section is dropped when the text under its heading has fewer than 60 characters (it only names
   a group of articles).
4. A section longer than ``MAX_SECTION_CHARS`` is cut at paragraph boundaries into parts; the
   parts keep the label and add ``(part 2)`` and so on.
5. Fallback: when fewer than two headings were found, the text is cut at blank lines into
   paragraph blocks; a block shorter than ``MIN_BLOCK_CHARS`` joins the next block; labels are
   ``P1``, ``P2``, ...

White space is folded to single spaces in ``Section.text`` (as the external mode does), so a quote
that differs only in line breaks still matches.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_SECTION_CHARS = 8000
MIN_PREAMBLE_CHARS = 120
MIN_CONTAINER_BODY = 60
MIN_BLOCK_CHARS = 80
MAX_SECTIONS = 300

_LEGAL = re.compile(
    r"^(?P<label>(?:Điều|ĐIỀU)\s+\d{1,3}|(?:Chương|CHƯƠNG|Phần|PHẦN|Mục|MỤC)\s+(?:\d{1,3}|[IVXLC]{1,6}))"
    r"\s*(?:[.:\-–]\s*|\s+|$)"
)
_DOTTED = re.compile(r"^(?P<label>\d{1,2}(?:\.\d{1,2}){1,3})\.?[\s)]+\S")
_SIMPLE = re.compile(r"^(?P<label>\d{1,2})[.)]\s+\S")


@dataclass(frozen=True)
class Section:
    n: int  # 1-based ordinal
    label: str  # "Điều 5", "3.2", "P4", "Preamble"
    heading: str  # first line of the section, white space folded
    text: str  # heading and body, white space folded: what a quote is checked against

    @property
    def ref(self) -> str:
        """The short pointer stored in ``regkb_draft.article``: S1, S2, ..."""
        return f"S{self.n}"


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def parse_ref(ref: str) -> int:
    """'S12' -> 12. Raises ValueError for anything else."""
    m = re.fullmatch(r"S(\d{1,4})", ref or "")
    if not m:
        raise ValueError(f"not a section reference: {ref!r}")
    return int(m.group(1))


def _heading_label(line: str) -> str | None:
    for rx in (_LEGAL, _DOTTED, _SIMPLE):
        m = rx.match(line)
        if m:
            return fold(m.group("label"))
    return None


def _cut(label: str, lines: list[str]) -> list[tuple[str, list[str]]]:
    """Rule 4: cut an over-long section at paragraph (line) boundaries."""
    total = sum(len(x) + 1 for x in lines)
    if total <= MAX_SECTION_CHARS:
        return [(label, lines)]
    parts: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) + 1 > MAX_SECTION_CHARS:
            parts.append((label, cur))
            cur, size = [], 0
        # a single line longer than the limit is cut hard
        while len(line) > MAX_SECTION_CHARS:
            parts.append((label, [line[:MAX_SECTION_CHARS]]))
            line = line[MAX_SECTION_CHARS:]
        cur.append(line)
        size += len(line) + 1
    if cur:
        parts.append((label, cur))
    return [
        (label if i == 0 else f"{label} (part {i + 1})", ls) for i, (label, ls) in enumerate(parts)
    ]


def _by_headings(lines: list[str]) -> list[tuple[str, list[str]]] | None:
    blocks: list[tuple[str, list[str]]] = []
    label = "Preamble"
    cur: list[str] = []
    found = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        head = _heading_label(line)
        if head is not None:
            found += 1
            blocks.append((label, cur))
            label, cur = head, [line]
        else:
            cur.append(line)
    blocks.append((label, cur))
    if found < 2:
        return None
    out: list[tuple[str, list[str]]] = []
    for lab, ls in blocks:
        if lab == "Preamble":
            if sum(len(x) for x in ls) >= MIN_PREAMBLE_CHARS:
                out.append((lab, ls))
        elif _is_container(lab):
            if sum(len(x) for x in ls[1:]) >= MIN_CONTAINER_BODY:
                out.append((lab, ls))
        elif len(ls) > 1 or _has_body(ls):
            out.append((lab, ls))
    return out


def _is_container(label: str) -> bool:
    """Chương, Phần and Mục only group articles; one with no real text of its own is dropped."""
    return label.split(" ", 1)[0].lower() in ("chương", "phần", "mục")


def _has_body(lines: list[str]) -> bool:
    """A heading line that also carries text ('1. Staff must log every change.') has a body."""
    first = lines[0]
    m = _LEGAL.match(first) or _DOTTED.match(first) or _SIMPLE.match(first)
    rest = first[m.end("label") :] if m else first
    return len(re.sub(r"^[\s.:\-–)]+", "", rest)) >= 25


def _paragraph_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[list[str]] = []
    cur: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            cur.append(raw.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    merged: list[list[str]] = []
    carry: list[str] = []
    for b in blocks:
        b = carry + b
        carry = []
        if sum(len(x) for x in b) < MIN_BLOCK_CHARS:
            carry = b
        else:
            merged.append(b)
    if carry:
        if merged:
            merged[-1] += carry
        else:
            merged.append(carry)
    return [(f"P{i}", b) for i, b in enumerate(merged, 1)]


def split_sections(text: str) -> list[Section]:
    """Cut the (masked) text of an internal document into sections. See the module doc."""
    lines = text.splitlines()
    blocks = _by_headings(lines)
    if blocks is None:
        blocks = _paragraph_blocks(text)
    out: list[Section] = []
    for label, ls in blocks:
        for lab, part in _cut(label, ls):
            body = fold("\n".join(part))
            if not body:
                continue
            out.append(Section(len(out) + 1, lab, fold(part[0])[:160], body))
            if len(out) >= MAX_SECTIONS:
                return out
    return out
