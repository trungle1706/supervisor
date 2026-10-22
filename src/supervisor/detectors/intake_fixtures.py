"""Builders for synthetic test documents (WP-D1): a PDF, a DOCX and a PNG, in pure Python.

Used by the tests, the latency measurement and the intake harness, so none of them needs a binary
fixture file. The PDF holds Vietnamese text: every character gets a two byte code and a
``ToUnicode`` map, so a reader that extracts text (pypdf) gets the original characters back. The
text is drawn with a base font name only; the files are for parsers, not for the eye.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Sequence
from xml.sax.saxutils import escape


def simple_pdf(
    pages: Sequence[str], *, hidden: str | None = None, title: str | None = None
) -> bytes:
    """A PDF with one text line per ``\\n`` on each page. ``hidden`` is drawn in white on the
    first page (the white-on-white trick: it is text to a parser, invisible to a reader)."""
    alphabet = sorted({c for p in [*pages, hidden or ""] for c in p if c != "\n"})
    code = {c: i + 1 for i, c in enumerate(alphabet)}

    def hexline(line: str) -> str:
        return "<" + "".join(f"{code[c]:04X}" for c in line) + ">"

    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    cmap_lines = [f"<{code[c]:04X}> <{ord(c):04X}>" for c in alphabet] if alphabet else []
    chunks = ["\n".join(cmap_lines[i : i + 90]) for i in range(0, len(cmap_lines), 90)]
    bfchars = "".join(f"{len(c.splitlines())} beginbfchar\n{c}\nendbfchar\n" for c in chunks if c)
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
        f"{bfchars}endcmap CMapName currentdict /CMap defineresource pop end end\n"
    ).encode("ascii")
    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add(b"")  # 2: pages, filled below
    add(  # 3: the font
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Helvetica /Encoding /Identity-H "
        b"/DescendantFonts [4 0 R] /ToUnicode 5 0 R >>"
    )
    add(  # 4
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Helvetica "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>"
    )
    add(b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"endstream")  # 5
    kids: list[int] = []
    for n, page in enumerate(pages):
        ops = ["BT /F1 11 Tf 14 TL 40 780 Td"]
        for line in page.split("\n"):
            if line:
                ops.append(f"{hexline(line)} Tj")
            ops.append("T*")
        ops.append("ET")
        if hidden and n == 0:
            ops.append(f"q 1 1 1 rg BT /F1 8 Tf 40 20 Td {hexline(hidden)} Tj ET Q")
        stream = "\n".join(ops).encode("ascii")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(
            add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content
            )
        )
    objs[1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (
        len(kids),
        b" ".join(b"%d 0 R" % k for k in kids),
    )
    info = ""
    if title:
        info_id = add(
            b"<< /Title <FEFF" + title.encode("utf-16-be").hex().upper().encode() + b"> >>"
        )
        info = f" /Info {info_id} 0 R"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{info} >>\nstartxref\n{xref}\n%%EOF\n"
    out.write(trailer.encode())
    return out.getvalue()


def simple_docx(
    paragraphs: Sequence[str], *, header: str | None = None, hidden: str | None = None
) -> bytes:
    """A DOCX with one paragraph per item. ``hidden`` is a run marked ``w:vanish`` (hidden text
    in Word, still a ``w:t`` run for a parser)."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    if hidden:
        body += f"<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>{escape(hidden)}</w:t></w:r></w:p>"
    head = '<?xml version="1.0" encoding="UTF-8"?>'
    doc = f"{head}<w:document {ns}><w:body>{body}</w:body></w:document>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr("word/document.xml", doc)
        if header:
            hdr = (
                f'<?xml version="1.0"?><w:hdr {ns}><w:p><w:r><w:t>{escape(header)}</w:t></w:r>'
                "</w:p></w:hdr>"
            )
            z.writestr("word/header1.xml", hdr)
    return out.getvalue()


def tiny_png() -> bytes:
    """A valid 1x1 PNG (an image: uninspectable, no OCR)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )
