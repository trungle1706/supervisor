"""Compliance advisor (WP14): obligations matrix of a product against RegKB. Advisory only.

Not legal advice. Bank counsel must confirm.
"""

from supervisor.advisory.compliance.applicability import (
    RowApplicability,
    assess,
    fact_questions,
    regkb_profile,
)
from supervisor.advisory.compliance.decision33 import suggest_decision33
from supervisor.advisory.compliance.demo import corpus_product, demo_product
from supervisor.advisory.compliance.facts import (
    apply_answers,
    from_onboard,
    from_questionnaire,
    load_profile_input,
    policy_facts,
)
from supervisor.advisory.compliance.model import (
    ControlCheck,
    D33Entry,
    DateItem,
    Deadline,
    Decision33Suggestion,
    LimitFact,
    MatrixHeader,
    MatrixRow,
    Narrative,
    ObligationMatrix,
    Pointer,
    ProductControls,
    ProductProfile,
    Question,
    RuleFact,
    ThresholdFinding,
    to_plain,
)
from supervisor.advisory.compliance.questionnaire import (
    FIELDS,
    QuestionnaireError,
    make_question,
    questionnaire_schema,
    template_yaml,
    validate_answers,
)

__all__ = [
    "FIELDS",
    "ControlCheck",
    "D33Entry",
    "DateItem",
    "Deadline",
    "Decision33Suggestion",
    "LimitFact",
    "MatrixHeader",
    "MatrixRow",
    "Narrative",
    "ObligationMatrix",
    "Pointer",
    "ProductControls",
    "ProductProfile",
    "Question",
    "QuestionnaireError",
    "RowApplicability",
    "RuleFact",
    "ThresholdFinding",
    "apply_answers",
    "assess",
    "corpus_product",
    "demo_product",
    "fact_questions",
    "from_onboard",
    "from_questionnaire",
    "load_profile_input",
    "make_question",
    "policy_facts",
    "questionnaire_schema",
    "regkb_profile",
    "suggest_decision33",
    "template_yaml",
    "to_plain",
    "validate_answers",
]
