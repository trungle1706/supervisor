"""Logging helpers: one rotating file log and one audit table."""
import logging
import logging.handlers
import sqlite3

LOG = logging.getLogger("support")
LOG.setLevel(logging.INFO)
LOG.addHandler(logging.handlers.RotatingFileHandler("support.log", maxBytes=1_000_000, backupCount=3))

AUDIT_DB = "audit.db"


def log_event(event: str, **fields) -> None:
    """Write one event with its fields to the log file."""
    LOG.info("%s %s", event, fields)


def audit(actor: str, action: str, detail: dict) -> None:
    """Append one row to audit_log."""
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(
        "INSERT INTO audit_log (actor, action, detail) VALUES (?, ?, ?)",
        (actor, action, str(detail)),
    )
    conn.commit()
    conn.close()
