"""The regulator pack of one AI system (WP-L4, flag ``REGULATOR_PACK``).

One pack per system, as signed JSON and as HTML, built offline from the ``obligation_status``
rows, RegKB and the live evidence counts of ``duty_evidence``. No customer data, no personal
data (owners appear by role name only, typed free text appears only as a hash), no floats.

Content:

* header: system name and id, Decision 33 class, lifecycle stage, autonomy level, owner roles,
  generated at, RegKB version hash, pack version, the evidence window;
* one section per instrument: article, obligation id, duty, the verbatim ``text_vi`` quote from
  RegKB, applies, coverage, status, closing control, evidence counts per control, pointers (row
  ids), confirmed by (the person who confirmed a law-agent draft, as a keyed reference, else
  "RegKB data 2026-10-15") and the date;
* a summary: counts by status and coverage, the gap closure score;
* the banner "Not legal advice. Bank counsel must confirm." on every page and in the JSON.

The JSON carries ``content_sha256`` (SHA-256 of its canonical JSON without the signature block)
and an Ed25519 ``signature`` of the evidence signer over a fixed prefix and that hash. The offline
verifier (``python -m supervisor.evidence.verify regulator-pack.json``) checks both. A record of
the hash is also written to the evidence chain.

CLI: ``python -m supervisor.governance.regulator_pack --system <id> --out <dir>`` writes
``regulator-pack.json``, ``regulator-pack.html`` and ``public_key.pem``.

Advisory only. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.governance import duties_gap as dg
from supervisor.governance import duty_evidence as de

log = logging.getLogger("supervisor.governance")

PACK_FORMAT = "supervisor.regulator_pack"
PACK_VERSION = 1
BANNER = dg.BANNER
DEFAULT_CONFIRMED = "RegKB data 2026-10-15"
MAX_QUOTE = 4000
STATUSES = ("open", "closed", "waived")
COVERAGES = ("full", "partial", "none", "unknown")
APPLIES = ("yes", "needs_answer", "no")
JSON_NAME = "regulator-pack.json"
HTML_NAME = "regulator-pack.html"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str:
    d = dg.as_date(value)
    return d.isoformat() if d else ""


# ------------------------------------------------------------------------------ build


def _drafts(state: Any) -> list[dict[str, Any]]:
    try:
        return [dict(r) for r in state.query("regkb_draft", {"status": "confirmed"})]
    except Exception:  # noqa: BLE001 - a store before WP-L1
        return []


def _confirmation(env: de.Env, ob: Any, drafts: list[dict[str, Any]]) -> tuple[str, str]:
    """``(confirmed_by, confirmed_on)``. A duty that came from a confirmed law-agent draft names
    the confirmer as a keyed reference (an id can be an e-mail); any other duty is RegKB data."""
    from supervisor.transparency.service import actor_ref

    quote = (getattr(ob, "text_vi", None) or "").strip()
    draft = next(
        (
            d
            for d in drafts
            if d["instrument_id"] == ob.instrument_id
            and quote
            and str(d["text_vi"]).strip() == quote
        ),
        None,
    )
    who = getattr(ob, "confirmed_by", None) or (draft or {}).get("confirmed_by")
    if not who:
        return DEFAULT_CONFIRMED, ""
    on = _iso((draft or {}).get("confirmed_at"))
    return actor_ref(env.settings, str(who)), on


def _owner_roles(system: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Owner roles of the system by role name and head count. No person id."""
    counts: dict[str, int] = {}
    for m in system.get("team") or []:
        role = str(m.get("team_role") or "")
        if role:
            counts[role] = counts.get(role, 0) + 1
    if system.get("owner_user"):
        counts["system_owner"] = max(1, counts.get("system_owner", 0))
    return [{"role": r, "n": n} for r, n in sorted(counts.items())]


def build(env: de.Env, system: Mapping[str, Any]) -> dict[str, Any]:
    """The unsigned pack (a plain dict of strings, booleans, integers, lists and dicts)."""
    sid = str(system["system_id"])
    kb = dg.kb_of(env.settings)
    rows = dg.rows_of(env.state, sid)
    w = env.window()
    found = de.system_evidence(env, sid, rows, kb)
    drafts = _drafts(env.state)
    now = env.clock.now()
    by_inst: dict[str, list[dict[str, Any]]] = {}
    by_status = dict.fromkeys(STATUSES, 0)
    by_cov = dict.fromkeys(COVERAGES, 0)
    by_applies = dict.fromkeys(APPLIES, 0)
    matrix = {c: dict.fromkeys(STATUSES, 0) for c in COVERAGES}
    marks = {"works": 0, "no_evidence": 0, "none": 0}
    for r in rows:
        oid = str(r["obligation_id"])
        ob = kb.obligations.get(oid)
        info = found.get(oid) or {"controls": [], "mapped": 0, "all_work": False}
        mark = "none" if not info["mapped"] else "works" if info["all_work"] else "no_evidence"
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_cov[r["coverage"]] = by_cov.get(r["coverage"], 0) + 1
        by_applies[r["applies"]] = by_applies.get(r["applies"], 0) + 1
        if r["coverage"] in matrix and r["status"] in STATUSES:
            matrix[r["coverage"]][r["status"]] += 1
        marks[mark] += 1
        by, on = _confirmation(env, ob, drafts) if ob is not None else (DEFAULT_CONFIRMED, "")
        text = de.split_note(r["note"])
        evidence = [
            {
                "control_id": c["id"],
                "kind": c["kind"],
                "coverage": c["coverage"],
                "count": int(c["n"]),
                "works": bool(c["works"]),
                "advisory": bool(c["advisory"]),
                "measured": bool(c["measured"]),
                "source": c["source"],
            }
            for c in info["controls"]
        ]
        gap_task = (
            _task_id(sid, str(r["instrument_id"]), str(r["coverage"]))
            if r["coverage"] in ("partial", "none")
            else ""
        )
        by_inst.setdefault(str(r["instrument_id"]), []).append(
            {
                "obligation_id": oid,
                "article": getattr(ob, "article_ref", ""),
                "duty": getattr(ob, "summary_en", ""),
                "text_vi": (getattr(ob, "text_vi", None) or "")[:MAX_QUOTE],
                "applies": r["applies"],
                "coverage": r["coverage"],
                "status": r["status"],
                "closing_control": r["closing_control"] or "",
                "closed_by": de.close_basis(r),
                # the typed evidence reference or waive reason is free text: only its hash
                "note_sha256": _sha(text)[:16] if r["status"] != "open" and text else "",
                "due": _iso(r["due_date"]),
                "works": mark,
                "evidence": evidence,
                "pointers": {
                    "status_id": r["status_id"],
                    "gap_task_id": gap_task,
                    "sources": sorted({e["source"] for e in evidence}),
                },
                "confirmed_by": by,
                "confirmed_on": on or "",
            }
        )
    instruments = []
    for iid in sorted(by_inst):
        inst = None
        try:
            inst = kb.instrument(iid)
        except Exception:  # noqa: BLE001 - an instrument RegKB no longer knows
            inst = None
        instruments.append(
            {
                "instrument_id": iid,
                "number": getattr(inst, "number", iid),
                "title_en": getattr(inst, "title_en", ""),
                "binding": bool(getattr(inst, "binding", False)),
                "duties": sorted(by_inst[iid], key=lambda d: (d["coverage"], d["obligation_id"])),
            }
        )
    score = dg.score(rows)
    risk = system.get("effective_risk") or {}
    return {
        "format": PACK_FORMAT,
        "pack_version": PACK_VERSION,
        "banner": BANNER,
        "header": {
            "system_id": sid,
            "name": str(system.get("name") or ""),
            "decision33_class": str(system.get("decision33_class") or ""),
            "risk_level": str(risk.get("level") or system.get("risk_level") or ""),
            "lifecycle_stage": str(system.get("lifecycle_stage") or ""),
            "autonomy_level": str(system.get("autonomy_level") or ""),
            "owners": _owner_roles(system),
            "generated_at": format_ts(now),
            "regkb_version": str(kb.version),
            "window": {
                "start": format_ts(w.start),
                "end": format_ts(w.end),
                "days": int(env.settings.duty_evidence_window_days),
                "min_rows": int(env.settings.duty_evidence_min_rows),
            },
        },
        "summary": {
            "rows": len(rows),
            "by_status": by_status,
            "by_coverage": by_cov,
            "by_applies": by_applies,
            "coverage_by_status": matrix,
            "gap_closure_pct": score["pct"],
            "closed": score["closed"],
            "open": score["open"],
            "waived": score["waived"],
            "closed_by_evidence": sum(
                1 for r in rows if r["status"] == "closed" and de.close_basis(r) == "evidence"
            ),
            "controls_work": marks["works"],
            "controls_no_evidence": marks["no_evidence"],
            "no_supervisor_control": marks["none"],
        },
        "instruments": instruments,
    }


def _task_id(system_id: str, instrument_id: str, coverage: str) -> str:
    from supervisor.tasks.service import task_id_for

    return task_id_for(system_id, de.group_template(instrument_id, coverage))


# ------------------------------------------------------------------------------ sign


def content_hash(pack: Mapping[str, Any]) -> str:
    body = {k: v for k, v in pack.items() if k not in ("content_sha256", "signature")}
    return sha256_hex(body)


def sign(pack: dict[str, Any], signer: Any) -> dict[str, Any]:
    """Add ``content_sha256`` and the Ed25519 ``signature`` of the evidence signer."""
    from supervisor.evidence.verify import PACK_SIGNING_PREFIX

    digest = content_hash(pack)
    raw = signer.sign(PACK_SIGNING_PREFIX + digest.encode("ascii"))
    pem = getattr(signer, "public_key_pem", None)
    pack["content_sha256"] = digest
    pack["signature"] = {
        "algorithm": getattr(signer, "algorithm", "ed25519"),
        "key_id": signer.key_id,
        "key_kind": getattr(signer, "key_kind", "dev"),
        "signature": base64.b64encode(raw).decode("ascii"),
        "public_key": (pem() if callable(pem) else str(pem or "")),
    }
    return pack


def generate(env: de.Env, system: Mapping[str, Any], signer: Any) -> dict[str, Any]:
    """Build, sign and record one pack. The chain record holds the hash and the counts only."""
    pack = sign(build(env, system), signer)
    if env.sink is not None:
        try:
            env.sink.record(
                "regulator_pack",
                f"regulator_pack:{pack['header']['system_id']}:{pack['content_sha256'][:16]}",
                {
                    "system_id": pack["header"]["system_id"],
                    "content_sha256": pack["content_sha256"],
                    "pack_version": PACK_VERSION,
                    "rows": int(pack["summary"]["rows"]),
                    "regkb_version": pack["header"]["regkb_version"],
                    "key_id": pack["signature"]["key_id"],
                    "ts": pack["header"]["generated_at"],
                },
            )
        except Exception:  # noqa: BLE001 - the pack is still valid; log and go on
            log.exception("regulator pack chain record failed")
    return pack


def generate_for_console(ctx: Any, system_id: str) -> dict[str, Any]:
    """The pack for a console or API request (the caller has checked scope and permission)."""
    de.ensure_on(ctx.settings)
    system = ctx.systems.get(system_id)
    return generate(de.Env.from_console(ctx), system, ctx.runtime.chain.signer)


def to_json_bytes(pack: Mapping[str, Any]) -> bytes:
    return (json.dumps(pack, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ------------------------------------------------------------------------------ html

_CSS = """
body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;color:#1b1f24;background:#fff}
main{max-width:1100px;margin:0 auto;padding:72px 24px 56px}
.banner{position:fixed;top:0;left:0;right:0;background:#fff4d6;border-bottom:2px solid #c98a00;
 padding:8px 24px;font-weight:600;z-index:2}
.foot{margin-top:32px;padding-top:8px;border-top:2px solid #c98a00;font-weight:600}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 6px;border-bottom:1px solid #ccd}
table{border-collapse:collapse;width:100%;margin:6px 0 14px}
th,td{border:1px solid #ccd;padding:4px 7px;text-align:left;vertical-align:top;font-size:13px}
th{background:#f1f3f8}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
blockquote{margin:4px 0;padding:4px 10px;border-left:3px solid #99a;background:#f7f8fb}
.ok{color:#14702e;font-weight:600}.warn{color:#9a5b00;font-weight:600}.mute{color:#667}
.duty{break-inside:avoid;border:1px solid #ccd;margin:8px 0;padding:6px 10px}
@media print{.banner{position:fixed}.duty{page-break-inside:avoid}main{padding-top:48px}}
"""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _mark_text(mark: str) -> str:
    return {"works": "works", "no_evidence": "no evidence", "none": "no Supervisor control"}.get(
        mark, mark
    )


def render_html(pack: Mapping[str, Any]) -> str:
    """The pack as one self-contained HTML page (no script, no external file)."""
    h, s = pack["header"], pack["summary"]
    out: list[str] = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        f"<title>Regulator pack {_e(h['name'])}</title>",
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<style>{_CSS}</style></head><body>",
        f'<div class="banner" data-banner="top">{_e(BANNER)}</div><main>',
        f"<h1>Regulator pack: {_e(h['name'])}</h1>",
        "<table><tbody>",
    ]
    owners = ", ".join(f"{_e(o['role'])} ({int(o['n'])})" for o in h["owners"]) or "-"
    for k, v in (
        ("System id", h["system_id"]),
        ("Decision 33 class", h["decision33_class"] or "-"),
        ("Risk level", h["risk_level"] or "-"),
        ("Lifecycle stage", h["lifecycle_stage"] or "-"),
        ("Autonomy level", h["autonomy_level"] or "-"),
        ("Generated at", h["generated_at"]),
        ("RegKB version", h["regkb_version"]),
        ("Pack version", pack["pack_version"]),
        (
            "Evidence window",
            f"{h['window']['start']} to {h['window']['end']} "
            f"({h['window']['days']} days, at least {h['window']['min_rows']} row(s) per control)",
        ),
    ):
        out.append(f'<tr><th scope="row">{_e(k)}</th><td class="mono">{_e(v)}</td></tr>')
    out.append(f'<tr><th scope="row">Owner roles</th><td>{owners}</td></tr></tbody></table>')
    out.append("<h2>Summary</h2><table><thead><tr><th>Coverage</th>")
    out.extend(f"<th>{_e(st)}</th>" for st in STATUSES)
    out.append("</tr></thead><tbody>")
    for cov in COVERAGES:
        cells = "".join(f"<td>{int(s['coverage_by_status'][cov][st])}</td>" for st in STATUSES)
        out.append(f"<tr><th scope='row'>{_e(cov)}</th>{cells}</tr>")
    pct = s["gap_closure_pct"]
    out.append(
        "</tbody></table><table><tbody>"
        f"<tr><th scope='row'>Gap closure score</th><td data-score='1'>"
        f"{'-' if pct is None else str(int(pct)) + '%'} ({int(s['closed'])} closed, "
        f"{int(s['open'])} open, {int(s['waived'])} waived)</td></tr>"
        f"<tr><th scope='row'>Closed by evidence</th><td>{int(s['closed_by_evidence'])}</td></tr>"
        f"<tr><th scope='row'>Controls working / no evidence / no Supervisor control</th>"
        f"<td>{int(s['controls_work'])} / {int(s['controls_no_evidence'])} / "
        f"{int(s['no_supervisor_control'])}</td></tr></tbody></table>"
    )
    for inst in pack["instruments"]:
        out.append(
            f"<h2>{_e(inst['number'])} <span class='mute'>{_e(inst['title_en'])}</span></h2>"
        )
        for d in inst["duties"]:
            mark = d["works"]
            out.append(f'<div class="duty" data-obligation="{_e(d["obligation_id"])}">')
            out.append(
                f"<div><b class='mono'>{_e(d['obligation_id'])}</b> {_e(d['article'])}: "
                f"{_e(d['duty'])}</div>"
            )
            if d["text_vi"]:
                out.append(f'<blockquote lang="vi">{_e(d["text_vi"])}</blockquote>')
            out.append(
                f"<div>applies <b>{_e(d['applies'])}</b>, coverage <b>{_e(d['coverage'])}</b>, "
                f"status <b>{_e(d['status'])}</b>"
                + (f" ({_e(d['closed_by'])})" if d["closed_by"] else "")
                + f", closing control <span class='mono'>{_e(d['closing_control'] or '-')}</span>"
                + (f", due {_e(d['due'])}" if d["due"] else "")
                + f" - <span class='{'ok' if mark == 'works' else 'warn'}'>"
                f"{_e(_mark_text(mark))}</span></div>"
            )
            if d["evidence"]:
                out.append("<table><thead><tr><th>Control</th><th>Kind</th><th>Coverage</th>")
                out.append(
                    "<th>Rows in window</th><th>Source</th><th>State</th></tr></thead><tbody>"
                )
                for e in d["evidence"]:
                    state = (
                        "advisory"
                        if e["advisory"]
                        else "works"
                        if e["works"]
                        else "unmeasured"
                        if not e["measured"]
                        else "no evidence"
                    )
                    out.append(
                        f"<tr><td class='mono'>{_e(e['control_id'])}</td><td>{_e(e['kind'])}</td>"
                        f"<td>{_e(e['coverage'])}</td><td>{int(e['count'])}</td>"
                        f"<td>{_e(e['source'])}</td><td>{_e(state)}</td></tr>"
                    )
                out.append("</tbody></table>")
            p = d["pointers"]
            out.append(
                f"<div class='mute'>pointers: <span class='mono'>{_e(p['status_id'])}</span>"
                + (
                    f", task <span class='mono'>{_e(p['gap_task_id'])}</span>"
                    if p["gap_task_id"]
                    else ""
                )
                + f" | confirmed by {_e(d['confirmed_by'])}"
                + (f" on {_e(d['confirmed_on'])}" if d["confirmed_on"] else "")
                + (f" | note sha256 {_e(d['note_sha256'])}" if d["note_sha256"] else "")
                + "</div></div>"
            )
    sig = pack.get("signature") or {}
    out.append(
        f'<div class="foot" data-banner="bottom">{_e(BANNER)}</div>'
        f"<p class='mono mute'>content sha256 {_e(pack.get('content_sha256', ''))}; "
        f"signed by key {_e(str(sig.get('key_id', ''))[:16])} ({_e(sig.get('key_kind', ''))}). "
        "Verify the JSON offline: python -m supervisor.evidence.verify regulator-pack.json</p>"
        "</main></body></html>"
    )
    return "\n".join(out)


# ------------------------------------------------------------------------------ CLI


def write_files(pack: Mapping[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        JSON_NAME: to_json_bytes(pack),
        HTML_NAME: render_html(pack).encode("utf-8"),
        "public_key.pem": str((pack.get("signature") or {}).get("public_key", "")).encode("ascii"),
    }
    paths = []
    for name, data in files.items():
        p = out_dir / name
        p.write_bytes(data)
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.governance.regulator_pack", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--system", required=True, help="AI system id")
    ap.add_argument("--out", required=True, help="directory for the pack files")
    args = ap.parse_args(argv)
    from supervisor.core.errors import SupervisorError
    from supervisor.monitors.jobctx import ascii_line, standalone

    try:
        with standalone() as (settings, adapters, mctx):
            if not de.enabled(settings):
                print("[SKIP] the regulator pack is off (REGULATOR_PACK=1 turns it on)")  # noqa: T201
                return 0
            from supervisor.governance.systems import SystemService

            svc = SystemService.from_adapters(adapters, evidence=mctx.evidence)
            system = svc.get(args.system)
            pack = generate(de.Env.from_job(mctx, settings), system, mctx.evidence.signer)
            paths = write_files(pack, Path(args.out))
    except SupervisorError as exc:
        print(ascii_line(f"[FAIL] regulator_pack: {exc}"))  # noqa: T201
        return 1
    print(ascii_line("[OK] regulator_pack: " + ", ".join(str(p) for p in paths)))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
