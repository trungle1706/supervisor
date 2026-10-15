"""Health screen (WP12): the local preflight checks plus a plain summary of the setup.

Reuses ``supervisor.preflight``. Only checks that do not write run on a page view: the live
Databricks checks create and drop a probe table and write a probe file, so the screen points
at ``python -m supervisor.preflight`` for those. Every text passes ``preflight.scrub`` (no
token, no secret value is ever shown).
"""

from __future__ import annotations

import re
import time
from typing import Any

from supervisor import preflight
from supervisor.core.errors import ConfigError

STATUS_KIND = {"OK": "ok", "FAIL": "bad", "SKIP": "neutral"}
LLM_PROBE_TTL_S = 60
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")


def _clean(text: str) -> str:
    """preflight.scrub plus URL credentials (https://user:pass@host -> https://***@host)."""
    return _USERINFO.sub("***@", preflight.scrub(text or ""))


_probe: dict[str, Any] = {}


def _llm_check(settings: Any) -> preflight.Check:
    """The LLM endpoint probe (an HTTP GET, 3 s timeout), cached for a minute per URL so a
    page view does not call the endpoint every time."""
    key = str(getattr(settings, "llm_base_url", ""))
    hit = _probe.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < LLM_PROBE_TTL_S:
        return hit[1]
    check = preflight._check_llm(settings)
    _probe.clear()
    _probe[key] = (now, check)
    return check


def local_checks(settings: Any) -> list[preflight.Check]:
    checks = [preflight._check_python(), preflight._check_token(), preflight._check_truststore()]
    try:
        settings.data_dir  # noqa: B018 - settings already loaded by the app
    except ConfigError as exc:  # pragma: no cover - the app could not have started
        checks.append(preflight.Check("FAIL", "config", str(exc).splitlines()[0]))
        return checks
    checks.append(
        preflight.Check(
            "OK",
            "config",
            f"mode={settings.supervisor_mode} sql_backend={settings.effective_sql_backend}",
        )
    )
    checks.append(preflight._check_paths(settings))
    signer = preflight._check_signer_durable(settings)
    if signer is not None:
        checks.append(signer)
    checks.extend(preflight._check_extras())
    checks.append(_llm_check(settings))
    return checks


def _row(name: str, status: str, kind: str, detail: str = "", key: str = "") -> dict[str, Any]:
    """``key`` is a translated explanation; ``detail`` a literal value (scrubbed)."""
    return {
        "name": name,
        "status": status,
        "kind": kind,
        "detail": _clean(detail),
        "key": key,
        "last_anchor": None,
    }


def summary(ctx: Any) -> list[dict[str, Any]]:
    """Plain rows a reviewer understands: mode, identity, judges, key, anchor, Databricks."""
    s = ctx.settings
    rows = []
    store = "SQLite" if s.effective_sql_backend == "sqlite" else "Delta (SQL warehouse)"
    rows.append(
        _row(
            "h_mode",
            s.supervisor_mode,
            "info",
            store,
            key="h_mode_sched_on" if s.scheduler_on else "h_mode_sched_off",
        )
    )
    if ctx.provider.name == "dev_header":
        rows.append(_row("h_identity", "dev users file", "warn", key="h_identity_dev"))
    else:
        rows.append(_row("h_identity", "workspace SSO", "ok", key="h_identity_sso"))
    if getattr(s, "judge_t1_model", ""):
        fam = getattr(s, "judge_t1_family", None) or "-"
        status = "on" if s.judge_enabled else "off"
        rows.append(
            _row(
                "h_judge",
                status,
                "ok" if s.judge_enabled else "neutral",
                f"{s.judge_t1_model} ({fam}) · advisory only",
            )
        )
    else:
        rows.append(_row("h_judge", "mock", "warn", key="h_judge_mock"))
    sigs = ctx.tables.query("chain_signature", {"lane": "root"}, order_by=("-seq",), limit=1)
    kind = sigs[0]["key_kind"] if sigs else ("managed" if s.signer_key_managed else "dev")
    rows.append(
        _row(
            "h_key",
            f"{kind} key",
            "ok" if kind == "managed" else "warn",
            f"SIGNER_KIND={s.signer_kind}",
            key="h_key_managed" if kind == "managed" else "h_key_dev",
        )
    )
    anchors = ctx.tables.query("anchor", None, order_by=("-anchored_at",), limit=1)
    target = "write-once folder" if s.anchor_kind == "worm_dir" else "UC Volume"
    last = anchors[0]["anchored_at"] if anchors else None
    row = _row("h_anchor", target, "ok" if last else "neutral", key="" if last else "h_no_anchor")
    row["last_anchor"] = last
    rows.append(row)
    if preflight.databricks_wanted(s):
        rows.append(_row("h_databricks", "in use", "info", key="h_databricks_in_use"))
    else:
        rows.append(_row("h_databricks", "not in use", "neutral", key="h_databricks_off"))
    rows.append(
        _row(
            "h_onboard",
            "on" if s.console_onboard_enabled else "off",
            "ok" if s.console_onboard_enabled else "neutral",
            key="h_onboard_detail",
        )
    )
    return rows


def health(ctx: Any) -> dict[str, Any]:
    checks = local_checks(ctx.settings)
    return {
        "summary": summary(ctx),
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "kind": STATUS_KIND.get(c.status, "neutral"),
                "detail": _clean(c.detail),
                "fix": _clean(c.fix) if c.status != "OK" else "",
            }
            for c in checks
        ],
        "failed": sum(1 for c in checks if c.status == "FAIL"),
        "databricks": preflight.databricks_wanted(ctx.settings),
    }
