"""File attachments as ``context.documents`` for the collectors (WP-D1, docs/collectors.md).

The Python SDK, the LangGraph middleware and the FastAPI middleware send the files a user attached
to the gate, when the switch is on. The switch is the environment variable
``DOCUMENT_INTAKE_ENABLED`` (1, true, yes, on) of the agent process, or
``set_document_intake(True)``. Off (the default): no document is built or sent, and the request
is exactly the one the collector sent before.

This module is standard library only and does not import the server side. It never reads a file
from disk by itself: the caller passes bytes, text, a URL or a ``pathlib.Path`` it chose.

Limits mirror the gate: at most 10 documents (an eleventh is sent so the gate can say
``document.limit_exceeded``), 2 MB each (a larger one is cut to 2 MB + 1 byte for the same reason;
nothing larger leaves the process).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import mimetypes
import os
from collections.abc import Mapping, Sequence
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

MAX_DOCUMENTS = 10
MAX_DOC_BYTES = 2 * 1024 * 1024
ALLOWED_KEYS = ("name", "media_type", "text", "bytes_b64", "url")

_B64_CAP = ((MAX_DOC_BYTES * 4) // 3 + 16) // 4 * 4  # a whole number of base64 groups
_override: bool | None = None


def set_document_intake(value: bool | None) -> None:
    """Force the switch for this process (None = read the environment again)."""
    global _override
    _override = value


def intake_on() -> bool:
    if _override is not None:
        return _override
    return os.environ.get("DOCUMENT_INTAKE_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data[: MAX_DOC_BYTES + 1]).decode("ascii")


def _one(item: Any) -> dict[str, Any] | None:
    """One attachment as a document dict, or None when it is not a form we know."""
    if isinstance(item, Mapping):
        doc = {k: item[k] for k in ALLOWED_KEYS if isinstance(item.get(k), str)}
        if isinstance(item.get("bytes"), bytes | bytearray):
            doc["bytes_b64"] = _b64(bytes(item["bytes"]))
        given = [k for k in ("text", "bytes_b64", "url") if k in doc]
        return doc if len(given) == 1 else None
    if isinstance(item, bytes | bytearray):
        return {"bytes_b64": _b64(bytes(item))}
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes | bytearray):
        guess = mimetypes.guess_type(str(item[0]))[0]
        return {
            "name": str(item[0])[:255],
            "bytes_b64": _b64(bytes(item[1])),
            **({"media_type": guess} if guess else {}),
        }
    if isinstance(item, os.PathLike):
        path = Path(item)
        try:
            with path.open("rb") as fh:
                data = fh.read(MAX_DOC_BYTES + 1)
        except OSError:
            return None
        guess = mimetypes.guess_type(path.name)[0]
        return {
            "name": path.name[:255],
            "bytes_b64": _b64(data),
            **({"media_type": guess} if guess else {}),
        }
    return None


def to_documents(items: Sequence[Any] | None) -> list[dict[str, Any]]:
    """``context.documents`` from a list of attachments: dicts (``name``, ``media_type`` and one
    of ``text``, ``bytes_b64``, ``url``, or ``bytes``), bytes, ``(name, bytes)`` pairs and
    ``pathlib.Path`` objects. A form that is not one of these is skipped. Never raises."""
    out: list[dict[str, Any]] = []
    if not isinstance(items, list | tuple):
        return out
    for item in items:
        try:
            doc = _one(item)
        except Exception:  # noqa: BLE001 - a strange attachment is skipped, never an error
            doc = None
        if doc is not None:
            out.append(doc)
        if len(out) > MAX_DOCUMENTS:  # one more than the limit, so the gate can report it
            break
    return out


# ---------------------------------------------------------------------------- chat messages


def _data_url(url: str) -> tuple[str, str] | None:
    """(media type, base64) of a ``data:`` URL, else None."""
    if not url.startswith("data:") or ";base64," not in url:
        return None
    head, _, data = url.partition(";base64,")
    return head[5:], data


def _block_to_doc(block: Mapping[str, Any]) -> dict[str, Any] | None:
    """A chat content block (LangChain standard, Anthropic or OpenAI shape) as a document."""
    kind = block.get("type")
    name = block.get("filename") or block.get("name")
    media = block.get("mime_type") or block.get("media_type")
    data = block.get("base64") or (
        block.get("data") if block.get("source_type") == "base64" else None
    )
    url = block.get("url") if block.get("source_type") in (None, "url") else None
    source = block.get("source")
    if isinstance(source, Mapping):  # Anthropic: {"type": "document", "source": {...}}
        media = media or source.get("media_type")
        if source.get("type") == "base64":
            data = source.get("data")
        elif source.get("type") == "url":
            url = source.get("url")
        elif source.get("type") == "text":
            return {"text": str(source.get("data", "")), **({"name": name} if name else {})}
    if kind == "image_url":  # OpenAI: {"image_url": {"url": "data:image/png;base64,..."}}
        ref = block.get("image_url")
        ref = ref.get("url") if isinstance(ref, Mapping) else ref
        if isinstance(ref, str):
            parsed = _data_url(ref)
            if parsed:
                media, data = parsed
            else:
                url = ref
    elif kind not in ("file", "image", "document", "input_file"):
        return None
    doc: dict[str, Any] = {}
    if isinstance(name, str) and name:
        doc["name"] = name[:255]
    if isinstance(media, str) and media:
        doc["media_type"] = media
    if isinstance(data, str) and data:
        try:
            raw = base64.b64decode(data[:_B64_CAP], validate=False)
        except (binascii.Error, ValueError):
            return None
        doc["bytes_b64"] = _b64(raw)
    elif isinstance(url, str) and url:
        doc["url"] = url
    else:
        return None
    return doc


def documents_from_message(message: Any) -> list[dict[str, Any]]:
    """The attachments in the content blocks of one chat message (a dict or an object with a
    ``content`` attribute). Text blocks are not attachments."""
    content = (
        message.get("content")
        if isinstance(message, Mapping)
        else getattr(message, "content", None)
    )
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if isinstance(block, Mapping):
            try:
                doc = _block_to_doc(block)
            except Exception:  # noqa: BLE001
                doc = None
            if doc is not None:
                out.append(doc)
        if len(out) > MAX_DOCUMENTS:
            break
    return out


def latest_user_attachments(messages: Any) -> list[dict[str, Any]]:
    """The attachments of the newest human message in ``messages`` (oldest message first)."""
    if not isinstance(messages, list | tuple):
        return []
    for m in reversed(messages):
        kind = (
            m.get("type") or m.get("role") if isinstance(m, Mapping) else getattr(m, "type", None)
        )
        if kind in ("human", "user"):
            return documents_from_message(m)
    return []


# ---------------------------------------------------------------------------- multipart upload


def multipart_parts(content_type: str, body: bytes) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """(documents, text fields) of a ``multipart/form-data`` body. A part with a file name is a
    document; a part without one is a form field (kept as text, cut to 2000 characters)."""
    if not content_type.lower().startswith("multipart/"):
        return [], {}
    try:
        raw = b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n"
        msg = BytesParser(policy=policy.HTTP).parsebytes(raw + body)
        parts = list(msg.iter_parts()) if msg.is_multipart() else []
    except Exception:  # noqa: BLE001 - a body that does not parse is not an upload we can read
        return [], {}
    docs: list[dict[str, Any]] = []
    fields: dict[str, str] = {}
    for part in parts:
        with contextlib.suppress(Exception):  # a part we cannot read is left out
            data = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename is not None:
                docs.append(
                    {
                        "name": str(filename)[:255],
                        "media_type": part.get_content_type(),
                        "bytes_b64": _b64(bytes(data)),
                    }
                )
            else:
                label = str(
                    part.get_param("name", header="content-disposition") or f"field{len(fields)}"
                )
                fields[label[:64]] = bytes(data).decode("utf-8", "replace")[:2000]
        if len(docs) > MAX_DOCUMENTS:
            break
    return docs, fields
