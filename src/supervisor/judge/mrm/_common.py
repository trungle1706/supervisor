"""Helpers shared by the model card and the validation report (WP19)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from supervisor.config import Settings
from supervisor.judge.masking import IdentityMasker, mask_version_of
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.mrm.identity import JudgeIdentity, identity_from_router
from supervisor.judge.router import JudgeRouter

MOCK_CHALLENGER_ID = "mock-judge-challenger-v1"


def parse_now(text: str | None) -> datetime | None:
    """ISO timestamp (naive means UTC) for the hidden ``--now`` option."""
    if not text:
        return None
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utc_now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)


def router_factory(
    settings: Settings, model: str = "mock", *, gullible: bool = False
) -> Callable[[], JudgeRouter]:
    """``mock`` builds mock judges (same ids as the default settings); ``settings`` uses
    the configured judges."""
    if model == "settings" and not gullible:
        return lambda: JudgeRouter.from_settings(settings)

    def build() -> JudgeRouter:
        chats = {
            "t1": MockJudgeChat(1, model_id="mock-judge-t1-v1", gullible=gullible),
            "t2": MockJudgeChat(2, model_id="mock-judge-t2-v1", gullible=gullible),
        }
        return JudgeRouter.from_settings(settings, chats=chats)

    return build


def mask_version(settings: Settings) -> str:
    from supervisor.adapters.factory import make_masker

    masker = make_masker(settings) or IdentityMasker()
    return mask_version_of(masker)


def identity_for(settings: Settings, router: JudgeRouter) -> JudgeIdentity:
    return identity_from_router(
        router,
        t1_threshold_bp=settings.judge_t1_threshold_bp,
        t2_threshold_bp=settings.judge_t2_threshold_bp,
        mask_version=mask_version(settings),
    )


def ascii_safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")
