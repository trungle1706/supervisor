from __future__ import annotations

import io
import json
import logging

import pytest

from supervisor.config import load_settings
from supervisor.ops import logging_setup as L

PII = "goi 0912345678, CCCD 079123456789, mail nguyen.van@example.com"
RAW = ("0912345678", "079123456789", "nguyen.van@example.com")


@pytest.fixture
def restore_root():
    root = logging.getLogger()
    old_level, old = root.level, list(root.handlers)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in old:
        root.addHandler(h)
    root.setLevel(old_level)


def _capture(settings):
    L.configure_logging(settings)
    root = logging.getLogger()
    h = next(h for h in root.handlers if getattr(h, "_sv_ops_handler", False))
    buf = io.StringIO()
    h.setStream(buf)
    return buf


def test_json_line_has_context_and_scrubs(restore_root, tmp_path):
    buf = _capture(load_settings(log_format="json", log_level="INFO", data_dir=tmp_path))
    token = L.begin_request("req-abc12345")
    L.set_principal_id("alice@example.com")
    try:
        logging.getLogger("supervisor.t").info("hello %s", PII)
    finally:
        L.end_request(token)
    doc = json.loads(buf.getvalue().strip())
    assert doc["request_id"] == "req-abc12345"
    assert doc["principal_id"] == "alice@example.com"  # actor id is exempt
    assert doc["level"] == "INFO" and doc["logger"] == "supervisor.t"
    assert doc["ts"].endswith("Z")
    for raw in RAW:
        assert raw not in doc["msg"]


def test_text_format_scrubs_and_keeps_shape(restore_root, tmp_path):
    buf = _capture(load_settings(log_format="text", data_dir=tmp_path))
    logging.getLogger("supervisor.t").warning("x " + PII)
    line = buf.getvalue()
    assert " WARNING supervisor.t: x " in line
    for raw in RAW:
        assert raw not in line


def test_exception_fields_and_scrub(restore_root, tmp_path):
    buf = _capture(load_settings(log_format="json", data_dir=tmp_path))
    try:
        raise ValueError("bad 0912345678")
    except ValueError:
        logging.getLogger("supervisor.t").exception("failed")
    doc = json.loads(buf.getvalue().strip())
    assert doc["exc_type"] == "ValueError"
    assert "0912345678" not in doc["exc"]


def test_level_respected_and_idempotent(restore_root, tmp_path):
    s = load_settings(log_level="WARNING", data_dir=tmp_path)
    L.configure_logging(s)
    L.configure_logging(s)
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert sum(getattr(h, "_sv_ops_handler", False) for h in root.handlers) == 1


def test_log_file_rotating_utf8(restore_root, tmp_path):
    f = tmp_path / "logs" / "sv.log"
    s = load_settings(log_format="json", log_file=f, data_dir=tmp_path)
    L.configure_logging(s)
    logging.getLogger("supervisor.t").warning("xin chào " + PII)
    for h in logging.getLogger().handlers:
        h.flush()
    text = f.read_text(encoding="utf-8")
    assert "xin chào" in text and "0912345678" not in text
