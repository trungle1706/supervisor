"""Directory groups -> console roles (WP11 stub, OFF by default; Entra ID via SCIM).

Direction: bank directory (Entra ID) --SCIM--> Databricks workspace groups --> Supervisor
reads group membership. Supervisor never writes to the directory.

At request time the console already maps groups to roles (``config/auth.yaml``
``roles.<role>.groups`` with ``group_lookup: scim_me``, see
``adapters/auth/databricks_app.py``). This module is the offline contract and the review
report: given a directory snapshot, which user holds which role, and what is wrong.

Contract (``docs/bank-integration.md`` section SCIM):

* input: SCIM 2.0 ``Group`` resources (``displayName``, ``members[].value`` = user name /
  email), read with a read-only identity (``FILL-ME`` service principal, OAuth);
* mapping: ``config/auth.yaml`` roles -> group display names (FILL-ME until the bank
  names its groups; a FILL-ME group never matches);
* output: per-user roles, plus findings: unmapped roles, mapped groups missing in the
  directory, users who hold both ``reviewer`` and ``approver`` (allowed, but the two
  sign-offs must still come from two people), admins without a second admin;
* retry: ``RetryPolicy`` 3 attempts on the directory read; the report fails closed
  (no role is granted from a failed read).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from supervisor.adapters.integrations import RetryPolicy, is_placeholder, with_retry

ROLES = ("reviewer", "approver", "owner", "auditor", "admin")


class ScimDirectory(Protocol):
    def groups(self) -> Sequence[Mapping[str, Any]]:
        """SCIM Group resources: {"displayName": str, "members": [{"value": str}]}."""
        ...


@dataclass
class FakeScimDirectory:
    data: dict[str, list[str]] = field(default_factory=dict)  # group -> members
    fail_next: int = 0

    def groups(self) -> Sequence[Mapping[str, Any]]:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("fake directory unavailable")
        return [
            {"displayName": g, "members": [{"value": u} for u in members]}
            for g, members in sorted(self.data.items())
        ]


def load_role_groups(auth_yaml: Path) -> dict[str, list[str]]:
    doc = yaml.safe_load(Path(auth_yaml).read_text(encoding="utf-8")) or {}
    roles = doc.get("roles") or {}
    return {r: [str(g) for g in ((roles.get(r) or {}).get("groups") or [])] for r in ROLES}


@dataclass
class RoleReport:
    user_roles: dict[str, list[str]]
    findings: list[str]

    @property
    def ok(self) -> bool:
        return not self.findings


def role_report(
    directory: ScimDirectory,
    role_groups: Mapping[str, Sequence[str]],
    *,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], None] | None = None,
) -> RoleReport:
    kw: dict[str, Any] = {"sleep": sleep} if sleep else {}
    groups = with_retry(directory.groups, retry or RetryPolicy(), what="SCIM read", **kw)
    members = {
        str(g["displayName"]): {str(m["value"]) for m in g.get("members") or []} for g in groups
    }
    findings: list[str] = []
    user_roles: dict[str, set[str]] = {}
    for role in ROLES:
        mapped = [g for g in role_groups.get(role, ()) if not is_placeholder(g)]
        if not mapped:
            findings.append(f"role {role}: no group mapped (FILL-ME in config/auth.yaml)")
            continue
        for g in mapped:
            if g not in members:
                findings.append(f"role {role}: group {g!r} not found in the directory")
                continue
            for user in members[g]:
                user_roles.setdefault(user, set()).add(role)
    for user, roles in sorted(user_roles.items()):
        if {"reviewer", "approver"} <= roles:
            findings.append(
                f"user {user} holds reviewer and approver: allowed, but the two sign-offs "
                "of a high case must come from two different people"
            )
    admins = [u for u, r in user_roles.items() if "admin" in r]
    if len(admins) == 1:
        findings.append("only one admin: quarantine release has no second admin")
    return RoleReport({u: sorted(r) for u, r in sorted(user_roles.items())}, findings)


__all__ = [
    "ROLES",
    "FakeScimDirectory",
    "RoleReport",
    "ScimDirectory",
    "load_role_groups",
    "role_report",
]
