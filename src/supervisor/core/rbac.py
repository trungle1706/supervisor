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
    "decisions.export": (
        ("auditor", "admin"),
        "Export the filtered Gate decisions list as CSV: masked columns only, row cap (WP39)",
    ),
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
    "schema.view": (("admin",), "Schema self-check page: SQL plan, read-only (WP-P3)"),
    "audit.view": (("auditor", "admin"), "Audit log page: console_action rows (read-only)"),
    "integrations.view": (_ALL, "Integrations status page (read-only)"),
    # --- WP26 ---
    "mcp.tools.view": (_ALL, "List MCP tools and their diffs (read-only, WP26)"),
    "mcp.tools.propose": (
        ("reviewer", "approver", "owner", "admin", "operator"),
        "Give the first approval of a new or changed MCP tool (WP26)",
    ),
    "mcp.tools.approve": (
        ("reviewer", "approver", "owner", "admin"),
        "Approve a new or changed MCP tool; the second different person locks it (WP26)",
    ),
    # --- WP29 ---
    "risks.view": (_ALL, "Risks page, Risks tab and /v1/risks (read-only, WP29)"),
    "risks.edit": (
        ("reviewer", "owner", "admin"),
        "Create and change risks, link them to controls and rules (WP29)",
    ),
    # --- WP38 ---
    "collectors.add": (
        ("admin", "operator"),
        "Integrations catalogue: Add a collector (issues the first agent key, WP38)",
    ),
    # --- WP27 ---
    "session.view": (
        ("reviewer", "approver", "owner", "admin", "auditor", "operator"),
        "GET /v1/sessions/{id}: masked timeline and scores of one conversation (WP27)",
    ),
    # --- WP30 ---
    "controls.view": (_ALL, "Controls page, Controls tab and /v1/controls (read-only, WP30)"),
    "controls.edit": (
        ("reviewer", "owner", "admin"),
        "Create and change controls and what they cover (WP30)",
    ),
    "tasks.view": (_ALL, "Tasks page, Tasks tab and GET /v1/tasks (read-only, WP30)"),
    "tasks.edit": (
        ("reviewer", "owner", "admin"),
        "Generate, start and finish tasks, ask to waive one (WP30)",
    ),
    "tasks.approve": (
        ("approver", "admin"),
        "Second person for a task waiver; approve a lifecycle move or an approver task (WP30)",
    ),
    # --- WP31 ---
    "transparency.view": (_ALL, "Transparency page, Agent tab and GET /v1/transparency (WP31)"),
    "transparency.generate": (
        ("reviewer", "admin"),
        "Build and sign a transparency report (WP31)",
    ),
    # --- WP-G0 ---
    "systems.view": (_ALL, "Systems pages and GET /v1/systems: AI systems in your scope (WP-G0)"),
    "systems.edit": (
        ("reviewer", "owner", "admin"),
        "Register and change AI systems, their team and their links (WP-G0)",
    ),
    # --- WP-G1 ---
    "systems.approve": (
        ("approver", "reviewer", "owner", "admin"),
        "Answer a stage approval of an AI system (WP-G1)",
    ),
    "systems.review": (
        ("reviewer", "approver", "admin"),
        "Plan, change, complete and reopen reviews of an AI system (WP-G1)",
    ),
    # --- WP-G5 --- mounted only when GOVERNANCE_ACTIONS_ENABLED is on
    "incidents.view": (
        _ALL,
        "Incidents tab and GET /v1/incidents: incidents in your scope (WP-G5)",
    ),
    "incidents.transition": (
        ("reviewer", "owner", "admin"),
        "Move an incident on and close it (the holders of case.transition or systems.edit) (WP-G5)",
    ),
    # --- WP-G6 --- mounted only when MCP_SERVER_ENABLED is on
    "mcp.apps": (
        ("admin",),
        "List, approve and block the apps connected to the MCP server (WP-G6)",
    ),
    # --- WP-P2 --- agent registry API, gate mode and policy reload (AGENTS_API_ENABLED)
    "agents.edit": (
        ("reviewer", "owner", "admin"),
        "Register and change an agent in the registry, POST /v1/agents (WP-P2)",
    ),
    "agent.mode": (
        ("reviewer", "approver", "owner", "admin"),
        "Ask for or approve SHADOW to RUNNING (two persons); RUNNING to SHADOW needs the reviewer "
        "or admin role (WP-P2)",
    ),
    "policy.reload": (("admin",), "Reload the policy folders from disk (WP-P2)"),
    # --- WP-G1 (phase 12) --- guardian factory (GUARDIAN_FACTORY; 400 guardian_factory_off)
    "guardians.view": (_ALL, "Guardian factory registry and editor, read-only (WP-G1)"),
    "guardians.edit": (
        ("reviewer", "approver", "owner", "admin"),
        "Create, draft, save and retire guardian definitions; the owner group is also checked "
        "(WP-G1)",
    ),
    # --- WP-L1 --- law agent drafts (LAWAGENT_ENABLED); the page needs the flag
    "regkb.view": (
        _ALL,
        "Law agent drafts page: duties drafted from the stored official text (WP-L1)",
    ),
    "regkb.confirm": (
        ("approver", "admin"),
        "Confirm or drop a law agent draft; the compliance sign-off role (WP-L1)",
    ),
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
        "mcp.tools.view",
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
    ("GET", "/console/my/agents"): "console.view",  # WP-N2, read-only
    ("GET", "/console/my/agents/rows"): "console.view",
    ("GET", "/console/candidates"): "inventory.view",  # WP-N1, read-only
    ("GET", "/console/candidates/rows"): "inventory.view",
    ("GET", "/console/candidates/{node_id}/drawer"): "inventory.view",
    ("GET", "/v1/candidates"): "inventory.view",
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
    # --- WP-P2 (phase 8) --- Request / Approve RUNNING on the agent page (CONSOLE_STATE_ACTIONS)
    ("POST", "/console/agents/{agent_id}/running/{step}"): "agent.mode",
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
    ("POST", "/console/decisions/export"): "decisions.export",
    ("GET", "/console/decisions/exports/{name}"): "decisions.export",
    ("GET", "/console/traces"): "traces.view",
    ("GET", "/console/traces/rows"): "traces.view",
    ("GET", "/console/traces/{trace_id}"): "traces.view",
    ("GET", "/console/traces/{trace_id}/span/{span_id}"): "traces.view",
    ("GET", "/console/playground"): "playground.run",
    ("POST", "/console/playground/run"): "playground.run",
    ("GET", "/console/policies"): "policies.view",
    ("GET", "/console/catalog"): "console.view",
    ("GET", "/console/policies/rows"): "policies.view",
    ("GET", "/console/policies/{rule_id}/drawer"): "policies.view",
    ("GET", "/console/credentials"): "credentials.view",
    ("GET", "/console/users"): "users.view",
    ("GET", "/console/admin/schema"): "schema.view",
    ("GET", "/console/audit"): "audit.view",
    ("GET", "/console/audit/rows"): "audit.view",
    ("GET", "/console/audit/{action_id}/drawer"): "audit.view",
    ("GET", "/console/integrations"): "integrations.view",
    # --- WP26 ---
    ("GET", "/v1/mcp/tools"): "mcp.tools.view",
    ("GET", "/v1/mcp/tools/diff"): "mcp.tools.view",
    ("POST", "/v1/mcp/tools/propose"): "mcp.tools.propose",
    ("POST", "/v1/mcp/tools/approve"): "mcp.tools.approve",
    ("POST", "/v1/mcp/tools/observe"): AGENT,
    ("POST", "/v1/mcp/tools/blocked"): AGENT,
    # --- WP29 ---
    ("GET", "/console/risks"): "risks.view",
    ("GET", "/console/risks/rows"): "risks.view",
    ("GET", "/console/risks/{risk_id}/drawer"): "risks.view",
    ("GET", "/v1/risks"): "risks.view",
    ("GET", "/v1/risks/agents/{agent_id}"): "risks.view",
    ("GET", "/v1/risks/{risk_id}"): "risks.view",
    ("GET", "/v1/risks/{risk_id}/evidence"): "risks.view",
    ("POST", "/v1/risks"): "risks.edit",
    ("POST", "/v1/risks/{risk_id}"): "risks.edit",
    ("POST", "/v1/risks/{risk_id}/links"): "risks.edit",
    # --- WP38 ---
    ("GET", "/console/integrations/agent/{agent_id}/drawer"): "integrations.view",
    ("POST", "/console/integrations/{agent_id}/connect"): "collectors.add",
    # --- WP27 ---
    ("GET", "/v1/sessions/{session_id}"): "session.view",
    ("POST", "/v1/sessions/{session_id}/resume"): "agent.resume",
    # --- WP30 ---
    ("GET", "/console/controls"): "controls.view",
    ("GET", "/console/controls/rows"): "controls.view",
    ("GET", "/console/controls/{control_id}/drawer"): "controls.view",
    ("GET", "/console/tasks"): "tasks.view",
    ("GET", "/console/tasks/rows"): "tasks.view",
    ("GET", "/console/tasks/{task_id}/drawer"): "tasks.view",
    ("GET", "/v1/controls"): "controls.view",
    ("GET", "/v1/controls/agents/{agent_id}"): "controls.view",
    ("GET", "/v1/controls/{control_id}"): "controls.view",
    ("POST", "/v1/controls"): "controls.edit",
    ("POST", "/v1/controls/{control_id}"): "controls.edit",
    ("POST", "/v1/controls/{control_id}/maps"): "controls.edit",
    ("GET", "/v1/tasks"): "tasks.view",
    ("GET", "/v1/tasks/export.csv"): "tasks.view",
    ("GET", "/v1/tasks/agents/{agent_id}"): "tasks.view",
    ("GET", "/v1/tasks/{task_id}"): "tasks.view",
    ("POST", "/v1/tasks"): "tasks.edit",
    ("POST", "/v1/tasks/agents/{agent_id}/generate"): "tasks.edit",
    ("POST", "/v1/tasks/{task_id}/start"): "tasks.edit",
    ("POST", "/v1/tasks/{task_id}/done"): "tasks.edit",
    ("POST", "/v1/tasks/{task_id}/approve"): "tasks.approve",  # review WP30
    ("POST", "/v1/tasks/{task_id}/waive"): "tasks.edit",
    ("POST", "/v1/tasks/{task_id}/waive/approve"): "tasks.approve",
    ("POST", "/v1/tasks/{task_id}/waive/reject"): "tasks.approve",
    # --- WP31 ---
    ("GET", "/console/transparency"): "transparency.view",
    ("GET", "/console/transparency/rows"): "transparency.view",
    ("GET", "/console/transparency/{agent_id}/drawer"): "transparency.view",
    ("POST", "/console/transparency/{agent_id}/generate"): "transparency.generate",
    ("GET", "/v1/transparency"): "transparency.view",
    ("GET", "/v1/transparency/{agent_id}"): "transparency.view",
    ("POST", "/v1/transparency/{agent_id}/generate"): "transparency.generate",
    # --- WP-G0 --- mounted only when GOVERNANCE_ENABLED / CONSOLE_SYSTEMS_ENABLED are on
    ("GET", "/console/systems"): "systems.view",
    ("GET", "/console/systems/rows"): "systems.view",
    ("GET", "/console/systems/{system_id}"): "systems.view",
    ("GET", "/console/systems/{system_id}/drawer"): "systems.view",
    ("POST", "/console/systems"): "systems.edit",
    # --- WP-UX4b --- register wizard (CONSOLE_NAV_V3 as well)
    ("GET", "/console/systems/new"): "systems.edit",
    ("POST", "/console/systems/new/checks"): "systems.edit",
    ("POST", "/console/systems/new"): "systems.edit",
    ("POST", "/console/systems/{system_id}/intake-tasks"): "systems.edit",
    ("GET", "/v1/systems"): "systems.view",
    ("POST", "/v1/systems"): "systems.edit",
    ("GET", "/v1/systems/{system_id}"): "systems.view",
    ("PATCH", "/v1/systems/{system_id}"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/team"): "systems.edit",
    ("DELETE", "/v1/systems/{system_id}/team/{user}"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/links"): "systems.edit",
    ("DELETE", "/v1/systems/{system_id}/links/{component_id}"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/archive"): "systems.edit",
    # --- WP-G2 --- assignment rules and Decision 33 classification (same flag as WP-G0)
    ("GET", "/v1/systems/{system_id}/assignments"): "systems.view",
    ("GET", "/v1/systems/{system_id}/obligations"): "systems.view",
    ("GET", "/v1/systems/{system_id}/guardian-floor"): "systems.view",
    ("GET", "/v1/systems/{system_id}/rules/explain"): "systems.view",
    ("POST", "/v1/systems/{system_id}/assignments/run"): "systems.edit",
    ("GET", "/v1/systems/{system_id}/classification"): "systems.view",
    ("POST", "/v1/systems/{system_id}/classification"): "systems.edit",
    ("PATCH", "/v1/systems/{system_id}/classification"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/classification/apply"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/risk-level/lower"): "systems.edit",
    ("POST", "/console/systems/{system_id}/rules/run"): "systems.edit",
    ("POST", "/console/systems/{system_id}/classification/{step}"): "systems.edit",
    # --- WP-G1 --- stage approvals, stage move, reviews (same flag as /v1/systems)
    ("GET", "/v1/systems/{system_id}/approvals"): "systems.view",
    ("POST", "/v1/systems/{system_id}/approvals"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/approvals/{approval_id}/decide"): "systems.approve",
    ("POST", "/v1/systems/{system_id}/stage"): "systems.edit",
    ("GET", "/v1/systems/{system_id}/reviews"): "systems.view",
    ("POST", "/v1/systems/{system_id}/reviews"): "systems.review",
    ("PATCH", "/v1/systems/{system_id}/reviews/{review_id}"): "systems.review",
    ("POST", "/v1/systems/{system_id}/reviews/{review_id}/complete"): "systems.review",
    ("POST", "/v1/systems/{system_id}/reviews/{review_id}/reopen"): "systems.review",
    # --- WP-S1 --- per-system guardian bindings (GUARDIAN_BINDINGS_ENABLED + GOVERNANCE_ENABLED)
    ("GET", "/v1/systems/{system_id}/guardians"): "systems.view",
    ("PUT", "/v1/systems/{system_id}/guardians/{slug}"): "systems.edit",
    ("POST", "/console/systems/{system_id}/guardians/{slug}"): "systems.edit",
    # --- WP-P1 --- CONSOLE_WORKFLOW_ACTIONS: tasks and stage approvals as buttons. The task
    # buttons need only tasks.view here: the handler checks the role of the task or systems.edit.
    ("POST", "/console/systems/{system_id}/tasks/{task_id}/done"): "tasks.view",
    ("POST", "/console/systems/{system_id}/tasks/{task_id}/waive"): "tasks.view",
    ("POST", "/console/systems/{system_id}/tasks/{task_id}/waive/{answer}"): "tasks.approve",
    ("POST", "/console/systems/{system_id}/stage/request"): "systems.edit",
    ("POST", "/console/systems/{system_id}/stage/{approval_id}/decide"): "systems.approve",
    ("POST", "/console/systems/{system_id}/stage/move"): "systems.edit",
    # --- WP-L3 (phase 8) --- duties of a system (RISK_DUTIES; 400 risk_duties_off when off)
    ("POST", "/console/systems/{system_id}/duties/close"): "systems.edit",
    ("POST", "/console/systems/{system_id}/duties/waive"): "systems.approve",
    ("POST", "/console/systems/{system_id}/duties/reevaluate"): "systems.edit",
    # --- WP-L4 (phase 8) --- evidence refresh and the regulator pack (REGULATOR_PACK; 400 when off)
    ("POST", "/console/systems/{system_id}/duties/refresh-evidence"): "systems.edit",
    ("GET", "/v1/systems/{system_id}/regulator-pack.json"): "systems.view",
    ("GET", "/v1/systems/{system_id}/regulator-pack.html"): "systems.view",
    # --- WP-C2 (phase 12) --- eight risk types per system (RISK_DIMENSIONS; 400 when off)
    ("GET", "/v1/systems/{system_id}/risk-dimensions"): "systems.view",
    ("POST", "/v1/systems/{system_id}/risk-dimensions"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/risk-dimensions/{dim}/waive"): "systems.approve",
    ("GET", "/v1/risk-dimensions/summary"): "systems.view",
    ("POST", "/console/systems/{system_id}/risk-dimensions/{dim}/set"): "systems.edit",
    ("POST", "/console/systems/{system_id}/risk-dimensions/{dim}/confirm"): "systems.edit",
    ("POST", "/console/systems/{system_id}/risk-dimensions/{dim}/waive"): "systems.approve",
    # --- WP-P2 (phase 8) --- second person for a guardian switch-off (CONSOLE_STATE_ACTIONS)
    (
        "POST",
        "/v1/systems/{system_id}/guardian-off-requests/{request_id}/decide",
    ): "systems.approve",
    (
        "POST",
        "/console/systems/{system_id}/guardian-requests/{request_id}/{decision}",
    ): "systems.approve",
    # --- WP-C1 (phase 12) --- classification tree (CLASSIFICATION_V2; 400 classification_v2_off)
    ("GET", "/v1/systems/{system_id}/classification-v2"): "systems.view",
    ("POST", "/v1/systems/{system_id}/classification-v2"): "systems.edit",
    ("POST", "/v1/systems/{system_id}/classification-v2/approve"): "systems.approve",
    ("GET", "/v1/classification/summary"): "systems.view",
    ("GET", "/console/systems/{system_id}/classify"): "systems.view",
    ("POST", "/console/systems/{system_id}/classify"): "systems.edit",
    ("POST", "/console/systems/{system_id}/classify/approve"): "systems.approve",
    # --- WP-G1 (phase 12) --- guardian factory (GUARDIAN_FACTORY; 400 guardian_factory_off)
    ("GET", "/v1/guardian-defs"): "guardians.view",
    ("POST", "/v1/guardian-defs"): "guardians.edit",
    ("GET", "/v1/guardian-defs/{def_id}"): "guardians.view",
    ("POST", "/v1/guardian-defs/{def_id}"): "guardians.edit",
    ("POST", "/v1/guardian-defs/{def_id}/draft-artifact"): "guardians.edit",
    ("POST", "/v1/guardian-defs/{def_id}/retire"): "guardians.edit",
    ("POST", "/v1/guardian-defs/{def_id}/reopen"): "guardians.edit",
    ("POST", "/v1/guardian-defs/{def_id}/new-version"): "guardians.edit",
    ("GET", "/v1/guardian-defs-schema"): "guardians.view",
    ("GET", "/console/guardian-factory"): "guardians.view",
    ("GET", "/console/guardian-factory/{def_id}"): "guardians.view",
    ("POST", "/console/guardian-factory/{def_id}"): "guardians.edit",
    ("POST", "/console/guardian-factory/{def_id}/draft"): "guardians.edit",
    ("POST", "/console/guardian-factory/{def_id}/retire"): "guardians.edit",
    ("POST", "/console/guardian-factory/{def_id}/reopen"): "guardians.edit",
    ("POST", "/console/guardian-factory/{def_id}/new-version"): "guardians.edit",
    # --- WP-O1 (phase 9) --- candidate source intake (ONBOARD_INTAKE; 400 with the flag when off)
    ("GET", "/v1/intake/{node_id}"): "systems.view",
    ("POST", "/v1/intake/{node_id}"): "systems.edit",
    ("GET", "/console/intake/{node_id}"): "systems.view",
    ("POST", "/console/intake/{node_id}"): "systems.edit",
    # --- WP-O2 (phase 9) --- facts card (ONBOARD_FACTS; 400 with the flag when off)
    ("GET", "/v1/facts/{node_id}"): "systems.view",
    ("GET", "/v1/facts/{node_id}/export"): "systems.view",  # WP-F1 facts v1 export
    ("POST", "/v1/facts/{node_id}/{n}"): "systems.edit",
    ("GET", "/console/facts/{node_id}"): "systems.view",
    ("POST", "/console/facts/{node_id}"): "systems.edit",
    # --- WP-O3 (phase 9) --- pre-deploy assessment (ONBOARD_PREDEPLOY; 400 predeploy_off when off)
    ("GET", "/v1/predeploy/{node_id}"): "systems.view",
    ("POST", "/v1/predeploy/{node_id}/{n}"): "systems.edit",
    ("GET", "/console/predeploy/{node_id}"): "systems.view",
    ("POST", "/console/predeploy/{node_id}"): "systems.edit",
    # --- WP-O4 (phase 9) --- attach view (ONBOARD_ATTACH_VIEW; 400 attach_off when off)
    ("GET", "/console/attach/{node_id}"): "systems.view",
    ("POST", "/console/attach/{node_id}/check"): "systems.edit",
    # --- WP-O5 (phase 9) --- post-deploy assessment (ONBOARD_POSTDEPLOY; 400 postdeploy_off)
    ("GET", "/console/postdeploy/{node_id}"): "systems.view",
    ("GET", "/v1/postdeploy/{node_id}"): "systems.view",
    # --- WP-G5 --- incidents of the governance loop (GOVERNANCE_ACTIONS_ENABLED)
    ("GET", "/v1/incidents"): "incidents.view",
    ("GET", "/v1/incidents/{incident_id}"): "incidents.view",
    ("POST", "/v1/incidents/{incident_id}/transition"): "incidents.transition",
    ("GET", "/console/incidents"): "incidents.view",
    ("GET", "/console/incidents/rows"): "incidents.view",
    ("GET", "/console/incidents/{incident_id}/drawer"): "incidents.view",
    ("POST", "/console/incidents/{incident_id}/transition"): "incidents.transition",
    # --- WP-L1 --- law agent drafts (flag LAWAGENT_ENABLED; the routes answer 400 when it is off)
    ("GET", "/console/regkb/{instrument_id}/drafts"): "regkb.view",
    ("POST", "/console/regkb/{instrument_id}/drafts/{draft_id}/confirm"): "regkb.confirm",
    ("POST", "/console/regkb/{instrument_id}/drafts/{draft_id}/drop"): "regkb.confirm",
    # --- WP-G6 --- MCP server, connected apps, KPIs (MCP_SERVER_ENABLED)
    ("POST", "/mcp"): AGENT,  # the credential is the HMAC signature of a connected app
    ("GET", "/v1/mcp/apps"): "mcp.apps",
    ("POST", "/v1/mcp/apps/{app_id}/approve"): "mcp.apps",
    ("POST", "/v1/mcp/apps/{app_id}/block"): "mcp.apps",
    ("GET", "/v1/kpis"): "console.view",
    # --- WP-UX4a --- CONSOLE_NAV_V3 pages and section routes (read only)
    ("GET", "/console/governance"): "console.view",
    ("GET", "/console/supervisor"): "console.view",
    ("GET", "/console/workflows"): "console.view",
    ("GET", "/console/catalogues"): "console.view",
    ("GET", "/console/risks-controls"): "console.view",
    ("GET", "/console/activity"): "console.view",
    ("GET", "/console/guardians"): "console.view",
    # --- WP-P2 --- agent registry API, gate mode, policy reload
    ("POST", "/v1/agents"): "agents.edit",
    ("GET", "/v1/agents/{agent_id}"): "console.view",
    ("POST", "/gate/agents/{agent_id}/state"): "agent.mode",
    ("POST", "/gate/policy/reload"): "policy.reload",
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
