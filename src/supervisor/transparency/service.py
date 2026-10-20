"""TransparencyService (WP31): build, version, sign and serve reports.

``preview`` builds a report from the current facts and writes nothing. ``generate`` builds, and
when the facts changed since the last version of that (agent, variant), writes the files, one
``transparency_report`` chain record (hashes, counts and the diff to the previous version) and
the ``transparency_report`` rows (append-only), one per language. Same facts, same content hash:
a second run makes no new version unless ``force`` is set.

Files live under ``TRANSPARENCY_DIR/<agent>/<variant>/v<N>/`` and are never overwritten. On the
App the folder is ephemeral; the rows and the chain record keep the hashes, so a lost file is
visible (and the report can be built again from the facts).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import NotFoundError
from supervisor.transparency import allowlist, render
from supervisor.transparency.builder import (
    ReportBuilder,
    content_hash,
    diff_summary,
    section_hashes,
)
from supervisor.transparency.facts import Facts, Sources
from supervisor.transparency.model import (
    LANGS,
    RECORD_TYPE,
    SCHEMA_VERSION,
    VARIANTS,
    TransparencyError,
    check_agent,
    check_format,
    check_lang,
    check_variant,
    ensure_on,
)

log = logging.getLogger("supervisor.transparency")

CONTENT_TYPES = {
    "json": "application/json",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def report_id(agent_id: str, variant: str, lang: str, version: int) -> str:
    return "tr_" + sha256_hex({"a": agent_id, "v": variant, "l": lang, "n": version})[:24]


class TransparencyService:
    def __init__(
        self,
        src: Sources,
        *,
        evidence: Any = None,
        builder: ReportBuilder | None = None,
        pdf_font: Path | None = None,
    ) -> None:
        self.src = src
        self.settings = src.settings
        self.tables = src.tables
        self.evidence_sink = evidence
        self.facts = Facts(src)
        self.builder = builder or ReportBuilder(self.facts)
        self.pdf_font = pdf_font or getattr(self.settings, "casefile_pdf_font", None)

    @classmethod
    def from_adapters(
        cls, adapters: Any, evidence: Any = None, masker: Any = None
    ) -> TransparencyService:
        from supervisor.adapters.factory import make_masker

        src = Sources.from_adapters(
            adapters, chain=evidence, masker=masker or make_masker(adapters.settings)
        )
        return cls(src, evidence=evidence)

    @classmethod
    def from_context(cls, ctx: Any) -> TransparencyService:
        return cls(Sources.from_context(ctx), evidence=ctx.runtime.chain)

    # ------------------------------------------------------------------ build
    def preview(self, agent_id: str, variant: str, *, fresh_verify: bool = False) -> dict[str, Any]:
        """The report of the current facts, unsigned. The rendered text of both languages gets
        the same second check as a signed version (``live=1`` and ``lang`` cannot skip it)."""
        check_variant(variant)
        report, secrets = self._built(agent_id, variant, fresh_verify)
        check_text(report, variant, secrets)
        return report

    def _built(
        self, agent_id: str, variant: str, fresh_verify: bool
    ) -> tuple[dict[str, Any], dict[str, set[str]]]:
        self.builder.fresh_verify = fresh_verify
        return self.builder.build_pair(agent_id, variant)

    # ------------------------------------------------------------------ rows
    def rows(self, agent_id: str, variant: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"agent_id": agent_id}
        if variant:
            where["variant"] = variant
        rows = self.tables.query("transparency_report", where, order_by=("-version", "lang"))
        return [dict(r) for r in rows]

    def latest(self, agent_id: str, variant: str, lang: str | None = None) -> dict[str, Any] | None:
        rows = self.rows(agent_id, variant)
        if lang:
            rows = [r for r in rows if r["lang"] == lang]
        return rows[0] if rows else None

    def overview(self) -> list[dict[str, Any]]:
        """One line per registered agent: the latest version and date per variant."""
        out = []
        for agent in sorted(self.src.state.query("agent"), key=lambda r: str(r["agent_id"])):
            aid = str(agent["agent_id"])
            per: dict[str, Any] = {}
            for v in VARIANTS:
                row = self.latest(aid, v)
                per[v] = (
                    {
                        "version": int(row["version"]),
                        "generated_at": row["generated_at"],
                        "has_pdf": row.get("pdf_hash") is not None,
                        "verify_state": row["verify_state"],
                        "sections_available": int(row["sections_available"]),
                        "sections_total": int(row["sections_total"]),
                    }
                    if row
                    else None
                )
            out.append(
                {
                    "agent_id": aid,
                    "name": agent.get("name"),
                    "status": agent.get("status"),
                    "variants": per,
                }
            )
        return out

    # ------------------------------------------------------------------ files
    def _dir(self, agent_id: str, variant: str, version: int) -> Path:
        return Path(self.settings.transparency_dir) / agent_id / variant / f"v{version}"

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as fh:  # never overwrite
            fh.write(data)

    # ------------------------------------------------------------------ generate
    def generate(
        self,
        agent_id: str,
        variants: tuple[str, ...] = VARIANTS,
        *,
        actor: str,
        force: bool = False,
        fresh_verify: bool = True,
    ) -> list[dict[str, Any]]:
        """Build and sign the reports of ``agent_id``. One result per variant:
        ``made`` (new version), ``unchanged`` (facts equal the last version)."""
        ensure_on(self.settings)
        check_agent(agent_id)
        out = []
        for variant in variants:
            check_variant(variant)
            out.append(self._generate_one(agent_id, variant, actor, force, fresh_verify))
        return out

    def _generate_one(
        self, agent_id: str, variant: str, actor: str, force: bool, fresh_verify: bool
    ) -> dict[str, Any]:
        report, secrets = self._built(agent_id, variant, fresh_verify)
        chash = content_hash(report)
        prev = self.latest(agent_id, variant)
        if prev is not None and prev["content_hash"] == chash and not force:
            return {
                "agent_id": agent_id,
                "variant": variant,
                "status": "unchanged",
                "version": int(prev["version"]),
                "content_hash": chash,
            }
        version = (int(prev["version"]) if prev else 0) + 1
        report["report_version"] = version
        report["status"] = "signed"
        json_bytes = render.render_json(report)
        files: dict[str, bytes] = {"report.json": json_bytes}
        html_hash: dict[str, str] = {}
        pdf_hash: dict[str, str | None] = {}
        notices: list[str] = []
        check_text(report, variant, secrets)
        for lang in LANGS:
            html = render.render_html(report, lang)
            files[f"report.{lang}.html"] = html
            html_hash[lang] = _sha(html)
            res = render.render_pdf(report, lang, font_path=self.pdf_font)
            if res.fmt == "pdf":
                files[f"report.{lang}.pdf"] = res.data
                pdf_hash[lang] = _sha(res.data)
            else:
                pdf_hash[lang] = None
                notices.append(res.notice or "no PDF")
        sec_hashes = section_hashes(report)
        diff = diff_summary(prev_section_hashes(prev), sec_hashes)
        avail = sum(1 for s in report["sections"].values() if s["available"])
        verify = ((report["sections"].get("evidence") or {}).get("data") or {}).get("verify")
        verify_state = (verify or {}).get("state") or "not_run"
        folder = self._dir(agent_id, variant, version)
        try:
            for name, data in files.items():
                self._write(folder / name, data)
        except FileExistsError:
            raise TransparencyError(
                f"refusing to overwrite an existing report file in {folder.name}"
            ) from None
        by = actor_ref(self.settings, actor)  # R2: no person id in the chain or the evidence row
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "variant": variant,
            "version": version,
            "schema_version": SCHEMA_VERSION,
            "content_hash": chash,
            "json_sha256": _sha(json_bytes),
            "json_bytes": len(json_bytes),
            "sections_total": len(report["sections"]),
            "sections_available": avail,
            "verify_state": verify_state,
            "prev_version": int(prev["version"]) if prev else 0,
            "diff_first": bool(diff["first"]),
            "diff_changed_n": len(diff["changed"]),
            "diff_added_n": len(diff["added"]),
            "diff_removed_n": len(diff["removed"]),
            "diff_changed": diff["changed"],
            "generated_by": by,
            "ts": report["generated_at"],
        }
        for lang in LANGS:
            payload[f"html_sha256_{lang}"] = html_hash[lang]
            if pdf_hash[lang]:
                payload[f"pdf_sha256_{lang}"] = pdf_hash[lang]
        chain_hash: str | None = None
        if self.evidence_sink is not None:
            try:
                chain_hash = str(
                    self.evidence_sink.record(
                        RECORD_TYPE, f"transparency:{agent_id}:{variant}:{version}", payload
                    )
                )
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)  # not in the chain: do not keep it
                raise
        now = self.src.clock.now()
        new_rows = [
            {
                "report_id": report_id(agent_id, variant, lang, version),
                "agent_id": agent_id,
                "variant": variant,
                "lang": lang,
                "version": version,
                "schema_version": SCHEMA_VERSION,
                "generated_at": now,
                "generated_by": by,
                "content_hash": chash,
                "json_hash": _sha(json_bytes),
                "html_hash": html_hash[lang],
                "pdf_hash": pdf_hash[lang],
                "sections_total": len(report["sections"]),
                "sections_available": avail,
                "section_hashes": sec_hashes,
                "verify_state": verify_state,
                "chain_hash": chain_hash,
            }
            for lang in LANGS
        ]
        self.tables.append("transparency_report", new_rows)
        return {
            "agent_id": agent_id,
            "variant": variant,
            "status": "made",
            "version": version,
            "content_hash": chash,
            "json_hash": _sha(json_bytes),
            "diff": diff,
            "chain_hash": chain_hash,
            "verify_state": verify_state,
            "notices": sorted(set(notices)),
            "generated_at": format_ts(now),
        }

    # ------------------------------------------------------------------ serve
    def report(
        self, agent_id: str, variant: str, *, live: bool = False
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """(report data, info) for the console: the latest signed JSON (checked against the hash
        of its row), else a PREVIEW from the current facts. The data can be rendered in either
        language with ``render.document``."""
        check_agent(agent_id)
        check_variant(variant)
        row = None if live else self.latest(agent_id, variant)
        if row is None:
            return self.preview(agent_id, variant), {"status": "preview", "version": 0}
        path = self._dir(agent_id, variant, int(row["version"])) / "report.json"
        try:
            data = path.read_bytes()
        except OSError:
            raise NotFoundError(
                "the stored file is gone (the App wipes /tmp on restart); generate again"
            ) from None
        if _sha(data) != row["json_hash"]:
            raise TransparencyError("the stored file does not match its recorded hash")
        return json.loads(data.decode("utf-8")), {
            "status": "signed",
            "version": int(row["version"]),
            "hash": row["json_hash"],
        }

    def read(
        self, agent_id: str, variant: str, fmt: str, lang: str = "en", *, live: bool = False
    ) -> tuple[bytes, str, dict[str, Any]]:
        """(bytes, content type, info). The latest signed file when there is one (checked
        against the hash in its row); else a PREVIEW built from the current facts."""
        check_agent(agent_id)
        check_variant(variant)
        check_format(fmt)
        check_lang(lang)
        row = None if live else self.latest(agent_id, variant, lang)
        if row is not None:
            name = "report.json" if fmt == "json" else f"report.{lang}.{fmt}"
            want = row[{"json": "json_hash", "html": "html_hash", "pdf": "pdf_hash"}[fmt]]
            if want is None:
                raise TransparencyError("no PDF was made for this version (fpdf2 or font missing)")
            path = self._dir(agent_id, variant, int(row["version"])) / name
            try:
                data = path.read_bytes()
            except OSError:
                raise NotFoundError(
                    "the stored file is gone (the App wipes /tmp on restart); generate again"
                ) from None
            if _sha(data) != want:
                raise TransparencyError("the stored file does not match its recorded hash")
            return (
                data,
                CONTENT_TYPES[fmt],
                {"status": "signed", "version": int(row["version"]), "hash": want},
            )
        report = self.preview(agent_id, variant)
        if fmt == "json":
            data = render.render_json(report)
        elif fmt == "html":
            data = render.render_html(report, lang)
        else:
            res = render.render_pdf(report, lang, font_path=self.pdf_font)
            if res.fmt != "pdf":
                raise TransparencyError(res.notice or "no PDF could be made")
            data = res.data
        return data, CONTENT_TYPES[fmt], {"status": "preview", "version": 0, "hash": _sha(data)}


# Actors that are a role of the product, not a person: kept as they are on the chain.
SYSTEM_ACTORS = ("system:", "cli:", "job:")


def actor_ref(settings: Any, actor: str) -> str:
    """The actor as the chain may hold it (R2): a product role (``system:...``, ``cli:...``)
    as it is, a person as a keyed hash (an id can be an e-mail). The ``console_action`` audit
    row keeps the readable actor; the chain record and the append-only ``transparency_report``
    row (kept for years, no text) hold this ref. Same actor, same ref."""
    import hmac

    if actor.startswith(SYSTEM_ACTORS):
        return actor
    key, _ = settings.mask_key
    return "act_" + hmac.new(key, f"tr-actor:{actor}".encode(), hashlib.sha256).hexdigest()[:16]


def leaks(text: str, variant: str, secrets: dict[str, set[str]]) -> list[str]:
    """Why the rendered text may not be shown to ``variant`` (the second check, on the words)."""
    if variant == "internal":
        return []
    people = secrets["people"] if variant == "customer" else secrets["people"] - secrets["team"]
    return allowlist.text_leaks(
        text, variant, {"ids": secrets["ids"], "people": people}, digits=False
    )


def check_text(report: dict[str, Any], variant: str, secrets: dict[str, set[str]]) -> None:
    """The second check on the words of both languages (TransparencyError, HTTP 400)."""
    for lang in LANGS:
        bad = leaks(render.plain_text(report, lang), variant, secrets)
        if bad:
            raise TransparencyError(f"allow-list leak in the {lang} text: {bad[0]}")


def prev_section_hashes(row: dict[str, Any] | None) -> dict[str, str] | None:
    if row is None:
        return None
    sh = row.get("section_hashes")
    if isinstance(sh, str):
        sh = json.loads(sh)
    return dict(sh) if isinstance(sh, dict) else None
