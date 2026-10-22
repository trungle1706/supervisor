"""Guard model adapters (WP-D3): the three ways the ``guard_model`` detector reaches a model.

* :class:`MockGuardModel` - deterministic cue words, labelled mock, no network (tests, CI harness).
* :class:`ClassifierEndpointGuard` - ``POST <url>`` with ``{"inputs": [...]}`` (a Databricks
  serving endpoint that hosts a prompt-guard class model).
* :class:`ChatGuard` - an OpenAI-compatible chat model with a fixed classification prompt.

Port: ``supervisor.core.ports.GuardModelPort``. Factory: :func:`make_guard_model`.
"""

from __future__ import annotations

from supervisor.adapters.guard.chat import ChatGuard
from supervisor.adapters.guard.classifier_endpoint import ClassifierEndpointGuard
from supervisor.adapters.guard.factory import make_guard_model
from supervisor.adapters.guard.mock import MockGuardModel

__all__ = ["ChatGuard", "ClassifierEndpointGuard", "MockGuardModel", "make_guard_model"]
