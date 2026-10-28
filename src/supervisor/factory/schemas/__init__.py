"""The three frozen schemas of the agent factory (version 1)."""

from __future__ import annotations

from typing import Any

from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.factory.schemas.facts_v1 import FactsExportV1

MODELS: dict[str, Any] = {
    "facts_v1": FactsExportV1,
    "assessment_report_v1": AssessmentReportV1,
    "agent_definition_v1": AgentDefinitionV1,
}

__all__ = ["MODELS", "AgentDefinitionV1", "AssessmentReportV1", "FactsExportV1"]
