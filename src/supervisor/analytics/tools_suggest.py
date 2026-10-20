"""Least-privilege suggestion (WP22): declared tools versus tools used in a window.

Declared (what the agent may call): the allow-list rule of the agent in ``policies/*.yaml``
(a block/pause rule with ``when.tool.not_in: [...]`` and the agent in scope, such as PAY-07,
SVC-07, CRD-07); when the agent has no such rule, the tools of its manifest. Tools that are
in the manifest but not in the allow-list (or the other way round) are reported as drift.

A declared tool is ``used`` when the rollup shows at least one gate decision for it in the
window, ``exception`` when ``config/tool_exceptions.yaml`` holds an unexpired documented
exception for it, otherwise ``unused`` (a removal candidate). A tool called in the window
but not declared is ``undeclared`` (flagged for a human; never added by the suggestion).

The output is a YAML patch plus a unified diff. NOTHING here edits a policy or a manifest:
applying the diff is a human action through the normal policy change path
(docs/tool-analytics.md). With little history (``TOOL_ANALYTICS_MIN_HISTORY_DAYS``) the
confidence is ``low``; with no rollup rows in the window it is ``no_data`` and nothing is
proposed for removal.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date
from pathlib import Path
from typing import Any

import yaml

from supervisor.analytics.tools import (
    RISK_ORDER,
    UNKNOWN_RISK,
    AnalyticsError,
    load_daily,
    risk_classes,
    summarise,
    window_bounds,
)
from supervisor.config import REPO_ROOT, Settings
from supervisor.monitors.common import MonitorContext

SUGGESTION_VERSION = 1
POLICY_DIR = REPO_ROOT / "policies"
RISKY = ("money", "credit", "pii_export")
# The scheduler job recomputes the last 2 days; a newest stored day older than this means the
# rollup is not running, and "unused" would only mean "not rolled up".
STALE_DAYS = 2


# --------------------------------------------------------------------------- declared tools


def load_exceptions(path: Path | None) -> list[dict[str, Any]]:
    """Documented exceptions: a YAML list of ``{agent_id, tool, reason, approver, expires}``.
    A missing file is an empty list; a malformed file is an error (a silent skip would hide
    an exception someone relied on)."""
    if path is None or not Path(path).is_file():
        return []
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AnalyticsError(f"{path}: not valid YAML: {exc}") from exc
    items = doc.get("exceptions", []) if isinstance(doc, Mapping) else doc
    out = []
    for i, e in enumerate(items or []):
        if not isinstance(e, Mapping) or not all(
            str(e.get(k, "")).strip() for k in ("agent_id", "tool", "reason", "approver", "expires")
        ):
            raise AnalyticsError(
                f"{path}: exception #{i + 1} needs agent_id, tool, reason, approver, expires"
            )
        try:
            expires = (
                e["expires"]
                if isinstance(e["expires"], date)
                else date.fromisoformat(str(e["expires"]))
            )
        except ValueError as exc:
            raise AnalyticsError(f"{path}: exception #{i + 1}: expires must be YYYY-MM-DD") from exc
        out.append(
            {
                "agent_id": str(e["agent_id"]),
                "tool": str(e["tool"]),
                "reason": str(e["reason"]),
                "approver": str(e["approver"]),
                "expires": expires,
            }
        )
    return out


def allow_rules(policy: Any, agent_id: str) -> list[tuple[str, list[str]]]:
    """(rule id, tool list) of every block/pause rule that allows only the listed tools.

    Only unconditional allow-lists count: a rule with ``when.all`` / ``when.any`` predicates,
    an aggregate or a prior check stops other tools only in some cases, so it does not
    declare what the agent may call."""
    out = []
    for r in policy.rules_for(agent_id):
        t = r.when.tool
        if (
            t is not None
            and t.op == "not_in"
            and r.action in ("block", "pause")
            and not r.when.all
            and not r.when.any
            and r.aggregate is None
            and r.prior is None
        ):
            out.append((r.id, [str(v) for v in t.value]))
    return sorted(out)


def _manifest_tools(agent_id: str) -> tuple[list[str], dict[str, str]]:
    try:
        from supervisor_agents.common.manifest import load_manifest

        m = load_manifest(agent_id)
    except Exception:  # noqa: BLE001 - no manifest for this agent id
        return [], {}
    return list(m.tool_names), {t.name: t.risk_class for t in m.tools}


# --------------------------------------------------------------------------- the suggestion


def _risk_rank(risk: str | None) -> int:
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else len(RISK_ORDER)


def build_suggestion(
    agent_id: str,
    *,
    window_rows: Sequence[Mapping[str, Any]],
    history_first_day: date | None,
    policy_rules: Sequence[tuple[str, Sequence[str]]],
    manifest_tools: Sequence[str],
    risk: Mapping[str, str],
    exceptions: Sequence[Mapping[str, Any]],
    as_of: date,
    window_days: int,
    min_history_days: int,
) -> dict[str, Any]:
    """Pure function: the suggestion for one agent. ``window_rows`` are the rollup rows of
    this agent inside the window."""
    start, _ = window_bounds(as_of, window_days)
    if policy_rules:  # several allow rules: a tool must pass all of them
        sets = [set(t) for _, t in policy_rules]
        allowed = set.intersection(*sets)
        current = [t for t in policy_rules[0][1] if t in allowed]
        source = "policy"
    else:
        current = list(manifest_tools)
        source = "manifest"
    declared = list(dict.fromkeys(current))
    used = {r["tool_name"]: r for r in summarise(window_rows)}
    active = {
        e["tool"]: e for e in exceptions if e["agent_id"] == agent_id and e["expires"] >= as_of
    }
    history_days = (as_of - history_first_day).days + 1 if history_first_day else 0
    if not window_rows:
        confidence = "no_data"
    elif history_days < min_history_days:
        confidence = "low"
    else:
        confidence = "ok"

    def rc(tool: str) -> str:
        u = used.get(tool)
        return (
            u["risk_class"] if u and u["risk_class"] != UNKNOWN_RISK else risk.get(tool)
        ) or UNKNOWN_RISK

    def entry(tool: str, status: str) -> dict[str, Any]:
        u = used.get(tool) or {}
        e = active.get(tool)
        return {
            "tool": tool,
            "risk_class": rc(tool),
            "status": status,
            "calls": u.get("calls", 0),
            "allows": u.get("allows", 0),
            "blocks": u.get("blocks", 0),
            "pauses": u.get("pauses", 0),
            "last_seen": u.get("last_seen"),
            "exception": (
                {
                    "reason": e["reason"],
                    "approver": e["approver"],
                    "expires": e["expires"].isoformat(),
                }
                if e
                else None
            ),
        }

    tools = []
    for t in declared:
        if used.get(t, {}).get("calls", 0) > 0:
            tools.append(entry(t, "used"))
        elif t in active:
            tools.append(entry(t, "exception"))
        else:
            tools.append(entry(t, "unused"))
    undeclared = [
        entry(t, "undeclared") for t in sorted(used) if t not in declared and used[t]["calls"] > 0
    ]

    order = {"unused": 0, "undeclared": 1, "exception": 2, "used": 3}
    tools.sort(
        key=lambda e: (order[e["status"]], _risk_rank(e["risk_class"]), -e["calls"], e["tool"])
    )
    unused = [e for e in tools if e["status"] == "unused"]
    remove = [e["tool"] for e in unused] if confidence != "no_data" else []
    warnings = []
    if confidence == "no_data":
        warnings.append("no rollup rows in the window: nothing proposed (run the rollup first)")
    elif confidence == "low":
        warnings.append(
            f"only {history_days} days of history (minimum {min_history_days}): "
            "removals are low confidence"
        )
    if remove and len(remove) == len(declared):
        warnings.append("every declared tool is unused: consider retiring the agent")
    if undeclared:
        warnings.append(
            "tools called but not declared: "
            + ", ".join(e["tool"] for e in undeclared)
            + " (review; the gate blocked or paused them)"
        )
    drift_m = sorted(set(manifest_tools) - set(declared)) if policy_rules and manifest_tools else []
    drift_p = sorted(set(declared) - set(manifest_tools)) if policy_rules and manifest_tools else []
    return {
        "agent_id": agent_id,
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "window_from": start.isoformat(),
        "history_days": history_days,
        "confidence": confidence,
        "declared_source": source,
        "rule_ids": [r for r, _ in policy_rules],
        "rule_versions": {},
        "current": list(current),
        "proposed": [t for t in current if t not in remove],
        "remove": remove,
        "tools": tools,
        "undeclared": undeclared,
        "drift": {"manifest_not_in_policy": drift_m, "policy_not_in_manifest": drift_p},
        "warnings": warnings,
        "manifest_tools": list(manifest_tools),
    }


# --------------------------------------------------------------------------- text patches


def patch_rule_list(text: str, rule_id: str, remove: Sequence[str]) -> str | None:
    """Remove tool names from the flow-style ``not_in: [a, b]`` line of rule ``rule_id`` and
    raise the rule ``version`` by one (a deployed version with other content is refused, see
    ``gateway.policy.deploy_policy``). None when the rule, its ``version`` line or a one-line
    list cannot be found (a human edits it by hand)."""
    lines = text.split("\n")
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if re.match(rf"^\s*-\s*id:\s*{re.escape(rule_id)}\s*$", ln)
        ),
        None,
    )
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    version_at = None
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        vm = re.match(r"^(\s*version:\s*)(\d+)(\s*(#.*)?)$", ln)
        if vm and version_at is None:
            version_at = (j, vm)
        if (
            ln.strip()
            and re.match(rf"^\s{{0,{indent}}}-\s", ln)
            and (len(ln) - len(ln.lstrip())) <= indent
        ):
            return None  # next rule begins: no flow-style list found
        m = re.match(r"^(\s*not_in:\s*)\[(.*)\](\s*(#.*)?)$", ln)
        if m:
            if version_at is None:
                return None
            vj, vm = version_at
            lines[vj] = f"{vm.group(1)}{int(vm.group(2)) + 1}{vm.group(3)}"
            items = [i.strip() for i in m.group(2).split(",") if i.strip()]
            keep = [i for i in items if i.strip("'\"") not in set(remove)]
            lines[j] = f"{m.group(1)}[{', '.join(keep)}]{m.group(3)}"
            new = "\n".join(lines)
            # Fail closed: the text edit must equal the intended structural edit.
            return new if verify_rule_patch(text, new, rule_id, remove) else None
    return None


def patch_manifest_text(text: str, remove: Sequence[str]) -> str | None:
    """Delete the ``- name: <tool>`` blocks of ``remove`` from a manifest. None when nothing
    matched."""
    lines = text.split("\n")
    changed = False
    for tool in remove:
        for i, ln in enumerate(lines):
            if re.match(rf"^\s*-\s+name:\s*{re.escape(tool)}\s*$", ln):
                indent = len(ln) - len(ln.lstrip())
                j = i + 1
                while j < len(lines):
                    nxt = next((k for k in lines[j:] if k.strip()), None)  # next non-blank
                    if nxt is None or len(nxt) - len(nxt.lstrip()) <= indent:
                        break  # the block ends before the blank lines that precede its sibling
                    j += 1
                del lines[i:j]
                changed = True
                break
    if not changed:
        return None
    new = "\n".join(lines)
    return new if verify_manifest_patch(text, new, remove) else None


def _find_rule(doc: Any, rule_id: str) -> dict[str, Any] | None:
    rules = doc.get("rules") if isinstance(doc, dict) else None
    hits = [r for r in rules or [] if isinstance(r, dict) and r.get("id") == rule_id]
    return hits[0] if len(hits) == 1 else None


def verify_rule_patch(old: str, new: str, rule_id: str, remove: Sequence[str]) -> bool:
    """True when ``new`` parses to exactly ``old`` with the rule's ``when.tool.not_in`` list
    minus ``remove`` and its ``version`` plus one. Anything else (a comment that holds a
    bracket, a list on several lines, a second match) makes the text patch untrustworthy:
    the caller then leaves the rule to a human instead of emitting a wrong diff."""
    try:
        want, got = yaml.safe_load(old), yaml.safe_load(new)
    except yaml.YAMLError:
        return False
    rule = _find_rule(want, rule_id)
    if rule is None or not isinstance(rule.get("version"), int):
        return False
    tool = (rule.get("when") or {}).get("tool")
    if not isinstance(tool, dict) or not isinstance(tool.get("not_in"), list):
        return False
    tool["not_in"] = [t for t in tool["not_in"] if str(t) not in set(remove)]
    rule["version"] += 1
    return want == got


def verify_manifest_patch(old: str, new: str, remove: Sequence[str]) -> bool:
    """True when ``new`` parses to ``old`` minus the ``tools`` entries named in ``remove``."""
    try:
        want, got = yaml.safe_load(old), yaml.safe_load(new)
    except yaml.YAMLError:
        return False
    if not isinstance(want, dict) or not isinstance(want.get("tools"), list):
        return False
    want["tools"] = [
        t for t in want["tools"] if not (isinstance(t, dict) and t.get("name") in set(remove))
    ]
    return want == got


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _unified(path: Path, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{_rel(path)}",
            tofile=f"b/{_rel(path)}",
        )
    )


def find_policy_file(policy_dir: Path, rule_id: str) -> Path | None:
    pat = re.compile(rf"^\s*-\s*id:\s*{re.escape(rule_id)}\s*$", re.M)
    for f in sorted(Path(policy_dir).glob("*.yaml")):
        if pat.search(f.read_text(encoding="utf-8")):
            return f
    return None


def attach_diff(s: dict[str, Any], policy_dir: Path, manifest_dir: Path | None) -> dict[str, Any]:
    """Add ``diff`` (unified, policy then manifest) and the file names to a suggestion.

    All or nothing per agent: when one allow-list rule cannot be patched safely (shared with
    other agents, file not found, a list the text patch cannot edit exactly) or the manifest
    edit does not verify, the agent gets no diff at all and a warning says why. A partial
    diff (manifest without policy, or one rule of two) would leave the policy and the
    manifest out of step."""
    s["policy_file"] = None
    s["manifest_file"] = None
    s["_rule_files"] = {}  # rule id -> Path, for combined_diff
    s["_manifest_path"] = None
    s["diff"] = ""
    if not s["remove"]:
        return s
    parts: list[str] = []
    rule_files: dict[str, Path] = {}
    problems: list[str] = []
    scopes = s.get("rule_scopes") or {}
    for rule_id in s["rule_ids"]:
        scope = scopes.get(rule_id, [s["agent_id"]])
        if scope != [s["agent_id"]]:
            shown = "*" if scope == "*" else ", ".join(scope)
            problems.append(
                f"rule {rule_id} applies to more agents ({shown}): removing a tool there "
                "affects them too"
            )
            continue
        f = find_policy_file(policy_dir, rule_id)
        if f is None:
            problems.append(f"rule {rule_id}: policy file not found")
            continue
        old = f.read_text(encoding="utf-8")
        new = patch_rule_list(old, rule_id, s["remove"])
        if new is None:
            problems.append(
                f"rule {rule_id}: the not_in list is not a plain one-line list "
                "(or the edit did not verify)"
            )
            continue
        rule_files[rule_id] = f
        parts.append(_unified(f, old, new))
    m_remove = [t for t in s["remove"] if t in s["manifest_tools"]]
    mf = (manifest_dir / s["agent_id"] / "manifest.yaml") if manifest_dir else None
    manifest_part = None
    if m_remove and mf is not None and mf.is_file():
        old = mf.read_text(encoding="utf-8")
        new = patch_manifest_text(old, m_remove)
        if new is None:
            problems.append(f"{_rel(mf)}: the tool blocks could not be removed exactly")
        else:
            manifest_part = _unified(mf, old, new)
    if problems:
        s["warnings"].extend(f"NO DIFF, edit by hand: {p}" for p in problems)
        return s
    for rule_id, f in rule_files.items():
        s["policy_file"] = _rel(f)
        s["_rule_files"][rule_id] = f
    if manifest_part:
        s["manifest_file"] = _rel(mf)  # type: ignore[arg-type]
        s["_manifest_path"] = mf
        parts.append(manifest_part)
    s["diff"] = "".join(parts)
    return s


# --------------------------------------------------------------------------- rendering


def render_yaml(
    suggestions: Sequence[Mapping[str, Any]], *, as_of: date, window_days: int, diff_name: str
) -> str:
    """The YAML patch document (ASCII, deterministic, same input = same bytes)."""
    doc: dict[str, Any] = {
        "suggestion_version": SUGGESTION_VERSION,
        "status": "SUGGESTION - NOT APPLIED",
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "unified_diff_file": diff_name,
        "agents": {},
    }
    for s in suggestions:
        doc["agents"][s["agent_id"]] = {
            "confidence": s["confidence"],
            "declared_source": s["declared_source"],
            "policy_file": s.get("policy_file"),
            "manifest_file": s.get("manifest_file"),
            "rules": [
                {
                    "rule": rid,
                    "version": {
                        "current": s["rule_versions"].get(rid),
                        "proposed": (s["rule_versions"].get(rid) or 0) + 1,
                    },
                    "path": "when.tool.not_in",
                    "current": s["current"],
                    "proposed": s["proposed"],
                }
                for rid in s["rule_ids"]
            ],
            "remove": [
                {
                    "tool": e["tool"],
                    "risk_class": e["risk_class"],
                    "reason": f"no gate decision in the last {s['window_days']} days",
                }
                for e in s["tools"]
                if e["tool"] in s["remove"]
            ],
            "flag_undeclared": [
                {
                    "tool": e["tool"],
                    "risk_class": e["risk_class"],
                    "calls": e["calls"],
                    "blocks": e["blocks"],
                    "pauses": e["pauses"],
                    "last_seen": e["last_seen"].strftime("%Y-%m-%d") if e["last_seen"] else None,
                }
                for e in s["undeclared"]
            ],
            "keep_by_exception": [
                {"tool": e["tool"], **e["exception"]}
                for e in s["tools"]
                if e["status"] == "exception"
            ],
            "drift": s["drift"],
            "warnings": s["warnings"],
        }
    head = (
        "# Least-privilege SUGGESTION (WP22). Generated, not applied. Nothing was changed.\n"
        "# Apply only through the normal policy change path: pull request, two approvers,\n"
        "# deploy. See docs/tool-analytics.md, section 'Applying a suggestion'.\n"
    )
    return head + yaml.safe_dump(
        doc, sort_keys=False, allow_unicode=False, default_flow_style=False
    )


def render_text(s: Mapping[str, Any]) -> list[str]:
    """One screen per agent: ASCII lines for the CLI."""
    lines = [
        "",
        f"agent {s['agent_id']}  window {s['window_from']}..{s['as_of']} ({s['window_days']} d)  "
        f"declared from {s['declared_source']}  confidence {s['confidence']}",
        f"{'tool':<22} {'risk':<10} {'status':<10} {'calls':>7} {'block':>6} {'pause':>6} "
        f"{'last seen':>10}",
    ]
    for e in [*s["tools"], *s["undeclared"]]:
        last = e["last_seen"].strftime("%Y-%m-%d") if e["last_seen"] else "-"
        lines.append(
            f"{e['tool'][:22]:<22} {e['risk_class'][:10]:<10} {e['status']:<10} {e['calls']:>7} "
            f"{e['blocks']:>6} {e['pauses']:>6} {last:>10}"
        )
    if s["remove"]:
        lines.append("suggest remove: " + ", ".join(s["remove"]))
    for w in s["warnings"]:
        lines.append(f"WARNING: {w}")
    return lines


# --------------------------------------------------------------------------- orchestration


def build_all(
    state: Any,
    settings: Settings,
    *,
    as_of: date,
    days: int | None = None,
    agent_id: str | None = None,
    policy_dir: Path | None = None,
    manifest_dir: Path | None = None,
    with_diff: bool = True,
) -> list[dict[str, Any]]:
    """Suggestions for every agent in the policy (or one agent), from the stored rollup."""
    from supervisor.gateway.policy import PolicyError, load_policy_dir

    policy_dir = Path(policy_dir or POLICY_DIR)
    days = days or settings.tool_analytics_window_days
    start, end = window_bounds(as_of, days)
    try:
        policy = load_policy_dir(policy_dir)
    except (PolicyError, OSError) as exc:
        raise AnalyticsError(f"cannot load policy from {policy_dir}: {exc}") from exc
    if manifest_dir is None:
        from supervisor_agents.common.manifest import PACKAGE_DIR

        manifest_dir = PACKAGE_DIR
    exceptions = load_exceptions(settings.tool_analytics_exceptions_file)
    risk = risk_classes(policy_dir)
    agents = sorted(policy.doc.agents)
    if agent_id:
        if agent_id not in agents:
            raise AnalyticsError(f"unknown agent: {agent_id}")
        agents = [agent_id]
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in load_daily(state, end=end):
        by_agent.setdefault(r["agent_id"], []).append(r)
    # A rollup that stopped (job off, failing) looks like "no use" for every tool. The newest
    # stored day of ANY agent shows whether the rollup still runs.
    latest = max((rows[0]["usage_date"] for rows in by_agent.values()), default=None)
    stale = latest is not None and (as_of - latest).days > STALE_DAYS
    out = []
    for a in agents:
        all_rows = by_agent.get(a, [])
        window = [r for r in all_rows if start <= r["usage_date"] <= end]
        first = min((r["usage_date"] for r in all_rows), default=None)
        m_tools, m_risk = _manifest_tools(a)
        s = build_suggestion(
            a,
            window_rows=window,
            history_first_day=first,
            policy_rules=allow_rules(policy, a),
            manifest_tools=m_tools,
            risk={**m_risk, **risk},
            exceptions=exceptions,
            as_of=as_of,
            window_days=days,
            min_history_days=settings.tool_analytics_min_history_days,
        )
        if stale and s["confidence"] != "no_data":
            s["confidence"] = "low"
            s["warnings"].append(
                f"the rollup looks stale: newest day of any agent is {latest.isoformat()} "
                f"(as of {as_of.isoformat()}); run the rollup for the missing days first"
            )
        s["rule_versions"] = {r.id: r.version for r in policy.rules if r.id in s["rule_ids"]}
        s["rule_scopes"] = {
            r.id: r.agent_scope if r.agent_scope == "*" else sorted(r.agent_scope)
            for r in policy.rules
            if r.id in s["rule_ids"]
        }
        out.append(attach_diff(s, policy_dir, manifest_dir) if with_diff else s)
    return out


def write_all(
    ctx: MonitorContext,
    settings: Settings,
    *,
    as_of: date | None = None,
    days: int | None = None,
    agent_id: str | None = None,
    out_dir: Path | str | None = None,
    policy_dir: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, Any]:
    """Write ``least_privilege_<as_of>.yaml`` and ``.diff`` into ``out_dir`` (created if
    needed). Returns the file names, the CLI lines and the suggestions. Never edits a policy."""
    as_of = as_of or ctx.clock.now().astimezone(UTC).date()
    days = days or settings.tool_analytics_window_days
    sug = build_all(
        ctx.state, settings, as_of=as_of, days=days, agent_id=agent_id,
        policy_dir=policy_dir, manifest_dir=manifest_dir,
    )  # fmt: skip
    folder = Path(out_dir or settings.tool_analytics_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"least_privilege_{as_of.isoformat()}" + (f"_{agent_id}" if agent_id else "")
    diff_name = f"{stem}.diff"
    (folder / f"{stem}.yaml").write_text(
        render_yaml(sug, as_of=as_of, window_days=days, diff_name=diff_name),
        encoding="utf-8",
        newline="\n",
    )
    (folder / diff_name).write_text(combined_diff(sug), encoding="utf-8", newline="\n")
    text = [ln for s in sug for ln in render_text(s)]
    return {
        "files": [str(folder / f"{stem}.yaml"), str(folder / diff_name)],
        "text": text,
        "suggestions": sug,
    }


def _must(text: str | None, what: str) -> str:
    # attach_diff verified each edit on the original file; failing here means the edits of
    # two agents interact. Fail loudly rather than write a diff that differs from the YAML.
    if text is None:
        raise AnalyticsError(f"{what}: combined diff could not be built; edit by hand")
    return text


def combined_diff(sug: Sequence[Mapping[str, Any]]) -> str:
    """One unified diff for all agents. Edits to the same file (the baseline policy holds every
    allow-list rule) are applied one after the other, so each file appears once and the patch
    applies cleanly."""
    files: dict[Path, list[str]] = {}  # path -> [original, patched]
    for s in sug:
        if not s["remove"]:
            continue
        for rule_id, f in s.get("_rule_files", {}).items():
            cur = files.setdefault(f, [f.read_text(encoding="utf-8")] * 2)
            cur[1] = _must(patch_rule_list(cur[1], rule_id, s["remove"]), f"rule {rule_id}")
        mf = s.get("_manifest_path")
        if mf is not None:
            cur = files.setdefault(mf, [mf.read_text(encoding="utf-8")] * 2)
            m_remove = [t for t in s["remove"] if t in s["manifest_tools"]]
            cur[1] = _must(patch_manifest_text(cur[1], m_remove), _rel(mf))
    return "".join(_unified(f, old, new) for f, (old, new) in files.items() if old != new)
