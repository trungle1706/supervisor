"""Policy reload (WP-P2): read the policy folders again, deploy them, switch the gate to them.

``POST /gate/policy/reload`` (admin). A load or validation error changes nothing: the old policy
stays in force and the caller gets HTTP 400. The chain gets a ``policy_reload`` record with the old
and the new policy hash (hashes, counts and the person only).
"""

from __future__ import annotations

from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core.canonical import format_ts
from supervisor.core.errors import SupervisorError
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import (
    PolicyError,
    StorePolicyProvider,
    deploy_with_retry,
    load_policy_dirs,
)


class ReloadError(SupervisorError):
    """The policy could not be reloaded; the old policy is still in force (HTTP 400)."""


def reload_policy(gw: Gateway, principal: str) -> dict[str, Any]:
    provider = gw.policy
    if not isinstance(provider, StorePolicyProvider):
        raise ReloadError("policy reload needs the store policy provider")
    dirs = list(gw.policy_dirs) or [REPO_ROOT / "policies"]
    try:
        old = provider.current()
    except Exception as exc:  # noqa: BLE001
        raise ReloadError(f"the current policy cannot be read: {type(exc).__name__}") from exc
    try:
        new = load_policy_dirs(dirs)
    except (PolicyError, OSError, UnicodeDecodeError) as exc:
        raise ReloadError(f"policy not reloaded, the old policy stays: {exc}") from exc
    if provider.validator is not None:
        problems = provider.validator(new)
        if problems:
            raise ReloadError("policy not reloaded, the old policy stays: " + "; ".join(problems))
    state = gw.states.state
    for r in new.rules:  # a rule version already deployed with other content: refuse early
        row = state.get("rule", {"rule_id": r.id, "version": r.version})
        if row is not None and row["expression"] != r.model_dump(mode="json", by_alias=True):
            raise ReloadError(
                f"policy not reloaded, the old policy stays: rule {r.id} version {r.version} is "
                "already deployed with other content; bump the version"
            )
    try:
        counts = deploy_with_retry(new, state, gw.clock)
        current = provider.refresh()
    except Exception as exc:  # noqa: BLE001 - store outage: 400, never 500
        raise ReloadError(
            f"policy reload failed: {type(exc).__name__}; see the server log"
        ) from exc
    gw.states.invalidate()
    changed = old.policy_hash != current.policy_hash
    gw.evidence.record(
        "policy_reload",
        "policy",
        {
            "old_policy_hash": old.policy_hash,
            "new_policy_hash": current.policy_hash,
            "changed": changed,
            "folders": len(dirs),
            "rules": len(current.rules),
            "inserted": counts["inserted"],
            "retired": counts["retired"],
            "principal": principal,
            "ts": format_ts(gw.clock.now()),
        },
    )
    return {
        "changed": changed,
        "old_policy_hash": old.policy_hash,
        "policy_hash": current.policy_hash,
        "rules": len(current.rules),
        "folders": len(dirs),
    }
