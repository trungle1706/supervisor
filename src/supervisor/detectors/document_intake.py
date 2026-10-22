"""``document_intake``: what happened when the gate read the documents of a call (WP-D1).

The text of the documents is read BEFORE the detectors run (``detectors/intake.py``); this
detector reports the result. It looks at nothing itself (``parts = ()``): it reads
``meta.intake`` that the gate fills when ``DOCUMENT_INTAKE_ENABLED=1`` and the call carried
``context.documents``. Without that key it returns no finding, so a call without documents is
answered exactly as before.

Codes:

* ``document.uninspectable``: a document could not be read (image or scan, damaged, encrypted,
  unsupported type, too large, timeout, page not fetched). A fired finding per call, and one
  not-executed row (reason ``content_uninspectable``) for the documents that fail closed. On a
  money, credit or pii_export tool that row is the block ``GATE-DETECTOR-FAILED`` when
  ``fail_closed`` is true for this detector; otherwise it is only listed;
* ``document.limit_exceeded``: more than 10 documents or 10 unique URLs, or a document over 2 MB.
  The surplus is not read;
* ``url.ssrf_refused``: the link is not HTTPS or points inside (loopback, private, link-local,
  cloud metadata) or redirects to another host. Nothing was sent;
* ``url.domain_blocked``: the domain is not in ``URL_FETCH_ALLOWLIST``.

Every finding is report only (R1). No text, name or URL is in a finding.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    Entity,
    Finding,
    SettingsSchema,
    detector_id,
    threshold_for,
)
from supervisor.detectors.intake import (
    CODE_DOMAIN,
    CODE_LIMIT,
    CODE_SSRF,
    CODE_UNINSPECTABLE,
    reasons,
)

CODES: tuple[str, ...] = (CODE_UNINSPECTABLE, CODE_LIMIT, CODE_SSRF, CODE_DOMAIN)
# Frozen with the version string. Every finding scores 10000, so the preset never changes a result.
PRESETS: dict[str, int] = {"strict": 4_000, "balanced": 5_000, "lenient": 6_000}


class DocumentIntakeDetector:
    slug = "document_intake"
    name = "Document and URL intake"
    category = "content_security"
    deterministic = True  # rules and parsers, no model: its findings count in the session monitor
    version = "1.0.0"
    sides = ("input",)
    protocols = ("all",)
    parts: tuple[str, ...] = ()  # reads meta.intake, not a payload part
    presets = PRESETS
    settings_schema = SettingsSchema(())

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        meta = payload.get("meta") or {}
        intake = meta.get("intake") if isinstance(meta, Mapping) else None
        if not isinstance(intake, Mapping):
            return []
        events = [e for e in intake.get("events") or [] if isinstance(e, Mapping)]
        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        out: list[Finding] = []
        for code in CODES:
            n = sum(1 for e in events if e.get("code") == code)
            if n:
                out.append(
                    Finding(
                        detector_slug=self.slug,
                        detector_id=did,
                        code=code,
                        score_bp=10_000,
                        threshold_bp=threshold,
                        entities=(Entity("documents", None, n),),
                        action_hint="report",
                        detail=reasons(events, code),
                        preset=preset,
                    )
                )
        closing = int(intake.get("closing") or 0)
        why = reasons(events, CODE_UNINSPECTABLE, 2) or reasons(events, CODE_LIMIT, 2)
        if closing:
            # The part of the documents nobody could read. One row for the call; the registry
            # fails the call closed on a risky tool when this detector is set fail_closed.
            out.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code="not_executed.content_uninspectable",
                    not_executed_reason="content_uninspectable",
                    detail=f"{closing} unread: {why}"[:80],
                    preset=preset,
                )
            )
        return out
