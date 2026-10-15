"""Dependency and supply-chain runners (WP17, dimension ``dependency``).

Six runners, all offline and deterministic. They read the target's dependency files
(``target.dependency_files()``), its model inventory and its tool manifest. A runner
returns integer metrics; the engine applies the manifest thresholds.

* :class:`SbomRunner`            - own CycloneDX 1.5 JSON writer.
* :class:`OsvRunner`             - matcher against a bank-supplied offline OSV snapshot.
* :class:`LicenceRunner`         - licence allow list from installed metadata + override file.
* :class:`PinHashRunner`         - exact pins and sha256 hashes.
* :class:`ModelInventoryRunner`  - model pinning, region, vendor concentration.
* :class:`McpDriftRunner`        - tool manifest hash drift, undeclared tools, tool poisoning.

Synthetic data (``data/assurance/synthetic/...``) uses FAKE package names and FAKE advisory
ids (``SYN-2026-NNNN``) with known answers. It proves that the matchers work; it says
nothing about the real dependency set.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import re
import unicodedata
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supervisor.assurance import versions
from supervisor.assurance.depfiles import Component, DepSet, load_depset, normalise_name
from supervisor.assurance.model import EvalPack, RunContext, RunnerOutput
from supervisor.assurance.textutil import bp, sha256_lines

SYNTHETIC_DIR = Path("data") / "assurance" / "synthetic"
DEFAULT_ALLOW = "MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,PSF-2.0,ISC,Unlicense,0BSD,MPL-2.0".split(
    ","
)
SYNTHETIC_NOTE = (
    "synthetic data with fake packages and fake advisory ids: this proves the matcher works, "
    "not the real dependency set"
)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- selection


@dataclass
class Selected:
    deps: DepSet
    data_mode: str
    dataset_id: str
    dataset_sha256: str


def _synthetic_dir(ctx: RunContext) -> Path:
    return ctx.repo_root / SYNTHETIC_DIR


def _components_sha(deps: DepSet) -> str:
    return sha256_lines(
        [f"{c.name}=={c.version}|{','.join(c.hashes)}" for c in deps.sorted_components()]
    )


def select_deps(
    pack: EvalPack, ctx: RunContext, *, need_lock: bool = False
) -> Selected | RunnerOutput:
    """Pick the dependency set for a pack, or return a skip."""
    target = ctx.target
    if ctx.data_mode == "vendored":
        return RunnerOutput.skip(f"{pack.id}: no vendored sample exists for this pack")
    if ctx.data_mode == "synthetic":
        lock = _synthetic_dir(ctx) / "deps" / "uv.lock"
        deps = load_depset([lock])
        if not deps.components:
            return RunnerOutput.skip(f"synthetic lock missing or empty: {lock}")
        return Selected(deps, "synthetic", "synthetic:deps/uv.lock", _components_sha(deps))
    if getattr(target, "kind", "") not in ("agent", "judge"):
        return RunnerOutput.skip("target has no dependency files (needs an agent or judge target)")
    caps = getattr(target, "capabilities", None)
    if caps is not None and "deps" not in caps:
        return RunnerOutput.skip("target lacks the 'deps' capability")
    paths = list(target.dependency_files())
    if not paths:
        return RunnerOutput.skip("target returned no dependency files")
    deps = load_depset(paths)
    if not deps.components:
        why = "; ".join(deps.errors) or "no dependencies found"
        return RunnerOutput.skip(f"no usable dependency data: {why}")
    return Selected(deps, "bank_supplied_path", f"deps:{target.target_id}", _components_sha(deps))


def _base(sel: Selected, ctx: RunContext, **kw: Any) -> dict[str, Any]:
    return {
        "data_mode": sel.data_mode,
        "dataset_id": sel.dataset_id,
        "dataset_sha256": sel.dataset_sha256,
        "n_items": len(sel.deps.components),
        "is_mock": bool(getattr(ctx.target, "is_mock", False)),
        **kw,
    }


def _details(sel: Selected, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"files": list(sel.deps.files), "parse_errors": list(sel.deps.errors)}
    if sel.data_mode == "synthetic":
        out["note"] = SYNTHETIC_NOTE
    out.update(kw)
    return out


# --------------------------------------------------------------------------- 1. SBOM


def purl_of(c: Component) -> str:
    name = c.name  # PEP 503 form is lower case with hyphens, as the purl PyPI type wants
    return f"pkg:pypi/{name}@{c.version}" if c.version else f"pkg:pypi/{name}"


def build_sbom(
    components: list[Component], target_id: str, now: datetime, *, tool_version: str = "1"
) -> dict[str, Any]:
    """CycloneDX 1.5 JSON document (own writer; spec: cyclonedx.org/docs/1.5/json/)."""
    rows: list[dict[str, Any]] = []
    for c in sorted(components, key=lambda x: (x.name, x.version)):
        row: dict[str, Any] = {
            "type": "library",
            "bom-ref": purl_of(c),
            "name": c.name,
            "purl": purl_of(c),
            "properties": [
                {"name": "supervisor:direct", "value": "true" if c.is_direct else "false"},
                {"name": "supervisor:source", "value": c.source},
            ],
        }
        if c.version:
            row["version"] = c.version
        if c.hashes:
            row["hashes"] = [{"alg": "SHA-256", "content": h} for h in c.hashes]
        rows.append(row)
    seen: set[str] = set()
    uniq = []
    for r in rows:
        if r["bom-ref"] not in seen:
            seen.add(r["bom-ref"])
            uniq.append(r)
    content_hash = _sha(_canon(uniq))
    serial = uuid.UUID(hex=content_hash[:32], version=5)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "supervisor-assurance",
                        "version": tool_version,
                    }
                ]
            },
            "component": {
                "type": "application",
                "name": target_id,
                "bom-ref": f"target:{target_id}",
            },
        },
        "components": uniq,
    }


def validate_sbom(doc: Mapping[str, Any]) -> list[str]:
    """Structural check of the keys CycloneDX 1.5 requires; returns problems."""
    bad: list[str] = []
    if doc.get("bomFormat") != "CycloneDX":
        bad.append("bomFormat")
    if doc.get("specVersion") != "1.5":
        bad.append("specVersion")
    if not re.fullmatch(
        r"urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        str(doc.get("serialNumber", "")),
    ):
        bad.append("serialNumber")
    if not isinstance(doc.get("version"), int) or doc["version"] < 1:
        bad.append("version")
    for i, c in enumerate(doc.get("components", [])):
        if c.get("type") not in {"library", "application", "framework"} or not c.get("name"):
            bad.append(f"components[{i}]")
        for h in c.get("hashes", []):
            if h.get("alg") != "SHA-256" or not re.fullmatch(r"[0-9a-f]{64}", h.get("content", "")):
                bad.append(f"components[{i}].hashes")
    return bad


class SbomRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        sel = select_deps(pack, ctx)
        if isinstance(sel, RunnerOutput):
            return sel
        now = ctx.now or datetime.now(UTC)
        doc = build_sbom(sel.deps.sorted_components(), ctx.target.target_id, now)
        total = len(doc["components"])
        with_purl = sum(1 for c in doc["components"] if "@" in c["purl"])
        with_hash = sum(1 for c in doc["components"] if c.get("hashes"))
        text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        written = ""
        out_dir = ctx.extras.get("out_dir")
        if out_dir:
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(ctx.target.target_id))
            p = Path(out_dir) / f"sbom-{safe}.cdx.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            written = p.name
        return RunnerOutput(
            status="ok",
            metrics={
                "components_count": total,
                "components_with_purl_bp": bp(with_purl, total),
                "components_with_hash_bp": bp(with_hash, total),
            },
            details=_details(
                sel,
                serial_number=doc["serialNumber"],
                sbom_sha256=_sha(text),
                sbom_file=written,
                spec_version="1.5",
            ),
            **_base(sel, ctx),
        )


# --------------------------------------------------------------------------- 2. OSV


_SEV_ORDER = {"UNKNOWN": 0, "LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_MAX_OSV_MEMBER = 5 * 1024 * 1024
_MAX_OSV_FILES = 300_000


@dataclass
class OsvEntry:
    adv_id: str
    aliases: tuple[str, ...]
    severity: str
    versions: tuple[str, ...]
    ranges: tuple[tuple[dict[str, str], ...], ...]  # ECOSYSTEM ranges: tuple of event dicts

    def hits(self, version: str) -> bool:
        if any(versions.equal(version, v) for v in self.versions):
            return True
        return any(versions.in_ecosystem_range(version, list(r)) for r in self.ranges)


@dataclass
class OsvIndex:
    by_pkg: dict[str, list[OsvEntry]] = field(default_factory=dict)
    advisories: int = 0
    withdrawn: int = 0
    bad_files: int = 0
    lines: list[str] = field(default_factory=list)


def _severity(rec: Mapping[str, Any], aff: Mapping[str, Any]) -> str:
    for src in (rec.get("database_specific"), aff.get("database_specific")):
        if isinstance(src, Mapping):
            s = str(src.get("severity", "")).upper()
            if s in _SEV_ORDER and s != "UNKNOWN":
                return "MODERATE" if s == "MEDIUM" else s
    return "UNKNOWN"


def _add_record(idx: OsvIndex, rec: Mapping[str, Any]) -> None:
    if not isinstance(rec, Mapping) or not rec.get("id"):
        idx.bad_files += 1
        return
    if rec.get("withdrawn"):
        idx.withdrawn += 1
        return
    used = False
    for aff in rec.get("affected", []) or []:
        pkg = aff.get("package") or {}
        if str(pkg.get("ecosystem", "")) != "PyPI" or not pkg.get("name"):
            continue
        ranges = []
        for r in aff.get("ranges", []) or []:
            if r.get("type") == "ECOSYSTEM":
                ranges.append(tuple(dict(e) for e in r.get("events", []) if isinstance(e, dict)))
        entry = OsvEntry(
            adv_id=str(rec["id"]),
            aliases=tuple(str(a) for a in rec.get("aliases", []) or []),
            severity=_severity(rec, aff),
            versions=tuple(str(v) for v in aff.get("versions", []) or []),
            ranges=tuple(ranges),
        )
        idx.by_pkg.setdefault(normalise_name(str(pkg["name"])), []).append(entry)
        used = True
    if used:
        idx.advisories += 1
        idx.lines.append(f"{rec['id']}|{rec.get('modified', '')}")


def load_osv(path: Path) -> OsvIndex:
    """Read a directory of OSV JSON files or one ``.zip`` of them (no network)."""
    idx = OsvIndex()
    if path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            infos = [i for i in zf.infolist() if i.filename.lower().endswith(".json")]
            for info in infos[:_MAX_OSV_FILES]:
                if info.file_size > _MAX_OSV_MEMBER:
                    idx.bad_files += 1
                    continue
                try:
                    _add_record(idx, json.loads(zf.read(info)))
                except (ValueError, KeyError, zipfile.BadZipFile):
                    idx.bad_files += 1
    else:
        files = sorted(path.rglob("*.json"))[:_MAX_OSV_FILES]
        for f in files:
            try:
                if f.stat().st_size > _MAX_OSV_MEMBER:
                    idx.bad_files += 1
                    continue
                _add_record(idx, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                idx.bad_files += 1
    idx.lines.sort()
    return idx


class OsvRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        if ctx.data_mode == "synthetic":
            sel = select_deps(pack, ctx)
            if isinstance(sel, RunnerOutput):
                return sel
            snap = _synthetic_dir(ctx) / "osv"
        else:
            if ctx.osv_db_path is None:
                return RunnerOutput.skip("no offline OSV snapshot: set OSV_DB_PATH")
            snap = Path(ctx.osv_db_path)
            if not snap.exists():
                return RunnerOutput.skip(
                    f"no offline OSV snapshot: OSV_DB_PATH not found: {snap.name}"
                )
            sel = select_deps(pack, ctx)
            if isinstance(sel, RunnerOutput):
                return sel
        idx = load_osv(snap)
        if idx.advisories == 0:
            return RunnerOutput.skip("OSV snapshot holds no usable PyPI advisories")
        matched: list[dict[str, Any]] = []
        n_advisories = 0
        unpinned = 0
        for c in sel.deps.sorted_components():
            if not c.version:
                unpinned += 1
                continue
            hits = [e for e in idx.by_pkg.get(c.name, []) if e.hits(c.version)]
            if not hits:
                continue
            groups = _merge_aliases(hits)
            n_advisories += len(groups)
            matched.append(
                {
                    "component": c.name,
                    "version": c.version,
                    "advisories": sorted(g["ids"][0] for g in groups),
                    "severity": max((g["severity"] for g in groups), key=_SEV_ORDER.get),
                    "critical_high": sum(
                        1 for g in groups if g["severity"] in ("CRITICAL", "HIGH")
                    ),
                }
            )
        crit_high = sum(m["critical_high"] for m in matched)
        details = _details(
            sel,
            snapshot_advisories=idx.advisories,
            snapshot_withdrawn_ignored=idx.withdrawn,
            snapshot_unreadable_files=idx.bad_files,
            unpinned_not_matched=unpinned,
            unknown_severity=sum(1 for m in matched if m["severity"] == "UNKNOWN"),
            matches=[{k: v for k, v in m.items() if k != "critical_high"} for m in matched[:100]],
        )
        return RunnerOutput(
            status="ok",
            metrics={
                "vulnerable_components": len(matched),
                "critical_high_count": crit_high,
                "advisories_matched": n_advisories,
            },
            details=details,
            **{
                **_base(sel, ctx),
                "dataset_id": f"osv:{snap.name}",
                "dataset_sha256": sha256_lines(idx.lines),
            },
        )


def _merge_aliases(hits: list[OsvEntry]) -> list[dict[str, Any]]:
    """Advisories that name each other (id or alias) are one vulnerability."""
    groups: list[dict[str, Any]] = []
    for e in sorted(hits, key=lambda x: x.adv_id):
        names = {e.adv_id, *e.aliases}
        hit = [g for g in groups if g["names"] & names]
        merged = {"names": set(names), "ids": [e.adv_id], "severity": e.severity}
        for g in hit:
            merged["names"] |= g["names"]
            merged["ids"] += g["ids"]
            if _SEV_ORDER[g["severity"]] > _SEV_ORDER[merged["severity"]]:
                merged["severity"] = g["severity"]
            groups.remove(g)
        if _SEV_ORDER[e.severity] > _SEV_ORDER[merged["severity"]]:
            merged["severity"] = e.severity
        merged["ids"] = sorted(set(merged["ids"]))
        groups.append(merged)
    return groups


# --------------------------------------------------------------------------- 3. licences

# classifier tail (text after the last "::") -> SPDX id. "BSD License" does not say 2 or 3
# clauses; it is mapped to BSD-3-Clause (an approximation, noted in the pack description).
CLASSIFIER_SPDX: dict[str, str] = {
    "MIT License": "MIT",
    "MIT No Attribution License (MIT-0)": "MIT-0",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "The Unlicense (Unlicense)": "Unlicense",
    "Zero-Clause BSD (0BSD)": "0BSD",
    "GNU General Public License (GPL)": "GPL-3.0-only",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-3.0-only",
    "GNU Affero General Public License v3": "AGPL-3.0-only",
    "GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
}

# free text in the License field (lower case search, first 600 chars); first match wins
_TEXT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gnu affero|\bagpl"), "AGPL-3.0-only"),
    (re.compile(r"gnu lesser|gnu library|\blgpl"), "LGPL-3.0-only"),
    (re.compile(r"gnu general public|\bgpl"), "GPL-3.0-only"),
    (re.compile(r"apache"), "Apache-2.0"),
    (re.compile(r"mozilla public|\bmpl[- ]?2"), "MPL-2.0"),
    (re.compile(r"python software foundation|\bpsf\b"), "PSF-2.0"),
    (re.compile(r"bsd[- ]?2|2-clause|two-clause"), "BSD-2-Clause"),
    (re.compile(r"bsd"), "BSD-3-Clause"),
    (re.compile(r"\bisc\b"), "ISC"),
    (re.compile(r"unlicense"), "Unlicense"),
    (re.compile(r"\b0bsd\b"), "0BSD"),
    (re.compile(r"\bmit\b|permission is hereby granted, free of charge"), "MIT"),
]


def _spdx_from_text(text: str) -> str | None:
    low = " ".join(text.lower().split())[:600]
    for pat, spdx in _TEXT_RULES:
        if pat.search(low):
            return spdx
    return None


def licence_expression(meta: Any) -> str:
    """SPDX-style expression for an installed distribution, or ``UNKNOWN``."""
    expr = (meta.get("License-Expression") or "").strip()
    if expr:
        return expr
    cls = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    ids = []
    for c in cls:
        tail = c.split("::")[-1].strip()
        spdx = CLASSIFIER_SPDX.get(tail)
        if spdx and spdx not in ids:
            ids.append(spdx)
    if ids:
        return " OR ".join(ids)  # several classifiers are read as a dual licence (OR)
    text = (meta.get("License") or "").strip()
    if text and text.upper() != "UNKNOWN":
        spdx = _spdx_from_text(text)
        if spdx:
            return spdx
    return "UNKNOWN"


_TOKEN = re.compile(r"\(|\)|[^\s()]+")


def eval_expression(expr: str, allow: set[str]) -> bool | None:
    """True allowed / False disallowed / None unknown, for an SPDX expression.

    ``OR`` = any alternative allowed; ``AND`` = all terms allowed; ``WITH exc`` ignored."""
    toks = _TOKEN.findall(expr)
    pos = 0

    def peek() -> str | None:
        return toks[pos] if pos < len(toks) else None

    def atom() -> bool | None:
        nonlocal pos
        t = peek()
        if t is None:
            return None
        pos += 1
        if t == "(":
            v = or_()
            if peek() == ")":
                pos += 1
            return v
        if peek() is not None and peek().upper() == "WITH":  # type: ignore[union-attr]
            pos += 2
        low = t.lower().rstrip("+")
        if (
            t.upper() == "UNKNOWN"
            or low.startswith("licenseref")
            or not re.fullmatch(r"[a-z0-9.\-]+", low)
        ):
            return None
        return low in allow or t.lower() in allow

    def and_() -> bool | None:
        nonlocal pos
        vals = [atom()]
        while peek() is not None and peek().upper() == "AND":  # type: ignore[union-attr]
            pos += 1
            vals.append(atom())
        if False in vals:
            return False
        return None if None in vals else True

    def or_() -> bool | None:
        nonlocal pos
        vals = [and_()]
        while peek() is not None and peek().upper() == "OR":  # type: ignore[union-attr]
            pos += 1
            vals.append(and_())
        if True in vals:
            return True
        return None if None in vals else False

    return or_()


def _licence_overrides(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {normalise_name(str(k)): str(v) for k, v in raw.items() if isinstance(v, str)}


class LicenceRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        sel = select_deps(pack, ctx)
        if isinstance(sel, RunnerOutput):
            return sel
        allow_list = list(ctx.licence_allow) or DEFAULT_ALLOW
        allow = {a.strip().lower() for a in allow_list if a.strip()}
        if ctx.data_mode == "synthetic":
            overrides = _licence_overrides(_synthetic_dir(ctx) / "licences.json")
            use_installed = False
        else:
            bank = ctx.bank_dir(pack.id)
            overrides = _licence_overrides(bank / "licences.json" if bank else None)
            use_installed = True
        comps = sorted({c.name for c in sel.deps.components})
        disallowed: list[dict[str, str]] = []
        unknown: list[str] = []
        by_source = {"override": 0, "installed": 0, "none": 0}
        for name in comps:
            expr = ""
            if name in overrides:
                expr, src = overrides[name], "override"
            else:
                src = "none"
                if use_installed:
                    try:
                        expr, src = licence_expression(md.distribution(name).metadata), "installed"
                    except (md.PackageNotFoundError, ValueError):
                        expr = ""
            by_source[src] += 1
            verdict = eval_expression(expr, allow) if expr and expr != "UNKNOWN" else None
            if verdict is None:
                unknown.append(name)
            elif verdict is False:
                disallowed.append({"name": name, "licence": expr})
        total = len(comps)
        return RunnerOutput(
            status="ok",
            metrics={
                "disallowed_count": len(disallowed),
                "unknown_licence_bp": bp(len(unknown), total),
                "checked_count": total,
            },
            details=_details(
                sel,
                allow_list=sorted(allow_list),
                disallowed=disallowed[:100],
                unknown_licence=unknown[:100],
                lookup_source=by_source,
                note="licence read from the installed distribution (its version can differ "
                "from the lock) or from the bank override file",
            ),
            **_base(sel, ctx),
        )


# --------------------------------------------------------------------------- 4. pin + hash


class PinHashRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        sel = select_deps(pack, ctx)
        if isinstance(sel, RunnerOutput):
            return sel
        comps = sel.deps.sorted_components()
        total = len(comps)
        unpinned = [c for c in comps if not c.pinned]
        unhashed = [c for c in comps if not c.hashed]
        return RunnerOutput(
            status="ok",
            metrics={
                "unpinned_bp": bp(len(unpinned), total),
                "unhashed_bp": bp(len(unhashed), total),
                "lock_present": 1 if sel.deps.lock_present else 0,
            },
            details=_details(
                sel,
                unpinned_count=len(unpinned),
                unhashed_count=len(unhashed),
                unpinned=[c.name for c in unpinned[:100]],
                unhashed=[c.name for c in unhashed[:100]],
                declared_only=sel.deps.declared_only,
                rule="pinned = exact version (==, or a lock entry); hashed = at least one "
                "sha256 from the lock or a --hash option; pyproject ranges count as declared",
            ),
            **_base(sel, ctx),
        )


# --------------------------------------------------------------------------- 5. models

_UNKNOWN_REGION = {"", "unknown", "unspecified", "none", "n/a"}


class ModelInventoryRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        if ctx.data_mode == "vendored":
            return RunnerOutput.skip("no vendored sample exists for this pack")
        if ctx.data_mode == "synthetic":
            models = _synthetic_models()
            mode, ds = "synthetic", "synthetic:models"
        else:
            if getattr(target, "kind", "") not in ("agent", "judge"):
                return RunnerOutput.skip("target has no model inventory")
            caps = getattr(target, "capabilities", None)
            if caps is not None and "models" not in caps:
                return RunnerOutput.skip("target lacks the 'models' capability")
            models = list(target.model_inventory())
            mode, ds = "bank_supplied_path", f"models:{target.target_id}"
        if not models:
            return RunnerOutput.skip("no model inventory declared")
        total = len(models)
        vendors: dict[str, int] = {}
        for m in models:
            v = (m.vendor or "unknown").strip().lower()
            vendors[v] = vendors.get(v, 0) + 1
        unknown_region = [
            m for m in models if (m.hosting_region or "").strip().lower() in _UNKNOWN_REGION
        ]
        unpinned = [m for m in models if not m.version_pinned]
        lines = sorted(
            f"{m.role}|{m.vendor}|{m.family}|{m.model_id}|{m.version_pinned}|{m.hosting_region}"
            for m in models
        )
        details: dict[str, Any] = {
            "vendors": dict(sorted(vendors.items())),
            "unpinned_models": [m.model_id for m in unpinned],
            "unknown_region_models": [m.model_id for m in unknown_region],
            "roles": sorted({m.role for m in models}),
            "concentration_note": "one vendor for all models gives 10000 bp; the default "
            "threshold is therefore informational until the bank sets a lower limit",
        }
        if mode == "synthetic":
            details["note"] = "synthetic model list (fake vendors)"
        return RunnerOutput(
            status="ok",
            metrics={
                "models_count": total,
                "unpinned_models": len(unpinned),
                "unknown_region_count": len(unknown_region),
                "max_vendor_share_bp": bp(max(vendors.values()), total),
                "mock_models": sum(1 for m in models if m.is_mock),
            },
            n_items=total,
            data_mode=mode,  # type: ignore[arg-type]
            dataset_id=ds,
            dataset_sha256=sha256_lines(lines),
            is_mock=bool(getattr(target, "is_mock", False)),
            details=details,
        )


def _synthetic_models() -> list[Any]:
    from supervisor.assurance.model import ModelDependency

    return [
        ModelDependency("agent", "SynVendorA", "syn-a", "syn-a-large-2026-01", True, "VN", True),
        ModelDependency("judge_t1", "SynVendorB", "syn-b", "syn-b-small", False, None, True),
    ]


# --------------------------------------------------------------------------- 6. MCP drift

_INVISIBLE = {"Cf", "Co"}  # format (zero width, bidi, tag characters) and private use


def _tool_schema(t: Mapping[str, Any]) -> Any:
    for k in ("inputSchema", "schema", "args"):
        if k in t and t[k] is not None:
            return t[k]
    return {}


def tool_hash(t: Mapping[str, Any]) -> str:
    desc = " ".join(str(t.get("description", "")).split())
    return _sha(_canon({"name": t.get("name", ""), "description": desc, "schema": _tool_schema(t)}))


def _flatten_tools(manifest: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any], str]]:
    """(full name, tool dict, bare name) for declared tools, then MCP server tools."""
    out: list[tuple[str, Mapping[str, Any], str]] = []
    for t in manifest.get("tools", []) or []:
        if isinstance(t, Mapping) and t.get("name"):
            out.append((str(t["name"]), t, str(t["name"])))
    for s in manifest.get("mcp_servers", []) or []:
        if not isinstance(s, Mapping):
            continue
        for t in s.get("tools", []) or []:
            if isinstance(t, Mapping) and t.get("name"):
                out.append((f"{s.get('name', 'mcp')}/{t['name']}", t, str(t["name"])))
    return out


def set_hash(items: list[tuple[str, Mapping[str, Any], str]]) -> str:
    return _sha(_canon(sorted([n, tool_hash(t)] for n, t, _b in items)))


def registry_hash(manifest: Mapping[str, Any]) -> list[str]:
    """Candidates for the registry-style hash (``AgentManifest.tool_manifest_hash``):
    sha256 of sorted-key JSON of ``[{name, risk_class, args}]`` in given and in name order."""
    tools = [t for t in manifest.get("tools", []) or [] if isinstance(t, Mapping)]
    if not tools or not all("risk_class" in t for t in tools):
        return []
    spec = [
        {"name": t["name"], "risk_class": t["risk_class"], "args": t.get("args") or {}}
        for t in tools
    ]
    outs = []
    for seq in (spec, sorted(spec, key=lambda s: s["name"])):
        outs.append(_sha(_canon(seq)))
    return outs


def _strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _strings(v, depth + 1)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v, depth + 1)]
    return []


def poisoned(t: Mapping[str, Any]) -> list[str]:
    """Reasons a tool description looks poisoned (names of rules only, no text)."""
    from supervisor.gateway.tier0b import RegexClassifier

    texts = _strings(t.get("description", "")) + _strings(_tool_schema(t))
    blob = "\n".join(texts)
    reasons: list[str] = []
    if any(f.kind == "injection" for f in RegexClassifier().classify("tool", {"d": blob})):
        reasons.append("injection_phrase")
    if any(unicodedata.category(ch) in _INVISIBLE for ch in blob):
        reasons.append("hidden_characters")
    return reasons


def _baseline(pack: EvalPack, ctx: RunContext) -> Any:
    bank = ctx.bank_dir(pack.id)
    tid = str(ctx.target.target_id)
    if bank is not None:
        for name in (tid, re.sub(r"[^A-Za-z0-9_.-]+", "_", tid)):
            p = bank / f"{name}.json"
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
    return ctx.extras.get("tool_baseline")


class McpDriftRunner:
    def run(self, pack: EvalPack, ctx: RunContext) -> RunnerOutput:
        target = ctx.target
        if ctx.data_mode == "vendored":
            return RunnerOutput.skip("no vendored sample exists for this pack")
        baseline: Any = None
        if ctx.data_mode == "synthetic":
            p = _synthetic_dir(ctx) / "mcp_tool_manifest.json"
            try:
                manifest = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return RunnerOutput.skip(f"synthetic manifest missing: {p.name}")
            mode, ds = "synthetic", "synthetic:mcp_tool_manifest.json"
            baseline = manifest.pop("baseline", None)
        else:
            if getattr(target, "kind", "") != "agent":
                return RunnerOutput.skip("the judge has no tool manifest (agent targets only)")
            caps = getattr(target, "capabilities", None)
            if caps is not None and "tool_manifest" not in caps:
                return RunnerOutput.skip("target lacks the 'tool_manifest' capability")
            manifest = dict(target.tool_manifest() or {})
            mode, ds = "bank_supplied_path", f"tools:{target.target_id}"
            baseline = _baseline(pack, ctx)
        items = _flatten_tools(manifest)
        if not items:
            return RunnerOutput.skip("no tools declared: nothing to check for drift")
        names_full = {n for n, _t, _b in items}
        names_all = names_full | {b for _n, _t, b in items}
        current = {n: tool_hash(t) for n, t, _b in items}
        cur_set = set_hash(items)
        drift: list[str] = []
        checks: list[str] = []
        # (a) declared hash
        declared_hash = manifest.get("declared_hash")
        if declared_hash:
            checks.append("declared_hash")
            if declared_hash != cur_set and declared_hash not in registry_hash(manifest):
                drift.append("declared_hash_mismatch")
        # (b) registered tool names
        undeclared: list[str] = []
        if manifest.get("registered") is not None:
            checks.append("registered")
            registered = {str(n) for n in manifest["registered"]}
            undeclared = sorted(n for n in registered if n not in names_all)
            for n, _t, b in items:
                if n not in registered and b not in registered:
                    drift.append(f"missing_tool:{n}")
        # (c) baseline
        if baseline:
            checks.append("baseline")
            if isinstance(baseline, str):
                if baseline != cur_set and baseline not in registry_hash(manifest):
                    drift.append("baseline_hash_mismatch")
            elif isinstance(baseline, Mapping):
                bt = baseline.get("tools")
                ref = baseline.get("tool_manifest_hash") or baseline.get("set_hash")
                if isinstance(bt, Mapping):
                    for n in sorted(set(bt) | set(current)):
                        if n not in bt:
                            drift.append(f"added_since_baseline:{n}")
                        elif n not in current:
                            drift.append(f"removed_since_baseline:{n}")
                        elif bt[n] != current[n]:
                            drift.append(f"changed_since_baseline:{n}")
                elif ref and ref != cur_set and ref not in registry_hash(manifest):
                    drift.append("baseline_hash_mismatch")
        poisoned_tools = {n: r for n, t, _b in items if (r := poisoned(t))}
        measured = bool(checks)
        details = {
            "checks_run": checks,
            "drift": drift[:100],
            "undeclared": undeclared[:100],
            "poisoned": {k: v for k, v in sorted(poisoned_tools.items())},
            "tools_count": len(items),
            "set_hash": cur_set,
            "tool_hashes": dict(sorted(current.items())),
            "baseline_source": "none" if not baseline else "supplied",
        }
        if not measured:
            details["note"] = (
                "no declared_hash, registered list or baseline was supplied: drift and "
                "undeclared tools could not be measured (reported as null)"
            )
        if mode == "synthetic":
            details["note"] = SYNTHETIC_NOTE
        return RunnerOutput(
            status="ok",
            metrics={
                "drift_count": len(drift) if measured else None,
                "undeclared_tools": len(undeclared) if "registered" in checks else None,
                "poisoned_descriptions": len(poisoned_tools),
            },
            n_items=len(items),
            data_mode=mode,  # type: ignore[arg-type]
            dataset_id=ds,
            dataset_sha256=sha256_lines(sorted(f"{n}|{h}" for n, h in current.items())),
            is_mock=bool(getattr(target, "is_mock", False)),
            details=details,
        )
