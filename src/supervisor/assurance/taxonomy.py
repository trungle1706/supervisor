"""Controlled vocabularies that pack manifests map to (``maps_to``).

* ``REGKB_DUTIES``: duty ids shared with WP13 (RegKB). Same words in both packages.
* ``OWASP_LLM``: OWASP Top 10 for LLM Applications 2025 (https://genai.owasp.org/llm-top-10/).
* ``OWASP_AGENTIC``: OWASP Top 10 for Agentic Applications (ASI01..ASI10), the same
  labels the red-team pack ``agents/redteam/incidents.jsonl`` uses.
* ``ATLAS``: MITRE ATLAS technique ids used by the packs (https://atlas.mitre.org/).
* ``FINVAULT``: FinVault-style finance harm classes, as in the red-team pack.
"""

from __future__ import annotations

REGKB_DUTIES: frozenset[str] = frozenset(
    {
        "human_oversight",
        "logging",
        "incident_report_24h",
        "bias_monitoring",
        "ai_disclosure",
        "right_to_human_review",
        "data_localisation",
        "cross_border_notice",
        "retention",
        "model_inventory",
        "independent_validation",
        "change_control",
        "conformity_assessment",
        "registration",
        "customer_confidentiality",
        "transaction_authentication",
        "dpia",
        "data_subject_rights",
        "consent",
        "explainability",
        "outsourcing_oversight",
    }
)

OWASP_LLM_NAMES: dict[str, str] = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}
OWASP_LLM: frozenset[str] = frozenset(OWASP_LLM_NAMES)

OWASP_AGENTIC_NAMES: dict[str, str] = {
    "ASI01": "Agent Goal Hijack",
    "ASI02": "Tool Misuse and Exploitation",
    "ASI03": "Identity and Privilege Abuse",
    "ASI04": "Agentic Supply Chain Vulnerabilities",
    "ASI05": "Unexpected Code Execution",
    "ASI06": "Memory and Context Poisoning",
    "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Failures",
    "ASI09": "Human-Agent Trust Exploitation",
    "ASI10": "Rogue Agents",
}
OWASP_AGENTIC: frozenset[str] = frozenset(OWASP_AGENTIC_NAMES)

# MITRE ATLAS techniques referenced by the packs. Ids and names checked against
# mitre-atlas/atlas-data dist/ATLAS.yaml on 2026-10-15 (ATLAS renamed ML -> AI).
ATLAS_NAMES: dict[str, str] = {
    "AML.T0010": "AI Supply Chain Compromise",
    "AML.T0015": "Evade AI Model",
    "AML.T0024": "Exfiltration via AI Inference API",
    "AML.T0029": "Denial of AI Service",
    "AML.T0043": "Craft Adversarial Data",
    "AML.T0048": "External Harms",
    "AML.T0051": "LLM Prompt Injection",
    "AML.T0051.000": "LLM Prompt Injection: Direct",
    "AML.T0051.001": "LLM Prompt Injection: Indirect",
    "AML.T0053": "AI Agent Tool Invocation (formerly LLM Plugin Compromise)",
    "AML.T0054": "LLM Jailbreak",
    "AML.T0056": "Extract LLM System Prompt",
    "AML.T0057": "LLM Data Leakage",
}
ATLAS: frozenset[str] = frozenset(ATLAS_NAMES)

FINVAULT: frozenset[str] = frozenset(
    {
        "policy_violation",
        "limit_circumvention",
        "unauthorized_transaction",
        "data_leakage",
        "fraud_facilitation",
        "compliance_bypass",
        "hallucinated_commitment",
        "unfair_lending",
    }
)
