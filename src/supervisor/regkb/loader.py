"""Load, validate and merge regulation files into a ``KnowledgeBase``.

    kb = load_kb()                              # regulations/vn + regulations/intl
    kb = load_kb(internal_dir=Path("C:/bank/internal"))   # plus the bank's own rules

The loader collects every problem and raises one ``SchemaError`` (a file breaks the schema)
or ``SemanticError`` (a RegKB rule is broken). ``error.errors`` lists all of them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from supervisor.regkb.errors import RegKBError, SchemaError, SemanticError
from supervisor.regkb.hashing import instrument_hash, version_hash
from supervisor.regkb.model import (
    AppliesTo,
    Control,
    DatedFact,
    Dates,
    Instrument,
    KnowledgeBase,
    Obligation,
    Source,
)
from supervisor.regkb.validator import validate

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LIVE = ("in_force", "issued")
HEADER_KEYS = ("jurisdiction", "issuer", "number", "title_vi", "title_en", "binding")
CONTROL_VOCAB = {"monitor": "monitors", "console": "console", "evidence": "evidence"}
# (sub directory, required instrument id prefix)
SOURCE_DIRS = (("vn", "VN-"), ("intl", "INTL-"))


def _today() -> dt.date:
    """Check date for in_force / issued against dates.effective (tests patch this)."""
    return dt.date.today()


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _find_dates(node: Any, path: str = "$") -> list[str]:
    """Paths of unquoted YAML dates (PyYAML parses 2025-01-01 as a date object)."""
    found: list[str] = []
    if isinstance(node, dt.date):  # datetime is a subclass
        found.append(path)
    elif isinstance(node, dict):
        for k, v in node.items():
            found.extend(_find_dates(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found.extend(_find_dates(v, f"{path}[{i}]"))
    return found


def _who(data: Any, path: str, default: str) -> str:
    """Obligation id for an issue path like $.obligations[2].sources, else the instrument id."""
    m = re.match(r"\$\.obligations\[(\d+)\]", path)
    if m and isinstance(data.get("obligations"), list):
        try:
            return str(data["obligations"][int(m.group(1))].get("id", default))
        except (IndexError, AttributeError):
            pass
    return default


def _src(d: dict[str, Any]) -> Source:
    return Source(**{k: d.get(k) for k in Source.__dataclass_fields__})


def _fact(d: dict[str, Any]) -> DatedFact:
    return DatedFact(**{k: d.get(k) for k in DatedFact.__dataclass_fields__})


def _dates(d: dict[str, Any]) -> Dates:
    return Dates(
        issued=_fact(d["issued"]) if "issued" in d else None,
        effective=_fact(d["effective"]) if "effective" in d else None,
        compliance_deadline=_fact(d["compliance_deadline"]) if "compliance_deadline" in d else None,
        milestones=tuple(_fact(m) for m in d["milestones"]) if "milestones" in d else None,
    )


def _tuple(value: Any) -> tuple[Any, ...] | None:
    return None if value is None else tuple(value)


def _instrument(d: dict[str, Any], file: str) -> Instrument:
    return Instrument(
        id=d["id"],
        jurisdiction=d["jurisdiction"],
        kind=d["kind"],
        issuer=d["issuer"],
        number=d["number"],
        title_en=d["title_en"],
        status=d["status"],
        binding=d["binding"],
        dates=_dates(d["dates"]),
        sources=tuple(_src(s) for s in d["sources"]),
        verification=d["verification"],
        primary_text_fetched=d["primary_text_fetched"],
        last_checked=d["last_checked"],
        title_vi=d.get("title_vi"),
        supersedes=_tuple(d.get("supersedes")),
        superseded_by=_tuple(d.get("superseded_by")),
        related=_tuple(d.get("related")),
        notes=d.get("notes"),
        file=file,
    )


def _obligation(d: dict[str, Any], file: str) -> Obligation:
    a = d["applies_to"]
    applies = AppliesTo(
        agent_class=_tuple(a.get("agent_class")),
        data_classes=_tuple(a.get("data_classes")),
        autonomy=_tuple(a.get("autonomy")),
        cross_border=a.get("cross_border"),
        model_hosting=_tuple(a.get("model_hosting")),
        role=_tuple(a.get("role")),
    )
    return Obligation(
        id=d["id"],
        instrument_id=d["instrument_id"],
        jurisdiction=d["jurisdiction"],
        instrument_kind=d["instrument_kind"],
        issuer=d["issuer"],
        number=d["number"],
        title_en=d["title_en"],
        status=d["status"],
        binding=d["binding"],
        dates=_dates(d["dates"]),
        article_ref=d["article_ref"],
        summary_en=d["summary_en"],
        duties=tuple(d["duties"]),
        applies_to=applies,
        control_mapping=tuple(
            Control(c["kind"], c["id"], c["coverage"], c.get("note")) for c in d["control_mapping"]
        ),
        evidence_needed=tuple(d["evidence_needed"]),
        verification=d["verification"],
        sources=tuple(_src(s) for s in d["sources"]),
        confidence=d["confidence"],
        title_vi=d.get("title_vi"),
        text_vi=d.get("text_vi"),
        text_en=d.get("text_en"),
        summary_vi=d.get("summary_vi"),
        addressee=d.get("addressee"),
        notes=d.get("notes"),
        confirmed_by=d.get("confirmed_by"),
        file=file,
    )


class _Vocab:
    """Ids that control_mapping and duties may use."""

    def __init__(self, schema_dir: Path) -> None:
        self.duties = set((_load_yaml(schema_dir / "duties.yaml") or {}).get("duties", {}))
        controls = _load_yaml(schema_dir / "controls.yaml") or {}
        self.by_kind: dict[str, set[str]] = {"process": set(controls.get("process", {}))}
        for kind, key in CONTROL_VOCAB.items():
            self.by_kind[kind] = set(controls.get(key, {}))
        manifests = PACKAGE_ROOT / "catalogue" / "manifests"
        self.by_kind["catalogue"] = {
            str(_load_yaml(p).get("id")) for p in sorted(manifests.glob("*.yaml"))
        }
        policy = _load_yaml(REPO_ROOT / "policies" / "baseline.yaml") or {}
        self.by_kind["rule"] = {str(r["id"]) for r in policy.get("rules", [])}


class _Loader:
    def __init__(self, root: Path, internal_dir: Path | None) -> None:
        self.root = root
        self.base = root.parent  # local_path in sources is relative to this
        self.internal_dir = internal_dir
        schema_dir = root / "schema"
        if not (schema_dir / "obligation.schema.json").is_file():
            schema_dir = REPO_ROOT / "regulations" / "schema"
        self.schema = json.loads((schema_dir / "obligation.schema.json").read_text("utf-8"))
        self.vocab = _Vocab(schema_dir)
        self.schema_errors: list[str] = []
        self.semantic_errors: list[str] = []
        self.warnings: list[str] = []
        self.instruments: dict[str, Instrument] = {}
        self.obligations: dict[str, Obligation] = {}

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.base).as_posix()
        except ValueError:
            return path.as_posix()

    def files(self) -> list[tuple[Path, str, bool]]:
        out = []
        for sub, prefix in SOURCE_DIRS:
            out += [(p, prefix, False) for p in sorted((self.root / sub).glob("*.yaml"))]
        if self.internal_dir is not None:
            out += [(p, "INT-", True) for p in sorted(self.internal_dir.glob("*.yaml"))]
        return out

    def run(self) -> KnowledgeBase:
        for path, prefix, internal in self.files():
            self.load_file(path, prefix, internal)
        if self.schema_errors or self.semantic_errors:
            cls = SchemaError if self.schema_errors else SemanticError
            errors = self.schema_errors + self.semantic_errors
            raise cls(f"{len(errors)} problem(s) in the regulation files", errors)
        instruments = tuple(sorted(self.instruments.values(), key=lambda i: i.id))
        obligations = dict(sorted(self.obligations.items()))
        hashes = {
            i.id: instrument_hash(i, (o for o in obligations.values() if o.instrument_id == i.id))
            for i in instruments
        }
        return KnowledgeBase(
            instruments,
            obligations,
            version_hash(instruments, obligations.values()),
            hashes,
            tuple(self.warnings),
        )

    # ---- one file -------------------------------------------------------------------
    def load_file(self, path: Path, prefix: str, internal: bool) -> None:
        rel = self.rel(path)
        try:
            data = _load_yaml(path)
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
            self.schema_errors.append(f"{rel}: cannot read YAML: {exc}".replace("\n", " "))
            return
        dates = _find_dates(data)
        if dates:
            self.schema_errors += [f'{rel}: {p}: quote dates (write "YYYY-MM-DD")' for p in dates]
            return
        name = "?"
        if isinstance(data, dict) and isinstance(data.get("instrument"), dict):
            name = str(data["instrument"].get("id", "?"))
        issues = validate(data, {"$ref": "#/$defs/instrument_file"}, self.schema)
        if issues:
            self.schema_errors += [f"{rel}: {_who(data, i.path, name)}: {i}" for i in issues]
            return
        header = data["instrument"]
        resolved = []
        for raw in data["obligations"]:
            merged = dict(raw)
            merged["instrument_id"] = header["id"]
            merged["instrument_kind"] = header["kind"]
            for key in HEADER_KEYS:
                if key in header:
                    merged[key] = header[key]
            merged.setdefault("status", header["status"])
            merged.setdefault("dates", header["dates"])
            issues = validate(merged, self.schema)
            if issues:
                self.schema_errors += [f"{rel}: {raw['id']}: {i}" for i in issues]
            else:
                resolved.append(merged)
        if len(resolved) != len(data["obligations"]):
            return
        inst = _instrument(header, rel)
        self.check_instrument(inst, prefix, internal)
        if inst.id in self.instruments:
            self.sem(
                rel, inst.id, f"duplicate instrument id (also in {self.instruments[inst.id].file})"
            )
        else:
            self.instruments[inst.id] = inst
        for merged in resolved:
            ob = _obligation(merged, rel)
            self.check_obligation(ob, inst)
            if ob.id in self.obligations:
                self.sem(
                    rel, ob.id, f"duplicate obligation id (also in {self.obligations[ob.id].file})"
                )
            else:
                self.obligations[ob.id] = ob

    # ---- rules ----------------------------------------------------------------------
    def check_timing(self, rel: str, ident: str, status: str, dates: Dates) -> None:
        """in_force before the effective date is an error; issued after it is a warning."""
        eff = dates.effective.date if dates.effective is not None else None
        if not eff:
            return
        today = _today().isoformat()
        if status == "in_force" and eff > today:
            self.sem(rel, ident, f"status in_force but effective date {eff} is after {today}")
        elif status == "issued" and eff <= today:
            self.warnings.append(
                f"{rel}: {ident}: status issued but effective date {eff} has passed; "
                "check the text and set in_force"
            )

    def sem(self, rel: str, ident: str, message: str) -> None:
        self.semantic_errors.append(f"{rel}: {ident}: {message}")

    def check_instrument(self, inst: Instrument, prefix: str, internal: bool) -> None:
        sem = lambda msg: self.sem(inst.file, inst.id, msg)  # noqa: E731
        if not inst.id.startswith(prefix):
            sem(f"instrument id must start with {prefix} in this directory")
        if inst.kind == "internal" and not internal:
            sem("kind internal is only allowed in the internal directory")
        if inst.kind == "draft" and inst.status in LIVE:
            sem("a draft instrument cannot have status in_force or issued")
        if inst.status in ("reference", "draft") and inst.binding:
            sem(f"status {inst.status} requires binding false")
        self.check_timing(inst.file, inst.id, inst.status, inst.dates)
        if inst.verification == "VERIFIED_PRIMARY" and not any(
            s.kind == "primary" for s in inst.sources
        ):
            sem("VERIFIED_PRIMARY needs at least one source of kind primary")
        for src in inst.sources:
            self.check_source(src, inst.file, inst.id)

    def check_obligation(self, ob: Obligation, inst: Instrument) -> None:
        sem = lambda msg: self.sem(ob.file, ob.id, msg)  # noqa: E731
        if not ob.id.startswith(inst.id + "-"):
            sem(f"obligation id must start with {inst.id}-")
        if ob.status in LIVE and (inst.kind == "draft" or inst.status == "draft"):
            sem("an obligation of a draft instrument cannot have status in_force or issued")
        if ob.status in ("reference", "draft") and ob.binding:
            sem(f"status {ob.status} requires binding false")
        self.check_timing(ob.file, ob.id, ob.status, ob.dates)
        for duty in ob.duties:
            if duty not in self.vocab.duties:
                sem(f"unknown duty {duty!r} (add it to regulations/schema/duties.yaml)")
        for c in ob.control_mapping:
            if c.id not in self.vocab.by_kind.get(c.kind, set()):
                sem(f"control_mapping {c.kind}:{c.id} does not resolve")
        if ob.verification == "VERIFIED_PRIMARY":
            if not any(s.kind == "primary" for s in ob.sources):
                sem("VERIFIED_PRIMARY needs at least one source of kind primary")
            if ob.jurisdiction == "VN" and not (ob.text_vi or "").strip():
                sem("VERIFIED_PRIMARY for a VN instrument needs a non-empty text_vi")
        if ob.verification == "ASSUMED" and not (ob.notes or "").strip():
            self.warnings.append(f"{ob.file}: {ob.id}: ASSUMED without notes explaining why")
        for src in ob.sources:
            self.check_source(src, ob.file, ob.id)

    def check_source(self, src: Source, rel: str, ident: str) -> None:
        if not src.local_path:
            return
        base = self.base.resolve()
        path = (base / src.local_path).resolve()
        if base not in path.parents:
            self.sem(rel, ident, f"source local_path {src.local_path} leaves the repository")
        elif not path.is_file():
            self.sem(rel, ident, f"source local_path {src.local_path} does not exist")
        elif src.sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != src.sha256:
            self.sem(rel, ident, f"source local_path {src.local_path} sha256 does not match")


def load_kb(root: Path | None = None, internal_dir: Path | None = None) -> KnowledgeBase:
    """Load regulations/{vn,intl}/*.yaml (and ``internal_dir``/*.yaml when given)."""
    base = Path(os.path.abspath(root)) if root is not None else REPO_ROOT / "regulations"
    internal = Path(os.path.abspath(internal_dir)) if internal_dir is not None else None
    if not base.is_dir():
        raise RegKBError(f"regulations root {base} is not a directory")
    if internal is not None and not internal.is_dir():
        raise RegKBError(f"internal rules directory {internal} is not a directory")
    return _Loader(base, internal).run()
