"""Process bootstrap. Call :func:`bootstrap` first in every entry point.

The bank network re-signs HTTPS with a private CA that only the OS trust store
knows. ``truststore.inject_into_ssl()`` makes Python's ``ssl`` use that store.
It must run before any HTTPS client is created.
"""

from __future__ import annotations

import os
from pathlib import Path

_INJECTED = False


def _flag_from_env_file(name: str, env_file: Path) -> str | None:
    """Read one KEY=value line from a .env file without importing settings."""
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def truststore_requested() -> bool:
    """True when SSL_OS_TRUSTSTORE=1 is set in the environment or in ./.env."""
    value = os.environ.get("SSL_OS_TRUSTSTORE")
    if value is None:
        value = _flag_from_env_file("SSL_OS_TRUSTSTORE", Path.cwd() / ".env")
    return value == "1"


def inject_truststore() -> bool:
    """Inject the OS trust store into ``ssl`` once. Return True if injected."""
    global _INJECTED
    if _INJECTED:
        return True
    if not truststore_requested():
        return False
    import truststore

    truststore.inject_into_ssl()
    _INJECTED = True
    return True


def truststore_active() -> bool:
    return _INJECTED


def bootstrap() -> None:
    """Entry-point hook. Keep it cheap and free of side effects beyond SSL."""
    inject_truststore()
