"""Build the guard model port from settings (WP-D3).

Rules kept here:

* A URL that is not loopback needs ``LLM_ALLOW_REMOTE=1``, unless it is the workspace's own
  serving endpoint in ``databricks_app`` mode (reached with the App's identity). Same rule as
  ``LLM_BASE_URL`` and the judge URLs (zero AI egress).
* The ``chat`` adapter obeys the judge family rule: the family is derived from the model id
  (``judge.family.resolve_family``), it must be known, and it must differ from the family of every
  agent in the committed manifests and the registry.
* ``LLM_MOCK=1`` or ``GUARD_MODEL_ADAPTER=mock`` gives the labelled mock. ``auto`` without a URL
  gives the mock too.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.adapters.guard.chat import ChatGuard
from supervisor.adapters.guard.classifier_endpoint import ClassifierEndpointGuard
from supervisor.adapters.guard.mock import MockGuardModel
from supervisor.config import Settings, is_loopback_url
from supervisor.core.errors import ConfigError
from supervisor.core.ports import GuardModelPort, StateStore

log = logging.getLogger(__name__)


def check_remote(settings: Settings, url: str, setting: str) -> None:
    ok = is_loopback_url(url) or settings.llm_allow_remote or _is_workspace_url(settings, url)
    if not ok:
        raise ConfigError(
            f"{setting} must be a loopback address unless LLM_ALLOW_REMOTE=1 "
            "(zero AI egress house rule)"
        )


def _is_workspace_url(settings: Settings, url: str) -> bool:
    if settings.supervisor_mode != "databricks_app" or not settings.databricks_host:
        return False
    base = settings.serving_base_url.rstrip("/")
    if url.rstrip("/") == base or url.startswith(base + "/"):
        return True
    # WP-L1: the workspace AI Gateway (Unity Catalog model services) is also the workspace itself.
    return bool(settings.is_workspace_serving_url(url))


def check_guard_family(
    model_id: str, family: str, agent_families: Mapping[str, str | Iterable[str]]
) -> None:
    """The judge family rule for the guard chat model: known, and not the family of any agent."""
    from supervisor.judge.router import FamilyConflictError, normalize_family

    fam = normalize_family(family)
    if fam in ("", "unknown"):
        raise FamilyConflictError(
            f"guard model {model_id!r}: family unknown; use a model id that shows its family "
            "(the judge family rule applies to the guard chat model)"
        )
    problems = []
    for agent_id, fams in sorted(agent_families.items()):
        fam_set = {fams} if isinstance(fams, str) else set(fams)
        if fam in {normalize_family(f) for f in fam_set}:
            problems.append(
                f"guard model {model_id!r} is family {fam!r}, the same as agent {agent_id!r}"
            )
    if problems:
        raise FamilyConflictError(
            "guard model family must differ from the agent model family: " + "; ".join(problems)
        )


def _agent_families(state: StateStore | None) -> dict[str, set[str]]:
    from supervisor.judge.router import load_manifest_families, load_registry_families

    out: dict[str, set[str]] = {}
    for agent_id, fam in load_manifest_families().items():
        if fam:
            out.setdefault(agent_id, set()).add(fam)
    if state is not None:
        for agent_id, fams in load_registry_families(state, None).items():
            out.setdefault(agent_id, set()).update(fams)
    return out


def _workspace_headers(settings: Settings, client: Any = None) -> Any:
    if client is None:
        from supervisor.adapters.sql.databricks_rest import make_workspace_client

        client = make_workspace_client(settings)
    return client.config.authenticate


def make_guard_model(
    settings: Settings,
    *,
    state: StateStore | None = None,
    agent_families: Mapping[str, str | Iterable[str]] | None = None,
    transport: Any = None,
    client: Any = None,
) -> GuardModelPort:
    """The adapter the settings name. Raises ``ConfigError`` (and ``FamilyConflictError``, a
    ``ConfigError``) at start-up; never at call time."""
    kind = settings.guard_model_adapter
    url = settings.guard_model_url.strip()
    if kind == "auto":
        kind = "classifier" if url else "mock"
    if kind == "mock" or settings.llm_mock:
        return MockGuardModel()
    timeout_s = settings.guard_model_timeout_ms / 1000
    key = settings.guard_model_api_key.get_secret_value() if settings.guard_model_api_key else None
    if kind == "classifier":
        if not url:
            raise ConfigError("GUARD_MODEL_ADAPTER=classifier needs GUARD_MODEL_URL")
        check_remote(settings, url, "GUARD_MODEL_URL")
        headers = _workspace_headers(settings, client) if _is_workspace_url(settings, url) else None
        return ClassifierEndpointGuard(
            url,
            model_id=settings.guard_model_name,
            api_key=key,
            headers=headers,
            timeout_s=timeout_s,
            model_version=settings.guard_model_version,
            transport=transport,
        )
    # kind == "chat"
    model = settings.guard_model_name or settings.judge_t1_model
    base_url = url or settings.judge_t1_base_url or settings.llm_base_url
    if not model or not base_url:
        raise ConfigError("GUARD_MODEL_ADAPTER=chat needs GUARD_MODEL_NAME and a base URL")
    check_remote(settings, base_url, "GUARD_MODEL_URL")
    from supervisor.adapters.llm.openai_compatible import OpenAICompatibleChat
    from supervisor.judge.family import resolve_family

    secret = key
    if secret is None:
        # L1: a judge or LLM key goes only to the endpoint it belongs to, never to another URL
        norm = base_url.rstrip("/")
        for url_of, other in (
            (settings.judge_t1_base_url, settings.judge_api_key),
            (settings.llm_base_url, settings.llm_api_key),
        ):
            if other is not None and url_of and url_of.rstrip("/") == norm:
                secret = other.get_secret_value()
                break
    chat: Any
    if secret is None and _is_workspace_url(settings, base_url):
        # WP-L1: workspace endpoint or AI Gateway, authenticated as the App's own identity.
        from supervisor.databricks.serving import DatabricksServingChat

        chat = DatabricksServingChat(
            base_url,
            model,
            _workspace_headers(settings, client),
            timeout_s=timeout_s,
            max_tokens=64,
            strict_schema=settings.llm_strict_schema,
            send_temperature=settings.llm_send_temperature,
            api_shape=getattr(settings, "llm_api_shape", "chat"),
            transport=transport,
        )
    else:
        chat = OpenAICompatibleChat(
            base_url,
            model,
            api_key=secret,
            timeout_s=timeout_s,
            max_tokens=64,
            strict_schema=settings.llm_strict_schema,
            send_temperature=settings.llm_send_temperature,
            api_shape=getattr(settings, "llm_api_shape", "chat"),
            transport=transport,
        )
    try:
        chat.family, chat.family_source = resolve_family(
            "GUARD_MODEL_NAME",
            model,
            None,
            override_test_only=False,
            strict=True,
            endpoint_family=chat.endpoint_family() if settings.judge_family_probe else None,
        )
        families = dict(agent_families) if agent_families is not None else _agent_families(state)
        check_guard_family(model, chat.family, families)
    except BaseException:
        chat.close()
        raise
    return ChatGuard(chat, timeout_s=timeout_s, model_version=settings.guard_model_version)
