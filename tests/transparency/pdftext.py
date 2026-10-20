"""Stdlib-only text layer of an fpdf2 PDF (Unicode TTF font with a ToUnicode CMap), for tests.

Not a general PDF reader: enough to grep what the transparency PDF prints (WP31 review)."""

from __future__ import annotations

import re
import zlib

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_ESC = {"n": b"\n", "r": b"\r", "t": b"\t", "b": b"\b", "f": b"\f", "(": b"(", ")": b")"}


def _streams(data: bytes) -> list[bytes]:
    out = []
    for m in _STREAM.finditer(data):
        try:
            out.append(zlib.decompress(m.group(1)))
        except zlib.error:
            out.append(m.group(1))
    return out


def _cmap(streams: list[bytes]) -> dict[int, str]:
    m: dict[int, str] = {}
    for s in streams:
        t = s.decode("latin-1")
        for block in re.findall(r"beginbfchar(.*?)endbfchar", t, re.S):
            for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                m[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be", "replace")
        for block in re.findall(r"beginbfrange(.*?)endbfrange", t, re.S):
            for a, b, c in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
            ):
                for i in range(int(a, 16), int(b, 16) + 1):
                    m[i] = chr(int(c, 16) + i - int(a, 16))
    return m


def _literal(lit: str, cmap: dict[int, str]) -> str:
    raw = bytearray()
    b = lit.encode("latin-1")
    i = 0
    while i < len(b):
        if b[i : i + 1] == b"\\" and i + 1 < len(b):
            n = chr(b[i + 1])
            if n in "01234567":
                j = i + 1
                while j < len(b) and j < i + 4 and chr(b[j]) in "01234567":
                    j += 1
                raw.append(int(b[i + 1 : j], 8))
                i = j
                continue
            raw += _ESC.get(n, n.encode("latin-1"))
            i += 2
            continue
        raw += b[i : i + 1]
        i += 1
    return "".join(
        cmap.get(int.from_bytes(raw[k : k + 2], "big"), "?") for k in range(0, len(raw) - 1, 2)
    )


def pdf_text(data: bytes) -> str:
    streams = _streams(data)
    cmap = _cmap(streams)
    lines = []
    for s in streams:
        if b"BT" not in s:
            continue
        for chunk in re.findall(r"BT(.*?)ET", s.decode("latin-1"), re.S):
            parts = [
                "".join(cmap.get(int(hx[i : i + 4], 16), "?") for i in range(0, len(hx), 4))
                for hx in re.findall(r"<([0-9A-Fa-f]+)>", chunk)
            ]
            parts += [_literal(x, cmap) for x in re.findall(r"\(((?:\\.|[^\\)])*)\)", chunk)]
            lines.append("".join(parts))
    return "\n".join(lines)
