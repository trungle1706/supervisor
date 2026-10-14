"""Bank-integration stubs (WP11): SIEM, ITSM, pager, SCIM. All OFF by default.

Each module has a contract (``docs/bank-integration.md``: fields, direction, auth
placeholder, retry policy, what the bank owner must provide), an adapter that is safe to
ship (file sink, in-memory fakes) and tests. Nothing here opens a network connection
unless the bank owner turns a transport on and fills in the FILL-ME values; the runtime
stays offline by default (CLAUDE.md).

Settings (environment or ``.env``; read by ``IntegrationSettings``, not by the core
``Settings``, so the core is unchanged while these are stubs):

=====================  =======  ==================================================
Variable               Default  Meaning
=====================  =======  ==================================================
SIEM_ENABLED           0        emit SIEM events from the evidence chain
SIEM_SINK              file     ``file`` (LogSiemSink) or ``webhook`` (HEC-style POST)
SIEM_FORMAT            json     ``json`` (one object per line) or ``cef``
SIEM_FILE_PATH         -        default ``<DATA_DIR>/siem/events.log``
SIEM_WEBHOOK_URL       -        FILL-ME; needs SIEM_SINK=webhook
ITSM_ENABLED           0        open / update tickets for cases (fake until wired)
PAGER_ENABLED          0        page on critical cases (fake until wired)
SCIM_ENABLED           0        group -> role report from a SCIM directory (fake)
=====================  =======  ==================================================
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic_settings import BaseSettings, SettingsConfigDict

from supervisor.config import env_file_path
from supervisor.core.errors import SupervisorError

T = TypeVar("T")


class IntegrationError(SupervisorError):
    """An integration call failed after its retries (HTTP 400 at the console)."""


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    siem_enabled: bool = False
    siem_sink: Literal["file", "webhook"] = "file"
    siem_format: Literal["json", "cef"] = "json"
    siem_file_path: Path | None = None
    siem_webhook_url: str = ""
    itsm_enabled: bool = False
    pager_enabled: bool = False
    scim_enabled: bool = False


def load_integration_settings(**overrides: object) -> IntegrationSettings:
    overrides.setdefault("_env_file", str(env_file_path()))
    return IntegrationSettings(**overrides)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry with exponential backoff. Contract default: 3 attempts, 1 s, 2 s."""

    attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0

    def delays(self) -> list[float]:
        return [min(self.base_delay_s * (2**i), self.max_delay_s) for i in range(self.attempts - 1)]


def with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    retry_on: tuple[type[BaseException], ...] = (OSError, TimeoutError, ConnectionError),
    sleep: Callable[[float], None] = time.sleep,
    what: str = "call",
) -> T:
    """Call ``fn``; retry on transport errors per ``policy``; raise IntegrationError."""
    last: BaseException | None = None
    delays = policy.delays()
    for attempt in range(policy.attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if attempt < len(delays):
                sleep(delays[attempt])
    raise IntegrationError(
        f"{what} failed after {policy.attempts} attempt(s): {type(last).__name__}: {last}"
    )


def is_placeholder(value: str | None) -> bool:
    return not value or not value.strip() or "FILL-ME" in value


__all__ = [
    "IntegrationError",
    "IntegrationSettings",
    "RetryPolicy",
    "is_placeholder",
    "load_integration_settings",
    "with_retry",
]
