"""From the report data to display blocks, in one language (WP31).

The HTML template and the PDF writer both read the blocks, so the two files say the same thing.
Labels come from the console i18n tables (keys ``tp_*``). Nothing here changes a fact: it picks
words for codes. The customer variant is written in plain sentences; the other two use tables.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from supervisor.console.i18n import translator
from supervisor.transparency.model import SECTIONS

Block = dict[str, Any]
T = Callable[..., str]


def kv(rows: Sequence[tuple[str, Any]]) -> Block:
    return {"k": "kv", "rows": [(a, b) for a, b in rows]}


def table(head: Sequence[str], rows: Sequence[Sequence[Any]]) -> Block:
    return {"k": "table", "head": list(head), "rows": [list(r) for r in rows]}


def para(text: str, cls: str = "") -> Block:
    return {"k": "p", "text": text, "cls": cls}


class Words:
    """Value formatting for one language."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.t: T = translator(lang)

    def v(self, x: Any) -> str:
        if x is None or x == "":
            return "-"
        if x is True:
            return self.t("tp_yes")
        if x is False:
            return self.t("tp_no")
        if isinstance(x, list | tuple):
            return ", ".join(self.v(i) for i in x) or "-"
        return str(x)

    def word(self, prefix: str, code: Any) -> str:
        """The label for a code, ``tp_<prefix>_<code>``; the code itself when there is none."""
        if code is None:
            return "-"
        key = f"tp_{prefix}_{code}"
        text = self.t(key)
        return str(code) if text == key else text

    def counts(self, d: Mapping[str, Any], prefix: str) -> str:
        return ", ".join(f"{self.word(prefix, k)}: {n}" for k, n in d.items()) or "-"


def _sec(sid: str, w: Words, sec: Mapping[str, Any], blocks: list[Block]) -> dict[str, Any]:
    t = w.t
    out: list[Block] = []
    if sec.get("illustrative") and sec.get("available"):
        out.append(para(t("tp_illustrative_note"), "mock"))
    if not sec.get("available"):
        reason = w.word("reason", sec.get("reason"))
        ref = sec.get("ref")
        out.append(para(reason + (f" ({ref})" if ref else ""), "note"))
    else:
        out += blocks
    return {"id": sid, "title": t(f"tp_s_{sid}"), "blocks": out}


# --------------------------------------------------------------------------- detailed variants


def _identity(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    rows = [
        (t("tp_f_agent_id"), d.get("agent_id")),
        (t("tp_f_name"), d.get("display_name")),
        (t("tp_f_owner_team"), d.get("owner_team")),
        (t("tp_f_owner_user"), d.get("owner_user")) if "owner_user" in d else None,
        (t("tp_f_business_owner"), d.get("business_owner")) if "business_owner" in d else None,
        (t("tp_f_kind"), w.word("kind", d.get("kind"))),
        (t("tp_f_purpose"), d.get("purpose")),
        (t("tp_f_host"), f"{w.v(d.get('host_type'))} / {w.v(d.get('plug_point'))}"),
        (t("tp_f_model_family"), d.get("model_family")),
        (t("tp_f_risk_tier"), d.get("risk_tier")),
        (t("tp_f_status"), f"{w.v(d.get('status'))} / {w.v(d.get('gate_state'))}"),
        (t("tp_f_registered"), d.get("registered_day")),
    ]
    rows = [(a, w.v(b)) for r in rows if r is not None for a, b in [r]]
    o = d.get("oversight") or {}
    rows += [(t(f"tp_f_ov_{k}"), w.v(o.get(k))) for k in sorted(o)]
    return [kv(rows)]


def _classification(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_d33_class"), w.word("d33", d.get("decision33_class"))),
                (t("tp_f_class_source"), w.word("src", d.get("class_source"))),
                (t("tp_f_matrix_class"), w.word("d33", d.get("matrix_class"))),
            ]
        )
    ]
    if d.get("entries"):
        out.append(
            table(
                [t("tp_f_entry"), t("tp_f_triggered"), t("tp_f_obligations")],
                [
                    [
                        w.word("entry", e.get("entry")),
                        w.v(e.get("triggered"))
                        if e.get("triggered") is not None
                        else t("tp_unknown"),
                        ", ".join(e.get("obligation_ids") or []),
                    ]
                    for e in d["entries"]
                ],
            )
        )
    return out


def _inventory(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_own_risk"), w.word("lvl", d.get("own_risk"))),
                (t("tp_f_eff_risk"), w.word("lvl", d.get("effective_risk"))),
                (t("tp_f_nodes"), d.get("node_count")),
            ]
        )
    ]
    if d.get("links"):
        out.append(
            table(
                [
                    t("tp_f_group"),
                    t("tp_f_component"),
                    t("tp_f_eff_risk"),
                    t("tp_f_source"),
                    t("tp_f_evidence_ref"),
                ],
                [
                    [
                        x.get("group"),
                        x.get("name"),
                        w.word("lvl", x.get("effective_risk")),
                        x.get("source"),
                        x.get("evidence_ref"),
                    ]
                    for x in d["links"]
                ],
            )
        )
    if d.get("more"):
        out.append(para(t("tp_more", n=d["more"]), "note"))
    return out


def _compliance(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_matrix_source"), w.word("src", d.get("source_kind"))),
                (t("tp_f_as_of"), d.get("as_of")),
                (t("tp_f_regkb"), d.get("regkb_version")),
                (t("tp_f_obl_total"), d.get("obligations_total")),
                (t("tp_f_by_status"), w.counts(d.get("by_status") or {}, "st")),
                (t("tp_f_by_applies"), w.counts(d.get("by_applies") or {}, "ap")),
                (t("tp_f_questions"), d.get("questions_open")),
                (t("tp_f_thr_gaps"), d.get("threshold_gaps")),
                (t("tp_f_thr_exceeds"), d.get("threshold_exceeds")),
            ]
        ),
        para(t("tp_advisory"), "note"),
    ]
    if d.get("d33_rows"):
        out.append(para(t("tp_d33_rows"), "h3"))
        out.append(
            table(
                [t("tp_f_obligation"), t("tp_f_article"), t("tp_f_applies"), t("tp_f_status")],
                [
                    [
                        x.get("obligation_id"),
                        x.get("article_ref"),
                        w.word("ap", x.get("applies")),
                        w.word("st", x.get("status")),
                    ]
                    for x in d["d33_rows"]
                ],
            )
        )
    if d.get("d33_ids_missing"):
        out.append(para(t("tp_d33_missing", ids=", ".join(d["d33_ids_missing"])), "overdue"))
    if d.get("gaps"):
        out.append(para(t("tp_gaps"), "h3"))
        out.append(
            table(
                [t("tp_f_obligation"), t("tp_f_status")],
                [[x.get("obligation_id"), w.word("st", x.get("status"))] for x in d["gaps"]],
            )
        )
    if d.get("gaps_more"):
        out.append(para(t("tp_more", n=d["gaps_more"]), "note"))
    return out


def _cards(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out: list[Block] = []
    a = d.get("agent_card")
    if a:
        out.append(para(t("tp_agent_card"), "h3"))
        out.append(
            kv(
                [
                    (t("tp_f_version"), a.get("version")),
                    (t("tp_f_purpose"), a.get("purpose")),
                    (t("tp_f_classes"), w.v(a.get("agent_classes"))),
                    (t("tp_f_autonomy"), a.get("autonomy")),
                    (t("tp_f_data_classes"), w.v(a.get("data_classes"))),
                    (t("tp_f_roles"), w.v(a.get("roles"))),
                    (t("tp_f_customer_types"), w.v(a.get("customer_types"))),
                    (t("tp_f_provenance"), a.get("provenance_n")),
                ]
            )
        )
        if a.get("limits"):
            out.append(
                table(
                    [
                        t("tp_f_limit"),
                        t("tp_f_period"),
                        t("tp_f_scope"),
                        t("tp_f_value_vnd"),
                        t("tp_f_source_ref"),
                    ],
                    [
                        [
                            x.get("id"),
                            x.get("period"),
                            x.get("scope"),
                            x.get("value_vnd"),
                            x.get("ref"),
                        ]
                        for x in a["limits"]
                    ],
                )
            )
    j = d.get("judge_card")
    if j:
        out.append(para(t("tp_judge_card"), "h3"))
        rows = [
            (t("tp_f_judge"), j.get("judge_id")),
            (t("tp_f_mock"), w.v(j.get("is_mock"))),
            (t("tp_f_model_version"), j.get("model_version")),
            (t("tp_f_prompt_version"), j.get("prompt_version")),
            (t("tp_f_rubric"), j.get("rubric_version")),
            (t("tp_f_mask_version"), j.get("mask_version")),
            (t("tp_f_metrics"), w.word("mst", j.get("metrics_status"))),
            (t("tp_f_catch"), j.get("catch_rate_bp")),
            (t("tp_f_false_alarm"), j.get("false_alarm_bp")),
            (
                t("tp_f_roles_assigned"),
                f"{w.v(j.get('roles_assigned'))} / {w.v(j.get('roles_total'))}",
            ),
        ]
        for k, name in sorted((j.get("role_names") or {}).items()):
            rows.append((t("tp_f_role_name", role=k), name))
        out.append(kv(rows))
    return out


def _assurance(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_packs"), d.get("packs_total")),
                (t("tp_f_by_status"), w.counts(d.get("by_status") or {}, "ast")),
                (t("tp_f_mock_n"), d.get("mock_n")),
            ]
        )
    ]
    if d.get("packs"):
        out.append(
            table(
                [
                    t("tp_f_pack"),
                    t("tp_f_status"),
                    t("tp_f_day"),
                    t("tp_f_mock"),
                    t("tp_f_items"),
                    t("tp_f_metrics"),
                ],
                [
                    [
                        x.get("pack_id"),
                        w.word("ast", x.get("status")),
                        x.get("day"),
                        w.v(x.get("is_mock")),
                        x.get("n_items"),
                        ", ".join(f"{k}={v}" for k, v in (x.get("metrics") or {}).items()),
                    ]
                    for x in d["packs"]
                ],
            )
        )
    if d.get("more"):
        out.append(para(t("tp_more", n=d["more"]), "note"))
    return out


def _judge_mrm(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_mock"), w.v(d.get("judge_is_mock"))),
                (t("tp_f_validations"), d.get("validations_n")),
                (t("tp_f_latest_decision"), d.get("latest_decision")),
                (t("tp_f_required"), w.v(d.get("validation_required"))),
            ]
        )
    ]
    if d.get("latest"):
        out.append(
            table(
                [t("tp_f_day"), t("tp_f_decision"), t("tp_f_mock"), t("tp_f_model_version")],
                [
                    [x.get("day"), x.get("decision"), w.v(x.get("is_mock")), x.get("model_version")]
                    for x in d["latest"]
                ],
            )
        )
    return out


def _masking(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    return [
        kv(
            [
                (t("tp_f_masking_on"), w.v(d.get("masking_on"))),
                (t("tp_f_masker"), d.get("masker_kind")),
                (t("tp_f_mask_version"), d.get("mask_version")),
                (t("tp_f_capture"), d.get("capture_level")),
                (t("tp_f_amounts"), w.v(d.get("amounts_masked"))),
            ]
        )
    ]


def _monitors(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [kv([(t(f"tp_mon_{k}"), w.v(v)) for k, v in sorted((d.get("flags") or {}).items())])]
    b = d.get("bindings") or {}
    if b:
        out.append(
            table(
                [t("tp_f_monitor"), t("tp_f_bound"), t("tp_f_source"), t("tp_f_gap")],
                [
                    [t(f"tp_mon_{k}"), w.v(x.get("bound")), x.get("source"), x.get("gap")]
                    for k, x in sorted(b.items())
                ],
            )
        )
    if "oversight_day" in d:
        out.append(
            kv(
                [
                    (t("tp_f_day"), d.get("oversight_day")),
                    (t("tp_f_coverage"), d.get("coverage_bp")),
                    (t("tp_f_events_seen"), d.get("events_seen")),
                    (t("tp_f_events_gated"), d.get("events_gated")),
                ]
            )
        )
    return out


def _risks(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (
                    t("tp_f_inherent"),
                    f"{d.get('inherent_score')} {w.word('lvl', d.get('inherent_level'))}",
                ),
                (
                    t("tp_f_residual"),
                    f"{d.get('residual_score')} {w.word('lvl', d.get('residual_level'))}",
                ),
                (t("tp_f_risks_n"), d.get("risks_n")),
                (t("tp_f_by_band"), w.counts(d.get("by_band") or {}, "lvl")),
                (t("tp_f_by_evidence"), w.counts(d.get("by_evidence") or {}, "rev")),
            ]
        )
    ]
    if d.get("evidence_monitors"):
        out.append(para(t("tp_evidence_rule", m=", ".join(d["evidence_monitors"])), "note"))
    if d.get("top"):
        head = [
            t("tp_f_risk"),
            t("tp_f_category"),
            t("tp_f_inherent"),
            t("tp_f_residual"),
            t("tp_f_evidence"),
            t("tp_f_links"),
            t("tp_f_via"),
        ]
        has_owner = any("owner" in x for x in d["top"])
        if has_owner:
            head.append(t("tp_f_owner"))
        rows = []
        for x in d["top"]:
            row = [
                f"{x.get('risk_id')} {x.get('title')}",
                w.t("rk_cat_" + str(x.get("category"))),
                x.get("inherent_score"),
                f"{x.get('residual_score')} {w.word('lvl', x.get('residual_band'))}",
                w.word("rev", x.get("evidence_state") or "none")
                + " ("
                + t("rk_reason_" + str(x.get("evidence_reason")))
                + ")",
                t("tp_links_val", e=x.get("evidence_links_n"), r=x.get("reference_links_n")),
                x.get("via"),
            ]
            if has_owner:
                row.append(x.get("owner"))
            rows.append(row)
        out.append(table(head, rows))
    if d.get("more"):
        out.append(para(t("tp_more", n=d["more"]), "note"))
    return out


def _controls(w: Words, d: Mapping[str, Any]) -> list[Block]:
    if not d:
        return [para(w.t("tp_controls_empty"), "note")]
    return [kv([(str(k), w.v(v)) for k, v in sorted(d.items()) if not isinstance(v, dict | list)])]


def _evidence(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    lane = d.get("lane") or {}
    root = d.get("root") or {}
    ver = d.get("verify") or {}
    rows = [
        (t("tp_f_lane"), lane.get("lane")),
        (t("tp_f_entries"), lane.get("entries")),
        (t("tp_f_head"), lane.get("head_hash")),
        (
            t("tp_f_root_key"),
            f"{w.v(root.get('key_kind'))} / {w.v(root.get('key_id'))}" if root else None,
        ),
        (t("tp_f_anchored"), w.v(d.get("anchored"))),
        (t("tp_f_verify"), w.word("ver", ver.get("state"))),
        (t("tp_f_verify_how"), w.word("how", ver.get("how"))),
        (t("tp_f_failures"), ver.get("failures")),
    ]
    out = [kv([(a, w.v(b)) for a, b in rows])]
    if ver.get("state") == "failed":
        out.append(para(t("tp_verify_failed"), "overdue"))
    return out


def _cases(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    out = [
        kv(
            [
                (t("tp_f_open"), d.get("open_n")),
                (t("tp_f_closed"), d.get("closed_n")),
                (t("tp_f_total"), d.get("total_n")),
                (t("tp_f_by_severity"), w.counts(d.get("by_severity") or {}, "sev")),
                (t("tp_f_oldest"), d.get("oldest_open_hours")),
            ]
        )
    ]
    if d.get("items"):
        head = [t("tp_f_case"), t("tp_f_severity"), t("tp_f_status"), t("tp_f_day")]
        has_sum = any("summary" in x for x in d["items"])
        if has_sum:
            head.append(t("tp_f_summary"))
        rows = []
        for x in d["items"]:
            row = [
                x.get("case_id"),
                w.word("sev", x.get("severity")),
                x.get("status"),
                x.get("opened_day"),
            ]
            if has_sum:
                row.append(x.get("summary"))
            rows.append(row)
        out.append(table(head, rows))
    if d.get("more"):
        out.append(para(t("tp_more", n=d["more"]), "note"))
    return out


def _backlog(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    if not d.get("items"):
        return [para(t("tp_backlog_none"), "note")]
    out = [
        table(
            [t("tp_f_item"), t("tp_f_returns")],
            [[x.get("item"), x.get("returns_when")] for x in d["items"]],
        )
    ]
    if d.get("more"):
        out.append(para(t("tp_more", n=d["more"]), "note"))
    return out


def _not_shown(w: Words, d: Mapping[str, Any]) -> list[Block]:
    t = w.t
    rows = []
    for x in d.get("items") or []:
        text = w.word("ns", x.get("code"))
        if x.get("n") is not None:
            text += f" ({x['n']})"
        if x.get("ref"):
            text += f" [{x['ref']}]"
        rows.append(text)
    return [{"k": "ul", "li": rows}] if rows else [para(t("tp_ns_none"), "note")]


DETAILED: dict[str, Callable[[Words, Mapping[str, Any]], list[Block]]] = {
    "identity": _identity,
    "classification": _classification,
    "inventory": _inventory,
    "compliance": _compliance,
    "cards": _cards,
    "assurance": _assurance,
    "judge_mrm": _judge_mrm,
    "masking": _masking,
    "monitors": _monitors,
    "risks": _risks,
    "controls": _controls,
    "evidence": _evidence,
    "cases": _cases,
    "backlog": _backlog,
    "not_shown": _not_shown,
}


# --------------------------------------------------------------------------- customer variant


def _customer(w: Words, sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Short plain sentences. Only what the customer allow-list lets through."""
    t = w.t

    def data(sid: str) -> Mapping[str, Any]:
        s = sections.get(sid) or {}
        return s.get("data") or {} if s.get("available") else {}

    out: list[dict[str, Any]] = []
    ident = data("identity")
    if ident:
        lines = [para(t("tp_c_what", what=t(f"tp_c_kind_{ident.get('kind') or 'other'}")))]
        o = ident.get("oversight") or {}
        if o.get("executes_payments") is True:
            lines.append(
                para(
                    t("tp_c_pay_approved")
                    if o.get("human_approval_before_execution") is True
                    else t("tp_c_pay_auto")
                    if o.get("human_approval_before_execution") is False
                    else t("tp_c_pay_unknown")
                )
            )
        if o.get("credit_decisions") is True:
            lines.append(
                para(
                    t("tp_c_credit_approved")
                    if o.get("independent_credit_approval") is True
                    else t("tp_c_credit_auto")
                )
            )
        out.append({"id": "identity", "title": t("tp_c_h_what"), "blocks": lines})
    cls = data("classification").get("decision33_class")
    if cls:
        out.append(
            {
                "id": "classification",
                "title": t("tp_c_h_class"),
                "blocks": [para(t(f"tp_c_d33_{cls}"))],
            }
        )
    prot: list[Block] = []
    if "masking_on" in data("masking"):
        prot.append(
            para(t("tp_c_mask_on") if data("masking")["masking_on"] else t("tp_c_mask_off"))
        )
    flags = data("monitors").get("flags")
    if flags is not None:
        n = sum(1 for v in flags.values() if v)
        prot.append(para(t("tp_c_monitors", n=n, m=len(flags))))
    ver = (data("evidence").get("verify") or {}).get("state")
    if ver:
        prot.append(para(t(f"tp_c_chain_{ver}"), "overdue" if ver == "failed" else ""))
    if prot:
        out.append({"id": "masking", "title": t("tp_c_h_protect"), "blocks": prot})
    r = data("risks")
    chk: list[Block] = []
    if r and not r.get("risks_n"):
        chk.append(para(t("tp_c_risks_none")))
    elif r:
        chk.append(
            para(
                t(
                    "tp_c_risks",
                    n=r.get("risks_n", 0),
                    level=w.word("lvl", r.get("residual_level")),
                )
            )
        )
        if sections["risks"].get("illustrative"):
            chk.append(para(t("tp_illustrative_note"), "mock"))
    a = data("assurance")
    if a:
        by = a.get("by_status") or {}
        chk.append(para(t("tp_c_tests", n=a.get("packs_total", 0), ok=by.get("ok", 0))))
        if a.get("mock_n"):
            chk.append(para(t("tp_c_tests_mock"), "mock"))
    if chk:
        out.append({"id": "risks", "title": t("tp_c_h_checks"), "blocks": chk})
    ns = data("not_shown")
    items = list(dict.fromkeys(w.word("ns", x.get("code")) for x in ns.get("items") or []))
    out.append(
        {
            "id": "not_shown",
            "title": t("tp_s_not_shown"),
            "blocks": [{"k": "ul", "li": items}] if items else [para(t("tp_ns_none"), "note")],
        }
    )
    return out


def to_blocks(report: Mapping[str, Any], lang: str) -> list[dict[str, Any]]:
    """The sections of ``report`` as display blocks in ``lang`` (``vi`` or ``en``)."""
    w = Words(lang)
    sections = report["sections"]
    if report["variant"] == "customer":
        return _customer(w, sections)
    out = []
    for sid in SECTIONS:
        sec = sections.get(sid)
        if sec is None:
            continue
        if not sec.get("available"):
            out.append(_sec(sid, w, sec, []))
            continue
        out.append(_sec(sid, w, sec, DETAILED[sid](w, sec.get("data") or {})))
    return out
