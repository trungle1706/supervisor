# ruff: noqa: E501
"""Merge deterministic findings with the agent's verified findings.

Rules (documented in docs/onboarding/code-agent.md):

* A deterministic finding is never removed. The agent can only add evidence and attributes.
* Same key (kind + name) in both: the deterministic value of an attribute with basis ``manifest``
  or ``ast`` stays. A different agent value is listed as a ``Disagreement`` with
  ``applied=deterministic``.
* The deterministic value of an attribute with basis ``name`` (a guess from a name, or from the
  absence of a match) can be replaced by a verified agent value. The change is listed too
  (``applied=agent``), so nothing is silent.
* Risk-lowering claims never replace a deterministic value: ``irreversible`` true -> false,
  ``effect`` money / credit / write / message / delete -> read, and ``approval`` false -> true.
  They are listed with ``applied=deterministic``. ``approval`` is derived from the ``hitl``
  findings only (a verified approval step that names the tool in ``guards``).
* A finding the agent found and the scanner did not is added with ``source=agent``.
"""

from __future__ import annotations

from collections.abc import Sequence

from supervisor.onboard.codeagent.models import KINDS, Disagreement, Finding

MAX_EVIDENCE = 5
CONF_DET = 9500
CONF_AGENT_ALONE = 6000
CONF_AGENT_CORROBORATED = 8500
NOISE_ATTRS = ("target", "scope", "provider", "family", "guards", "internal", "direction")
REFINES_TO = (
    "message",
    "delete",
    "money",
    "credit",
)  # a coarse "write" found by the rules, made specific
IRREVERSIBLE_EFFECTS = ("money", "credit", "message", "delete")
_RISK_RANK = {"read": 0, "other": 1, "write": 2, "message": 3, "delete": 3, "credit": 3, "money": 4}


def _refines(attr: str, det: object, agent: object) -> bool:
    return attr == "effect" and det == "write" and agent in REFINES_TO


def _s(v: object) -> str:
    return str(v).lower() if isinstance(v, bool) else str(v)


def _lowers_risk(attr: str, det: object, agent: object) -> bool:
    if attr == "irreversible":
        return det is True and agent is False
    if attr == "effect":
        return _RISK_RANK.get(str(agent), 1) < _RISK_RANK.get(str(det), 1)
    if attr == "approval":
        return det is False and agent is True
    return False


def _guards(findings: Sequence[Finding]) -> set[str]:
    out: set[str] = set()
    for f in findings:
        if f.kind == "hitl":
            out.update(
                g.strip().lower() for g in str(f.attrs.get("guards", "")).split(",") if g.strip()
            )
    return out


def merge(
    det: Sequence[Finding], agent: Sequence[Finding]
) -> tuple[list[Finding], list[Disagreement]]:
    known_tools = {f.name.lower() for f in [*det, *agent] if f.kind == "tool"}
    # a data flow is "tool -> sink": its tool must be a tool of the report, not a function call
    agent = [
        f
        for f in agent
        if f.kind != "data_flow" or str(f.attrs.get("tool", "")).lower() in known_tools
    ]
    # a data flow of the agent is accepted only for a tool the rules found no data flow for
    flowed = {str(f.attrs.get("tool", "")).lower() for f in det if f.kind == "data_flow"}
    agent = [
        f
        for f in agent
        if f.kind != "data_flow" or str(f.attrs.get("tool", "")).lower() not in flowed
    ]
    rows: dict[tuple[str, str], Finding] = {f.key(): f.model_copy(deep=True) for f in det}
    notes: list[Disagreement] = []
    for a in agent:
        cur = rows.get(a.key())
        if cur is None:
            rows[a.key()] = a.model_copy(deep=True)
            continue
        cur.corroborated = True
        for ev in a.evidence:
            if all(e.ref() != ev.ref() for e in cur.evidence) and len(cur.evidence) < MAX_EVIDENCE:
                cur.evidence.append(ev)
        for attr, val in a.attrs.items():
            if attr == "approval":
                old = cur.attrs.get("approval")
                if old is not None and _s(old) != _s(val):
                    notes.append(
                        Disagreement(
                            kind=cur.kind,
                            name=cur.name,
                            attr=attr,
                            deterministic=_s(old),
                            agent=_s(val),
                            applied="deterministic",
                            reason="approval is derived from verified approval steps only",
                            evidence=a.evidence[:2],
                        )
                    )
                continue
            if attr not in cur.attrs:
                cur.attrs[attr] = val
                cur.attr_basis[attr] = "agent"
                continue
            old = cur.attrs[attr]
            if _s(old) == _s(val) or attr in NOISE_ATTRS:
                continue
            basis = cur.attr_basis.get(attr, "ast")
            firm = basis in ("manifest", "ast") and not _refines(attr, old, val)
            lowers = _lowers_risk(attr, old, val)
            apply_agent = (not firm) and (not lowers)
            reason = (
                "firm deterministic value kept"
                if firm
                else "risk-lowering claim needs a person"
                if lowers
                else "deterministic value was a guess from a name; verified agent evidence replaces it"
            )
            notes.append(
                Disagreement(
                    kind=cur.kind,
                    name=cur.name,
                    attr=attr,
                    deterministic=_s(old),
                    agent=_s(val),
                    applied="agent" if apply_agent else "deterministic",
                    reason=reason,
                    evidence=a.evidence[:2],
                )
            )
            if apply_agent:
                cur.attrs[attr] = val
                cur.attr_basis[attr] = "agent"
    out = list(rows.values())
    _derive_approval(out, notes)
    _derive_irreversible(out)
    _effect_consistency(out, notes)
    for f in out:
        f.confidence_bp = _confidence(f)
    out.sort(
        key=lambda f: (KINDS.index(f.kind), f.name.lower(), f.evidence[0].file, f.evidence[0].line)
    )
    return out, notes


def _derive_approval(findings: list[Finding], notes: list[Disagreement]) -> None:
    guarded = _guards(findings)
    for f in findings:
        if f.kind != "tool":
            continue
        if f.name.lower() in guarded and f.attrs.get("approval") is not True:
            f.attrs["approval"] = True
            f.attr_basis["approval"] = "agent"
        elif "approval" not in f.attrs and f.attrs.get("effect") in (
            "write",
            "money",
            "credit",
            "message",
            "delete",
        ):
            f.attrs["approval"] = False
            f.attr_basis["approval"] = "name"


def _confidence(f: Finding) -> int:
    if f.source == "deterministic":
        base = CONF_DET
        if any(b == "name" for b in f.attr_basis.values()):
            base -= 1500
        if any(b == "agent" for b in f.attr_basis.values()) and f.corroborated:
            base = min(10000, base)
        return base
    return CONF_AGENT_CORROBORATED if f.corroborated else CONF_AGENT_ALONE


def _effect_consistency(findings: list[Finding], notes: list[Disagreement]) -> None:
    """A tool whose body (or a helper it calls) has a verified write cannot be ``read``, whatever
    the agent says. The write comes from a data_flow finding with evidence."""
    writers = {
        str(f.attrs.get("tool", "")).lower()
        for f in findings
        if f.kind == "data_flow"
        and f.attrs.get("direction") == "write"
        and f.source == "deterministic"
    }
    for f in findings:
        if f.kind == "tool" and f.name.lower() in writers and f.attrs.get("effect") == "read":
            notes.append(
                Disagreement(
                    kind="tool",
                    name=f.name,
                    attr="effect",
                    deterministic="write",
                    agent="read",
                    applied="deterministic",
                    reason="a write to a data sink is reached from this tool; it is not read-only",
                    evidence=f.evidence[:1],
                )
            )
            f.attrs["effect"] = "write"
            f.attr_basis["effect"] = "ast"


def _derive_irreversible(findings: list[Finding]) -> None:
    """``irreversible`` follows from the effect (money, credit, message, delete) unless a firm rule
    value is already there. The model is not asked to repeat what the effect already says."""
    for f in findings:
        if f.kind != "tool" or "effect" not in f.attrs:
            continue
        if f.attr_basis.get("irreversible") in ("manifest", "ast"):
            continue
        want = f.attrs["effect"] in IRREVERSIBLE_EFFECTS
        if (
            f.attrs.get("irreversible") is True
            and not want
            and f.attr_basis.get("irreversible") == "agent"
        ):
            continue  # agent said irreversible for another effect: kept, it only raises a risk
        if f.attrs.get("irreversible") is not want and (want or "irreversible" not in f.attrs):
            f.attrs["irreversible"] = want
            f.attr_basis["irreversible"] = (
                f.attr_basis.get("effect", "name")
                if f.attr_basis.get("effect") != "agent"
                else "agent"
            )
