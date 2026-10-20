"""Role matrix (WP18): which role may do what, and which route needs which permission.

Pure Python, no web or SQL imports. One source of truth for:

* ``ROLES``        every role the product knows (``adapters.auth.base.ROLES`` is this tuple).
* ``PERMISSIONS``  permission id -> (roles that hold it, one-line description).
* ``ROUTES``       (HTTP method, route template) -> permission id, or one of the markers
                   ``PUBLIC`` (no login needed), ``AGENT`` (machine ingress: the agent's own
                   identity, not a human role), ``DEV_ONLY`` (only the dev_header provider).
* ``allowed()``    does any role in a set hold a permission.
* ``matrix_markdown()``  the table in ``docs/console.md`` (a test keeps them equal).

Phase-1 grants are kept exactly: a role that could do something before still can.
``owner`` is the agent-owner role of ADR D04 (the other half of a two-person resume).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

ROLES: tuple[str, ...] = (
    "viewer",
    "reviewer",
    "approver",
    "owner",
    "admin",
    "auditor",
    "operator",
)

# Roles of phase 1 (before WP18). Their grants must not shrink.
PHASE1_ROLES: tuple[str, ...] = ("reviewer", "approver", "owner", "auditor", "admin")

PUBLIC = "PUBLIC"
AGENT = "AGENT"
DEV_ONLY = "DEV_ONLY"
MARKERS: tuple[str, ...] = (PUBLIC, AGENT, DEV_ONLY)

_ALL = ROLES
_P1_OP = (*PHASE1_ROLES, "operator")

# permission id -> (roles, description)
PERMISSIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "console.view": (_ALL, "Open console pages (queue, case, agents, evidence, case files)"),
    "health.view": (_ALL, "Health page"),
    "metrics.view": (_ALL, "Metrics page"),
    "onboard.view": (_ALL, "Onboarding page, status and generated files"),
    "compliance.view": (_ALL, "Compliance tab (advisory obligations matrix, read-only)"),
    "inventory.view": (_ALL, "Inventory page and /v1/inventory (read-only, WP24)"),
    "gate.read": (_ALL, "Read agent gate state and gate metrics (API)"),
    "case.assign": (("reviewer", "admin"), "Assign a case"),
    "case.itsm": (("reviewer", "admin"), "Set the ITSM reference of a case"),
    "case.transition": (("reviewer", "admin"), "Triage, contain or close a case"),
    "case.comment": (("reviewer", "approver", "owner", "admin"), "Comment on a case"),
    "case.signoff": (("reviewer", "approver", "admin"), "Sign off a case (two-person rule)"),
    "case.report_sent": (
        ("reviewer", "approver", "admin"),
        "Record that an incident report (preliminary or formal) was sent to the authority",
    ),
    "case.verify": (PHASE1_ROLES, "Verify the evidence lane of one agent"),
    "chain.verify": (_P1_OP, "Verify the whole evidence chain"),
    "intake.run": (("reviewer", "admin", "operator"), "Run case intake now"),
    "inbox.read": (PHASE1_ROLES, "Mark an inbox notice read"),
    "evidence.export": (
        ("reviewer", "approver", "admin", "auditor"),
        "Build an audit pack or chain export",
    ),
    "evidence.download": (
        ("reviewer", "approver", "admin", "auditor"),
        "Download a built audit pack",
    ),
    "tools.view": (_ALL, "Tools page and /v1/analytics/tools (tool usage, read-only)"),
    "tools.download": (
        ("owner", "admin"),
        "Download the least-privilege diff of an agent (WP22; a suggestion, never applied)",
    ),
    "onboard.start": (("reviewer", "owner", "admin"), "Start an onboarding run"),
    "agent.pause": (("reviewer", "approver", "owner", "admin"), "Pause an agent (D04)"),
    "agent.resume": (("reviewer", "owner", "admin"), "Approve a resume (D04, two people)"),
    "agent.quarantine": (("admin",), "Quarantine an agent"),
    "agent.release": (("admin",), "Release an agent from quarantine"),
    "alert.ack": (("operator", "admin"), "Acknowledge an alert (WP21)"),
    # --- WP-UX3 ---
    "decisions.view": (_ALL, "Gate decisions list and drawer (read-only)"),
    "traces.view": (_ALL, "Traces list and span viewer (masked payloads only)"),
    "playground.run": (
        ("reviewer", "approver", "owner", "admin", "operator"),
        "Playground: dry-run gate check, no side effect (WP-UX3)",
    ),
    "policies.view": (_ALL, "Policies page: deployed rules and versions (read-only)"),
    "credentials.view": (
        ("owner", "admin"),
        "Credentials page: agent key metadata, never a secret (read-only)",
    ),
    "users.view": (("admin",), "Users and roles page (read-only)"),
    "audit.view": (("auditor", "admin"), "Audit log page: console_action rows (read-only)"),
    "integrations.view": (_ALL, "Integrations status page (read-only)"),
}

# Permissions a non-person caller (service principal, system) keeps: they are the read-only
# views the phase-1 console let every non-user principal open. Everything else needs a role.
NON_USER_OK: frozenset[str] = frozenset(
    {
        "console.view",
        "health.view",
        "metrics.view",
        "onboard.view",
        "compliance.view",
        "inventory.view",
        "gate.read",
        "tools.view",
        "case.verify",
        "chain.verify",
    }
)

# Permission template used for the one console route that serves four agent actions.
_AGENT_ACTION = "agent.{action}"

ROUTES: dict[tuple[str, str], str] = {
    # public
    ("GET", "/"): PUBLIC,
    ("GET", "/healthz"): PUBLIC,
    ("GET", "/health"): PUBLIC,
    ("GET", "/ready"): PUBLIC,
    ("GET", "/version"): PUBLIC,
    ("GET", "/openapi.json"): PUBLIC,
    ("GET", "/console/static/{name}"): PUBLIC,
    ("GET", "/console/static/fonts/{name}"): PUBLIC,
    ("GET", "/console/home"): PUBLIC,
    ("GET", "/console/export"): PUBLIC,
    # machine ingress
    ("POST", "/gate/check"): AGENT,
    ("POST", "/v1/traces"): AGENT,
    # dev switcher
    ("POST", "/console/dev/user"): DEV_ONLY,
    # gateway human routes (enforced only with API_RBAC_ENABLED)
    ("POST", "/gate/pause"): "agent.pause",
    ("POST", "/gate/resume"): "agent.resume",
    ("POST", "/gate/quarantine"): "agent.quarantine",
    ("POST", "/gate/release"): "agent.release",
    ("GET", "/gate/agents/{agent_id}/state"): "gate.read",
    ("GET", "/gate/metrics"): "gate.read",
    ("GET", "/gate/detectors"): "gate.read",  # WP37
    # console pages
    ("GET", "/console/"): "console.view",
    ("GET", "/console/cases"): "console.view",
    ("GET", "/console/queue/rows"): "console.view",
    ("GET", "/console/cases/{case_id}"): "console.view",
    ("GET", "/console/cases/{case_id}/tab/{tab}"): "console.view",
    ("GET", "/console/cases/{case_id}/casefile.{fmt}"): "console.view",
    ("GET", "/console/cases/{case_id}/signoff"): "console.view",
    ("GET", "/console/agents"): "console.view",
    ("GET", "/console/evidence"): "console.view",
    ("GET", "/console/inbox"): "console.view",
    ("GET", "/console/metrics"): "metrics.view",
    ("GET", "/console/health"): "health.view",
    ("GET", "/console/onboard"): "onboard.view",
    ("GET", "/console/onboard/status"): "onboard.view",
    ("GET", "/console/onboard/files/{agent}/{name}"): "onboard.view",
    ("GET", "/console/compliance"): "compliance.view",
    ("GET", "/console/compliance/{agent}"): "compliance.view",
    ("GET", "/console/compliance/{agent}/obligation/{obligation_id}"): "compliance.view",
    ("GET", "/console/integration"): "onboard.view",
    ("GET", "/console/integration/{name}"): "onboard.view",
    ("GET", "/console/integration/{name}/patches/{file}"): "onboard.view",
    ("GET", "/console/assurance"): "console.view",  # WP17, read-only
    ("GET", "/console/assurance/{run_id}"): "console.view",
    ("GET", "/console/inventory"): "inventory.view",  # WP24, read-only
    ("GET", "/v1/inventory/unmanaged"): "inventory.view",
    ("GET", "/v1/inventory/{agent_id}"): "inventory.view",
    ("GET", "/console/exports/{name}"): "evidence.download",
    ("GET", "/console/search"): "console.view",  # WP-UX1, read-only
    ("GET", "/console/soon/{page}"): "console.view",  # WP-UX1 placeholder pages
    ("GET", "/console/agents/rows"): "console.view",
    ("GET", "/console/agents/{agent_id}/drawer"): "console.view",
    # --- WP-UX2 ---
    ("GET", "/console/agents/{agent_id}"): "console.view",
    ("GET", "/console/agents/{agent_id}/tab/{tab}"): "console.view",
    ("GET", "/console/cases/{case_id}/drawer"): "console.view",
    ("GET", "/console/alerts"): "metrics.view",
    ("GET", "/console/alerts/rows"): "metrics.view",
    ("GET", "/console/alerts/{alert_id}/drawer"): "metrics.view",
    ("GET", "/console/signoff"): "console.view",
    ("GET", "/console/signoff/rows"): "console.view",
    ("GET", "/console/signoff/{case_id}/drawer"): "console.view",
    ("GET", "/console/analytics"): "metrics.view",
    ("GET", "/console/analytics/tab/{tab}"): "metrics.view",
    ("GET", "/console/inbox/rows"): "console.view",
    ("GET", "/console/inventory/rows"): "inventory.view",
    # --- end WP-UX2 ---
    ("GET", "/console/tools"): "tools.view",  # WP22
    ("GET", "/console/tools/{agent_id}/diff"): "tools.download",
    ("GET", "/v1/analytics/tools"): "tools.view",
    # console actions
    ("POST", "/console/cases/{case_id}/assign"): "case.assign",
    ("POST", "/console/cases/{case_id}/comment"): "case.comment",
    ("POST", "/console/cases/{case_id}/itsm"): "case.itsm",
    ("POST", "/console/cases/{case_id}/transition"): "case.transition",
    ("POST", "/console/cases/{case_id}/report-sent"): "case.report_sent",
    ("POST", "/console/cases/{case_id}/verify"): "case.verify",
    ("POST", "/console/cases/{case_id}/signoff"): "case.signoff",
    ("POST", "/console/agents/{agent_id}/{action}"): _AGENT_ACTION,
    ("POST", "/console/intake/run"): "intake.run",
    ("POST", "/console/chain/verify"): "chain.verify",
    ("POST", "/console/chain/export"): "evidence.export",
    ("POST", "/console/export"): "evidence.export",
    ("POST", "/console/onboard/start"): "onboard.start",
    ("POST", "/console/inbox/{notice_id}/read"): "inbox.read",
    ("POST", "/console/alerts/{alert_id}/ack"): "alert.ack",
    # --- WP-UX3 ---
    ("GET", "/console/decisions"): "decisions.view",
    ("GET", "/console/decisions/rows"): "decisions.view",
    ("GET", "/console/decisions/{event_id}/drawer"): "decisions.view",
    ("GET", "/console/traces"): "traces.view",
    ("GET", "/console/traces/rows"): "traces.view",
    ("GET", "/console/traces/{trace_id}"): "traces.view",
    ("GET", "/console/traces/{trace_id}/span/{span_id}"): "traces.view",
    ("GET", "/console/playground"): "playground.run",
    ("POST", "/console/playground/run"): "playground.run",
    ("GET", "/console/policies"): "policies.view",
    ("GET", "/console/policies/rows"): "policies.view",
    ("GET", "/console/policies/{rule_id}/drawer"): "policies.view",
    ("GET", "/console/credentials"): "credentials.view",
    ("GET", "/console/users"): "users.view",
    ("GET", "/console/audit"): "audit.view",
    ("GET", "/console/audit/rows"): "audit.view",
    ("GET", "/console/audit/{action_id}/drawer"): "audit.view",
    ("GET", "/console/integrations"): "integrations.view",
}


def roles_for(permission: str) -> tuple[str, ...]:
    """Roles that hold ``permission``, in ``ROLES`` order. Unknown permission: ``KeyError``."""
    held = PERMISSIONS[permission][0]
    return tuple(r for r in ROLES if r in held)


def allowed(roles: Iterable[str], permission: str) -> bool:
    """True when any of ``roles`` holds ``permission``. An unknown permission is never allowed."""
    entry = PERMISSIONS.get(permission)
    if entry is None:
        return False
    return any(r in entry[0] for r in roles)


def normalise_path(path: str) -> str:
    """``/v1/gate/<x>`` is an alias of ``/gate/<x>``."""
    if path.startswith("/v1/gate/") or path == "/v1/gate":
        return path[3:]
    return path


def route_entry(method: str, template: str) -> str | None:
    """The matrix entry for a route template: a permission id (maybe a template), a marker,
    or None when the route is not in the matrix."""
    return ROUTES.get((method.upper(), normalise_path(template)))


def resolve_permission(entry: str, path_params: Mapping[str, str] | None = None) -> str:
    """Fill ``agent.{action}`` from the path. The result may be an unknown permission (a bad
    action name); the route itself answers that with a 400."""
    if "{" in entry:
        try:
            return entry.format(**(path_params or {}))
        except KeyError:
            return entry
    return entry


def matrix_markdown() -> str:
    """The role x permission table (an ``x`` where the role holds the permission)."""
    head = "| Permission | What it allows | " + " | ".join(ROLES) + " |"
    sep = "|---|---|" + "|".join(":-:" for _ in ROLES) + "|"
    lines = [head, sep]
    for pid, (held, desc) in PERMISSIONS.items():
        cells = " | ".join("x" if r in held else "" for r in ROLES)
        lines.append(f"| `{pid}` | {desc} | {cells} |")
    return "\n".join(lines) + "\n"
