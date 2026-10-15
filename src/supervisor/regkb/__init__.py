"""Regulation knowledge base (WP13): load, validate, query and hash regulatory obligations.

    kb = load_kb()                       # regulations/vn + regulations/intl
    result = evaluate(kb.get(oid).applies_to, ProductProfile(agent_classes=("payment",)))

Not legal advice. Bank counsel must confirm.
"""

from supervisor.regkb.errors import (
    RegKBError,
    SchemaError,
    SemanticError,
    UnknownObligationError,
    UnsupportedKeywordError,
)
from supervisor.regkb.loader import load_kb
from supervisor.regkb.model import (
    Applicability,
    AppliesTo,
    Control,
    DatedFact,
    Instrument,
    KnowledgeBase,
    Obligation,
    ProductProfile,
    Source,
)
from supervisor.regkb.predicates import applicable, evaluate

DISCLAIMER = "Not legal advice. Bank counsel must confirm. / Khong phai tu van phap ly."

__all__ = [
    "DISCLAIMER",
    "Applicability",
    "AppliesTo",
    "Control",
    "DatedFact",
    "Instrument",
    "KnowledgeBase",
    "Obligation",
    "ProductProfile",
    "RegKBError",
    "SchemaError",
    "SemanticError",
    "Source",
    "UnknownObligationError",
    "UnsupportedKeywordError",
    "applicable",
    "evaluate",
    "load_kb",
]
